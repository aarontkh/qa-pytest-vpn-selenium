"""
core/browser.py
===============
Browser lifecycle management and the Page Object Model base class.

BrowserFactory
    Creates and destroys Chrome WebDriver instances. Every browser gets
    a unique temporary user-data directory — no shared DNS cache, cookies,
    or session state between test rounds. Essential for geo-testing accuracy.

BasePage
    Base class for all Page Objects. Owns the retry logic (two-tier:
    in-session refresh vs full browser restart) so subclass page objects
    only need to describe *what* they are testing, not *how* to retry.
"""

import logging
import os
import re
import shutil
import tempfile
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import TimeoutException, WebDriverException
from webdriver_manager.chrome import ChromeDriverManager

from core.config import (
    MAX_RETRIES,
    RETRYABLE_IN_SESSION,
    CHROME_ERROR_CODES,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Chromedriver path — resolved once, cached for the process lifetime
# ---------------------------------------------------------------------------
_chromedriver_path: str | None = None


def _resolve_chromedriver() -> str:
    global _chromedriver_path
    if _chromedriver_path is not None:
        return _chromedriver_path

    path = ChromeDriverManager(driver_version=None).install()

    # webdriver_manager sometimes returns the zip path instead of the binary
    if not (path.endswith("chromedriver") or path.endswith("chromedriver.exe")):
        d = os.path.dirname(path)
        for fname in os.listdir(d):
            if fname.startswith("chromedriver") and not fname.endswith(".zip"):
                path = os.path.join(d, fname)
                break

    logger.info("ChromeDriver resolved: %s", path)
    _chromedriver_path = path
    return path


# ---------------------------------------------------------------------------
# Chrome error detection (kept here so BasePage can use it internally)
# ---------------------------------------------------------------------------

def _detect_error_in_source(page_source: str) -> str | None:
    upper = page_source.upper()
    for code in CHROME_ERROR_CODES:
        if code in upper:
            return code
    lower = page_source.lower()
    if "this site can" in lower and "reached" in lower:
        m = re.search(r"(ERR_[A-Z_]+|DNS_[A-Z_]+)", page_source, re.IGNORECASE)
        return m.group(1).upper() if m else "SITE_CANNOT_BE_REACHED"
    return None


def _detect_error_in_exception(exc: Exception) -> str:
    m = re.search(r"(ERR_[A-Z_]+|DNS_[A-Z_]+)", str(exc), re.IGNORECASE)
    if m:
        return m.group(1).upper()
    return "ERR_TIMED_OUT" if "timeout" in str(exc).lower() else "UNKNOWN_ERROR"


def _detect_error_from_driver(driver) -> str | None:
    try:
        err = _detect_error_in_source(driver.page_source)
        if err:
            return err
    except Exception:
        pass
    try:
        title = (driver.title or "").upper()
        for code in CHROME_ERROR_CODES:
            if code in title:
                return code
        if "not found" in title.lower() or "can't be reached" in title.lower():
            return "SITE_CANNOT_BE_REACHED"
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# BrowserFactory
# ---------------------------------------------------------------------------

class BrowserFactory:
    """
    Creates headless or visible Chrome instances with clean temp profiles.

    Usage::

        factory = BrowserFactory(headless=True)
        driver, tmp = factory.create()
        ...
        factory.destroy(driver, tmp)
    """

    def __init__(self, headless: bool = True, page_load_timeout: int = 90):
        self.headless = headless
        self.page_load_timeout = page_load_timeout
        # Resolve chromedriver once at factory construction time
        _resolve_chromedriver()

    def create(self) -> tuple[webdriver.Chrome, str]:
        """Return a fresh (driver, temp_profile_dir) pair."""
        tmp = tempfile.mkdtemp(prefix="starvpn_")
        opts = Options()
        if self.headless:
            opts.add_argument("--headless=new")
        for arg in [
            f"--user-data-dir={tmp}",
            "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
            "--window-size=1920,1080", "--ignore-certificate-errors",
            "--disable-extensions", "--disable-popup-blocking",
            "--disable-application-cache", "--disable-cache",
            "--disk-cache-size=0", "--aggressive-cache-discard",
            "--dns-prefetch-disable", "--no-first-run",
            "--no-default-browser-check",
        ]:
            opts.add_argument(arg)

        svc = Service(executable_path=_resolve_chromedriver())
        driver = webdriver.Chrome(service=svc, options=opts)
        driver.set_page_load_timeout(self.page_load_timeout)
        return driver, tmp

    @staticmethod
    def destroy(driver: webdriver.Chrome | None, tmp: str | None) -> None:
        """Safely quit driver and delete the temp profile."""
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
        if tmp and os.path.exists(tmp):
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# BasePage — Page Object Model root
# ---------------------------------------------------------------------------

class BasePage:
    """
    Root Page Object.  Subclasses represent individual testable surfaces
    (a marketing domain, a redirect subdomain, a login page, etc.).

    Retry contract
    --------------
    - Up to MAX_RETRIES total attempts per navigation.
    - Errors in RETRYABLE_IN_SESSION → page.refresh() in the same browser.
    - All other errors → full browser teardown + fresh launch.

    Subclass contract
    -----------------
    Subclasses call ``self._navigate(url, timeout, wait_after)`` and
    inspect ``self.current_url`` / ``self.page_source`` to implement
    their pass/fail logic.  They never touch the driver directly.
    """

    def __init__(self, factory: BrowserFactory):
        self._factory = factory
        self._driver: webdriver.Chrome | None = None
        self._tmp: str | None = None

    # ------------------------------------------------------------------
    # Internal: browser lifecycle
    # ------------------------------------------------------------------

    def _open(self) -> None:
        self._driver, self._tmp = self._factory.create()

    def _close(self) -> None:
        BrowserFactory.destroy(self._driver, self._tmp)
        self._driver = None
        self._tmp = None

    # ------------------------------------------------------------------
    # Internal: single navigation attempt
    # ------------------------------------------------------------------

    def _try_get(self, url: str, timeout: int, wait: int) -> tuple[bool, str | None]:
        """
        One navigation attempt.  Returns (success, error_code).
        success=True means the page loaded without a detectable Chrome error.
        """
        try:
            self._driver.set_page_load_timeout(timeout)
            self._driver.get(url)
            time.sleep(wait)
            err = _detect_error_in_source(self._driver.page_source)
            return (False, err) if err else (True, None)
        except TimeoutException:
            return False, _detect_error_from_driver(self._driver) or "ERR_TIMED_OUT"
        except WebDriverException as exc:
            return False, _detect_error_from_driver(self._driver) or _detect_error_in_exception(exc)

    # ------------------------------------------------------------------
    # Protected: navigate with full retry (called by subclasses)
    # ------------------------------------------------------------------

    def _navigate(self, url: str, timeout: int, wait: int = 3) -> tuple[bool, str | None]:
        """
        Navigate to *url* with two-tier retry logic.

        Returns ``(True, None)`` on success or
        ``(False, error_code)`` after all retries are exhausted.
        """
        last_error: str | None = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                self._open()
                in_session = 0

                while True:
                    ok, err = self._try_get(url, timeout, wait)
                    if ok:
                        return True, None

                    in_session += 1
                    if err in RETRYABLE_IN_SESSION and in_session < MAX_RETRIES:
                        logger.info("  [RETRY in-session] %s — %s (%d/%d)", url, err, in_session, MAX_RETRIES)
                        time.sleep(3)
                        continue

                    last_error = err
                    break

            except Exception as exc:
                last_error = (_detect_error_from_driver(self._driver) or "UNEXPECTED")
            finally:
                self._close()

            if attempt < MAX_RETRIES:
                logger.info("  [RETRY fresh browser] %s — %s (%d/%d)", url, last_error, attempt, MAX_RETRIES)
                time.sleep(3)

        return False, last_error

    # ------------------------------------------------------------------
    # Properties subclasses may read (only valid during _navigate)
    # ------------------------------------------------------------------

    @property
    def current_url(self) -> str:
        try:
            return self._driver.current_url if self._driver else ""
        except Exception:
            return ""

    @property
    def page_source(self) -> str:
        try:
            return self._driver.page_source if self._driver else ""
        except Exception:
            return ""

    def save_screenshot(self, path: str) -> bool:
        """Save a PNG screenshot to *path*. Returns True on success."""
        try:
            if self._driver:
                self._driver.save_screenshot(path)
                return True
        except Exception:
            pass
        return False
