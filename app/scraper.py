import json
import os
import random
import string
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from playwright.sync_api import (
    Error as PlaywrightError,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

DOWNLOAD_DIR = Path(os.getenv("DOWNLOADS_DIR", "downloads"))
COOKIES_PATH = Path(os.getenv("COOKIES_PATH", "cookies.json"))

DEFAULT_LOGIN_URL = "https://www.coursefinder.ai/"
DEFAULT_DASHBOARD_URL = "https://www.coursefinder.ai/dashboard"

DEFAULT_TIMEOUT_SECONDS = int(
    os.getenv("SCRAPER_TIMEOUT", "30")
)

DEFAULT_TIMEOUT_MS = DEFAULT_TIMEOUT_SECONDS * 1000


class ScraperError(Exception):
    pass


# =========================================================
# HELPERS
# =========================================================

def load_env_vars() -> None:
    load_dotenv()


def get_env_credentials() -> Tuple[str, str]:

    load_env_vars()

    email = os.getenv(
        "SCRAPER_EMAIL",
        ""
    ).strip()

    password = os.getenv(
        "SCRAPER_PASSWORD",
        ""
    ).strip()

    if not email or not password:
        raise ScraperError(
            "SCRAPER_EMAIL and SCRAPER_PASSWORD "
            "must exist in .env"
        )

    return email, password


def ensure_download_dir() -> None:
    DOWNLOAD_DIR.mkdir(
        parents=True,
        exist_ok=True
    )


def random_email() -> str:

    token = ''.join(
        random.choices(
            string.ascii_lowercase +
            string.digits,
            k=10
        )
    )

    return f"user+{token}@example.com"


def safe_count(locator_or_selector, page=None) -> int:

    try:

        if isinstance(locator_or_selector, str):
            return page.locator(
                locator_or_selector
            ).count()

        return locator_or_selector.count()

    except Exception:
        return 0


def safe_click(locator, page: Page) -> None:

    try:
        locator.click()

    except Exception:

        try:
            locator.click(force=True)

        except Exception:

            handle = locator.element_handle()

            if handle:

                page.evaluate(
                    "(el) => el.click()",
                    handle
                )


def save_cookies(context, path=COOKIES_PATH):

    cookies = context.cookies()

    with path.open(
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            cookies,
            f,
            indent=2
        )


def load_cookies(context, path=COOKIES_PATH):

    try:

        with path.open(
            "r",
            encoding="utf-8"
        ) as f:

            cookies = json.load(f)

    except Exception:
        return False

    try:

        context.add_cookies(cookies)

        return True

    except Exception:
        return False


def is_session_active(page: Page) -> bool:

    if "login" in page.url.lower():
        return False

    login_buttons = page.locator(
        'button:has-text("Login")'
    )

    if safe_count(login_buttons, page) > 0:
        return False

    return True


def _sanitize_slug(
    text: str,
    max_len: int = 40
) -> str:

    safe = ''.join(
        c for c in text
        if c.isalnum() or c in (
            ' ',
            '_',
            '-'
        )
    )

    return (
        safe
        .strip()
        .replace(' ', '_')[:max_len]
    )


def _make_output_path(
    suggested_filename: str,
    query: str
) -> Path:

    ensure_download_dir()

    stem = (
        Path(suggested_filename).stem
        or "download"
    )

    ext = (
        Path(suggested_filename).suffix
        or ".xlsx"
    )

    ts = datetime.utcnow().strftime(
        "%Y%m%dT%H%M%S"
    )

    filename = (
        f"{_sanitize_slug(query)}_"
        f"{ts}_{stem}{ext}"
    )

    return DOWNLOAD_DIR / filename


# =========================================================
# LOGIN
# =========================================================

def login_with_credentials(
    page: Page,
    email: str,
    password: str
) -> None:

    login_button = page.locator(
        'button:has-text("Login")'
    )

    login_button.first.wait_for(
        state="visible",
        timeout=DEFAULT_TIMEOUT_MS
    )

    safe_click(
        login_button.first,
        page
    )

    page.wait_for_timeout(3000)

    email_input = page.locator(
        'input[type="email"]'
    )

    email_input.first.fill(email)

    page.wait_for_timeout(1000)

    continue_button = page.locator(
        'button:has-text("Continue")'
    )

    safe_click(
        continue_button.first,
        page
    )

    page.wait_for_timeout(3000)

    password_input = page.locator(
        'input[type="password"]'
    )

    password_input.first.fill(password)

    page.wait_for_timeout(1000)

    continue_button = page.locator(
        'button:has-text("Continue")'
    )

    safe_click(
        continue_button.first,
        page
    )

    page.wait_for_timeout(5000)

    save_cookies(page.context)


# =========================================================
# NAVIGATION
# =========================================================

def navigate_to_search_program(page: Page) -> None:
    """
    Navigate safely to Search Program page.
    Handles:
    - delayed auth redirects
    - SPA rendering
    - async hydration
    - dashboard loading
    """

    print("Navigating to dashboard...")

    # =====================================================
    # OPEN DASHBOARD
    # =====================================================

    page.goto(
        DEFAULT_DASHBOARD_URL,
        wait_until="domcontentloaded",
        timeout=60000
    )

    # Give React app time
    page.wait_for_timeout(5000)

    # =====================================================
    # WAIT FOR PAGE TO STABILIZE
    # =====================================================

    try:
        page.wait_for_load_state(
            "networkidle",
            timeout=15000
        )
    except Exception:
        pass

    page.wait_for_timeout(3000)

    # =====================================================
    # TRY MULTIPLE SEARCH PROGRAM SELECTORS
    # =====================================================

    selectors = [
        'button:has-text("Search Programs")',
        'text="Search Programs"',
        'a:has-text("Search Programs")',
        '[href*="search-program"]',
    ]

    search_program_button = None

    for selector in selectors:

        try:
            locator = page.locator(selector)

            count = safe_count(locator, page)

            if count == 0:
                continue

            for i in range(count):

                try:
                    candidate = locator.nth(i)

                    visible = candidate.is_visible()

                    if visible:
                        search_program_button = candidate
                        break

                except Exception:
                    continue

            if search_program_button:
                break

        except Exception:
            continue

    # =====================================================
    # FALLBACK DIRECT NAVIGATION
    # =====================================================

    if not search_program_button:

        print(
            "Search Programs button not found."
            " Navigating directly."
        )

        page.goto("https://www.coursefinder.ai/search-program")

        page.wait_for_timeout(5000)

        return

    # =====================================================
    # CLICK SEARCH PROGRAMS
    # =====================================================

    print("Clicking Search Programs")

    try:

        handle = (
            search_program_button
            .element_handle()
        )

        if handle:

            page.evaluate(
                "(el) => el.click()",
                handle
            )

        else:

            safe_click(
                search_program_button,
                page
            )

    except Exception:

        safe_click(
            search_program_button,
            page
        )

    # =====================================================
    # WAIT FOR SEARCH PAGE
    # =====================================================

    try:

        page.wait_for_url(
            "**/search-program",
            timeout=30000
        )

    except Exception:
        pass

    page.wait_for_timeout(5000)

    # =====================================================
    # VERIFY SEARCH INPUT EXISTS
    # =====================================================

    search_input = page.locator(
        'input[placeholder*="Search Program"]'
    )

    search_input.first.wait_for(
        state="visible",
        timeout=30000
    )

    print("Successfully opened Search Program page")


# =========================================================
# SELECT CURRENT PAGE
# =========================================================

def click_select_all_checkbox(page: Page):

    page.wait_for_timeout(1500)

    selectors = [
        'label:has-text("Select All")',
        'div:has-text("Select All")',
        'text="Select All"',
    ]

    for selector in selectors:

        locator = page.locator(selector)

        if safe_count(locator, page) == 0:
            continue

        for i in range(locator.count()):

            try:

                element = locator.nth(i)

                handle = element.element_handle()

                if not handle:
                    continue

                clicked = page.evaluate("""
                    element => {

                        let current = element;

                        while (current) {

                            const checkbox =
                                current.querySelector(
                                    'input[type="checkbox"]'
                                );

                            if (checkbox) {

                                checkbox.click();

                                checkbox.dispatchEvent(
                                    new Event(
                                        'change',
                                        {
                                            bubbles: true
                                        }
                                    )
                                );

                                return true;
                            }

                            current =
                                current.parentElement;
                        }

                        element.click();

                        return true;
                    }
                """, handle)

                if clicked:

                    print(
                        "Selected current page"
                    )

                    page.wait_for_timeout(2000)

                    return

            except Exception:
                continue

    raise ScraperError(
        "Unable to click Select All checkbox"
    )


# =========================================================
# NEXT PAGINATION
# =========================================================

def click_next_pagination(
    page: Page
) -> bool:

    page.wait_for_timeout(1500)

    arrows = page.locator(
        'path[d="M9.5 18L15.5 12L9.5 6"]'
    )

    count = safe_count(arrows, page)

    if count == 0:
        return False

    for i in range(count):

        try:

            svg = arrows.nth(i)

            handle = svg.element_handle()

            if not handle:
                continue

            result = page.evaluate("""
                element => {

                    let parent = element;

                    while (parent) {

                        if (
                            parent.tagName === 'BUTTON' ||
                            parent.getAttribute(
                                'role'
                            ) === 'button'
                        ) {

                            const disabled =
                                parent.disabled ||
                                parent.getAttribute(
                                    'disabled'
                                ) !== null ||
                                parent.getAttribute(
                                    'aria-disabled'
                                ) === 'true';

                            if (disabled) {
                                return false;
                            }

                            parent.click();

                            return true;
                        }

                        parent =
                            parent.parentElement;
                    }

                    return false;
                }
            """, handle)

            if result:

                try:

                    page.wait_for_load_state(
                        "networkidle",
                        timeout=10000
                    )

                except Exception:
                    pass

                page.wait_for_timeout(3000)

                print("Moved to next page")

                return True

        except Exception:
            continue

    return False


# =========================================================
# SELECT ALL PAGINATION RECORDS
# =========================================================

def select_all_results_across_pages(
    page: Page
):

    max_pages = 100

    for page_number in range(max_pages):

        print(
            f"Selecting page "
            f"{page_number + 1}"
        )

        click_select_all_checkbox(page)

        has_next = click_next_pagination(page)

        if not has_next:

            print(
                "Reached final page"
            )

            break


# =========================================================
# DOWNLOAD BUTTON
# =========================================================

def click_full_download_button(
    page: Page
):

    page.wait_for_timeout(2000)

    buttons = page.locator("button")

    count = safe_count(buttons, page)

    for i in range(count):

        try:

            btn = buttons.nth(i)

            text = (
                btn.inner_text()
                .strip()
                .lower()
            )

            if (
                text != "download" or
                "top 25" in text
            ):
                continue

            handle = btn.element_handle()

            if not handle:
                continue

            enabled = page.evaluate("""
                element => {

                    return !(
                        element.disabled ||
                        element.getAttribute(
                            'disabled'
                        ) !== null ||
                        element.getAttribute(
                            'aria-disabled'
                        ) === 'true'
                    );
                }
            """, handle)

            if not enabled:
                continue

            page.evaluate(
                "(el) => el.click()",
                handle
            )

            print(
                "Clicked Download button"
            )

            page.wait_for_timeout(3000)

            return

        except Exception:
            continue

    raise ScraperError(
        "Unable to click Download button"
    )


# =========================================================
# SELECT FIELDS
# =========================================================

def click_select_fields_button(
    page: Page
):

    page.wait_for_timeout(2000)

    selectors = [
        'button:has-text("Select Fields")',
        'text="Select Fields"',
    ]

    for selector in selectors:

        locator = page.locator(selector)

        if safe_count(locator, page) == 0:
            continue

        try:

            btn = locator.first

            handle = btn.element_handle()

            if handle:

                page.evaluate(
                    "(el) => el.click()",
                    handle
                )

                print(
                    "Clicked Select Fields"
                )

                page.wait_for_timeout(3000)

                return

        except Exception:
            continue

    raise ScraperError(
        "Unable to click Select Fields"
    )


# =========================================================
# MODAL SELECT ALL
# =========================================================

def click_modal_select_all(
    page: Page
):

    page.wait_for_timeout(2000)

    selectors = [
        'button:has-text("Select All")',
        'text="Select All"',
    ]

    for selector in selectors:

        locator = page.locator(selector)

        if safe_count(locator, page) == 0:
            continue

        for i in range(locator.count()):

            try:

                btn = locator.nth(i)

                text = btn.inner_text()

                if "Select All" not in text:
                    continue

                handle = btn.element_handle()

                if handle:

                    page.evaluate(
                        "(el) => el.click()",
                        handle
                    )

                    print(
                        "Clicked modal Select All"
                    )

                    page.wait_for_timeout(2000)

                    return

            except Exception:
                continue

    raise ScraperError(
        "Unable to click modal Select All"
    )


# =========================================================
# DOWNLOAD EXCEL
# =========================================================

def click_download_to_excel(
    page: Page
):

    page.wait_for_timeout(2000)

    selectors = [
        'button:has-text("Download to Excel")',
        'text="Download to Excel"',
    ]

    for selector in selectors:

        locator = page.locator(selector)

        if safe_count(locator, page) == 0:
            continue

        try:

            btn = locator.first

            handle = btn.element_handle()

            if handle:

                page.evaluate(
                    "(el) => el.click()",
                    handle
                )

                print(
                    "Clicked Download to Excel"
                )

                return

        except Exception:
            continue

    raise ScraperError(
        "Unable to click Download to Excel"
    )


# =========================================================
# MAIN SEARCH + DOWNLOAD
# =========================================================

def search_program_and_download(
    page: Page,
    query: str
) -> Path:

    if not query.strip():
        raise ScraperError(
            "Search query cannot be empty"
        )

    # =====================================================
    # SEARCH INPUT
    # =====================================================

    search_input = page.locator(
        'input[placeholder="Search Program / University"], '
        'input[placeholder*="Search Program / University"]'
    )

    search_input.first.wait_for(
        state="visible",
        timeout=DEFAULT_TIMEOUT_MS
    )

    search_input.first.fill("")

    page.wait_for_timeout(1000)

    search_input.first.fill(query)

    page.wait_for_timeout(1500)

    # =====================================================
    # SEARCH BUTTON
    # =====================================================

    search_button = page.locator(
        'button:has-text("Search")'
    )

    if safe_count(search_button, page) == 0:

        search_button = page.locator(
            'text="Search"'
        )

    if safe_count(search_button, page) == 0:
        raise ScraperError(
            "Search button not found"
        )

    safe_click(
        search_button.first,
        page
    )

    try:

        page.wait_for_load_state(
            "networkidle",
            timeout=DEFAULT_TIMEOUT_MS
        )

    except Exception:
        pass

    page.wait_for_timeout(5000)

    # =====================================================
    # SELECT ALL RECORDS
    # =====================================================

    print(
        f"Selecting all records for: "
        f"{query}"
    )

    select_all_results_across_pages(page)

    print("All records selected")

    # =====================================================
    # DOWNLOAD FLOW
    # =====================================================

    click_full_download_button(page)

    click_select_fields_button(page)

    click_modal_select_all(page)

    ensure_download_dir()

    with page.expect_download(
        timeout=120000
    ) as download_info:

        click_download_to_excel(page)

    download = download_info.value

    suggested = (
        download.suggested_filename
        or "download.xlsx"
    )

    output_path = _make_output_path(
        suggested,
        query
    )

    download.save_as(str(output_path))

    print(
        f"Downloaded: {output_path}"
    )

    return output_path


# =========================================================
# PLAYWRIGHT INSTALL
# =========================================================

def install_playwright_browsers():

    try:

        subprocess.run(
            [
                sys.executable,
                "-m",
                "playwright",
                "install",
                "chromium",
            ],
            check=True,
        )

    except Exception as exc:

        raise ScraperError(
            f"Playwright install failed: {exc}"
        )


# =========================================================
# RUN SCRAPER
# =========================================================

def run_scraper(
    email: str,
    password: str,
    queries: List[str],
    headless: bool = True,
) -> List[Dict[str, Any]]:

    results = []

    with sync_playwright() as playwright:

        try:

            browser = playwright.chromium.launch(
                headless=headless
            )

        except PlaywrightError:

            install_playwright_browsers()

            browser = playwright.chromium.launch(
                headless=headless
            )

        context = browser.new_context(
            accept_downloads=True
        )

        page = context.new_page()

        try:

            cookies_loaded = load_cookies(
                context
            )

            if cookies_loaded:

                page.goto(
                    DEFAULT_DASHBOARD_URL,
                    timeout=DEFAULT_TIMEOUT_MS
                )

                page.wait_for_timeout(5000)

            else:

                page.goto(
                    DEFAULT_LOGIN_URL,
                    timeout=DEFAULT_TIMEOUT_MS
                )

                page.wait_for_timeout(5000)

            if not is_session_active(page):

                login_with_credentials(
                    page,
                    email,
                    password
                )

            navigate_to_search_program(
                page
            )

            for query in queries:

                try:

                    path = (
                        search_program_and_download(
                            page,
                            query
                        )
                    )

                    results.append({
                        "query": query,
                        "success": True,
                        "filename": str(path),
                        "error": None,
                    })

                except Exception as exc:

                    results.append({
                        "query": query,
                        "success": False,
                        "filename": None,
                        "error": str(exc),
                    })

        finally:

            browser.close()

    return results


# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":

    email, password = get_env_credentials()

    queries = [
        "Master of Accountancy",
        "PhD Accounting",
    ]

    result = run_scraper(
        email=email,
        password=password,
        queries=queries,
        headless=False,
    )

    print(
        json.dumps(
            result,
            indent=2
        )
    )