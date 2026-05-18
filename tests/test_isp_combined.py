"""
tests/test_isp_combined.py
===========================
Combined geo-distributed ISP test — one VPN switch per round.

For each schedule entry:
  1. Switch VPN exit location           (one API call per round)
  2. Fetch exit IP info
  3. Test all DL subdomains             (redirect checks)
  4. Test all marketing domains         (availability checks)
  5. Write one CSV row with all results

This is more efficient than running the domain and subdomain test files
separately, which each switch the VPN independently — doubling API calls
and runtime. Use this file for production runs.

The two separate files (test_isp_domain_availability.py and
test_isp_subdomain_redirects.py) remain available for targeted testing
of one surface at a time.

CSV columns
-----------
Date, Time, ISP, Tested IP, Location, ASN,
Blocked DL Subdomains,          ← "ALL PASS" or "sub1, sub24, sub26"
<domain> Status ...             ← one column per domain in tested_domains.txt

Running
-------
    pytest tests/test_isp_combined.py -v              # all 51 rounds
    pytest tests/test_isp_combined.py --country us    # US rounds only
    pytest tests/test_isp_combined.py --run 1         # round 1 only
    pytest tests/test_isp_combined.py --show          # visible browser
    pytest tests/test_isp_combined.py -k "GB or DE"   # filter by name
    pytest -m "not geo"                                # skip (CI)
"""

import logging

import pytest

from core.reporting import (
    build_headers,
    csv_column,
    local_datetime,
    write_row,
)
from core.vpn import fetch_ip_info
from pages.domain_page import DomainPage
from pages.subdomain_page import SubdomainPage

logger = logging.getLogger(__name__)


@pytest.mark.geo
def test_isp_combined(
    vpn_entry,
    vpn_client,
    browser_factory,
    domain_urls,
    subdomain_urls,
):
    """
    One VPN switch per round — tests subdomains then domains, writes
    one CSV row with all results combined.

    Failures in subdomains and domains are both collected before asserting
    so a single blocked subdomain does not prevent domain results from
    being recorded.
    """
    label = _entry_id(vpn_entry)
    logger.info("=" * 55)
    logger.info("Round: %s", label)

    # ------------------------------------------------------------------
    # Switch VPN — one call for the whole round
    # ------------------------------------------------------------------
    assert vpn_client.switch_exit_location(vpn_entry), (
        f"[{label}] VPN switch failed — check StarVPN client and credentials"
    )

    ip_info = fetch_ip_info()
    assert ip_info is not None, (
        f"[{label}] Could not fetch IP info after VPN switch"
    )

    date_str, time_str = local_datetime()

    # ------------------------------------------------------------------
    # Step 1 — Test DL subdomains
    # ------------------------------------------------------------------
    blocked_labels = []
    for url in subdomain_urls:
        page = SubdomainPage(browser_factory, url)
        if page.is_blocked(ip_info=ip_info, date_str=date_str):
            blocked_labels.append(page.label)

    blocked_summary = (
        ", ".join(blocked_labels)
        if blocked_labels
        else "ALL PASS"
    )
    logger.info(
        "Subdomains: %s blocked — %s",
        len(blocked_labels),
        ", ".join(blocked_labels) if blocked_labels else "none",
    )

    # ------------------------------------------------------------------
    # Step 2 — Test marketing domains
    # ------------------------------------------------------------------
    headers = build_headers(domain_urls)
    row = _build_row(ip_info, date_str, time_str, blocked_summary)

    failed_domains = []
    for url in domain_urls:
        page = DomainPage(browser_factory, url)
        result = page.test(ip_info=ip_info, date_str=date_str)
        row[csv_column(url)] = result
        if result == "FAIL":
            failed_domains.append(url)

    # ------------------------------------------------------------------
    # Step 3 — Write CSV row (always written, even if assertions fail)
    # ------------------------------------------------------------------
    write_row(row, headers)

    # ------------------------------------------------------------------
    # Assert — report both subdomain blocks and domain failures together
    # ------------------------------------------------------------------
    failures = []

    if blocked_labels:
        pct = round(len(blocked_labels) / len(subdomain_urls) * 100)
        failures.append(
            f"Subdomains: {len(blocked_labels)}/{len(subdomain_urls)} "
            f"blocked ({pct}%): {', '.join(blocked_labels)}"
        )

    if failed_domains:
        failures.append(
            f"Domains: {len(failed_domains)} failed: "
            + ", ".join(failed_domains)
        )

    assert not failures, (
        f"[{label}] IP={ip_info.get('query', '?')} "
        f"({ip_info.get('regionName', '')}, {ip_info.get('country', '')}):\n"
        + "\n".join(f"  {f}" for f in failures)
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _entry_id(entry: dict) -> str:
    return f"{entry['country'].upper()}-{entry['region_label'].replace(' ', '_')}"


def _build_row(
    ip_info: dict,
    date_str: str,
    time_str: str,
    blocked_summary: str,
) -> dict:
    region  = ip_info.get("regionName", "")
    country = ip_info.get("country", "")
    return {
        "Date":                  date_str,
        "Time":                  time_str,
        "ISP":                   ip_info.get("isp", ""),
        "Tested IP":             ip_info.get("query", ""),
        "Location":              f"{region}, {country}" if region else country,
        "ASN":                   ip_info.get("as", ""),
        "Blocked DL Subdomains": blocked_summary,
    }