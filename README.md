# qa_pytest_vpn_selenium

A pytest-based QA automation framework with two independent test suites:

1. **ISP Geo Test Suite** — verifies domain and subdomain availability across 51 geographic locations and ISPs using StarVPN for IP rotation
2. **Installer Flow Test Suite** — simulates a real user downloading and installing Browser from campaign lander pages, with passive Windows Defender observation at every step

---

## Project structure

```
qa_pytest_vpn_selenium/
│
├── core/                          # ISP suite internals
│   ├── config.py                  # Constants, timeouts, file paths, config loaders
│   ├── browser.py                 # BrowserFactory + BasePage (Page Object Model root)
│   ├── vpn.py                     # StarVPNClient + IP info helpers
│   └── reporting.py               # CSV writing + screenshot helpers
│
├── pages/                         # ISP suite page objects
│   ├── domain_page.py             # Tests whether a marketing domain loads
│   └── subdomain_page.py          # Tests whether a subdomain redirects correctly
│
├── tests/
│   ├── test_smoke.py              # 30 unit tests — no VPN, no browser, runs in CI
│   ├── test_isp_combined.py       # ISP geo suite — 51 rounds, one VPN switch per round
│   └── test_installer_flow.py     # Installer flow suite — standalone, one test per lander URL
│
├── conftest.py                    # Fixtures and CLI options for the ISP suite
├── pytest.ini                     # Pytest configuration
├── requirements.txt               # Python dependencies
│
├── .github/
│   └── workflows/
│       └── smoke-tests.yml        # CI: runs smoke tests on every push
│
├── starvpn_config.json            # VPN schedule (51 rounds across 9 countries)
├── starvpn_credentials.json       # StarVPN API credentials — NEVER commit
├── starvpn_credentials.example.json  # Credentials template (safe to commit)
│
├── tested_domains.txt             # Domains tested in every ISP round
├── tested_dl_subdomains.txt       # Subdomains tested in every ISP round
├── lander_urls.txt                # Lander URLs for the installer suite (gitignored)
└── thankyoupage_url.txt           # Expected thank-you page URL (gitignored)
```

---

---

# Suite 1 — ISP Geo Test Suite

## How it works

```
┌─────────────────┐                              ┌──────────────────────┐
│  Your Machine   │  All traffic routed via VPN  │  StarVPN Client      │
│                 │ ◀──────────────────────────▶ │  (system-wide VPN)   │
│                 │                              └──────────────────────┘
│  pytest         │  API switches exit location
│                 │ ──────────────────────────▶  api.starhome.io
│  Chrome         │  Tests run against target URLs
│                 │ ──────────────────────────▶  tested_domains.txt
└─────────────────┘                              tested_dl_subdomains.txt
```

StarVPN runs as a system-wide VPN tunnel. The framework calls the StarVPN API between rounds to switch which country/ISP the traffic exits from. Each round uses a fresh Chrome profile with no shared state.

Each of the 51 VPN schedule entries becomes an independent pytest test case:

```
PASSED  test_isp_combined.py::test_isp_combined[BE-Random]
PASSED  test_isp_combined.py::test_isp_combined[CA-Alberta]
FAILED  test_isp_combined.py::test_isp_combined[US-New_York]
```

## Prerequisites

- Python 3.10+
- Google Chrome
- StarVPN desktop client installed, running, and connected
- StarVPN API credentials

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure StarVPN credentials

```bash
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

Credentials are at: https://www.starvpn.com/dashboard/index.php?m=dashboard&page=api

| Field | Where to find it |
|-------|-----------------|
| `email` | Your StarVPN account email |
| `auth_token` | Click "Create Auth Token" on the API dashboard |
| `custom` | The `username` value in the example payload — usually `1` |
| `port` | Your account slot number — usually `"1"` |
| `ip_type` | Usually `"Rotating IP"` |

> ⚠️ `starvpn_credentials.json` is gitignored. Never commit it.

### 3. Connect StarVPN

Start the StarVPN desktop client and verify it's routing traffic:

```bash
curl http://ip-api.com/json/
# Should show a non-local country
```

## Configuring what gets tested

### Domains (`tested_domains.txt`)

One URL per line. Each domain gets its own column in `test_results.csv` automatically. Lines starting with `#` are ignored.

```
https://example.com
https://example.net
```

**Pass condition:** page loads without a Chrome network error.

**On failure:** screenshot saved to `screenshots/DD-MM-YYYY_Region_Country_IP_domain_FAIL.png`.

### DL Subdomains (`tested_dl_subdomains.txt`)

One URL per line. Currently 36 entries.

**Pass condition:** subdomain loads and the final URL contains the expected redirect target.

**Changing the redirect target** — edit `core/config.py`:

```python
SUBDOMAIN_REDIRECT_TARGET = "yourredirecttarget.com"
```

### VPN schedule (`starvpn_config.json`)

| Code | Country | Rounds |
|------|---------|--------|
| `be` | Belgium | 1 |
| `ca` | Canada | 4 |
| `fr` | France | 1 |
| `de` | Germany | 3 |
| `it` | Italy | 3 |
| `nl` | Netherlands | 1 |
| `es` | Spain | 4 |
| `gb` | United Kingdom | 4 |
| `us` | United States | 30 |
| | **Total** | **51** |

## Running

### Verify setup first (no VPN needed)

```bash
pytest tests/test_smoke.py -v
```

All 30 should pass before running geo tests.

### Run all 51 rounds

```bash
pytest tests/test_isp_combined.py -v
```

### Filter by country

```bash
pytest tests/test_isp_combined.py --country gb -v
pytest tests/test_isp_combined.py --country us gb de -v
```

Country codes: `be` `ca` `fr` `de` `it` `nl` `es` `gb` `us`

### Filter by round number (1-based, matches `starvpn_config.json` order)

```bash
pytest tests/test_isp_combined.py --run 1 -v
pytest tests/test_isp_combined.py --run 18 19 20 -v
```

### Filter by location name

```bash
pytest tests/test_isp_combined.py -k "BE-Random" -v
pytest tests/test_isp_combined.py -k "GB or DE" -v
```

### Show the browser window

```bash
pytest tests/test_isp_combined.py --show -v
```

### Skip VPN tests (CI mode)

```bash
pytest -m "not geo" -v
```

### CLI options

| Option | Description | Example |
|--------|-------------|---------|
| `--show` | Show browser instead of headless | `--show` |
| `--country CODE` | Run only these countries | `--country us gb` |
| `--run N` | Run specific round numbers | `--run 3 7 12` |

### Markers

| Marker | Meaning |
|--------|---------|
| `@pytest.mark.geo` | Requires StarVPN. Skip with `-m "not geo"` |
| `@pytest.mark.smoke` | No VPN or network needed |

### Test ID format

| Test ID | Country | Location |
|---------|---------|----------|
| `BE-Random` | Belgium | Random region |
| `CA-British_Columbia` | Canada | BC |
| `GB-England_Sky` | UK | England, Sky ISP |
| `US-New_York` | USA | New York |

Use these with `-k` to rerun a specific failed location.

## Output files

| File | Description |
|------|-------------|
| `test_results.csv` | One row per round. Columns: Date, Time, ISP, Tested IP, Location, ASN, Blocked DL Subdomains, then one status column per domain |
| `screenshots/` | PNG on failures — `DD-MM-YYYY_Region_Country_IP_label_FAIL.png` |
| `starvpn_isp_test.log` | Full execution log |

All three are gitignored.

## Resilience

**StarVPN API rate limiting** — parses `"Please wait N seconds"` responses, sleeps, and retries automatically.

**ip-api.com failures** — retries up to 3 times with 5s waits if the response is empty after a VPN switch.

**Browser retries** — transient errors trigger a page refresh; all other errors reopen the browser entirely. Up to 3 attempts per URL.

**Stale IP detection** — if the same IP appears across consecutive rounds, `ip_update_now` is called to force a new one.

---

---

# Suite 2 — Installer Flow Test Suite

## How it works

For each entry in `lander_urls.txt`, the suite simulates exactly what a real user does:

1. Opens the campaign lander in Chrome with a fresh temporary profile
2. Finds and clicks the download button
3. Waits for the thank-you page
4. Waits 15s, then checks Windows Defender for any new detections and checks if a new `.exe` appeared in Downloads
5. If a file downloaded cleanly, launches it and waits another 15s before checking Defender again
6. Checks whether Browser is running (polls for up to 30s)
7. Records the result and cleans up

All Defender observation is **passive** — the framework never triggers a scan, it only reads what Defender has already logged.

> **Standalone** — `test_installer_flow.py` has no imports from `core/` or `pages/`. It only depends on `pytest`, `selenium`, and `webdriver-manager`.

## Known outcomes

| Result | Meaning |
|--------|---------|
| `PASS` | File downloaded, installed cleanly, Browser.exe running |
| `Chrome Block` | No file appeared in Downloads and Defender shows no flag — Chrome Safe Browsing blocked it |
| `setup.exe Flagged Trojan:Win32/Suschil!rfn` | Defender flagged the installer file during or after download |
| `updater.7z Flagged Trojan:Win32/Suschil!rfn` | Defender flagged a component extracted during installation |
| `Unexpected Behaviour: not detected` | Installer ran without Defender flags but Browser never launched |
| `Error: <message>` | Unexpected exception during the test |

## Prerequisites

- Windows 10/11
- Python 3.10+
- Google Chrome and/or Microsoft Edge
- Windows Defender with real-time protection on

## Setup

### 1. Create `lander_urls.txt`

One entry per line in the format `v<version> - <url>`:

```
v133.0.6943.177 - https://example.com?abc123&gclid=...
v133.0.6943.200 - https://example.com?def456&gclid=...
```

The version string becomes the column header in the CSV report. Each URL becomes one test case.

> `lander_urls.txt` is gitignored — never commit campaign URLs.

### 2. Create `thankyoupage_url.txt`

Single line — the URL the lander redirects to after the download button is clicked:

```
https://example.com/thankyou
```

> Also gitignored.

## Running

```bash
# Run all landers (Chrome, default)
pytest tests/test_installer_flow.py -v

# Run all landers with Edge
pytest tests/test_installer_flow.py --browser edge -v

# Run a single lander
pytest tests/test_installer_flow.py -k "lander_1" -v

# Run a single lander with Edge
pytest tests/test_installer_flow.py -k "lander_1" --browser edge -v

# Short traceback
pytest tests/test_installer_flow.py -v --tb=short
```

### CLI options

| Option | Description | Default |
|--------|-------------|---------|
| `--browser chrome` | Use Google Chrome | ✓ default |
| `--browser edge` | Use Microsoft Edge | |

**Edge note:** Edge ships `msedgedriver.exe` alongside the browser binary — no internet download required. The script finds it automatically in the standard install locations (`Program Files\Microsoft\Edge\Application\` or `%LOCALAPPDATA%\Microsoft\Edge\Application\`).

Landers are numbered in order of appearance in `lander_urls.txt`.

## How the test works step by step

```
Open lander URL in Chrome or Edge (fresh temp profile)
    ↓
Find and click download button
    ↓
Wait for thank-you page
    ↓
Wait 15s
    ↓
Check Defender + check Downloads folder
    ↓
    ├── Defender flag found         → "<component> Flagged <threat>"   [end]
    ├── No file in Downloads        → "Chrome Block"                   [end]
    └── File downloaded, no flag   → Launch installer
                                        ↓
                                    Wait 15s
                                        ↓
                                    Check Defender
                                        ↓
                                    ├── Flag found  → "<component> Flagged <threat>"        [end, skip uninstall]
                                    └── No flag     → Poll for Browser.exe (up to 30s)
                                                        ↓
                                                    ├── Running     → "PASS"
                                                    └── Not running → "Unexpected Behaviour: not detected"
                                                        ↓
                                                    Cleanup
```

## Download button detection

The script tries the following selectors in order, checking all matching elements on the page for one that is visible and enabled:

```python
"button.downloadBtn"           # exact class match — tried first
"button.download_link"
".download_link"
# XPath: any <a> or <button> whose text contains "download"
# XPath: any <a> or <button> with "download" in class
# XPath: any <a> or <button> with "download" in id
# XPath: any element with href containing ".exe"
"a[href*='.exe']"
"a[href*='download']"
"button.download, .btn-download, #download-btn"
```

Each matching element is checked with `is_displayed()` and `is_enabled()`. The element is scrolled into view before clicking.

## Output — `reports/installer_report.csv`

A persistent CSV that accumulates results across runs. New version columns are added automatically.

| date | time | 133.0.6943.177 | 133.0.6943.200 | 133.0.6943.201 |
|------|------|----------------|----------------|----------------|
| 15-05-2026 | 14:55 | PASS | PASS | Chrome Block |
| 16-05-2026 | 10:06 | PASS | PASS | Chrome Block |

The `reports/` directory is gitignored.

## Cleanup behaviour

After every test (pass or fail):

1. Force-kills: `setup.exe`, `Browser.exe`, `BrowserUpdater.exe`, `Update.exe`
2. **Tier 1** — Registry uninstall (`HKCU` then `HKLM`) with `--force-uninstall`
3. **Tier 2** — WMI `Win32_Product` uninstall (fallback)
4. **Tier 3** — `Get-Package` uninstall (final fallback)
5. Deletes the downloaded installer file from Downloads

If Defender flagged a component during install, the uninstall steps are skipped (nothing was fully installed).

> The `Software` folder may persist after uninstall — left by the Omaha updater. Does not affect subsequent tests.

---

---

# CI / GitHub Actions

`.github/workflows/smoke-tests.yml` runs on every push or pull request touching `core/`, `pages/`, `tests/`, `conftest.py`, `pytest.ini`, or `requirements.txt`.

It runs the 30 smoke tests — no VPN, no real browser, no Windows-specific code — catching regressions in shared framework logic on every commit.

Full geo tests and installer tests must be run locally.

---

# Troubleshooting

## ISP suite

**`starvpn_credentials.json` not found**
```bash
copy starvpn_credentials.example.json starvpn_credentials.json
# Edit with your credentials
```

**VPN connectivity check fails**
Ensure the StarVPN client is open and connected before running:
```bash
curl http://ip-api.com/json/
```

**Tests show `[NOTSET]` instead of location names**
Credentials file missing or invalid — fix credentials and re-run.

**Chrome not found / chromedriver error**
Install Google Chrome. `webdriver-manager` handles chromedriver automatically.

**`[ERROR]` lines in smoke test output**
Expected — two tests deliberately verify missing-file handling. Both pass.

## Installer suite

**`lander_urls.txt` not found**
Create the file with one `v<version> - <url>` entry per line.

**`thankyoupage_url.txt` not found**
Create the file with the single expected thank-you page URL.

**Download button not found**
The lander page may use a different button class. Open the lander manually, inspect the download button element, and add its selector to `DOWNLOAD_BUTTON_SELECTORS` at the top of `test_installer_flow.py`.

**`Chrome Block` reported but download should have worked**
The lander URL may be flagged by the browser's Safe Browsing database. Open the URL manually to confirm. New installer builds may take time to clear Google's or Microsoft's reputation system.

**Edge: `msedgedriver not found` or driver error**
The script looks for `msedgedriver.exe` in `Program Files\Microsoft\Edge\Application\` and `%LOCALAPPDATA%\Microsoft\Edge\Application\`. If Edge is installed in a non-standard location, add `msedgedriver.exe` to your `PATH` manually.

**`Unexpected Behaviour: not detected` after what looked like a clean install**
The installer ran but Browser didn't launch within the 30s poll window. Check whether the install actually completed by looking in `%LOCALAPPDATA%\Software`. May indicate a silent install failure unrelated to Defender.

**Cleanup leaves `Software` folder behind**
Expected — the Omaha updater leaves this folder even after a successful uninstall. Does not affect subsequent test runs.
