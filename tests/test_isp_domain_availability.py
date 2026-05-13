"""
tests/test_isp_domain_availability.py
======================================
Geo-distributed domain availability tests.

Each test function is parametrized by `vpn_entry` — pytest_generate_tests()
in conftest.py generates one independent test case per schedule entry, so
PyCharm and the terminal show individual pass/fail results per geo-location:

    PASSED  test_domains_load[BE-Random]
    PASSED  test_domains_load[CA-Alberta]
    FAILED  test_domains_load[US-New_York]
    PASSED  test_domains_load[US-North_Carolina]

Running
-------
    pytest tests/test_isp_domain_availability.py              # all 51 rounds
    pytest tests/test_isp_domain_availability.py --country us # US rounds only
    pytest tests/test_isp_domain_availability.py --run 1      # round 1 only
    pytest tests/test_isp_domain_availability.py --show       # visible browser
    pytest -m "not geo"                                        # skip (CI)
    pytest -k "US-New_York or GB"                             # filter by name
"""

import logging

import pytest

from core.reporting import build_headers, csv_column, local_datetime, write_row
from core.vpn import fetch_ip_info
from pages.domain_page import DomainPage

logger = logging.getLogger(__name__)


@pytest.mark.geo
def test_domains_load(vpn_entry, vpn_client, browser_factory, domain_urls):
    """
    Switches the VPN to the location in vpn_entry, then asserts that
    every domain in tested_domains.txt loads without a Chrome error.

    One test case is generated per schedule entry. A failure in one
    location does not affect other locations.

    Country routing is verified inside switch_exit_location() and logged
    as a warning if there is a mismatch — no separate test needed.
    """
    label = _entry_id(vpn_entry)
    logger.info("=" * 55)
    logger.info("Round: %s", label)

    # Switch VPN exit location
    assert vpn_client.switch_exit_location(vpn_entry), (
        f"[{label}] VPN switch failed — check StarVPN client and credentials"
    )

    # Get exit IP info for result annotation and screenshots
    ip_info = fetch_ip_info()
    assert ip_info is not None, f"[{label}] Could not fetch IP info after VPN switch"

    date_str, time_str = local_datetime()
    headers = build_headers(domain_urls)
    row = _build_row(ip_info, date_str, time_str)

    # Test each domain and collect results
    failed_domains = []
    for url in domain_urls:
        page = DomainPage(browser_factory, url)
        result = page.test(ip_info=ip_info, date_str=date_str)
        row[csv_column(url)] = result
        if result == "FAIL":
            failed_domains.append(url)

    write_row(row, headers)

    assert not failed_domains, (
        f"[{label}] {len(failed_domains)} domain(s) failed from IP {ip_info.get('query', '?')}:\n"
        + "\n".join(f"  - {url}" for url in failed_domains)
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _entry_id(entry: dict) -> str:
    return f"{entry['country'].upper()}-{entry['region_label'].replace(' ', '_')}"


def _build_row(ip_info: dict, date_str: str, time_str: str) -> dict:
    region = ip_info.get("regionName", "")
    country = ip_info.get("country", "")
    return {
        "Date":                  date_str,
        "Time":                  time_str,
        "ISP":                   ip_info.get("isp", ""),
        "Tested IP":             ip_info.get("query", ""),
        "Location":              f"{region}, {country}" if region else country,
        "ASN":                   ip_info.get("as", ""),
        "Blocked DL Subdomains": "N/A",
    }