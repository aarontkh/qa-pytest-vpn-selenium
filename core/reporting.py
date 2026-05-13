"""
core/reporting.py
=================
Test result recording utilities.

All CSV and screenshot logic lives here so test files stay clean.
The CSV schema is driven entirely by the domain list — adding a URL
to tested_domains.txt automatically produces a new column with no code
changes required.
"""

import csv
import logging
import os
from datetime import datetime

from core.config import RESULTS_CSV, SCREENSHOT_DIR

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# URL / column naming helpers
# ---------------------------------------------------------------------------

def display_name(url: str) -> str:
    """https://pulsebrowser.net  →  pulsebrowser.net"""
    return url.replace("https://", "").replace("http://", "").rstrip("/")


def csv_column(url: str) -> str:
    """https://pulsebrowser.net  →  pulsebrowser.net Status"""
    return f"{display_name(url)} Status"


def screenshot_label(url: str) -> str:
    """https://pulsebrowser.net  →  pulsebrowser_net  (filesystem-safe)"""
    return display_name(url).replace(".", "_").replace("/", "_")


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

FIXED_COLUMNS = ["Date", "Time", "ISP", "Tested IP", "Location", "ASN", "Blocked DL Subdomains"]


def build_headers(domain_urls: list[str]) -> list[str]:
    """
    Build the full ordered column list for test_results.csv.
    Fixed metadata columns first, then one status column per domain.
    """
    return FIXED_COLUMNS + [csv_column(u) for u in domain_urls]


def write_row(row: dict, headers: list[str]) -> None:
    """
    Append one result row to test_results.csv.
    Creates the file with a header row if it does not already exist.
    """
    exists = os.path.exists(RESULTS_CSV)
    with open(RESULTS_CSV, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=headers)
        if not exists:
            writer.writeheader()
        writer.writerow(row)
    logger.info("Row written to %s", RESULTS_CSV)


# ---------------------------------------------------------------------------
# Screenshot helpers
# ---------------------------------------------------------------------------

def save_screenshot(driver, label: str, ip_info: dict, date_str: str) -> None:
    """
    Save a failure screenshot.
    Filename: DD-MM-YYYY_Region_Country_IP_label_FAIL.png
    """
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
    region  = ip_info.get("regionName", "Unknown").replace(" ", "")
    country = ip_info.get("country",    "Unknown").replace(" ", "")
    ip      = ip_info.get("query",      "Unknown")
    path    = os.path.join(SCREENSHOT_DIR, f"{date_str}_{region}_{country}_{ip}_{label}_FAIL.png")
    try:
        driver.save_screenshot(path)
        logger.info("Screenshot saved: %s", path)
    except Exception as exc:
        logger.error("Screenshot failed: %s", exc)


# ---------------------------------------------------------------------------
# Datetime helper
# ---------------------------------------------------------------------------

def local_datetime() -> tuple[str, str]:
    """Return (date_str, time_str) formatted for CSV output."""
    now = datetime.now()
    date_str = now.strftime("%d-%m-%Y")
    hour = now.strftime("%I").lstrip("0")
    time_str = f"{hour}.{now.strftime('%M')}{now.strftime('%p').lower()}"
    return date_str, time_str
