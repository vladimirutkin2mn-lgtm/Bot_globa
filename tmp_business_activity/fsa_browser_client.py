#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FSA client whose HTTP transport runs inside the already-open Chrome page.

This avoids Python/requests TLS and network-stack differences. The business
logic (search columns, detail verification, role extraction) is inherited from
FSAClient; only GET/POST transport is replaced by browser fetch().
"""
from __future__ import annotations

import json
from typing import Any

import requests

from fsa import FSAClient, SourceUnavailable

BLOCK_STATUSES = {401, 403, 429, 451, 502, 503, 504}


class BrowserFSAClient(FSAClient):
    def __init__(self, driver: Any, replay_headers: dict[str, str] | None = None) -> None:
        super().__init__()
        self.driver = driver
        self.replay_headers = dict(replay_headers or {})
        self._bootstrapped = True
        try:
            self.driver.set_script_timeout(120)
        except Exception:
            pass

    def bootstrap(self) -> None:
        # Browser session is already established.
        self._bootstrapped = True

    def close(self) -> None:
        try:
            self.driver.quit()
        except Exception:
            pass

    def _browser_fetch(self, method: str, url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = {
            "Accept": "application/json, text/plain, */*",
            **self.replay_headers,
        }
        # Never replay browser-only pseudo headers accidentally.
        headers = {
            str(k): str(v)
            for k, v in headers.items()
            if str(k).lower() not in {
                "cookie", "host", "content-length", "connection",
                "sec-fetch-site", "sec-fetch-mode", "sec-fetch-dest",
            }
        }

        script = r"""
        const method = arguments[0];
        const url = arguments[1];
        const payload = arguments[2];
        const replayHeaders = arguments[3] || {};
        const done = arguments[arguments.length - 1];

        (async () => {
          const headers = Object.assign(
            {"Accept": "application/json, text/plain, */*"},
            replayHeaders
          );

          // Current FSA frontend stores its bearer in fgis_token. Prefer the
          // live browser value because it can refresh while this run is active.
          try {
            const raw = window.localStorage.getItem("fgis_token");
            if (raw) {
              let token = raw;
              try {
                const parsed = JSON.parse(raw);
                if (typeof parsed === "string") token = parsed;
                else if (parsed && typeof parsed === "object") {
                  token = parsed.accessToken || parsed.access_token || parsed.token || parsed.jwt || raw;
                }
              } catch (_) {}

              token = String(token || "").trim();
              if (token && !token.toLowerCase().startsWith("bearer ")) {
                token = "Bearer " + token;
              }
              if (token && token.toLowerCase() !== "bearer null") {
                headers["Authorization"] = token;
              }
            }
          } catch (_) {}

          const opts = {
            method,
            headers,
            credentials: "include",
            cache: "no-store",
          };
          if (payload !== null && payload !== undefined) {
            headers["Content-Type"] = "application/json";
            opts.body = JSON.stringify(payload);
          }

          const controller = new AbortController();
          opts.signal = controller.signal;
          const timer = setTimeout(() => controller.abort(), 90000);

          try {
            const response = await fetch(url, opts);
            const text = await response.text();
            clearTimeout(timer);
            done({
              ok: true,
              status: response.status,
              statusText: response.statusText,
              text,
              url: response.url,
            });
          } catch (e) {
            clearTimeout(timer);
            done({
              ok: false,
              error: String(e && (e.stack || e.message) || e),
            });
          }
        })();
        """

        try:
            result = self.driver.execute_async_script(
                script, method.upper(), url, payload, headers
            )
        except Exception as e:
            raise SourceUnavailable(f"SeleniumFetchError: {type(e).__name__}: {e}") from e

        if not isinstance(result, dict):
            raise SourceUnavailable(f"SeleniumFetchError: unexpected result {result!r}")
        if not result.get("ok"):
            raise SourceUnavailable(f"BrowserFetchError: {result.get('error') or 'unknown'}")

        status = int(result.get("status") or 0)
        text = str(result.get("text") or "")

        if status in BLOCK_STATUSES:
            raise SourceUnavailable(f"HTTP {status}")

        if status >= 400:
            resp = requests.Response()
            resp.status_code = status
            resp.url = str(result.get("url") or url)
            resp._content = text.encode("utf-8", errors="replace")
            resp.encoding = "utf-8"
            raise requests.HTTPError(
                f"{status} {result.get('statusText') or ''}".strip(),
                response=resp,
            )

        try:
            data = json.loads(text)
        except Exception as e:
            raise RuntimeError(
                f"Non-JSON browser response from {url}: {text[:300]!r}"
            ) from e
        if not isinstance(data, dict):
            raise RuntimeError(f"Unexpected JSON type from {url}: {type(data).__name__}")
        return data

    def _post(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._browser_fetch("POST", url, payload)

    def _get(self, url: str) -> dict[str, Any]:
        return self._browser_fetch("GET", url, None)
