#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FSA client whose HTTP transport runs inside the already-open Chrome page.

This avoids Python/requests TLS and network-stack differences. The business
logic (search columns, detail verification, role extraction) is inherited from
FSAClient; only GET/POST transport is replaced by browser fetch().
"""
from __future__ import annotations

import json
import re
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
        self._frontend_inn_fields: list[str] | None = None
        self._search_profile: dict[str, dict[str, Any]] = {}
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

    def _discover_frontend_inn_fields(self) -> list[str]:
        """Read currently loaded FSA JS bundles and extract INN-like field names."""
        if self._frontend_inn_fields is not None:
            return self._frontend_inn_fields

        script = r"""
        const done = arguments[arguments.length - 1];
        (async () => {
          const urls = [...new Set(
            performance.getEntriesByType("resource")
              .map(x => x.name)
              .filter(u => u.startsWith(location.origin) && /\.js(?:\?|$)/i.test(u))
          )].slice(0, 160);

          const fields = new Set();
          const errors = [];
          const rx1 = /\b[A-Za-z_$][A-Za-z0-9_$]{0,70}(?:Inn|INN|inn)[A-Za-z0-9_$]{0,70}\b/g;
          const rx2 = /\b(?:applicant|manufacturer|manufacter|declarant|declarer|producer)[A-Za-z0-9_$]{0,70}\b/gi;

          for (let i = 0; i < urls.length; i += 12) {
            const batch = urls.slice(i, i + 12);
            const texts = await Promise.all(batch.map(async u => {
              try {
                const r = await fetch(u, {credentials:"include", cache:"force-cache"});
                return r.ok ? await r.text() : "";
              } catch (e) {
                errors.push(String(e));
                return "";
              }
            }));

            for (const text of texts) {
              if (!text) continue;
              for (const rx of [rx1, rx2]) {
                rx.lastIndex = 0;
                let m;
                while ((m = rx.exec(text)) !== null) {
                  const v = String(m[0] || "");
                  if (v.length <= 90) fields.add(v);
                  if (fields.size > 500) break;
                }
              }
            }
          }

          done({fields:[...fields], js_count:urls.length, errors:errors.slice(0,5)});
        })();
        """
        try:
            self.driver.set_script_timeout(180)
            result = self.driver.execute_async_script(script)
        except Exception:
            result = {}

        raw = result.get("fields", []) if isinstance(result, dict) else []
        keep: list[str] = []
        for value in raw:
            v = str(value)
            low = v.lower()
            # Search fields are expected to be semantic property names rather
            # than minifier symbols. Keep INN/tax identifiers around the
            # applicant/manufacturer/declarant roles.
            if (
                ("inn" in low or "tax" in low)
                and any(x in low for x in (
                    "applicant", "manufacturer", "manufacter",
                    "declarant", "declarer", "producer",
                ))
                and re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]{2,89}", v)
            ):
                keep.append(v)

        seeded = [
            "applicantInn", "applicantINN",
            "manufacturerInn", "manufacturerINN",
            "manufacterInn", "manufacterINN",
            "declarantInn", "declarantINN",
            "declarerInn", "declarerINN",
            "producerInn", "producerINN",
            "applicantTaxId", "manufacturerTaxId",
        ]
        out: list[str] = []
        seen: set[str] = set()
        for v in seeded + keep:
            if v not in seen:
                seen.add(v)
                out.append(v)
        self._frontend_inn_fields = out
        return out

    @staticmethod
    def _payload_variants(list_url: str, column_search: list[dict[str, str]]) -> list[tuple[str, dict[str, Any]]]:
        is_decl = "/rds/" in list_url
        sort_column = "declDate" if is_decl else "date"
        return [
            (
                "full-empty-dates",
                {
                    "size": 100,
                    "page": 0,
                    "filter": {
                        "idTechReg": [],
                        "regDate": {"minDate": "", "maxDate": ""},
                        "endDate": {"minDate": "", "maxDate": ""},
                        "columnsSearch": column_search,
                    },
                    "columnsSort": [{"column": sort_column, "sort": "DESC"}],
                },
            ),
            (
                "full-null-dates",
                {
                    "size": 100,
                    "page": 0,
                    "filter": {
                        "idTechReg": [],
                        "regDate": {"minDate": None, "maxDate": None},
                        "endDate": {"minDate": None, "maxDate": None},
                        "columnsSearch": column_search,
                    },
                    "columnsSort": [{"column": sort_column, "sort": "DESC"}],
                },
            ),
            (
                "minimal",
                {
                    "size": 100,
                    "page": 0,
                    "filter": {"columnsSearch": column_search},
                    "columnsSort": [{"column": sort_column, "sort": "DESC"}],
                },
            ),
        ]

    def _find_working_payload_profile(self, list_url: str) -> dict[str, Any]:
        cached = self._search_profile.get(list_url)
        if cached:
            return cached

        errors: list[str] = []
        for name, payload in self._payload_variants(list_url, []):
            try:
                data = self._post(list_url, payload)
                if isinstance(data, dict) and "items" in data:
                    profile = {"payload_variant": name, "accepted_columns": None}
                    self._search_profile[list_url] = profile
                    return profile
            except requests.HTTPError as e:
                status = getattr(e.response, "status_code", None)
                body = ""
                try:
                    body = (e.response.text or "")[:180]
                except Exception:
                    pass
                errors.append(f"{name}:HTTP{status}:{body}")
                continue

        raise RuntimeError(
            "FSA list payload schema rejected even with empty columnsSearch; "
            + " | ".join(errors[:6])
        )

    def _payload_for_profile(
        self,
        list_url: str,
        profile_name: str,
        column_search: list[dict[str, str]],
    ) -> dict[str, Any]:
        for name, payload in self._payload_variants(list_url, column_search):
            if name == profile_name:
                return payload
        raise RuntimeError(f"Unknown payload profile {profile_name}")

    def _discover_accepted_columns(self, list_url: str, inn: str) -> tuple[list[str], list[str]]:
        profile = self._find_working_payload_profile(list_url)
        cached = profile.get("accepted_columns")
        if isinstance(cached, list) and cached:
            return cached, []

        candidates = self._discover_frontend_inn_fields()
        accepted: list[str] = []
        attempts: list[str] = []
        for column in candidates:
            payload = self._payload_for_profile(
                list_url,
                str(profile["payload_variant"]),
                [{"column": column, "search": inn}],
            )
            try:
                data = self._post(list_url, payload)
                if isinstance(data, dict) and "items" in data:
                    accepted.append(column)
                    attempts.append(f"{column}:OK:{len(data.get('items') or [])}")
            except requests.HTTPError as e:
                status = getattr(e.response, "status_code", None)
                attempts.append(f"{column}:HTTP{status}")
                # FSA currently returns 500 for an unknown columnsSearch field.
                if status in (400, 404, 422, 500):
                    continue
                raise

        if not accepted:
            raise RuntimeError(
                "No accepted FSA INN search column. "
                f"payload={profile['payload_variant']}; "
                f"candidates={candidates[:40]}; attempts={attempts[:40]}"
            )

        profile["accepted_columns"] = accepted
        return accepted, attempts

    def _search_list(self, list_url: str, inn: str, columns: tuple[str, ...]):
        """Auto-discover the current frontend's valid INN search columns."""
        profile = self._find_working_payload_profile(list_url)
        accepted, _ = self._discover_accepted_columns(list_url, inn)

        by_id: dict[str, dict[str, Any]] = {}
        successful_columns: list[str] = []
        for column in accepted:
            payload = self._payload_for_profile(
                list_url,
                str(profile["payload_variant"]),
                [{"column": column, "search": inn}],
            )
            try:
                data = self._post(list_url, payload)
            except requests.HTTPError as e:
                status = getattr(e.response, "status_code", None)
                if status in (400, 404, 422, 500):
                    continue
                raise

            if not isinstance(data, dict) or "items" not in data:
                continue
            successful_columns.append(column)
            for item in data.get("items") or []:
                if not isinstance(item, dict):
                    continue
                doc_id = str(item.get("id") or item.get("documentId") or "")
                if doc_id:
                    by_id[doc_id] = item

        if not successful_columns:
            raise RuntimeError(
                "Previously accepted FSA INN columns stopped working: "
                + ",".join(accepted)
            )
        return list(by_id.values()), ",".join(successful_columns)

    def _post(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._browser_fetch("POST", url, payload)

    def _get(self, url: str) -> dict[str, Any]:
        return self._browser_fetch("GET", url, None)
