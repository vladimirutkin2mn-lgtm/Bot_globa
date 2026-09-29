#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any

from fsa_browser_client import BrowserFSAClient
from fsa_ui_capture import CapturedTemplate


class UICapturedFSAClient(BrowserFSAClient):
    def __init__(
        self,
        driver: Any,
        replay_headers: dict[str, str],
        pilot_inn: str,
        certificate_templates: list[CapturedTemplate],
        declaration_templates: list[CapturedTemplate],
    ) -> None:
        super().__init__(driver, replay_headers)
        self.pilot_inn = pilot_inn
        self.templates = {
            "CERTIFICATE": list(certificate_templates),
            "DECLARATION": list(declaration_templates),
        }

    def _search_list(self, list_url: str, inn: str, columns: tuple[str, ...]):
        registry = "DECLARATION" if "/rds/" in list_url else "CERTIFICATE"
        templates = self.templates.get(registry) or []
        if not templates:
            raise RuntimeError(f"No captured UI templates for {registry}")

        by_id: dict[str, dict[str, Any]] = {}
        successful = 0

        for template in templates:
            method, url, payload = template.render(inn, self.pilot_inn)
            data = self._browser_fetch(method, url, payload)
            items = []
            if isinstance(data, dict):
                items = data.get("items") or data.get("content") or []
            if not isinstance(items, list):
                items = []
            successful += 1

            for item in items:
                if not isinstance(item, dict):
                    continue
                doc_id = str(item.get("id") or item.get("documentId") or "")
                if doc_id:
                    by_id[doc_id] = item

        return list(by_id.values()), f"UI_CAPTURED:{successful}"
