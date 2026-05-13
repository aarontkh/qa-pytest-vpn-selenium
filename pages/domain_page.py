"""
pages/domain_page.py
====================
Page Object for a marketing domain (e.g. https://pulsebrowser.net).

Pass condition: the page loads without a detectable Chrome error.
Failure triggers a screenshot before returning "FAIL".
"""

import logging
import os

from core.browser import BasePage, BrowserFactory
from core.config import PAGE_LOAD_TIMEOUT, SCREENSHOT_DIR
from core.reporting import display_name, screenshot_label, save_screenshot

logger = logging.getLogger(__name__)


class DomainPage(BasePage):
    """
    Tests whether a marketing domain loads successfully.

    Usage::

        page = DomainPage(factory, "https://pulsebrowser.net")
        result = page.test(ip_info, date_str)   # "PASS" or "FAIL"
    """

    WAIT_AFTER_LOAD = 5   # seconds — give JS-heavy pages time to settle

    def __init__(self, factory: BrowserFactory, url: str):
        super().__init__(factory)
        self.url   = url
        self._name = display_name(url)
        self._shot_label = screenshot_label(url)

    def test(self, ip_info: dict | None = None, date_str: str = "") -> str:
        """
        Navigate to the domain and return ``"PASS"`` or ``"FAIL"``.

        *ip_info* and *date_str* are used only for naming the failure
        screenshot — both are optional for callers that don't need it
        (e.g. the smoke test).
        """
        logger.info("Testing domain: %s", self._name)
        ok, err = self._navigate(self.url, PAGE_LOAD_TIMEOUT, wait=self.WAIT_AFTER_LOAD)

        if ok:
            logger.info("  [PASS] %s", self._name)
            return "PASS"

        logger.info("  [FAIL] %s — %s", self._name, err)

        # Screenshot: open a short-lived extra browser purely for capture
        if ip_info and date_str:
            self._capture_screenshot(ip_info, date_str)

        return "FAIL"

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _capture_screenshot(self, ip_info: dict, date_str: str) -> None:
        """Open a fresh browser, load the page, save a screenshot."""
        drv = tmp = None
        try:
            drv, tmp = self._factory.create()
            drv.get(self.url)
            os.makedirs(SCREENSHOT_DIR, exist_ok=True)
            save_screenshot(drv, self._shot_label, ip_info, date_str)
        except Exception as exc:
            logger.warning("Screenshot capture failed for %s: %s", self._name, exc)
        finally:
            BrowserFactory.destroy(drv, tmp)
