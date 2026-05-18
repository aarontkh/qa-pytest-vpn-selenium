"""
core/config.py
==============
Central configuration for the qa_pytest_vpn_selenium framework.

All file paths, timeouts, and tunable constants live here so that
adding a new test suite never requires hunting through source files.
Config and credential loading is also handled here.
"""

import json
import logging
import os

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# File paths (relative to the project root, i.e. where pytest is invoked)
# ---------------------------------------------------------------------------
SUBDOMAIN_FILE          = "tested_dl_subdomains.txt"
DOMAIN_FILE             = "tested_domains.txt"
STARVPN_CONFIG_FILE     = "starvpn_config.json"
STARVPN_CREDENTIALS_FILE = "starvpn_credentials.json"
RESULTS_CSV             = "test_results.csv"
SCREENSHOT_DIR          = "screenshots"
LOG_FILE                = "starvpn_isp_test.log"

# ---------------------------------------------------------------------------
# Timeouts (seconds)
# ---------------------------------------------------------------------------
PAGE_LOAD_TIMEOUT   = 90   # full marketing domain load
SUBDOMAIN_TIMEOUT   = 60   # redirect subdomain load
VPN_SWITCH_WAIT     = 10   # pause after API call to change VPN exit
IP_API_TIMEOUT      = 30   # curl call to ip-api.com

# ---------------------------------------------------------------------------
# Retry behaviour
# ---------------------------------------------------------------------------
MAX_RETRIES = 3

# Errors that warrant a page-refresh within the same browser session.
# Every other error triggers a full browser teardown + fresh launch.
RETRYABLE_IN_SESSION = {"ERR_NETWORK_CHANGED", "ERR_SSL_PROTOCOL_ERROR"}

# ---------------------------------------------------------------------------
# Chrome error codes that the framework recognises
# ---------------------------------------------------------------------------
CHROME_ERROR_CODES = [
    "ERR_NAME_NOT_RESOLVED",
    "ERR_CONNECTION_REFUSED",
    "ERR_CONNECTION_TIMED_OUT",
    "ERR_CONNECTION_RESET",
    "ERR_CONNECTION_CLOSED",
    "ERR_INTERNET_DISCONNECTED",
    "ERR_SSL_PROTOCOL_ERROR",
    "ERR_SSL_VERSION_OR_CIPHER_MISMATCH",
    "ERR_CERT_AUTHORITY_INVALID",
    "ERR_CERT_COMMON_NAME_INVALID",
    "ERR_ADDRESS_UNREACHABLE",
    "ERR_NETWORK_CHANGED",
    "ERR_SOCKET_NOT_CONNECTED",
    "ERR_TIMED_OUT",
    "ERR_TOO_MANY_REDIRECTS",
    "ERR_EMPTY_RESPONSE",
    "ERR_ABORTED",
    "DNS_PROBE_FINISHED_NXDOMAIN",
    "DNS_PROBE_FINISHED_NO_INTERNET",
    "DNS_PROBE_FINISHED_BAD_CONFIG",
]

# ---------------------------------------------------------------------------
# StarVPN / VPN constants
# ---------------------------------------------------------------------------
STARVPN_API_URL         = "https://api.starhome.io"
SUBDOMAIN_REDIRECT_TARGET = "pulsebrowser.com"


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_vpn_config() -> dict | None:
    """
    Load the test schedule from starvpn_config.json and merge in
    API credentials from starvpn_credentials.json.

    Returns the merged dict on success, or None if either file is missing.
    The caller (conftest.py) decides whether to skip or abort.
    """
    if not os.path.exists(STARVPN_CONFIG_FILE):
        logger.error("Config file not found: %s", STARVPN_CONFIG_FILE)
        return None

    if not os.path.exists(STARVPN_CREDENTIALS_FILE):
        logger.error(
            "Credentials file not found: %s\n"
            "  Copy starvpn_credentials.example.json → starvpn_credentials.json\n"
            "  then fill in your API credentials from:\n"
            "  https://www.starvpn.com/dashboard/index.php?m=dashboard&page=api",
            STARVPN_CREDENTIALS_FILE,
        )
        return None

    with open(STARVPN_CONFIG_FILE) as fh:
        config = json.load(fh)
    with open(STARVPN_CREDENTIALS_FILE) as fh:
        credentials = json.load(fh)

    config.update(credentials)
    return config


def load_url_list(filepath: str, label: str = "URLs") -> list[str]:
    """
    Read non-empty lines from a plain-text URL list file.
    Returns an empty list (not an exception) if the file is missing.
    Lines starting with # are ignored.
    """
    if not os.path.exists(filepath):
        logger.error("URL list not found: %s", filepath)
        return []
    with open(filepath) as fh:
        lines = [line.strip() for line in fh
                 if line.strip() and not line.strip().startswith("#")]
    logger.info("Loaded %d %s from %s", len(lines), label, filepath)
    return lines


def load_lander_config(filepath: str) -> list[dict]:
    """
    Read lander URLs and their associated version from lander_urls.txt.

    Expected format (one entry per line):
        v133.0.6943.177 - https://example.com/lander-1
        v133.0.6943.200 - https://example.com/lander-2

    Returns a list of dicts: [{"version": "133.0.6943.177", "url": "https://..."}]
    Lines starting with # are ignored.
    Version prefix "v" is stripped automatically.
    Returns an empty list if the file is missing or malformed.
    """
    if not os.path.exists(filepath):
        logger.error("Lander config file not found: %s", filepath)
        return []

    entries = []
    with open(filepath) as fh:
        for lineno, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if " - " not in line:
                logger.warning(
                    "%s line %d: expected 'vVERSION - URL' format, got: %r — skipping",
                    filepath, lineno, line,
                )
                continue
            version_part, url_part = line.split(" - ", 1)
            version = version_part.strip().lstrip("v").lstrip("V")
            url = url_part.strip()
            if not version or not url:
                logger.warning(
                    "%s line %d: empty version or URL — skipping",
                    filepath, lineno,
                )
                continue
            entries.append({"version": version, "url": url})

    logger.info("Loaded %d lander entries from %s", len(entries), filepath)
    return entries


def filter_schedule(
    schedule: list[dict],
    country_codes: list[str] | None = None,
    run_indices: list[int] | None = None,
) -> list[dict]:
    """
    Return a filtered subset of the VPN test schedule.

    Priority: run_indices > country_codes > return full schedule.
    """
    if run_indices:
        return [
            schedule[i - 1]
            for i in run_indices
            if 1 <= i <= len(schedule)
        ]
    if country_codes:
        codes = {c.lower() for c in country_codes}
        return [e for e in schedule if e["country"].lower() in codes]
    return schedule

# ---------------------------------------------------------------------------
# Installer test suite
# ---------------------------------------------------------------------------
LANDER_URLS_FILE        = "lander_urls.txt"
THANKYOU_URL_FILE       = "thankyoupage_url.txt"
DOWNLOADS_DIR           = os.path.join(os.path.expandvars("%USERPROFILE%"), "Downloads")
LOCALAPPDATA_DIR        = os.path.expandvars("%LOCALAPPDATA%")
PULSE_SOFTWARE_DIR      = os.path.join(LOCALAPPDATA_DIR, "PulseSoftware")

# Expected folders after a successful install
EXPECTED_INSTALL_FOLDERS = [
    "PulseBrowser",
    "PulseBrowserUpdater",
    "Update",
]

# Expected program name in installed apps registry
INSTALLED_PROGRAM_NAME  = "Pulse Browser"

# Omaha/Google-style uninstaller — Pulse Browser uses the same pattern
UNINSTALL_REG_PATHS = [
    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
    r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
]

# Timeouts for installer flow (seconds)
DOWNLOAD_WAIT           = 60   # max wait for file to appear in Downloads
THANKYOU_PAGE_TIMEOUT   = 30   # max wait for thank-you page to load
INSTALL_WAIT            = 60   # max wait for PulseBrowser.exe to launch
POST_RUN_DEFENDER_WAIT  = 5    # wait after launch before defender check
LANDER_LOAD_TIMEOUT     = 30   # page load timeout for campaign lander