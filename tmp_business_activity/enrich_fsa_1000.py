#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

from fsa import FSAClient, aggregate_search, STATUS_UNAVAILABLE

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output_fsa_1000"
OUT.mkdir(exist_ok=True)


def load_inns() -> list[str]:
    inns: list[str] = []
    for i in range(1, 5):
        p = ROOT / f"inns_1000.part{i}"
        inns.extend(x.strip() for x in p.read_text(encoding="utf-8").splitlines() if x.strip())
    if len(inns) != 1000 or len(set(inns)) != 1000:
        raise RuntimeError(f"Expected 1000 unique INNs, got {len(inns)} / {len(set(inns))}")
    return inns


def main() -> int:
    inns = load_inns()
    client = FSAClient()
    rows: list[dict] = []
    raw_results: list[dict] = []
    status_counts = Counter()

    # If the source is geo/network blocked, one failed probe is enough. Mark all
    # remaining rows SOURCE_UNAVAILABLE instead of hammering the endpoint 999x.
    source_unavailable_reason = ""

    for n, inn in enumerate(inns, 1):
        if source_unavailable_reason:
            result = {
                "inn": inn,
                "status": STATUS_UNAVAILABLE,
                "source_error": source_unavailable_reason,
                "certificate_search_columns": "",
                "declaration_search_columns": "",
                "documents": [],
            }
        else:
            result = client.search_inn(inn)
            if result.get("status") == STATUS_UNAVAILABLE:
                source_unavailable_reason = str(result.get("source_error") or "SOURCE_UNAVAILABLE")

        raw_results.append(result)
        row = aggregate_search(result)
        rows.append(row)
        status_counts[row["ФСА статус"]] += 1

        if n % 50 == 0 or n == len(inns):
            print(f"[{n}/{len(inns)}] {dict(status_counts)}", flush=True)

        if not source_unavailable_reason:
            time.sleep(float(os.getenv("FSA_INN_DELAY", "0.15")))

    fields = list(rows[0].keys())
    out_csv = OUT / "fsa_1000.csv"
    with out_csv.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter=";")
        w.writeheader()
        w.writerows(rows)

    (OUT / "fsa_1000_raw.json").write_text(
        json.dumps(raw_results, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    summary = {
        "input_rows": len(inns),
        "status_counts": dict(status_counts),
        "source_unavailable_reason": source_unavailable_reason,
        "with_documents": sum(int(r["ФСА документы всего"] or 0) > 0 for r in rows),
        "with_active_documents": sum(int(r["ФСА действующие"] or 0) > 0 for r in rows),
        "manufacturer": sum(int(r["ФСА manufacturer"] or 0) > 0 for r in rows),
        "applicant": sum(int(r["ФСА applicant"] or 0) > 0 for r in rows),
        "importer": sum(int(r["ФСА importer"] or 0) > 0 for r in rows),
        "proxy_configured": bool(os.getenv("FSA_PROXY_URL")),
        "token_configured": bool(os.getenv("FSA_TOKEN")),
        "cookie_configured": bool(os.getenv("FSA_COOKIE")),
    }
    (OUT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
