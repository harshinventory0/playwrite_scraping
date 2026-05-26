import json
import os
import random
import string
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from playwright.sync_api import Error as PlaywrightError, Page, TimeoutError as PlaywrightTimeoutError, sync_playwright
from datetime import datetime

DOWNLOAD_DIR = Path(os.getenv("DOWNLOADS_DIR", "downloads"))
COOKIES_PATH = Path(os.getenv("COOKIES_PATH", "cookies.json"))
DEFAULT_LOGIN_URL = "https://www.coursefinder.ai/"
DEFAULT_DASHBOARD_URL = "https://www.coursefinder.ai/dashboard"
DEFAULT_SEARCH_URL = "https://www.coursefinder.ai/search-program"

DEFAULT_TIMEOUT_SECONDS = int(os.getenv('SCRAPER_TIMEOUT', '30'))
DEFAULT_TIMEOUT_MS = DEFAULT_TIMEOUT_SECONDS * 1000


class ScraperError(Exception):
    pass


def _is_execution_context_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return 'execution context was destroyed' in text or 'context was destroyed' in text or 'navigation' in text


def safe_count(locator_or_selector, page=None, retries: int = 2) -> int:
    """Safely return a locator count. Accepts either a Locator object or a selector string with a Page provided."""
    for attempt in range(retries):
        try:
            if isinstance(locator_or_selector, str):
                return page.locator(locator_or_selector).count()
            return locator_or_selector.count()
        except Exception as exc:
            if _is_execution_context_error(exc):
                time.sleep(0.5)
                if page:
                    try:
                        page.wait_for_load_state('networkidle', timeout=5000)
                    except Exception:
                        pass
                continue
            raise
    # Final attempt (best-effort)
    try:
        if isinstance(locator_or_selector, str):
            return page.locator(locator_or_selector).count()
        return locator_or_selector.count()
    except Exception:
        return 0


def safe_is_visible(locator, retries: int = 2) -> bool:
    for attempt in range(retries):
        try:
            return locator.first.is_visible()
        except Exception as exc:
            if _is_execution_context_error(exc):
                time.sleep(0.5)
                continue
            raise
    return False


def safe_scroll_into_view(locator, retries: int = 2) -> None:
    for attempt in range(retries):
        try:
            # Locator has scroll_into_view_if_needed
            locator.first.scroll_into_view_if_needed()
            return
        except Exception as exc:
            if _is_execution_context_error(exc):
                time.sleep(0.5)
                continue
            raise
    # final best-effort attempt
    try:
        locator.first.scroll_into_view_if_needed()
    except Exception:
        pass


def load_env_vars() -> None:
    load_dotenv()


def get_env_credentials() -> Tuple[str, str]:
    load_env_vars()
    email = os.getenv("SCRAPER_EMAIL", "").strip()
    password = os.getenv("SCRAPER_PASSWORD", "").strip()
    if not email or not password:
        raise ScraperError(
            "SCRAPER_EMAIL and SCRAPER_PASSWORD must be set in .env or passed explicitly."
        )
    return email, password


def random_email() -> str:
    token = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
    return f'user+{token}@example.com'


def ensure_download_dir() -> None:
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _sanitize_slug(text: str, max_len: int = 40) -> str:
    safe = ''.join(c for c in text if c.isalnum() or c in (' ', '_', '-'))
    return safe.strip().replace(' ', '_')[:max_len]


def _make_output_path(suggested_filename: str, query: str) -> Path:
    ensure_download_dir()
    stem = Path(suggested_filename).stem or 'downloaded_file'
    ext = Path(suggested_filename).suffix or '.xlsx'
    safe_prefix = _sanitize_slug(query)
    ts = datetime.utcnow().strftime('%Y%m%dT%H%M%S')
    filename = f"{safe_prefix}_{ts}_{stem}{ext}"
    return DOWNLOAD_DIR / filename


def save_cookies(context: Any, path: Path = COOKIES_PATH) -> None:
    cookies = context.cookies()
    with path.open('w', encoding='utf-8') as cookie_file:
        json.dump(cookies, cookie_file, indent=2)


def load_cookies(context: Any, path: Path = COOKIES_PATH) -> bool:
    try:
        with path.open('r', encoding='utf-8') as cookie_file:
            cookies = json.load(cookie_file)
    except (FileNotFoundError, json.JSONDecodeError):
        return False

    if not isinstance(cookies, list) or len(cookies) == 0:
        return False

    try:
        context.add_cookies(cookies)
        return True
    except Exception as exc:
        raise ScraperError(f'Unable to load cookies from {path}: {exc}')


def is_session_active(page: Page) -> bool:
    if 'login' in page.url.lower():
        return False

    login_buttons = page.locator('button:has-text("Login")')
    login_text = page.locator('text="Login to coursefinder.ai"')
    if safe_count(login_buttons, page) > 0 or safe_count(login_text, page) > 0:
        return False

    search_programs = page.locator('button:has-text("Search Programs")')
    search_text = page.locator('text="Search Programs"')
    return safe_count(search_programs, page) > 0 or safe_count(search_text, page) > 0 or '/dashboard' in page.url


def safe_click(locator: Any, page: Page) -> None:
    try:
        locator.click()
    except Exception:
        try:
            locator.click(force=True)
        except Exception:
            handle = locator.element_handle()
            if handle:
                page.evaluate(
                    'element => { const clickable = element.closest("button, a"); if (clickable) clickable.click(); else element.click(); }',
                    handle,
                )
            else:
                raise


def navigate_to_search_program(page: Page) -> None:
    search_programs = page.locator('button:has-text("Search Programs")')
    if safe_count(search_programs, page) == 0:
        search_programs = page.locator('text="Search Programs"')

    search_programs.first.wait_for(state='visible', timeout=DEFAULT_TIMEOUT_MS)
    search_programs.first.hover()
    page.wait_for_timeout(1500)
    safe_click(search_programs.first, page)
    page.wait_for_url('**/search-program', timeout=DEFAULT_TIMEOUT_MS)

    search_input = page.locator('input[placeholder="Search Program / University"], input[placeholder*="Search Program / University"]')
    search_input.first.wait_for(state='visible', timeout=DEFAULT_TIMEOUT_MS)
    page.wait_for_timeout(1000)


def login_with_credentials(page: Page, email: str, password: str) -> None:
    login_button = page.locator('button:has-text("Login to coursefinder.ai")')
    if safe_count(login_button, page) == 0:
        login_button = page.locator('text="Login to coursefinder.ai"')
    if safe_count(login_button, page) == 0:
        login_button = page.locator('button:has-text("Login")')

    if safe_count(login_button, page) == 0:
        raise ScraperError('Unable to find the login button on the page.')

    login_button.first.wait_for(state='visible', timeout=DEFAULT_TIMEOUT_MS)
    safe_click(login_button.first, page)
    page.wait_for_load_state('networkidle', timeout=DEFAULT_TIMEOUT_MS)

    email_input = page.locator(
        'input.kinde-control-select-text, .kinde-control-select-text input, input[type="email"], input[placeholder*="email"]'
    )
    email_input.first.wait_for(state='visible', timeout=DEFAULT_TIMEOUT_MS)
    email_input.first.fill(email)
    page.wait_for_timeout(1000)

    submit_button = page.locator(
        'button.kinde-button.kinde-button-variant-primary, button:has-text("Continue"), button:has-text("Next")'
    )
    if safe_count(submit_button, page) > 0:
        safe_click(submit_button.first, page)
        page.wait_for_timeout(1500)

    page.wait_for_load_state('networkidle', timeout=DEFAULT_TIMEOUT_MS)

    password_input = page.locator('input[type="password"], input[name="password"], input[placeholder*="Password"]')
    email_error = page.locator('text="No account found with this email"')

    try:
        password_input.first.wait_for(state='visible', timeout=DEFAULT_TIMEOUT_MS)
    except PlaywrightTimeoutError:
        if safe_count(email_error, page) > 0:
            raise ScraperError('Email validation error: ' + email_error.first.inner_text().strip())
        raise ScraperError(
            'Password screen was not reached after email submit. The login flow may have changed or the email may not have been accepted.'
        )

    password_input.first.fill(password)
    page.wait_for_timeout(1000)

    continue_button = page.locator(
        'button.kinde-button.kinde-button-variant-primary:has-text("Continue"), button:has-text("Continue")'
    )
    if safe_count(continue_button, page) > 0:
        safe_click(continue_button.first, page)
        page.wait_for_timeout(1500)

    page.wait_for_load_state('networkidle', timeout=DEFAULT_TIMEOUT_MS)

    validation_selectors = [
        'text=Passwords need to be at least 8 characters',
        'text=Please provide a valid password',
        'text=No account found with this email',
        '.error',
        '.input-error',
        '.validation-message',
        '.kinde-error',
    ]

    for selector in validation_selectors:
        locator = page.locator(selector)
        if safe_count(locator, page) > 0:
            try:
                locator.first.wait_for(state='visible', timeout=5000)
                message = locator.first.inner_text().strip()
                if message:
                    raise ScraperError('Login validation error: ' + message)
            except PlaywrightTimeoutError:
                continue

    if safe_count(password_input, page) > 0 and safe_is_visible(password_input):
        raise ScraperError('Password screen is still visible after submitting credentials. Login likely failed.')

    save_cookies(page.context)


def search_program_and_download(page: Page, query: str) -> Path:
    if not query.strip():
        raise ScraperError('Search query must not be empty.')

    search_input = page.locator('input[placeholder="Search Program / University"], input[placeholder*="Search Program / University"]')
    search_input.first.wait_for(state='visible', timeout=DEFAULT_TIMEOUT_MS)
    search_input.first.fill(query)
    page.wait_for_timeout(1000)

    search_button = page.locator('button:has-text("Search")')
    if safe_count(search_button, page) == 0:
        search_button = page.locator('text="Search"')
    if safe_count(search_button, page) == 0:
        raise ScraperError('Unable to find the Search button.')

    search_button.first.wait_for(state='visible', timeout=DEFAULT_TIMEOUT_MS)
    safe_click(search_button.first, page)

    # Wait for results to load and the download button to appear; poll to handle
    # client-side rendering and potential navigations.
    page.wait_for_load_state('networkidle', timeout=DEFAULT_TIMEOUT_MS)

    def _find_download_locator() -> Optional[Any]:
        # Try multiple selector strategies
        candidates = [
            'span:has-text("Download Top 25")',
            'button:has-text("Download Top 25")',
            'a:has-text("Download Top 25")',
            'text="Download Top 25"',
            'button:has-text("Download")',
            'text="Download"',
        ]
        for sel in candidates:
            loc = page.locator(sel)
            if safe_count(loc, page) > 0:
                return loc
        return None

    download_button = None
    start = datetime.utcnow()
    timeout_seconds = 20
    while (datetime.utcnow() - start).total_seconds() < timeout_seconds:
        download_button = _find_download_locator()
        if download_button is not None:
            break
        time.sleep(0.5)
        try:
            page.wait_for_load_state('networkidle', timeout=DEFAULT_TIMEOUT_MS if DEFAULT_TIMEOUT_MS < 5000 else 5000)
        except Exception:
            pass

    if download_button is None:
        # Save debug artifacts to help triage
        safe_prefix = ''.join(c for c in query if c.isalnum() or c in (' ', '_', '-')).strip().replace(' ', '_')[:40]
        ts = datetime.utcnow().strftime('%Y%m%dT%H%M%S')
        debug_dir = DOWNLOAD_DIR / 'debug'
        debug_dir.mkdir(parents=True, exist_ok=True)
        html_path = debug_dir / f'{safe_prefix}_{ts}.html'
        png_path = debug_dir / f'{safe_prefix}_{ts}.png'
        try:
            with html_path.open('w', encoding='utf-8') as fh:
                fh.write(page.content())
        except Exception:
            pass
        try:
            page.screenshot(path=str(png_path), full_page=True)
        except Exception:
            pass
        raise ScraperError(f'Unable to find the Download Top 25 button for query: {query}. Debug files: {html_path}, {png_path}')

    download_button = page.locator('span:has-text("Download Top 25")')
    if safe_count(download_button, page) == 0:
        download_button = page.locator('button:has-text("Download Top 25")')
    if safe_count(download_button, page) == 0:
        download_button = page.locator('a:has-text("Download Top 25")')
    if safe_count(download_button, page) == 0:
        download_button = page.locator('text="Download Top 25"')
    if safe_count(download_button, page) == 0:
        raise ScraperError('Unable to find the Download Top 25 button for query: ' + query)

    download_button.first.wait_for(state='attached', timeout=DEFAULT_TIMEOUT_MS)
    try:
        download_button.first.wait_for(state='visible', timeout=DEFAULT_TIMEOUT_MS)
    except PlaywrightTimeoutError:
        pass

    safe_scroll_into_view(download_button)
    page.wait_for_timeout(1000)
    safe_click(download_button.first, page)

    select_all_button = page.locator('button.SelectedFieldsToDownload_clearBtn___QDps:has-text("Select All")')
    if safe_count(select_all_button, page) == 0:
        select_all_button = page.locator('button:has-text("Select All")')
    select_all_button.first.wait_for(state='visible', timeout=DEFAULT_TIMEOUT_MS)
    safe_scroll_into_view(select_all_button)
    page.wait_for_timeout(1000)
    safe_click(select_all_button.first, page)
    page.wait_for_timeout(1000)

    download_excel_button = page.locator('button:has-text("Download to Excel")')
    if safe_count(download_excel_button, page) == 0:
        download_excel_button = page.locator('text="Download to Excel"')
    if safe_count(download_excel_button, page) == 0:
        raise ScraperError('Unable to find the Download to Excel button for query: ' + query)

    download_excel_button.first.wait_for(state='visible', timeout=DEFAULT_TIMEOUT_MS)
    safe_scroll_into_view(download_excel_button)
    page.wait_for_timeout(1000)

    ensure_download_dir()
    with page.expect_download(timeout=120000) as download_info:
        safe_click(download_excel_button.first, page)

    download = download_info.value
    suggested = download.suggested_filename or 'downloaded_file.xlsx'
    output_path = _make_output_path(suggested, query)
    download.save_as(str(output_path))
    return output_path


def run_scraper(
    email: str,
    password: str,
    queries: List[str],
    headless: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    if not queries:
        raise ScraperError('At least one search query is required.')

    load_env_vars()
    if headless is None:
        headless = os.getenv('HEADLESS', 'true').lower() in ('1', 'true', 'yes')

    results: List[Dict[str, Any]] = []

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=headless)
        except PlaywrightError as exc:
            if 'Executable doesn\'t exist' in str(exc) or 'playwright install' in str(exc).lower():
                install_playwright_browsers()
                browser = playwright.chromium.launch(headless=headless)
            else:
                raise

        context = browser.new_context(accept_downloads=True)
        page = context.new_page()

        try:
            cookies_loaded = False
            try:
                cookies_loaded = load_cookies(context)
            except ScraperError:
                cookies_loaded = False

            if cookies_loaded:
                page.goto(DEFAULT_DASHBOARD_URL, timeout=DEFAULT_TIMEOUT_MS)
                page.wait_for_load_state('networkidle', timeout=30000)
                if not is_session_active(page):
                    page.goto(DEFAULT_LOGIN_URL, timeout=30000)
                    page.wait_for_load_state('networkidle', timeout=30000)
            else:
                page.goto(DEFAULT_LOGIN_URL, timeout=30000)
                page.wait_for_load_state('networkidle', timeout=30000)

            if not is_session_active(page):
                login_with_credentials(page, email, password)

            navigate_to_search_program(page)

            for query in queries:
                try:
                    path = search_program_and_download(page, query)
                    results.append({
                        'query': query,
                        'success': True,
                        'filename': str(path),
                        'error': None,
                    })
                except Exception as exc:
                    results.append({
                        'query': query,
                        'success': False,
                        'filename': None,
                        'error': str(exc),
                    })

        finally:
            browser.close()

    return results


def install_playwright_browsers() -> None:
    try:
        subprocess.run(
            [sys.executable, '-m', 'playwright', 'install', 'chromium'],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise ScraperError(
            f'Failed to install Playwright Chromium binaries. stderr:\n{exc.stderr or exc}'
        ) from exc
    except FileNotFoundError as exc:
        raise ScraperError(
            'Unable to install Playwright browsers because the Python executable or Playwright module could not be found.'
        ) from exc
