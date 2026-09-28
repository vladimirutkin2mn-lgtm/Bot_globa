#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Capture the real anonymous FSA browser session via Selenium/Chrome.

The browser is used only to establish the public session. The bulk INN work
continues through the fast requests-based FSAClient.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

BASE = "https://pub.fsa.gov.ru"
START_URL = f"{BASE}/rss/certificate"


@dataclass
class BrowserSession:
    cookies: list[dict[str, Any]] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)
    api_urls_seen: list[str] = field(default_factory=list)
    debug: dict[str, Any] = field(default_factory=dict)


def _header_get(headers: dict[str, Any], name: str) -> str:
    for k, v in (headers or {}).items():
        if str(k).lower() == name.lower():
            return str(v)
    return ""


def _candidate_auth_from_storage(storage: dict[str, Any]) -> str:
    """Find a Bearer/JWT-looking token in local/session storage without key assumptions."""
    values: list[str] = []
    for area in ("local", "session"):
        blob = storage.get(area) or {}
        if isinstance(blob, dict):
            for v in blob.values():
                if isinstance(v, str):
                    values.append(v)
                    try:
                        decoded = json.loads(v)
                    except Exception:
                        decoded = None
                    if isinstance(decoded, dict):
                        values.extend(str(x) for x in decoded.values() if isinstance(x, (str, int, float)))

    jwt_re = re.compile(r"([A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})")
    for raw in values:
        s = str(raw).strip()
        if s.lower().startswith("bearer ") and len(s) > 20:
            return s
        m = jwt_re.search(s)
        if m:
            return "Bearer " + m.group(1)
    return ""


def _safe_headers(headers: dict[str, Any]) -> dict[str, str]:
    """Keep only session/auth headers useful for replaying FSA API calls."""
    allow = {
        "authorization",
        "lkid",
        "orgid",
        "x-xsrf-token",
        "x-csrf-token",
        "x-requested-with",
    }
    out: dict[str, str] = {}
    for k, v in (headers or {}).items():
        if str(k).lower() in allow and v not in (None, ""):
            out[str(k)] = str(v)
    return out


def capture_browser_session(wait_seconds: int = 30) -> BrowserSession:
    # Lazy Selenium import keeps unit/compile checks lightweight.
    from selenium import webdriver
    from selenium.common.exceptions import WebDriverException

    options = webdriver.ChromeOptions()
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    options.add_argument("--start-maximized")

    driver = None
    browser_name = "Chrome"
    try:
        driver = webdriver.Chrome(options=options)
    except Exception as chrome_exc:
        # Edge is preinstalled on practically every supported Windows machine.
        browser_name = "Edge"
        try:
            edge_options = webdriver.EdgeOptions()
            edge_options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
            edge_options.add_argument("--start-maximized")
            driver = webdriver.Edge(options=edge_options)
        except Exception as edge_exc:
            raise RuntimeError(
                "Не удалось запустить Chrome или Edge через Selenium. "
                f"Chrome: {chrome_exc}; Edge: {edge_exc}"
            ) from edge_exc

    assert driver is not None
    result = BrowserSession()
    best_auth = ""
    api_headers: dict[str, str] = {}
    api_urls: set[str] = set()
    status_by_url: dict[str, int] = {}

    print(
        f"Открываю FSA в {browser_name}. Не закрывайте окно браузера. "
        "Если сайт покажет проверку/согласие, пройдите её вручную.",
        flush=True,
    )

    try:
        try:
            driver.execute_cdp_cmd("Network.enable", {})
        except WebDriverException:
            pass

        driver.get(START_URL)
        deadline = time.time() + wait_seconds

        while time.time() < deadline:
            time.sleep(1)
            try:
                logs = driver.get_log("performance")
            except Exception:
                logs = []

            for entry in logs:
                try:
                    msg = json.loads(entry["message"])["message"]
                except Exception:
                    continue

                method = msg.get("method", "")
                params = msg.get("params") or {}

                if method == "Network.requestWillBeSent":
                    req = params.get("request") or {}
                    url = str(req.get("url") or "")
                    if "/api/v1/" in url and "pub.fsa.gov.ru" in url:
                        api_urls.add(url.split("?", 1)[0])
                        h = req.get("headers") or {}
                        useful = _safe_headers(h)
                        if useful:
                            api_headers.update(useful)
                        auth = _header_get(h, "Authorization")
                        if auth and auth.lower() != "bearer null":
                            best_auth = auth

                elif method == "Network.requestWillBeSentExtraInfo":
                    h = params.get("headers") or {}
                    useful = _safe_headers(h)
                    if useful:
                        api_headers.update(useful)
                    auth = _header_get(h, "Authorization")
                    if auth and auth.lower() != "bearer null":
                        best_auth = auth

                elif method == "Network.responseReceived":
                    response = params.get("response") or {}
                    url = str(response.get("url") or "")
                    if "pub.fsa.gov.ru" in url:
                        try:
                            status_by_url[url.split("?", 1)[0]] = int(response.get("status") or 0)
                        except Exception:
                            pass
                        h = response.get("headers") or {}
                        auth = _header_get(h, "Authorization")
                        if auth and auth.lower() != "bearer null":
                            best_auth = auth

            # The app normally issues an API request shortly after loading.
            # Once we have both cookies and a useful auth header, no need to wait.
            try:
                cookies_now = driver.get_cookies()
            except Exception:
                cookies_now = []
            if cookies_now and best_auth:
                break

        try:
            storage = driver.execute_script(
                """
                const dump = (s) => {
                  const o = {};
                  for (let i=0; i<s.length; i++) {
                    const k = s.key(i);
                    o[k] = s.getItem(k);
                  }
                  return o;
                };
                return {local: dump(window.localStorage), session: dump(window.sessionStorage)};
                """
            ) or {}
        except Exception:
            storage = {}

        if not best_auth:
            best_auth = _candidate_auth_from_storage(storage)

        try:
            cookies = driver.get_cookies()
        except Exception:
            cookies = []

        result.cookies = cookies
        result.headers = dict(api_headers)
        if best_auth:
            # Normalize key casing while preserving the exact value.
            result.headers["Authorization"] = best_auth
        result.api_urls_seen = sorted(api_urls)
        result.debug = {
            "browser": browser_name,
            "current_url": driver.current_url,
            "title": driver.title,
            "cookie_names": sorted({str(c.get("name") or "") for c in cookies if c.get("name")}),
            "authorization_captured": bool(best_auth),
            "api_urls_seen": sorted(api_urls),
            "statuses_seen": status_by_url,
            "local_storage_keys": sorted((storage.get("local") or {}).keys()) if isinstance(storage, dict) else [],
            "session_storage_keys": sorted((storage.get("session") or {}).keys()) if isinstance(storage, dict) else [],
        }
        return result
    finally:
        try:
            driver.quit()
        except Exception:
            pass


def apply_browser_session(client: Any, browser: BrowserSession) -> None:
    """Inject browser session into an existing FSAClient."""
    client._bootstrapped = True

    # Cookies are copied individually so requests can send them normally.
    for c in browser.cookies:
        name = str(c.get("name") or "")
        value = str(c.get("value") or "")
        if not name:
            continue
        kwargs: dict[str, Any] = {}
        if c.get("domain"):
            kwargs["domain"] = str(c["domain"])
        if c.get("path"):
            kwargs["path"] = str(c["path"])
        try:
            client.session.cookies.set(name, value, **kwargs)
        except Exception:
            client.session.cookies.set(name, value)

    if browser.headers:
        client.session.headers.update(browser.headers)
