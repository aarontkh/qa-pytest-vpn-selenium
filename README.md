# qa_pytest_vpn_selenium

A pytest-based test automation framework for verifying domain and subdomain availability across multiple geographic locations and ISPs, using StarVPN for IP rotation.

---

## How it works

```
┌─────────────────┐                              ┌──────────────────────┐
│  Your Machine   │  All traffic routed via VPN  │  StarVPN Client      │
│                 │ ◀──────────────────────────▶ │  (system-wide VPN)   │
│                 │                              └──────────────────────┘
│  pytest         │  API switches exit location
│                 │ ──────────────────────────▶  api.starhome.io
│                 │
│  Chrome         │  Tests run against target URLs
│                 │ ──────────────────────────▶  tested_domains.txt
└─────────────────┘                              tested_dl_subdomains.txt
```

StarVPN runs as a **system-wide VPN tunnel**. The framework uses the StarVPN API to change which country/region/ISP the traffic exits from between test rounds. Each round gets a fresh Chrome browser with a clean temporary profile — no shared DNS cache, cookies, or session state.

Each VPN schedule entry is a fully independent pytest test case. PyCharm and the terminal show individual results per geo-location:

```
PASSED  test_domains_load[BE-Random]
PASSED  test_domains_load[CA-Alberta]
FAILED  test_domains_load[US-New_York]
PASSED  test_domains_load[US-North_Carolina]
```

---

## Project structure

```
qa_pytest_vpn_selenium/
│
├── core/                        # Framework internals — don't edit unless extending
│   ├── config.py                # All constants, timeouts, file paths, config loaders
│   ├── browser.py               # BrowserFactory + BasePage (Page Object Model root)
│   ├── vpn.py                   # StarVPNClient + IP info helpers (with retry logic)
│   └── reporting.py             # CSV writing + screenshot helpers
│
├── pages/                       # Page Objects — one per testable surface
│   ├── domain_page.py           # Tests whether a marketing domain loads
│   └── subdomain_page.py        # Tests whether a subdomain redirects correctly
│
├── tests/                       # Test suites — add new ones here
│   ├── test_smoke.py                      # 30 unit tests (no VPN, runs in CI)
│   ├── test_isp_domain_availability.py   # 51 geo tests: domain load checks
│   └── test_isp_subdomain_redirects.py   # 51 geo tests: subdomain redirect checks
│
├── conftest.py                  # Fixtures, CLI options, parametrization logic
├── pytest.ini                   # Pytest configuration
├── requirements.txt             # Python dependencies
│
├── .github/
│   └── workflows/
│       └── smoke-tests.yml      # CI: runs smoke tests on every code change
│
├── starvpn_config.json          # VPN test schedule (51 rounds across 9 countries)
├── starvpn_credentials.json     # Your API credentials — NEVER commit this
├── starvpn_credentials.example.json  # Template for credentials (safe to commit)
│
├── tested_domains.txt           # ← EDIT THIS to change which domains are tested
├── tested_dl_subdomains.txt     # ← EDIT THIS to change which subdomains are tested
│
├── test_results.csv             # Output: one row per round (auto-generated)
├── screenshots/                 # Output: failure/block screenshots (auto-generated)
└── starvpn_isp_test.log         # Output: full execution log (auto-generated)
```

---

## Test count

With all 51 VPN rounds and the default domain/subdomain lists:

| Test file | Test cases | Requires VPN |
|-----------|-----------|-------------|
| `test_smoke.py` | 30 | No |
| `test_isp_domain_availability.py` | 51 (51 rounds × 1 test) | Yes |
| `test_isp_subdomain_redirects.py` | 51 (51 rounds × 1 test) | Yes |
| **Total** | **132** | |

Adding a domain to `tested_domains.txt` or a subdomain to `tested_dl_subdomains.txt` does not change the test count — the extra URLs are tested within each existing round.

---

## Prerequisites

- Python 3.10+
- Google Chrome installed
- StarVPN client installed, running, and connected
- StarVPN API credentials (see setup below)

---

## Setup

### 1. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure your StarVPN credentials

Copy the example file and fill in your details:

```bash
# macOS / Linux
cp starvpn_credentials.example.json starvpn_credentials.json

# Windows
copy starvpn_credentials.example.json starvpn_credentials.json
```

Edit `starvpn_credentials.json`:

```json
{
    "api_url": "https://api.starhome.io",
    "email": "your_email@example.com",
    "auth_token": "your_auth_token_here",
    "custom": 1,
    "port": "1",
    "ip_type": "Rotating IP"
}
```

Find your credentials at: https://www.starvpn.com/dashboard/index.php?m=dashboard&page=api

| Field | Where to find it |
|-------|-----------------|
| `email` | Your StarVPN account email |
| `auth_token` | Click "Create Auth Token" on the API dashboard |
| `custom` | The `username` value in the example payload — usually `1` |
| `port` | The slot number your account uses — usually `"1"` |
| `ip_type` | Usually `"Rotating IP"` |

> ⚠️ `starvpn_credentials.json` is in `.gitignore`. Never commit it. Only `starvpn_credentials.example.json` is safe to commit.

### 3. Connect StarVPN

Start and connect the StarVPN desktop client before running any geo tests. Verify it is routing traffic correctly:

```bash
curl http://ip-api.com/json/
```

The response should show a country other than your real location.

---

## Configuring what gets tested

### Domains (`tested_domains.txt`)

This file controls which marketing/product websites are tested in every geo round. One URL per line.

**Current domains:**
```
https://example.com
https://example.net
```

**To add a domain:** append a new line.
```
https://newsite.com
```

**To remove a domain:** delete its line. Lines starting with `#` are ignored.

Each domain automatically gets its own column in `test_results.csv` — no code changes needed. Adding `https://newsite.com` produces a `newsite.com Status` column on the next run.

**Pass condition:** the page loads without a Chrome network error (`ERR_NAME_NOT_RESOLVED`, `ERR_CONNECTION_REFUSED`, etc.).

**On failure:** a screenshot is saved to `screenshots/` with the filename format `DD-MM-YYYY_Region_Country_IP_domain_FAIL.png`.

---

### DL Subdomains (`tested_dl_subdomains.txt`)

This file controls which download-redirect subdomains are tested in every geo round. One URL per line.

**Current subdomains:** 36 entries (e.g. `download1.example.com` through `download36.example.com`).

**To add a subdomain:** append a new line.
```
https://download37.example.com
```

**To remove a subdomain:** delete its line.

**Pass condition:** the subdomain loads and the final URL contains the expected redirect target (redirect succeeded). A subdomain that returns a Chrome error or redirects elsewhere is reported as BLOCKED.

**On block:** a screenshot is saved to `screenshots/` with the same filename format as domain failures — `DD-MM-YYYY_Region_Country_IP_download1_FAIL.png` (using the subdomain label as the identifier).

**Changing the redirect target:** update `SUBDOMAIN_REDIRECT_TARGET` in `core/config.py`:
```python
SUBDOMAIN_REDIRECT_TARGET = "yourredirecttarget.com"
```

---

### VPN test schedule (`starvpn_config.json`)

The schedule defines which country, region, and ISP are used in each of the 51 rounds. The current schedule covers:

| Code | Country | Rounds |
|------|---------|--------|
| `be` | Belgium | 1 |
| `ca` | Canada | 4 (AB, BC, ON, QC) |
| `fr` | France | 1 |
| `de` | Germany | 3 (Baden, Bayern, Nordrhein) |
| `it` | Italy | 3 (Telecom, Vodafone, Wind) |
| `nl` | Netherlands | 1 |
| `es` | Spain | 4 (Digi, Orange, Telefonica, Vodafone) |
| `gb` | United Kingdom | 4 (Scotland BT/Virgin, England Sky/TalkTalk) |
| `us` | United States | 30 (one per state) |
| | **Total** | **51** |

Use the `--country` and `--run` CLI flags to run a subset of the schedule without editing this file.

---

## Running tests

### Quick reference

```bash
# Verify the framework is set up correctly (no VPN needed):
pytest tests/test_smoke.py -v

# All domain availability tests across all 51 rounds:
pytest tests/test_isp_domain_availability.py -v

# All subdomain redirect tests across all 51 rounds:
pytest tests/test_isp_subdomain_redirects.py -v

# Run with a visible browser window:
pytest tests/test_isp_domain_availability.py --show -v

# Filter by country code:
pytest tests/test_isp_domain_availability.py --country us -v
pytest tests/test_isp_domain_availability.py --country us gb de -v

# Filter by round number (1-based, matches the schedule order):
pytest tests/test_isp_domain_availability.py --run 1 -v
pytest tests/test_isp_domain_availability.py --run 18 19 20 21 -v

# Filter by test ID name using -k:
pytest tests/test_isp_domain_availability.py -k "US-New_York" -v
pytest tests/test_isp_domain_availability.py -k "GB or DE" -v

# Run all geo tests (domains + subdomains) across all rounds:
pytest tests/ -m geo -v

# Skip all geo tests — CI mode, no VPN needed:
pytest -m "not geo" -v
```

### CLI options

| Option | Description | Example |
|--------|-------------|---------|
| `--show` | Show the browser window instead of headless | `--show` |
| `--country CODE` | Filter to one or more country codes | `--country us gb` |
| `--run N` | Filter to specific round numbers (1-based) | `--run 3 7 12` |

**Debug a specific location with a visible browser:**
```bash
pytest tests/test_isp_domain_availability.py --run 41 --show -v
# Round 41 = New York, USA
```

**Rerun only a failed location by name:**
```bash
pytest tests/test_isp_domain_availability.py -k "US-New_York" -v
```

### Markers

| Marker | Meaning |
|--------|---------|
| `@pytest.mark.geo` | Requires a live StarVPN connection. Skip with `-m "not geo"` |
| `@pytest.mark.smoke` | No VPN or network needed. Always safe to run |

### How test IDs are formed

Each parametrized test case is named `COUNTRYCODE-Region_Label`. Examples:

| Test ID | Country | Location |
|---------|---------|----------|
| `BE-Random` | Belgium | Random region |
| `CA-British_Columbia` | Canada | BC |
| `GB-England_Sky` | United Kingdom | England, Sky ISP |
| `US-New_York` | United States | New York |
| `IT-Random_(Telecom_Italia)` | Italy | Telecom Italia ISP |

---

## Output files

| File | Description |
|------|-------------|
| `test_results.csv` | One row per round. Columns: Date, Time, ISP, Tested IP, Location, ASN, Blocked DL Subdomains, then one `<domain> Status` column per domain in `tested_domains.txt` |
| `screenshots/` | PNG screenshots on domain failures and blocked subdomains. Filename: `DD-MM-YYYY_Region_Country_IP_label_FAIL.png` |
| `starvpn_isp_test.log` | Full execution log with timestamps, retry details, and Chrome error codes |

All three are in `.gitignore` and will not be committed.

---

## Resilience and retry behaviour

The framework handles common transient failures automatically — no manual intervention needed.

### StarVPN API rate limiting
The StarVPN API enforces a cooldown between consecutive calls. If it responds with `"Please wait N seconds"`, the framework parses the wait time, sleeps for that duration plus a 2-second buffer, and retries automatically. This appears in the log as:
```
INFO  API rate limit — waiting 13s before retry (Please wait 11 seconds)
INFO  StarVPN API [HTTP 200]: {"result":"success",...}
```

### ip-api.com transient failures
Immediately after a VPN switch the tunnel sometimes needs a moment to fully establish, causing `ip-api.com` to return an empty response. The framework retries up to 3 times with a 5-second wait between attempts:
```
WARNING  ip-api bad JSON (attempt 1/3): Expecting value...
INFO     Retrying ip-api.com in 5s…
INFO     IP info — IP: 80.42.61.59  ISP: TalkTalk...
```

### Browser-level retries
Each page load has a two-tier retry system. Transient network errors (`ERR_NETWORK_CHANGED`, `ERR_SSL_PROTOCOL_ERROR`) trigger a page refresh within the same browser session. All other errors close the browser and retry with a completely fresh instance. Up to 3 total attempts per URL.

### Stale IP detection
When `--repeat` is used or the VPN assigns the same IP across consecutive rounds, the framework detects the match and calls `ip_update_now` to force a new IP before proceeding.

---

## CI / GitHub Actions

The workflow in `.github/workflows/smoke-tests.yml` runs automatically on every push or pull request that changes code in `core/`, `pages/`, `tests/`, `conftest.py`, `pytest.ini`, or `requirements.txt`.

It runs the 30 smoke tests which require no VPN or real browser, catching regressions in framework logic on every commit. Full geo tests must be run locally with StarVPN connected.

Changes to non-code files (README, config JSON, domain lists) do not trigger the workflow.

**Viewing results:** go to the **Actions** tab in your GitHub repo after a push. Each run shows pass/fail per test and uploads a JUnit XML report as a downloadable artifact, retained for 14 days.

---

## Adding a new test suite

1. **Create `tests/test_<your_suite>.py`**

2. **Declare `vpn_entry` as a function argument** — pytest generates one test case per schedule entry automatically, no loop needed:

```python
# tests/test_my_new_suite.py
import pytest

@pytest.mark.geo
def test_something(vpn_entry, vpn_client, browser_factory, domain_urls):
    """One test case per schedule entry — pytest parametrizes automatically."""
    vpn_client.switch_exit_location(vpn_entry)
    # ... your assertions here
```

3. **Available fixtures** (defined in `conftest.py`):

| Fixture | Scope | What it provides |
|---------|-------|-----------------|
| `vpn_entry` | function | One schedule entry — triggers parametrization |
| `vpn_config` | session | Merged config + credentials dict |
| `vpn_client` | session | `StarVPNClient` instance |
| `browser_factory` | session | `BrowserFactory` (headless unless `--show`) |
| `domain_urls` | session | List of URLs from `tested_domains.txt` |
| `subdomain_urls` | session | List of URLs from `tested_dl_subdomains.txt` |
| `schedule` | session | Full filtered schedule list |
| `ip_info` | function | Fresh ip-api.com response dict |

4. **Add a Page Object** in `pages/` if testing a new type of surface:

```python
# pages/my_page.py
from core.browser import BasePage, BrowserFactory
from core.config import PAGE_LOAD_TIMEOUT

class MyPage(BasePage):
    def __init__(self, factory: BrowserFactory, url: str):
        super().__init__(factory)
        self.url = url

    def test(self) -> str:
        ok, err = self._navigate(self.url, PAGE_LOAD_TIMEOUT)
        return "PASS" if ok else "FAIL"
```

5. **Tag geo tests** with `@pytest.mark.geo` so they are excluded in CI automatically.

6. **Add smoke tests** for any new framework logic in `tests/test_smoke.py` — they will run automatically in CI on the next push.

---

## Troubleshooting

**`starvpn_credentials.json` not found**
```bash
copy starvpn_credentials.example.json starvpn_credentials.json
# Then edit the file with your credentials
```

**VPN connectivity check fails at test startup**
Make sure the StarVPN desktop client is open and connected:
```bash
curl http://ip-api.com/json/
# Should show a non-local country
```

**Tests show `[NOTSET]` instead of location names**
The credentials file is missing or invalid — the schedule could not be loaded during collection. Fix credentials first, then re-run.

**Chrome not found / chromedriver error**
Install Google Chrome. `webdriver-manager` downloads the matching chromedriver version automatically — no manual installation needed.

**Tests skip immediately without running**
Either the credentials or config file is missing, or the `--country`/`--run` filter produced zero rounds. Read the skip message in the output for the specific reason.

**`[ERROR]` lines appearing in smoke test output**
The two error lines in the smoke test output are expected — they are produced by tests that deliberately verify the framework handles missing files gracefully. Both tests pass. This is not a problem.

**Same IP across consecutive rounds**
Detected and handled automatically. The framework calls `ip_update_now` to force a fresh IP and logs a warning if the IP still does not change after the refresh.
