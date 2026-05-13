"""
tests/test_smoke.py
====================
Fast unit tests — no VPN, no browser, no network required.

These run on every push via GitHub Actions to catch regressions in the
framework code itself: config loading, CSV header logic, chrome error
detection, schedule filtering, URL helpers, and datetime formatting.

Run with:
    pytest tests/test_smoke.py -v
    pytest -m smoke
"""

import json
import pytest


# ---------------------------------------------------------------------------
# Chrome error detection
# ---------------------------------------------------------------------------

class TestChromeErrorDetection:
    """core/browser.py — _detect_error_in_source / _detect_error_in_exception"""

    # Import here so the test file has no top-level side effects
    @pytest.fixture(autouse=True)
    def _imports(self):
        from core.browser import _detect_error_in_source, _detect_error_in_exception
        self.detect_source = _detect_error_in_source
        self.detect_exc    = _detect_error_in_exception

    def test_detects_err_name_not_resolved(self):
        assert self.detect_source("<html>ERR_NAME_NOT_RESOLVED</html>") == "ERR_NAME_NOT_RESOLVED"

    def test_detects_dns_probe_nxdomain(self):
        assert self.detect_source("<html>DNS_PROBE_FINISHED_NXDOMAIN</html>") == "DNS_PROBE_FINISHED_NXDOMAIN"

    def test_detects_site_cannot_be_reached(self):
        result = self.detect_source("<html>This site can't be reached</html>")
        assert result is not None

    def test_returns_none_for_clean_page(self):
        assert self.detect_source("<html><body><h1>Welcome</h1></body></html>") is None

    def test_case_insensitive(self):
        assert self.detect_source("<html>err_name_not_resolved</html>") == "ERR_NAME_NOT_RESOLVED"

    def test_extracts_error_code_from_exception(self):
        assert self.detect_exc(Exception("net::ERR_CONNECTION_REFUSED")) == "ERR_CONNECTION_REFUSED"

    def test_timeout_keyword_returns_timed_out(self):
        assert self.detect_exc(Exception("timeout waiting for page load")) == "ERR_TIMED_OUT"

    def test_unrecognised_exception_returns_unknown(self):
        assert self.detect_exc(Exception("some random selenium error")) == "UNKNOWN_ERROR"


# ---------------------------------------------------------------------------
# Reporting helpers
# ---------------------------------------------------------------------------

class TestReportingUtils:
    """core/reporting.py — display_name, csv_column, screenshot_label, build_headers"""

    @pytest.fixture(autouse=True)
    def _imports(self):
        from core.reporting import (
            display_name, csv_column, screenshot_label,
            build_headers, local_datetime, FIXED_COLUMNS,
        )
        self.display_name     = display_name
        self.csv_column       = csv_column
        self.screenshot_label = screenshot_label
        self.build_headers    = build_headers
        self.local_datetime   = local_datetime
        self.FIXED_COLUMNS    = FIXED_COLUMNS

    def test_display_name_strips_https(self):
        assert self.display_name("https://pulsebrowser.net") == "pulsebrowser.net"

    def test_display_name_strips_http_and_trailing_slash(self):
        assert self.display_name("http://example.com/") == "example.com"

    def test_csv_column_format(self):
        assert self.csv_column("https://pulsebrowser.net") == "pulsebrowser.net Status"

    def test_screenshot_label_no_dots(self):
        label = self.screenshot_label("https://pulsebrowser.net")
        assert "." not in label
        assert label == "pulsebrowser_net"

    def test_build_headers_has_all_fixed_columns(self):
        headers = self.build_headers([])
        for col in self.FIXED_COLUMNS:
            assert col in headers

    def test_build_headers_appends_domain_columns(self):
        urls    = ["https://pulsebrowser.net", "https://browsergo.com"]
        headers = self.build_headers(urls)
        assert "pulsebrowser.net Status" in headers
        assert "browsergo.com Status" in headers

    def test_build_headers_domain_columns_are_last(self):
        headers = self.build_headers(["https://pulsebrowser.net"])
        assert headers[-1] == "pulsebrowser.net Status"

    def test_local_datetime_returns_two_strings(self):
        date_str, time_str = self.local_datetime()
        assert isinstance(date_str, str) and isinstance(time_str, str)
        assert len(date_str) == 10     # DD-MM-YYYY
        assert "." in time_str         # e.g. "9.30am"


# ---------------------------------------------------------------------------
# Schedule filtering
# ---------------------------------------------------------------------------

class TestScheduleFiltering:
    """core/config.py — filter_schedule"""

    @pytest.fixture(autouse=True)
    def _setup(self):
        from core.config import filter_schedule
        self.filter = filter_schedule
        self.schedule = [
            {"country": "us", "country_name": "United States", "region": "ny",
             "region_label": "New York",    "timeinterval": "sticky"},
            {"country": "gb", "country_name": "United Kingdom", "region": "eng",
             "region_label": "England Sky", "timeinterval": "stickysky"},
            {"country": "de", "country_name": "Germany",        "region": "berlin",
             "region_label": "Berlin",      "timeinterval": "sticky"},
        ]

    def test_no_filter_returns_full_schedule(self):
        assert len(self.filter(self.schedule)) == 3

    def test_filter_by_single_country(self):
        result = self.filter(self.schedule, country_codes=["us"])
        assert len(result) == 1 and result[0]["country"] == "us"

    def test_filter_by_multiple_countries(self):
        result = self.filter(self.schedule, country_codes=["us", "gb"])
        assert len(result) == 2

    def test_country_filter_is_case_insensitive(self):
        result = self.filter(self.schedule, country_codes=["US"])
        assert len(result) == 1

    def test_filter_by_run_index(self):
        result = self.filter(self.schedule, run_indices=[2])
        assert len(result) == 1 and result[0]["country"] == "gb"

    def test_run_indices_take_priority_over_country(self):
        # run_indices=[1] → US only, even though country_codes says gb
        result = self.filter(self.schedule, country_codes=["gb"], run_indices=[1])
        assert len(result) == 1 and result[0]["country"] == "us"

    def test_out_of_range_run_index_is_silently_skipped(self):
        assert self.filter(self.schedule, run_indices=[99]) == []

    def test_unknown_country_code_returns_empty(self):
        assert self.filter(self.schedule, country_codes=["zz"]) == []


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

class TestConfigLoading:
    """core/config.py — load_vpn_config"""

    @pytest.fixture(autouse=True)
    def _import(self):
        from core.config import load_vpn_config
        self.load = load_vpn_config

    def test_returns_none_when_credentials_missing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "starvpn_config.json").write_text(json.dumps({"schedule": []}))
        assert self.load() is None

    def test_returns_none_when_config_missing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "starvpn_credentials.json").write_text(json.dumps({"email": "x"}))
        assert self.load() is None

    def test_merges_schedule_and_credentials(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        schedule = [{"country": "us", "country_name": "US", "region": "ny",
                     "region_label": "NY", "timeinterval": "sticky"}]
        (tmp_path / "starvpn_config.json").write_text(json.dumps({"schedule": schedule}))
        (tmp_path / "starvpn_credentials.json").write_text(json.dumps({
            "api_url": "https://api.starhome.io", "email": "test@example.com",
            "auth_token": "fake", "custom": 1, "port": "1", "ip_type": "Rotating IP",
        }))
        result = self.load()
        assert result is not None
        assert result["email"] == "test@example.com"
        assert len(result["schedule"]) == 1
        assert result["schedule"][0]["country"] == "us"


# ---------------------------------------------------------------------------
# SubdomainPage label extraction
# ---------------------------------------------------------------------------

class TestSubdomainPageLabel:
    """pages/subdomain_page.py — label property"""

    @pytest.fixture(autouse=True)
    def _import(self):
        from pages.subdomain_page import SubdomainPage
        self.SubdomainPage = SubdomainPage

    def _page(self, url):
        # Pass None as factory — label is a pure property, no browser needed
        p = object.__new__(self.SubdomainPage)
        p.url = url
        return p

    def test_extracts_get1_label(self):
        assert self._page("https://get1.pulsebrowser.net").label == "get1"

    def test_extracts_get36_label(self):
        assert self._page("https://get36.pulsebrowser.net").label == "get36"

    def test_falls_back_to_url_when_no_match(self):
        url = "https://other.example.com"
        assert self._page(url).label == url
