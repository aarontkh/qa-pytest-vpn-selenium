"""
pages/subdomain_page.py
=======================
Page Object for a DL redirect subdomain (e.g. https://get1.pulsebrowser.net).

Pass condition: the page loads AND the final URL contains the expected
redirect target (pulsebrowser.com).  Any Chrome error OR a redirect to
an unexpected destination is treated as BLOCKED.

On block, a screenshot is saved to screenshots/ if ip_info and date_str
are provided — matching the same behaviour as DomainPage on failure.
"""

import logging
import os
import re

from core.browser import BasePage, BrowserFactory
from core.config import SUBDOMAIN_TIMEOUT, SUBDOMAIN_REDIRECT_TARGET, SCREENSHOT_DIR
from core.reporting import save_screenshot

logger = logging.getLogger(__name__)


class SubdomainPage(BasePage):
    """
    Tests whether a download-redirect subdomain resolves and redirects
    correctly.

    Usage::

        page = SubdomainPage(factory, "https://get1.pulsebrowser.net")
        is_blocked = page.is_blocked(ip_info, date_str)   # True = blocked, False = OK
    """

    WAIT_AFTER_LOAD = 3

    def __init__(self, factory: BrowserFactory, url: str):
        super().__init__(factory)
        self.url = url

    @property
    def label(self) -> str:
        """Short label extracted from the URL, e.g. 'get1'."""
        m = re.search(r"https?://(get\d+)\.", self.url)
        return m.group(1) if m else self.url

    def is_blocked(
        self,
        ip_info: dict | None = None,
        date_str: str = "",
    ) -> bool:
        """
        Return ``True`` if the subdomain is blocked or misbehaving,
        ``False`` if it redirected successfully.

        *ip_info* and *date_str* are optional. When provided, a screenshot
        is saved to screenshots/ on block — same behaviour as DomainPage.
        """
        ok, err = self._navigate(self.url, SUBDOMAIN_TIMEOUT, wait=self.WAIT_AFTER_LOAD)

        if not ok:
            logger.info("  [BLOCKED] %s — %s", self.label, err)
            if ip_info and date_str:
                self._capture_screenshot(ip_info, date_str)
            return True

        current = self.current_url.lower()
        if SUBDOMAIN_REDIRECT_TARGET in current:
            logger.info("  [OK] %s — redirected to %s", self.label, SUBDOMAIN_REDIRECT_TARGET)
        else:
            logger.info("  [OK] %s — loaded (url: %s)", self.label, current)

        return False

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _capture_screenshot(self, ip_info: dict, date_str: str) -> None:
        """
        Open a fresh browser, navigate to the URL, and save a screenshot
        of whatever the browser shows — including Chrome error pages.

        The get() call is wrapped separately so a TimeoutException or
        network error does not prevent the screenshot from being taken.
        """
        drv = tmp = None
        try:
            drv, tmp = self._factory.create()
            try:
                drv.get(self.url)
            except Exception:
                # Navigation failed — the Chrome error page is what we
                # want to capture so proceed to save the screenshot.
                pass
            os.makedirs(SCREENSHOT_DIR, exist_ok=True)
            save_screenshot(drv, self.label, ip_info, date_str)
        except Exception as exc:
            logger.warning("Screenshot capture failed for %s: %s", self.label, exc)
        finally:
            BrowserFactory.destroy(drv, tmp)