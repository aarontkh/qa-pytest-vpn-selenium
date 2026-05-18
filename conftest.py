"""
conftest.py
===========
Pytest fixtures and CLI options for the qa_pytest_vpn_selenium framework.

Fixture overview
----------------
vpn_config      session  — merged config + credentials dict (skips if missing)
vpn_client      session  — StarVPNClient instance
browser_factory session  — BrowserFactory (headless unless --show)
domain_urls     session  — list of URLs from tested_domains.txt
subdomain_urls  session  — list of URLs from tested_dl_subdomains.txt
schedule        session  — full filtered schedule list (for reference)
vpn_entry       function — one schedule entry, injected per parametrized round

CLI options added
-----------------
--show         Run with a visible browser instead of headless
--country CODE Filter schedule to one or more country codes (e.g. --country us gb)
--run N        Filter schedule to specific round numbers, 1-based (e.g. --run 3 7)

How parametrization works
--------------------------
pytest_generate_tests() intercepts collection of any test that declares a
`vpn_entry` argument and generates one parametrized test case per schedule
entry. Each case gets a human-readable ID like `US-New_York` or `GB-England_Sky`
so failures are immediately visible in PyCharm and the terminal without
reading logs.

How to add a new test suite
----------------------------
1. Create tests/test_<your_suite>.py
2. Declare `vpn_entry` as a function argument — pytest injects each schedule
   entry automatically, one test per round.
3. Use the other fixtures (vpn_client, browser_factory, etc.) as normal.
4. Tag geo tests with @pytest.mark.geo so CI can skip them: pytest -m "not geo"
"""

import logging
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from core.config import (
    load_vpn_config,
    load_url_list,
    filter_schedule,
    DOMAIN_FILE,
    SUBDOMAIN_FILE,
)
from core.vpn import StarVPNClient, check_vpn_connectivity, fetch_ip_info
from core.browser import BrowserFactory

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Markers
# ---------------------------------------------------------------------------

def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "geo: requires a live StarVPN connection and real VPN geo-switching",
    )
    config.addinivalue_line(
        "markers",
        "smoke: fast, no-VPN tests — safe to run in CI without StarVPN",
    )
    config.addinivalue_line(
        "markers",
        "installer: Windows-only installer flow tests — requires local machine, no VPN needed",
    )


# ---------------------------------------------------------------------------
# Custom CLI options
# ---------------------------------------------------------------------------

def pytest_addoption(parser):
    parser.addoption(
        "--show",
        action="store_true",
        default=False,
        help="Show browser window (default: headless)",
    )
    parser.addoption(
        "--country",
        nargs="+",
        metavar="CODE",
        default=None,
        help="Run only rounds for these country codes, e.g. --country us gb",
    )
    parser.addoption(
        "--run",
        nargs="+",
        type=int,
        metavar="N",
        default=None,
        help="Run specific round numbers (1-based), e.g. --run 1 5 10",
    )


# ---------------------------------------------------------------------------
# Dynamic parametrization — one test per schedule entry
# ---------------------------------------------------------------------------

def _build_schedule(config) -> list[dict]:
    """Load and filter the VPN schedule based on CLI options."""
    cfg = load_vpn_config()
    if cfg is None:
        return []
    full = cfg.get("schedule", [])
    return filter_schedule(
        full,
        country_codes=config.getoption("--country", default=None),
        run_indices=config.getoption("--run", default=None),
    )


def _entry_id(entry: dict) -> str:
    """Human-readable test ID: US-New_York, GB-England_Sky, etc."""
    return f"{entry['country'].upper()}-{entry['region_label'].replace(' ', '_')}"


def pytest_generate_tests(metafunc):
    """
    Intercept collection of any test that declares a `vpn_entry` argument
    and parametrize it with every entry in the filtered schedule.

    This is what makes PyCharm show individual pass/fail results per
    geo-location rather than one result for the entire suite.
    """
    if "vpn_entry" in metafunc.fixturenames:
        schedule = _build_schedule(metafunc.config)
        metafunc.parametrize(
            "vpn_entry",
            schedule,
            ids=[_entry_id(e) for e in schedule],
            scope="function",
        )


# ---------------------------------------------------------------------------
# Session-scoped fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def vpn_config():
    """
    Load and return the merged VPN config + credentials dict.
    Skips the entire session if either config file is missing.
    """
    cfg = load_vpn_config()
    if cfg is None:
        pytest.skip(
            "StarVPN config or credentials file not found.\n"
            "Copy starvpn_credentials.example.json -> starvpn_credentials.json "
            "and fill in your API credentials."
        )
    return cfg


@pytest.fixture(scope="session")
def vpn_client(vpn_config):
    """Return a configured StarVPNClient instance."""
    return StarVPNClient(vpn_config)


@pytest.fixture(scope="session")
def browser_factory(request):
    """
    Return a BrowserFactory configured from CLI options.
    Pass --show to make the browser window visible during a run.
    """
    headless = not request.config.getoption("--show")
    return BrowserFactory(headless=headless)


@pytest.fixture(scope="session")
def domain_urls():
    """Load domain URLs from tested_domains.txt. Skips if file is empty."""
    urls = load_url_list(DOMAIN_FILE, "domains")
    if not urls:
        pytest.skip(f"{DOMAIN_FILE} is missing or empty")
    return urls


@pytest.fixture(scope="session")
def subdomain_urls():
    """Load subdomain URLs from tested_dl_subdomains.txt. Skips if file is empty."""
    urls = load_url_list(SUBDOMAIN_FILE, "subdomains")
    if not urls:
        pytest.skip(f"{SUBDOMAIN_FILE} is missing or empty")
    return urls


@pytest.fixture(scope="session")
def schedule(vpn_config, request):
    """
    Return the full filtered schedule as a list.
    Useful for suites that need the whole list rather than individual
    entries via vpn_entry.
    """
    full = vpn_config.get("schedule", [])
    if not full:
        pytest.skip("Schedule is empty in starvpn_config.json")
    filtered = filter_schedule(
        full,
        country_codes=request.config.getoption("--country"),
        run_indices=request.config.getoption("--run"),
    )
    if not filtered:
        pytest.skip("No matching rounds found for the given --country / --run filter")
    return filtered

# ---------------------------------------------------------------------------
# Installer suite fixtures (session-scoped)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def lander_urls():
    """Load campaign lander entries from lander_urls.txt. Skips if file is empty."""
    from core.config import LANDER_URLS_FILE, load_lander_config
    entries = load_lander_config(LANDER_URLS_FILE)
    if not entries:
        pytest.skip(f"{LANDER_URLS_FILE} is missing or empty")
    return entries


@pytest.fixture(scope="session")
def thankyou_url():
    """
    Load the single shared thank-you page URL from thankyoupage_url.txt.
    Skips if the file is missing or empty.
    """
    from core.config import THANKYOU_URL_FILE
    urls = load_url_list(THANKYOU_URL_FILE, "thank-you URL")
    if not urls:
        pytest.skip(f"{THANKYOU_URL_FILE} is missing or empty")
    return urls[0].strip()

# ---------------------------------------------------------------------------
# Function-scoped fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def ip_info():
    """
    Fetch fresh IP metadata from ip-api.com.
    Fails the test immediately if ip-api.com is unreachable.
    """
    info = fetch_ip_info()
    assert info is not None, (
        "Could not fetch IP info from ip-api.com. "
        "Check internet connectivity and StarVPN client status."
    )
    return info


# ---------------------------------------------------------------------------
# Session-level VPN pre-flight
# ---------------------------------------------------------------------------

def pytest_collection_finish(session):
    """
    After test collection, if any geo-marked tests are selected,
    run a VPN connectivity check and abort early if it fails.
    """
    geo_items = [i for i in session.items if i.get_closest_marker("geo")]
    if not geo_items:
        return

    result = check_vpn_connectivity()
    if result is None:
        pytest.exit(
            "VPN connectivity check failed. "
            "Ensure StarVPN is running and connected before running geo tests.",
            returncode=1,
        )
