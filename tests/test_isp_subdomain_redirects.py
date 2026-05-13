"""
tests/test_isp_subdomain_redirects.py
======================================
Geo-distributed subdomain redirect tests.

Each test function is parametrized by `vpn_entry` — one independent test
case per schedule entry, visible individually in PyCharm and the terminal:

    PASSED  test_subdomains_redirect[BE-Random]
    PASSED  test_subdomains_redirect[CA-Alberta]
    FAILED  test_subdomains_redirect[US-New_York]

Running
-------
    pytest tests/test_isp_subdomain_redirects.py              # all 51 rounds
    pytest tests/test_isp_subdomain_redirects.py --country gb # UK rounds only
    pytest tests/test_isp_subdomain_redirects.py --run 18 19  # specific rounds
    pytest tests/test_isp_subdomain_redirects.py --show       # visible browser
    pytest -m "not geo"                                        # skip (CI)
    pytest -k "GB or DE"                                       # filter by name
"""

import logging

import pytest

from core.reporting import local_datetime
from core.vpn import fetch_ip_info
from pages.subdomain_page import SubdomainPage

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Test 1 — Subdomain redirect checks per geo-location
# ---------------------------------------------------------------------------

@pytest.mark.geo
def test_subdomains_redirect(vpn_entry, vpn_client, browser_factory, subdomain_urls):
    """
    Switches the VPN to the location in vpn_entry, then asserts that
    every subdomain in tested_dl_subdomains.txt redirects to
    pulsebrowser.com correctly.

    One test case is generated per schedule entry. Reports all blocked
    subdomains together in a single failure message per location.
    A screenshot is saved to screenshots/ for each blocked subdomain.
    """
    label = _entry_id(vpn_entry)
    logger.info("=" * 55)
    logger.info("Round: %s (%d subdomains)", label, len(subdomain_urls))

    assert vpn_client.switch_exit_location(vpn_entry), (
        f"[{label}] VPN switch failed — check StarVPN client and credentials"
    )

    ip_info = fetch_ip_info()
    assert ip_info is not None, f"[{label}] Could not fetch IP info after VPN switch"

    date_str, _ = local_datetime()

    blocked = []
    for url in subdomain_urls:
        page = SubdomainPage(browser_factory, url)
        if page.is_blocked(ip_info=ip_info, date_str=date_str):
            blocked.append(page.label)

    total = len(subdomain_urls)
    pct = round(len(blocked) / total * 100) if blocked else 0

    assert not blocked, (
        f"[{label}] {len(blocked)}/{total} subdomains blocked ({pct}%) "
        f"from IP {ip_info.get('query', '?')} "
        f"({ip_info.get('regionName', '')}, {ip_info.get('country', '')}):\n"
        + "  " + ", ".join(blocked)
    )


# ---------------------------------------------------------------------------
# Test 2 — Sanity check (no VPN required)
# ---------------------------------------------------------------------------

@pytest.mark.smoke
def test_subdomain_list_not_empty(subdomain_urls):
    """
    Sanity check: the subdomain list must not have been accidentally
    truncated below the expected minimum.
    """
    MIN = 10
    assert len(subdomain_urls) >= MIN, (
        f"Only {len(subdomain_urls)} subdomains in tested_dl_subdomains.txt — "
        f"expected at least {MIN}. Has the file been truncated?"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _entry_id(entry: dict) -> str:
    return f"{entry['country'].upper()}-{entry['region_label'].replace(' ', '_')}"