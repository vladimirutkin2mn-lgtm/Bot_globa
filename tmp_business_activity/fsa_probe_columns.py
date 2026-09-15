#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path

import requests

from fsa import FSAClient, CERT_LIST, DECL_LIST, SourceUnavailable

OUT = Path(__file__).resolve().parent / "output_fsa_probe"
OUT.mkdir(exist_ok=True)

INNS = ["6660014681", "7701276779"]
COLUMNS = [
    "applicantInn", "applicantINN", "manufacturerInn", "manufacturerINN",
    "applicantName", "manufacturerName", "productFullName",
]


def main():
    client = FSAClient()
    report = []
    for registry, url in (("CERT", CERT_LIST), ("DECL", DECL_LIST)):
        for inn in INNS:
            for column in COLUMNS:
                payload = {
                    "size": 10,
                    "page": 0,
                    "filter": {"columnsSearch": [{"column": column, "search": inn}]},
                    "columnsSort": [{"column": "date", "sort": "DESC"}],
                }
                rec = {"registry": registry, "inn": inn, "column": column}
                try:
                    data = client._post(url, payload)
                    rec.update({
                        "http": "OK",
                        "has_items_key": isinstance(data, dict) and "items" in data,
                        "total": data.get("total") if isinstance(data, dict) else None,
                        "items": len(data.get("items") or []) if isinstance(data, dict) else None,
                        "first_item_keys": sorted((data.get("items") or [{}])[0].keys())[:80]
                        if isinstance(data, dict) and (data.get("items") or []) else [],
                    })
                except SourceUnavailable as e:
                    rec.update({"http": "SOURCE_UNAVAILABLE", "error": str(e)})
                except requests.HTTPError as e:
                    rec.update({"http": f"HTTP_{getattr(e.response, 'status_code', 'ERR')}", "error": str(e)})
                except Exception as e:
                    rec.update({"http": "ERROR", "error": f"{type(e).__name__}: {e}"})
                report.append(rec)
                print(json.dumps(rec, ensure_ascii=False), flush=True)
    (OUT / "probe.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
