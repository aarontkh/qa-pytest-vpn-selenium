"""
core/vpn.py
===========
StarVPN API client and IP-info helper.

StarVPNClient  — wraps api.starhome.io calls (switch location, refresh IP)
fetch_ip_info  — calls ip-api.com to get current exit IP / ISP / location
check_vpn_connectivity — pre-flight check printed before a test run
"""

import json
import re
import logging
import subprocess
import time

import requests

from core.config import (
    STARVPN_API_URL,
    VPN_SWITCH_WAIT,
    IP_API_TIMEOUT,
)

logger = logging.getLogger(__name__)
_IP_API_URL = "http://ip-api.com/json/?fields=66846719"


# ---------------------------------------------------------------------------
# IP info
# ---------------------------------------------------------------------------

_IP_API_MAX_RETRIES = 3
_IP_API_RETRY_WAIT  = 5  # seconds between retries


def fetch_ip_info() -> dict | None:
    """
    Call ip-api.com via curl and return the parsed JSON.

    Retries up to _IP_API_MAX_RETRIES times with a short wait between
    attempts. An empty or invalid response immediately after a VPN switch
    is common — the tunnel needs a moment to fully establish before
    outbound HTTP requests resolve correctly.

    Returns a dict with keys: query, country, countryCode, regionName,
    isp, as, proxy, hosting — or None if all attempts fail.
    """
    for attempt in range(1, _IP_API_MAX_RETRIES + 1):
        try:
            result = subprocess.run(
                ["curl", "-s", _IP_API_URL],
                capture_output=True, text=True, timeout=IP_API_TIMEOUT,
            )
            data = json.loads(result.stdout)
            if data.get("status") == "success":
                logger.info(
                    "IP info — IP: %s  ISP: %s  Location: %s, %s",
                    data.get("query"), data.get("isp"),
                    data.get("regionName"), data.get("country"),
                )
                return data
            logger.warning(
                "ip-api non-success (attempt %d/%d): %s",
                attempt, _IP_API_MAX_RETRIES, data,
            )
        except subprocess.TimeoutExpired:
            logger.warning("ip-api.com timed out (attempt %d/%d)", attempt, _IP_API_MAX_RETRIES)
        except json.JSONDecodeError as exc:
            logger.warning("ip-api bad JSON (attempt %d/%d): %s", attempt, _IP_API_MAX_RETRIES, exc)
        except Exception as exc:
            logger.warning("ip-api error (attempt %d/%d): %s", attempt, _IP_API_MAX_RETRIES, exc)

        if attempt < _IP_API_MAX_RETRIES:
            logger.info("Retrying ip-api.com in %ds…", _IP_API_RETRY_WAIT)
            time.sleep(_IP_API_RETRY_WAIT)

    logger.error("ip-api.com failed after %d attempts", _IP_API_MAX_RETRIES)
    return None


def check_vpn_connectivity() -> dict | None:
    """
    Print a connectivity summary and return the ip-api payload on success,
    or None if the check fails.  Called once at the start of a test run.
    """
    print("\n" + "=" * 60)
    print("  StarVPN ISP Test — VPN Connectivity Check")
    print("=" * 60)
    print("\n  Checking connection…")

    try:
        result = subprocess.run(
            ["curl", "-s", "--max-time", "15", _IP_API_URL],
            capture_output=True, text=True, timeout=20,
        )
        if result.returncode != 0 or not result.stdout.strip():
            print("\n  FAILED — Could not reach ip-api.com")
            print("=" * 60 + "\n")
            return None

        data = json.loads(result.stdout)
        if data.get("status") != "success":
            print("\n  FAILED — ip-api.com returned an error")
            print("=" * 60 + "\n")
            return None

        is_vpn = data.get("proxy", False) or data.get("hosting", False)
        print(f"\n  Current IP : {data.get('query', 'unknown')}")
        print(f"  Country    : {data.get('country', 'unknown')}")
        print(f"  ISP        : {data.get('isp', 'unknown')}")
        print(f"  VPN        : {'Detected' if is_vpn else 'Not confirmed (may still be connected)'}")
        print(f"\n  OK — Proceeding with tests")
        print("=" * 60 + "\n")

        logger.info(
            "VPN check passed — IP: %s, Country: %s, ISP: %s",
            data.get("query"), data.get("country"), data.get("isp"),
        )
        return data

    except subprocess.TimeoutExpired:
        print("\n  FAILED — Connection timed out")
    except json.JSONDecodeError:
        print("\n  FAILED — Invalid response from ip-api.com")
    except FileNotFoundError:
        print("\n  FAILED — curl is not installed")
    except Exception as exc:
        print(f"\n  FAILED — {exc}")

    print("=" * 60 + "\n")
    return None


# ---------------------------------------------------------------------------
# StarVPN API client
# ---------------------------------------------------------------------------

class StarVPNClient:
    """
    Thin HTTP client for api.starhome.io.

    Responsibilities:
    - Build auth payloads from the config dict.
    - Switch the VPN exit location (country / region / ISP).
    - Force an IP refresh when the same IP appears across consecutive rounds.
    - Track the last used IP to detect stale-IP situations automatically.
    """

    def __init__(self, config: dict):
        self._cfg = config
        self._api_url: str = config.get("api_url", STARVPN_API_URL)
        self._last_ip: str | None = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _base_payload(self) -> dict:
        return {
            "email":      self._cfg["email"],
            "auth_token": self._cfg["auth_token"],
            "custom":     self._cfg.get("custom", 1),
            "port":       self._cfg.get("port", "1"),
            "ip_type":    self._cfg.get("ip_type", "Rotating IP"),
        }

    def _post(self, payload: dict, _attempt: int = 1) -> bool:
        """
        POST a payload to the StarVPN API.

        The API enforces a per-call cooldown and returns:
            {"result": "error", "message": "Please wait 11 seconds"}
        when called too quickly. This method parses the wait time from
        that message and retries exactly once after sleeping, so callers
        never need to handle rate-limiting themselves.

        Max attempts: 2 (one retry after a rate-limit response).
        All other errors fail immediately without retrying.
        """
        try:
            r = requests.post(
                self._api_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
            logger.info("StarVPN API [HTTP %s]: %s", r.status_code, r.text[:300])

            if r.status_code != 200:
                logger.error("HTTP %s from StarVPN API", r.status_code)
                return False

            try:
                body = r.json()
            except Exception:
                return True  # non-JSON 200 — treat as success

            if body.get("result") == "error":
                message = body.get("message", "Unknown")

                # Rate-limit response: "Please wait N seconds"
                # Parse N, sleep, then retry once.
                wait_match = re.search(r"(\d+)\s+second", message, re.IGNORECASE)
                if wait_match and _attempt == 1:
                    wait_secs = int(wait_match.group(1)) + 2  # +2s buffer
                    logger.info(
                        "API rate limit — waiting %ds before retry (%s)",
                        wait_secs, message,
                    )
                    time.sleep(wait_secs)
                    return self._post(payload, _attempt=2)

                logger.error("API error: %s", message)
                return False

            return True

        except Exception as exc:
            logger.error("StarVPN API request failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def refresh_ip(self) -> bool:
        """Force a new exit IP within the current location."""
        logger.info("Requesting IP refresh")
        return self._post({**self._base_payload(), "command": "ip_update_now"})

    def switch_exit_location(self, entry: dict) -> bool:
        """
        Change the VPN exit to the country / region / ISP in *entry*.

        Waits VPN_SWITCH_WAIT seconds after the API call, then verifies
        the exit IP. If the IP is unchanged from the previous round it
        automatically calls refresh_ip() and waits again.

        Returns True if the API accepted the request (regardless of
        whether the IP actually changed — caller sees a warning in logs).
        """
        logger.info(
            "Switching VPN → %s - %s (country=%s, region=%s, timeinterval=%s)",
            entry["country_name"], entry["region_label"],
            entry["country"], entry["region"], entry["timeinterval"],
        )

        payload = {
            **self._base_payload(),
            "command":      "update_ip_configuration",
            "country":      entry["country"],
            "region":       entry["region"],
            "timeinterval": entry["timeinterval"],
        }

        if not self._post(payload):
            return False

        logger.info("Waiting %ds for VPN to update…", VPN_SWITCH_WAIT)
        time.sleep(VPN_SWITCH_WAIT)

        ip_info = fetch_ip_info()
        if not ip_info:
            logger.warning("Could not verify exit IP after switch — proceeding anyway")
            return True

        current_ip = ip_info.get("query", "")

        # Auto-refresh if IP is identical to the previous round
        if self._last_ip and current_ip == self._last_ip:
            logger.info("IP %s unchanged from previous round — forcing refresh", current_ip)
            self.refresh_ip()
            time.sleep(VPN_SWITCH_WAIT)
            ip_info = fetch_ip_info() or ip_info
            new_ip = ip_info.get("query", current_ip)
            if new_ip == current_ip:
                logger.warning("IP still %s after refresh — proceeding anyway", current_ip)
            else:
                logger.info("IP refreshed: %s → %s", current_ip, new_ip)
            current_ip = new_ip

        # Country verification (warning only, not a hard failure)
        actual_cc = ip_info.get("countryCode", "").lower()
        expected_cc = entry["country"].lower()
        if actual_cc == expected_cc:
            logger.info("VPN verified — exiting from %s (%s)", ip_info.get("country"), current_ip)
        else:
            logger.warning(
                "Country mismatch: expected %s, got %s (%s) — proceeding anyway",
                expected_cc.upper(), actual_cc.upper(), ip_info.get("country"),
            )

        self._last_ip = current_ip
        return True