# =========================================================
# IMPORTS
# =========================================================

# Standard library imports
import json
import os
import random
import string
import subprocess
import sys
import time

# Date & time utilities
from datetime import datetime

# File path handling
from pathlib import Path

# Typing support
from typing import Any, Dict, List, Optional, Tuple

# Load environment variables from .env
from dotenv import load_dotenv

# Excel merging
import pandas as pd

# Playwright sync API imports
from playwright.sync_api import (
    Error as PlaywrightError,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

# =========================================================
# CONFIGURATION
# =========================================================

# Directory where downloaded Excel files will be stored
DOWNLOAD_DIR = Path(
    os.getenv("DOWNLOADS_DIR", "downloads")
)

# Cookie storage file
COOKIES_PATH = Path(
    os.getenv("COOKIES_PATH", "cookies.json")
)

# URLs
DEFAULT_LOGIN_URL = "https://www.coursefinder.ai/"
DEFAULT_DASHBOARD_URL = (
    "https://www.coursefinder.ai/dashboard"
)

# Timeout configuration
DEFAULT_TIMEOUT_SECONDS = int(
    os.getenv("SCRAPER_TIMEOUT", "30")
)

DEFAULT_TIMEOUT_MS = (
    DEFAULT_TIMEOUT_SECONDS * 1000
)

# =========================================================
# CUSTOM EXCEPTION
# =========================================================

class ScraperError(Exception):
    """
    Custom exception used throughout scraper.
    """
    pass


# =========================================================
# HELPER FUNCTIONS
# =========================================================

def load_env_vars() -> None:
    """
    Load .env variables into environment.
    """

    load_dotenv()


def get_env_credentials() -> Tuple[str, str]:
    """
    Read scraper credentials from .env file.
    """

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
            "SCRAPER_EMAIL and "
            "SCRAPER_PASSWORD must exist in .env"
        )

    return email, password


def ensure_download_dir() -> None:
    """
    Create downloads directory if it doesn't exist.
    """

    DOWNLOAD_DIR.mkdir(
        parents=True,
        exist_ok=True
    )


def random_email() -> str:
    """
    Generate random email.
    Mostly useful for testing.
    """

    token = ''.join(
        random.choices(
            string.ascii_lowercase +
            string.digits,
            k=10
        )
    )

    return f"user+{token}@example.com"


def safe_count(locator_or_selector, page=None) -> int:
    """
    Safely count matching Playwright locators.
    Prevents scraper crash on invalid selectors.
    """

    try:

        if isinstance(locator_or_selector, str):

            return page.locator(
                locator_or_selector
            ).count()

        return locator_or_selector.count()

    except Exception:
        return 0


def safe_click(locator, page: Page) -> None:
    """
    Robust click helper.

    Tries:
    1. Normal click
    2. Force click
    3. JavaScript click fallback
    """

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


def save_cookies(
    context,
    path=COOKIES_PATH
):
    """
    Save browser cookies locally.
    Helps avoid repeated logins.
    """

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


def load_cookies(
    context,
    path=COOKIES_PATH
):
    """
    Load saved cookies into browser context.
    """

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
    """
    Check whether user is already logged in.
    """

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
    """
    Clean filename-safe text.
    """

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
    """
    Generate final output file path.
    """

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
    """
    Login to CourseFinder AI.
    """

    # Find login button
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

    # Fill email
    email_input = page.locator(
        'input[type="email"]'
    )

    email_input.first.fill(email)

    page.wait_for_timeout(1000)

    # Continue
    continue_button = page.locator(
        'button:has-text("Continue")'
    )

    safe_click(
        continue_button.first,
        page
    )

    page.wait_for_timeout(3000)

    # Fill password
    password_input = page.locator(
        'input[type="password"]'
    )

    password_input.first.fill(password)

    page.wait_for_timeout(1000)

    # Submit login
    continue_button = page.locator(
        'button:has-text("Continue")'
    )

    safe_click(
        continue_button.first,
        page
    )

    page.wait_for_timeout(5000)

    # Save session cookies
    save_cookies(page.context)


# =========================================================
# NAVIGATION
# =========================================================

def navigate_to_search_program(
    page: Page
) -> None:
    """
    Navigate to Search Program page.

    Handles:
    - SPA rendering delay
    - hydration issues
    - async redirects
    """

    print("Navigating to dashboard...")

    # Open dashboard
    page.goto(
        DEFAULT_DASHBOARD_URL,
        wait_until="domcontentloaded",
        timeout=60000
    )

    # Give React app time to load
    page.wait_for_timeout(5000)

    # Wait for network to stabilize
    try:

        page.wait_for_load_state(
            "networkidle",
            timeout=15000
        )

    except Exception:
        pass

    page.wait_for_timeout(3000)

    # Multiple selectors for reliability
    selectors = [
        'button:has-text("Search Programs")',
        'text="Search Programs"',
        'a:has-text("Search Programs")',
        '[href*="search-program"]',
    ]

    search_program_button = None

    # Try locating Search Program button
    for selector in selectors:

        try:

            locator = page.locator(selector)

            count = safe_count(
                locator,
                page
            )

            if count == 0:
                continue

            for i in range(count):

                try:

                    candidate = locator.nth(i)

                    if candidate.is_visible():

                        search_program_button = candidate

                        break

                except Exception:
                    continue

            if search_program_button:
                break

        except Exception:
            continue

    # Fallback direct navigation
    if not search_program_button:

        print(
            "Search Programs button not found. "
            "Using direct navigation."
        )

        page.goto(
            "https://www.coursefinder.ai/search-program"
        )

        page.wait_for_timeout(5000)

        return

    print("Clicking Search Programs")

    # Click button
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

    # Wait for URL
    try:

        page.wait_for_url(
            "**/search-program",
            timeout=30000
        )

    except Exception:
        pass

    page.wait_for_timeout(5000)

    # Verify search input exists
    search_input = page.locator(
        'input[placeholder*="Search Program"]'
    )

    search_input.first.wait_for(
        state="visible",
        timeout=30000
    )

    print(
        "Successfully opened Search Program page"
    )


# =========================================================
# SELECT CURRENT PAGE RECORDS
# =========================================================

def click_select_all_checkbox(
    page: Page
):
    """
    Click Select All checkbox
    for current pagination page.
    """

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

                # Find nearby checkbox
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
    """
    Click next pagination arrow.

    Returns:
    - True -> next page exists
    - False -> reached last page
    """

    page.wait_for_timeout(1500)

    # SVG arrow selector
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

            # Traverse to clickable parent
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
    """
    Select records across all pages.
    """

    max_pages = 100

    for page_number in range(max_pages):

        print(
            f"Selecting page "
            f"{page_number + 1}"
        )

        # Select current page records
        click_select_all_checkbox(page)

        # Move next
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
    """
    Click main Download button.

    Important:
    Avoids 'Download Top 25'.
    """

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

            # Ignore Download Top 25
            if (
                text != "download" or
                "top 25" in text
            ):
                continue

            handle = btn.element_handle()

            if not handle:
                continue

            # Ensure enabled
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
# SELECT FIELDS MODAL
# =========================================================

def click_select_fields_button(
    page: Page
):
    """
    Open Select Fields modal.
    """

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
    """
    Select all export fields inside modal.
    """

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
    """
    Click final Download to Excel button.
    """

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


def _download_current_page(
    page: Page,
    query: str,
    page_index: int = 1,
) -> Path:
    """
    Select all records on the current page and download that page's Excel.
    Returns the saved Path.
    """

    # Select current page records
    click_select_all_checkbox(page)

    # Trigger download flow for this page
    click_full_download_button(page)

    click_select_fields_button(page)

    click_modal_select_all(page)

    ensure_download_dir()

    # Wait for download event
    with page.expect_download(timeout=120000) as download_info:

        click_download_to_excel(page)

    download = download_info.value

    suggested = download.suggested_filename or f"download_page_{page_index}.xlsx"

    # Make path; include page index to ensure ordering
    output_path = _make_output_path(suggested, f"{query}_page{page_index}")

    download.save_as(str(output_path))

    print(f"Downloaded page {page_index}: {output_path}")

    # Unselect the current page records to avoid hitting selection limits
    try:

        # Clicking 'Select All' again should toggle/unselect the current page
        click_select_all_checkbox(page)

        page.wait_for_timeout(1000)

        print(f"Unselected page {page_index}")

    except Exception:

        print(
            f"Warning: failed to unselect records on page {page_index}"
        )

    return output_path


def _merge_excels(
    paths: List[Path],
    output_path: Optional[Path] = None,
) -> Path:
    """
    Merge multiple Excel files into a single Excel file.

    - Reads each file with pandas, concatenates rows, writes combined file.
    - Returns Path to combined file.
    """

    if not paths:
        raise ScraperError("No files to merge")

    dfs = []

    for p in paths:

        try:
            df = pd.read_excel(p)
            dfs.append(df)
        except Exception as exc:
            raise ScraperError(f"Failed reading Excel {p}: {exc}")

    combined = pd.concat(dfs, ignore_index=True, sort=False)

    if output_path is None:
        # Use query-derived name from first path
        ts = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
        output_path = DOWNLOAD_DIR / f"combined_{ts}.xlsx"

    try:
        combined.to_excel(output_path, index=False, engine="openpyxl")
    except Exception as exc:
        raise ScraperError(f"Failed writing combined Excel: {exc}")

    print(f"Merged {len(paths)} files -> {output_path}")

    return output_path


# =========================================================
# SEARCH + DOWNLOAD FLOW
# =========================================================

def search_program_and_download(
    page: Page,
    query: str
) -> Path:
    """
    Complete search + download workflow.
    """

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

    # Clear old query
    search_input.first.fill("")

    page.wait_for_timeout(1000)

    # Enter new query
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

    # Wait for results
    try:

        page.wait_for_load_state(
            "networkidle",
            timeout=DEFAULT_TIMEOUT_MS
        )

    except Exception:
        pass

    page.wait_for_timeout(5000)

    # =====================================================
    # SELECT ALL RESULTS
    # =====================================================

    print(f"Starting per-page downloads for: {query}")

    page_files: List[Path] = []

    page_index = 1

    # Loop through pagination, downloading each page separately
    while True:

        print(f"Processing page {page_index}")

        # Download current page
        path = _download_current_page(page, query, page_index)

        page_files.append(path)

        # Move to next page if available
        has_next = click_next_pagination(page)

        if not has_next:

            print("Reached final page")

            break

        page_index += 1

    # If only one page file, return it directly
    if len(page_files) == 1:

        return page_files[0]

    # Merge multiple page files into a single workbook
    combined_suggested = f"combined_{_sanitize_slug(query)}.xlsx"

    combined_path = _make_output_path(combined_suggested, query)

    merged = _merge_excels(page_files, output_path=combined_path)

    # Cleanup individual page files
    for p in page_files:

        try:
            p.unlink()
        except Exception:
            print(f"Warning: failed to delete temp file {p}")

    return merged


# =========================================================
# PLAYWRIGHT INSTALLER
# =========================================================

def install_playwright_browsers():
    """
    Install Chromium browser binaries.
    """

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
# MAIN SCRAPER RUNNER
# =========================================================

def run_scraper(
    email: str,
    password: str,
    queries: List[str],
    headless: bool = True,
) -> List[Dict[str, Any]]:
    """
    Main scraper execution function.
    """

    results = []

    with sync_playwright() as playwright:

        try:

            # Launch browser
            browser = playwright.chromium.launch(
                headless=headless
            )

        except PlaywrightError:

            # Install browsers if missing
            install_playwright_browsers()

            browser = playwright.chromium.launch(
                headless=headless
            )

        # Create browser context
        context = browser.new_context(
            accept_downloads=True
        )

        # Create browser page
        page = context.new_page()

        try:

            # Try restoring session
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

            # Login if needed
            if not is_session_active(page):

                login_with_credentials(
                    page,
                    email,
                    password
                )

            # Open search program page
            navigate_to_search_program(
                page
            )

            # Process all queries
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

            # Close browser
            browser.close()

    return results


# =========================================================
# SCRIPT ENTRYPOINT
# =========================================================

if __name__ == "__main__":

    # Load credentials
    email, password = get_env_credentials()

    # Example queries
    queries = [
        "Master of Accountancy",
        "PhD Accounting",
    ]

    # Run scraper
    result = run_scraper(
        email=email,
        password=password,
        queries=queries,
        headless=False,
    )

    # Print final results
    print(
        json.dumps(
            result,
            indent=2
        )
    )