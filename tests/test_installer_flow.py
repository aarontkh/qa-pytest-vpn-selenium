"""
tests/test_installer_flow.py
============================
Simple installer flow test — one test per lander URL in lander_urls.txt.

Steps per test
--------------
1.  Parse version from lander_urls.txt entry
2.  Open the lander URL in Chrome
3.  Click the download button
4.  Wait for the thank-you page
5.  Assume download starts automatically
6.  Wait 15s, then check Defender for new flags since test start
7.  Determine outcome:
      - No flag + no new file  → Chrome Block
      - Flag detected          → "<component> Flagged <threat>"  (test ends)
      - No flag + new file     → run the installer
8.  Wait 15s after launching installer, check Defender again
9.  Flag detected              → "<component> Flagged <threat>"  (test ends, kill installer)
    No flag, pulse not running → "Unexpected Behaviour: Pulse not detected"
    No flag, pulse running     → "PASS"
10. Cleanup: kill processes → uninstall → delete file

lander_urls.txt format
-----------------------
    v133.0.6943.177 - https://browsergo.com?abc&gclid=...
    v133.0.6943.200 - https://browsergo.com?def&gclid=...

Running
-------
    pytest tests/test_installer_flow.py -v
    pytest tests/test_installer_flow.py -k "lander_1" -v
"""

import csv
import json
import logging
import os
import subprocess
import shutil
import tempfile
import time
import winreg
from datetime import datetime

import pytest
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

LANDER_URLS_FILE  = "lander_urls.txt"
THANKYOU_URL_FILE = "thankyoupage_url.txt"
DOWNLOADS_DIR     = os.path.join(os.path.expandvars("%USERPROFILE%"), "Downloads")
REPORT_DIR        = "reports"
REPORT_FILE       = os.path.join(REPORT_DIR, "installer_report.csv")

DEFENDER_WAIT     = 15  # seconds to wait before each Defender check
THANKYOU_TIMEOUT  = 30  # seconds to wait for thank-you page
PULSE_WAIT        = 30  # seconds to poll for PulseBrowser.exe after clean install

PULSE_EXE         = "PulseBrowser.exe"
INSTALLER_PROGRAM = "Pulse Browser"

# Selectors tried in order — first visible+enabled match wins.
# Specific class-based selectors first, generic XPath fallbacks last.
DOWNLOAD_BUTTON_SELECTORS = [
    (By.CSS_SELECTOR, "button.downloadBtn"),
    (By.CSS_SELECTOR, "button.download_link"),
    (By.CSS_SELECTOR, ".download_link"),
    (By.XPATH, "//*[contains(translate(text(),'DOWNLOAD','download'),'download') and (self::a or self::button)]"),
    (By.XPATH, "//*[contains(@class,'download') and (self::a or self::button)]"),
    (By.XPATH, "//*[contains(@id,'download') and (self::a or self::button)]"),
    (By.XPATH, "//*[contains(@href,'.exe')]"),
    (By.CSS_SELECTOR, "a[href*='.exe']"),
    (By.CSS_SELECTOR, "a[href*='download']"),
    (By.CSS_SELECTOR, "button.download, .btn-download, #download-btn"),
]


# ---------------------------------------------------------------------------
# Load lander entries
# ---------------------------------------------------------------------------

def _load_landers() -> list[dict]:
    if not os.path.exists(LANDER_URLS_FILE):
        return []
    entries = []
    with open(LANDER_URLS_FILE) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or " - " not in line:
                continue
            version_raw, url = line.split(" - ", 1)
            version = version_raw.strip().lstrip("vV")
            entries.append({"version": version, "url": url.strip()})
    logger.info("Loaded %d lander entries from %s", len(entries), LANDER_URLS_FILE)
    return entries


def _load_thankyou_url() -> str:
    if not os.path.exists(THANKYOU_URL_FILE):
        return ""
    with open(THANKYOU_URL_FILE) as fh:
        return fh.read().strip()


# ---------------------------------------------------------------------------
# Parametrize
# ---------------------------------------------------------------------------

def pytest_generate_tests(metafunc):
    if "lander_entry" in metafunc.fixturenames:
        entries = _load_landers()
        ids = [f"lander_{i+1}" for i in range(len(entries))]
        metafunc.parametrize("lander_entry", entries, ids=ids)


# ---------------------------------------------------------------------------
# Chrome driver
# ---------------------------------------------------------------------------

def _make_driver() -> tuple[webdriver.Chrome, str]:
    """Return (driver, temp_profile_dir). Caller must delete temp_profile_dir."""
    tmp_dir = tempfile.mkdtemp(prefix="lander_test_")
    opts = Options()
    opts.add_argument(f"--user-data-dir={tmp_dir}")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--no-first-run")
    opts.add_argument("--no-default-browser-check")
    opts.add_experimental_option("prefs", {
        "download.default_directory": DOWNLOADS_DIR,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
    })
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=opts)
    driver.set_page_load_timeout(30)
    return driver, tmp_dir


def _clear_browser_data(driver: webdriver.Chrome) -> None:
    """Clear cookies, cache, and storage via CDP."""
    try:
        driver.execute_cdp_cmd("Network.clearBrowserCookies", {})
        driver.execute_cdp_cmd("Network.clearBrowserCache", {})
        driver.execute_cdp_cmd(
            "Storage.clearDataForOrigin",
            {
                "origin": "*",
                "storageTypes": (
                    "cookies,cache_storage,indexeddb,"
                    "local_storage,service_workers,websql"
                ),
            },
        )
        logger.info("Browser data cleared via CDP")
    except Exception as exc:
        logger.debug("CDP clear skipped: %s", exc)


def _find_and_click_download(driver: webdriver.Chrome) -> bool:
    """
    Try each selector in DOWNLOAD_BUTTON_SELECTORS in order.
    For each selector, check all matching elements for one that is
    visible and enabled. Scrolls into view before clicking.
    Returns True if a button was found and clicked.
    """
    for by, selector in DOWNLOAD_BUTTON_SELECTORS:
        try:
            elements = driver.find_elements(by, selector)
            for el in elements:
                if el.is_displayed() and el.is_enabled():
                    logger.info("Download button found via [%s] %r — clicking", by, selector)
                    driver.execute_script("arguments[0].scrollIntoView(true);", el)
                    time.sleep(0.5)
                    el.click()
                    logger.info("Download button clicked")
                    return True
        except Exception:
            continue
    logger.error("No download button found")
    return False


def _wait_for_thankyou(driver: webdriver.Chrome, original_url: str, timeout: int = 30) -> str:
    """
    Poll until the URL changes from *original_url*.
    Returns the new URL, or the current URL if timeout is reached.
    """
    logger.info("Waiting for thank-you page (up to %ds)…", timeout)
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(1)
        try:
            current = driver.current_url.rstrip("/")
            if current != original_url.rstrip("/"):
                logger.info("Thank-you page reached: %s", current)
                return current
        except Exception:
            pass
    try:
        current = driver.current_url
    except Exception:
        current = ""
    logger.warning("Thank-you page not reached within %ds. URL: %s", timeout, current)
    return current


# ---------------------------------------------------------------------------
# Defender query
# ---------------------------------------------------------------------------

def _defender_check(since: datetime) -> dict | None:
    """
    Query Get-MpThreatDetection for any detection since *since*.
    Returns {"threat": str, "component": str} or None if clean.
    """
    since_str = since.strftime("%Y-%m-%dT%H:%M:%S")
    ps = (
        f"$since = [datetime]'{since_str}'; "
        "$t = Get-MpThreatDetection -ErrorAction SilentlyContinue; "
        "if ($t) { "
        "  $r = $t | Where-Object { $_.InitialDetectionTime -ge $since } "
        "  | Sort-Object InitialDetectionTime -Descending; "
        "  if ($r) { $r[0] | Select-Object ThreatID, Resources "
        "  | ConvertTo-Json -Depth 2 } else { '{}' } "
        "} else { '{}' }"
    )
    try:
        proc = subprocess.run(
            ["powershell", "-NonInteractive", "-Command", ps],
            capture_output=True, text=True, timeout=60,
        )
        d = json.loads(proc.stdout.strip() or "{}")
        if not d or not d.get("ThreatID"):
            return None

        tid = d["ThreatID"]
        name_proc = subprocess.run(
            ["powershell", "-NonInteractive", "-Command",
             f"(Get-MpThreat -ThreatID {tid} -ErrorAction SilentlyContinue).ThreatName"],
            capture_output=True, text=True, timeout=30,
        )
        threat_name = name_proc.stdout.strip() or "Unknown"
        resources   = str(d.get("Resources", ""))
        component   = _extract_filename(resources)

        return {"threat": threat_name, "component": component}
    except Exception as exc:
        logger.warning("Defender check failed: %s", exc)
        return None


def _extract_filename(raw: str) -> str:
    """Extract just the filename from a Defender Resources string."""
    first   = raw.split("', '")[0]
    cleaned = first.replace("'", "").replace('"', "").replace('[', "").replace(']', "")
    cleaned = cleaned.replace("file:_", "").replace("file:", "")
    if "|" in cleaned:
        cleaned = cleaned.split("|")[0]
    cleaned = cleaned.strip()
    for sep in ["\\", "/"]:
        parts = [p.strip() for p in cleaned.split(sep) if p.strip()]
        if len(parts) > 1:
            return parts[-1]
    return cleaned[:60] if cleaned else "unknown"


# ---------------------------------------------------------------------------
# Downloads folder helpers
# ---------------------------------------------------------------------------

def _snapshot_downloads() -> set[str]:
    """Return the current set of .exe filenames in Downloads."""
    if not os.path.exists(DOWNLOADS_DIR):
        return set()
    return {f for f in os.listdir(DOWNLOADS_DIR) if f.lower().endswith(".exe")}


def _new_exe(before: set[str]) -> str | None:
    """Return the path of a new .exe in Downloads, or None."""
    after = _snapshot_downloads()
    new   = after - before
    if not new:
        return None
    return os.path.join(DOWNLOADS_DIR, sorted(new)[0])


# ---------------------------------------------------------------------------
# Process helpers
# ---------------------------------------------------------------------------

def _is_running(exe_name: str) -> bool:
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {exe_name}", "/NH"],
            capture_output=True, text=True, timeout=10,
        )
        return exe_name.lower() in result.stdout.lower()
    except Exception:
        return False


def _wait_for_process(exe_name: str, timeout: int = 30) -> bool:
    """Poll every 2s for up to *timeout* seconds. Returns True if found."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _is_running(exe_name):
            return True
        time.sleep(2)
    return False


def _kill(exe_name: str) -> None:
    try:
        result = subprocess.run(
            ["taskkill", "/F", "/IM", exe_name],
            capture_output=True, text=True,
        )
        if "SUCCESS" in result.stdout:
            logger.info("Killed: %s", exe_name)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Installer launch (non-blocking)
# ---------------------------------------------------------------------------

def _launch_installer(file_path: str) -> None:
    logger.info("Launching installer: %s", os.path.basename(file_path))
    subprocess.Popen(
        ["powershell", "-NonInteractive", "-Command",
         f'Start-Process -FilePath "{file_path}"'],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

def _cleanup(file_path: str = "", skip_uninstall: bool = False) -> None:
    logger.info("Cleanup starting…")
    for proc in ["setup.exe", PULSE_EXE, "PulseBrowserUpdater.exe", "PulseUpdate.exe"]:
        _kill(proc)
    time.sleep(2)

    if not skip_uninstall:
        if not _uninstall_tier1():
            if not _uninstall_tier2():
                _uninstall_tier3()

    if file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
            logger.info("Deleted: %s", file_path)
        except Exception as exc:
            logger.warning("Could not delete installer file: %s", exc)

    logger.info("Cleanup complete")


def _uninstall_tier1() -> bool:
    for hive, hive_name in [
        (winreg.HKEY_CURRENT_USER, "HKCU"),
        (winreg.HKEY_LOCAL_MACHINE, "HKLM"),
    ]:
        for reg_path in [
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
            r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
        ]:
            try:
                with winreg.OpenKey(hive, reg_path) as root:
                    i = 0
                    while True:
                        try:
                            with winreg.OpenKey(root, winreg.EnumKey(root, i)) as sub:
                                try:
                                    name, _ = winreg.QueryValueEx(sub, "DisplayName")
                                    if INSTALLER_PROGRAM.lower() in str(name).lower():
                                        cmd, _ = winreg.QueryValueEx(sub, "UninstallString")
                                        if "--force-uninstall" not in str(cmd):
                                            cmd = str(cmd) + " --force-uninstall"
                                        logger.info("Tier 1 uninstall (%s): %s", hive_name, cmd)
                                        subprocess.run(cmd, shell=True, timeout=60, capture_output=True)
                                        time.sleep(5)
                                        return True
                                except FileNotFoundError:
                                    pass
                            i += 1
                        except OSError:
                            break
            except Exception:
                pass
    return False


def _uninstall_tier2() -> bool:
    ps = f"""
$p = Get-WmiObject Win32_Product -EA SilentlyContinue | Where-Object {{ $_.Name -like '*{INSTALLER_PROGRAM}*' }}
if ($p) {{ $p.Uninstall() | Out-Null; Write-Output 'DONE' }} else {{ Write-Output 'NOT_FOUND' }}
"""
    try:
        r = subprocess.run(["powershell", "-NonInteractive", "-Command", ps],
                           capture_output=True, text=True, timeout=120)
        if "DONE" in r.stdout:
            time.sleep(5)
            return True
    except Exception:
        pass
    return False


def _uninstall_tier3() -> bool:
    ps = f"""
$p = Get-Package -Provider Programs -IncludeWindowsInstaller -EA SilentlyContinue | Where-Object {{ $_.Name -like '*{INSTALLER_PROGRAM}*' }}
if ($p) {{ Uninstall-Package -Name $p.Name -Force -EA SilentlyContinue | Out-Null; Write-Output 'DONE' }} else {{ Write-Output 'NOT_FOUND' }}
"""
    try:
        r = subprocess.run(["powershell", "-NonInteractive", "-Command", ps],
                           capture_output=True, text=True, timeout=120)
        if "DONE" in r.stdout:
            time.sleep(5)
            return True
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# CSV report
# ---------------------------------------------------------------------------

_RUN_TIME: datetime | None = None


def _session_run_time() -> datetime:
    global _RUN_TIME
    if _RUN_TIME is None:
        _RUN_TIME = datetime.now()
    return _RUN_TIME


def _write_report(version: str, result: str) -> None:
    os.makedirs(REPORT_DIR, exist_ok=True)
    run_time     = _session_run_time()
    run_date     = run_time.strftime("%d-%m-%Y")
    run_time_str = run_time.strftime("%H:%M")

    existing_versions: list[str] = []
    existing_rows: list[dict]    = []

    if os.path.exists(REPORT_FILE):
        with open(REPORT_FILE, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            existing_versions = [c for c in (reader.fieldnames or []) if c not in ("date", "time")]
            existing_rows = list(reader)

    if version not in existing_versions:
        existing_versions.append(version)

    fieldnames = ["date", "time"] + existing_versions

    target_row = None
    for row in existing_rows:
        if row.get("date") == run_date and row.get("time") == run_time_str:
            target_row = row
            break
    if target_row is None:
        target_row = {"date": run_date, "time": run_time_str}
        existing_rows.append(target_row)

    target_row[version] = result

    with open(REPORT_FILE, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in existing_rows:
            for v in existing_versions:
                row.setdefault(v, "")
            writer.writerow(row)

    logger.info("Report updated — v%s: %s", version, result)


# ---------------------------------------------------------------------------
# Main test
# ---------------------------------------------------------------------------

@pytest.mark.installer
def test_installer_flow(lander_entry):
    version  = lander_entry["version"]
    url      = lander_entry["url"]
    thankyou = _load_thankyou_url()

    logger.info("=" * 60)
    logger.info("Test Run: v%s", version)
    logger.info("URL: %s", url)
    logger.info("=" * 60)

    test_start     = datetime.now()
    driver         = None
    tmp_dir        = None
    installer_file = None
    skip_uninstall = False

    try:
        # ------------------------------------------------------------------
        # Steps 2–4: Open lander, click download button
        # ------------------------------------------------------------------
        driver, tmp_dir = _make_driver()
        logger.info("Opening lander: %s", url)
        driver.get(url)
        time.sleep(3)  # let page JS settle before searching for button

        clicked = _find_and_click_download(driver)
        assert clicked, f"Download button not found on {url}"

        # ------------------------------------------------------------------
        # Step 5: Wait for thank-you page
        # ------------------------------------------------------------------
        if thankyou:
            _wait_for_thankyou(driver, original_url=url, timeout=THANKYOU_TIMEOUT)

        # ------------------------------------------------------------------
        # Steps 6–7: Snapshot Downloads, wait 15s, check Defender + new file
        # ------------------------------------------------------------------
        downloads_before = _snapshot_downloads()
        logger.info("Waiting %ds then checking Defender and Downloads…", DEFENDER_WAIT)
        time.sleep(DEFENDER_WAIT)

        flag     = _defender_check(since=test_start)
        new_file = _new_exe(downloads_before)

        # ------------------------------------------------------------------
        # Step 8: Three-way branch
        # ------------------------------------------------------------------
        if flag:
            result = f"{flag['component']} Flagged {flag['threat']}"
            logger.warning("Defender flag: %s", result)
            _write_report(version, result)
            return

        if new_file is None:
            result = "Chrome Block"
            logger.warning("No file in Downloads — Chrome blocked the download")
            _write_report(version, result)
            return

        # File downloaded, no flag → launch the installer
        installer_file = new_file
        logger.info("Downloaded: %s — launching installer", os.path.basename(installer_file))
        _launch_installer(installer_file)

        # ------------------------------------------------------------------
        # Step 9: Wait 15s, check Defender again
        # ------------------------------------------------------------------
        logger.info("Waiting %ds then checking Defender…", DEFENDER_WAIT)
        time.sleep(DEFENDER_WAIT)

        flag = _defender_check(since=test_start)

        # ------------------------------------------------------------------
        # Steps 10–11: Two-way branch
        # ------------------------------------------------------------------
        if flag:
            result = f"{flag['component']} Flagged {flag['threat']}"
            logger.warning("Defender flag during install: %s", result)
            skip_uninstall = True
            _write_report(version, result)
            return

        logger.info("Waiting for %s (up to %ds)…", PULSE_EXE, PULSE_WAIT)
        if not _wait_for_process(PULSE_EXE, timeout=PULSE_WAIT):
            result = "Unexpected Behaviour: Pulse not detected"
            logger.warning(result)
        else:
            result = "PASS"
            logger.info("PASS — PulseBrowser.exe is running")

        _write_report(version, result)

    except Exception as exc:
        result = f"Error: {str(exc)[:120]}"
        logger.error("Unexpected error: %s", exc)
        _write_report(version, result)
        raise

    finally:
        # ------------------------------------------------------------------
        # Step 12: Cleanup
        # ------------------------------------------------------------------
        if driver:
            try:
                _clear_browser_data(driver)
                driver.quit()
            except Exception:
                pass
        if tmp_dir and os.path.exists(tmp_dir):
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass
        _cleanup(file_path=installer_file or "", skip_uninstall=skip_uninstall)