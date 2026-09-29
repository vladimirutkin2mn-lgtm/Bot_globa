#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

BASE = "https://pub.fsa.gov.ru"

REGISTRIES = {
    "CERTIFICATE": {
        "page_url": f"{BASE}/rss/certificate",
        "api_fragment": "/api/v1/rss/common/certificates",
        "label": "СЕРТИФИКАТЫ",
    },
    "DECLARATION": {
        "page_url": f"{BASE}/rds/declaration",
        "api_fragment": "/api/v1/rds/common/declarations",
        "label": "ДЕКЛАРАЦИИ",
    },
}


@dataclass
class CapturedTemplate:
    registry: str
    method: str
    url: str
    post_data: str = ""

    def fingerprint(self, pilot_inn: str) -> str:
        return "|".join([
            self.method.upper(),
            self.url.replace(pilot_inn, "{INN}"),
            self.post_data.replace(pilot_inn, "{INN}"),
        ])

    def safe_dict(self, pilot_inn: str) -> dict[str, Any]:
        u = urlsplit(self.url.replace(pilot_inn, "{INN}"))
        masked_body = self.post_data.replace(pilot_inn, "{INN}")
        # Search request bodies are filter JSON, but never persist unexpected
        # huge data or anything resembling an auth token.
        if len(masked_body) > 5000:
            masked_body = masked_body[:5000] + "...[truncated]"
        return {
            "registry": self.registry,
            "method": self.method,
            "endpoint": f"{u.scheme}://{u.netloc}{u.path}",
            "url_masked": self.url.replace(pilot_inn, "{INN}"),
            "post_data_masked": masked_body,
        }

    def render(self, target_inn: str, pilot_inn: str) -> tuple[str, str, Any | None]:
        url = self.url.replace(pilot_inn, target_inn)
        if not self.post_data:
            return self.method.upper(), url, None

        raw = self.post_data.replace(pilot_inn, target_inn)
        try:
            body = json.loads(raw)
        except Exception as e:
            raise RuntimeError(
                "UI request body is not JSON; cannot safely replay it"
            ) from e
        return self.method.upper(), url, body


def _drain_performance_logs(driver: Any) -> None:
    try:
        driver.get_log("performance")
    except Exception:
        pass


def _extract_request(entry: dict[str, Any]) -> dict[str, Any] | None:
    try:
        msg = json.loads(entry["message"])["message"]
    except Exception:
        return None
    if msg.get("method") != "Network.requestWillBeSent":
        return None
    req = (msg.get("params") or {}).get("request") or {}
    return req if isinstance(req, dict) else None


def capture_registry_templates(
    driver: Any,
    registry: str,
    pilot_inn: str,
    max_wait_seconds: int = 150,
    idle_after_capture_seconds: int = 30,
) -> list[CapturedTemplate]:
    cfg = REGISTRIES[registry]
    driver.get(cfg["page_url"])
    time.sleep(4)
    _drain_performance_logs(driver)

    print("", flush=True)
    print("=" * 72, flush=True)
    print(f"НАСТРОЙКА FSA: {cfg['label']}", flush=True)
    print(f"Тестовый ИНН: {pilot_inn}", flush=True)
    print(
        "В открытом браузере один раз выполните поиск по этому ИНН через "
        "обычный интерфейс FSA.",
        flush=True,
    )
    print(
        "Если видите ОТДЕЛЬНЫЕ поля «ИНН заявителя» и «ИНН изготовителя», "
        "сделайте два поиска по очереди: сначала по одному полю, затем по другому.",
        flush=True,
    )
    print(
        "Скрипт сам перехватит запросы. После последнего пойманного запроса "
        f"он подождёт {idle_after_capture_seconds} сек. и продолжит.",
        flush=True,
    )
    print("=" * 72, flush=True)

    deadline = time.time() + max_wait_seconds
    last_capture_at: float | None = None
    captured: list[CapturedTemplate] = []
    seen: set[str] = set()

    while time.time() < deadline:
        time.sleep(0.5)
        try:
            logs = driver.get_log("performance")
        except Exception:
            logs = []

        for entry in logs:
            req = _extract_request(entry)
            if not req:
                continue

            url = str(req.get("url") or "")
            method = str(req.get("method") or "GET").upper()
            post_data = str(req.get("postData") or "")

            if cfg["api_fragment"] not in url:
                continue
            # Exclude details / identifiers / account. We only want a list
            # search request in which the pilot INN is literally present.
            if "/identifiers" in url or "/account" in url:
                continue
            if pilot_inn not in url and pilot_inn not in post_data:
                continue

            t = CapturedTemplate(
                registry=registry,
                method=method,
                url=url,
                post_data=post_data,
            )
            fp = t.fingerprint(pilot_inn)
            if fp in seen:
                continue
            seen.add(fp)
            captured.append(t)
            last_capture_at = time.time()
            print(
                f"Пойман рабочий UI-запрос #{len(captured)}: "
                f"{method} {urlsplit(url).path}",
                flush=True,
            )

        if captured and last_capture_at is not None:
            if time.time() - last_capture_at >= idle_after_capture_seconds:
                break

    if not captured:
        raise RuntimeError(
            f"Не удалось перехватить поиск FSA для {cfg['label']}. "
            f"Нужно было выполнить поиск по ИНН {pilot_inn} в открытом браузере."
        )

    print(
        f"Готово: для {cfg['label']} поймано шаблонов поиска: {len(captured)}",
        flush=True,
    )
    return captured
