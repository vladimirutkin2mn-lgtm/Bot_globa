#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import json
import os
import time
from collections import Counter
from pathlib import Path

from fsa import aggregate_search, STATUS_ERROR, STATUS_UNAVAILABLE
from fsa_selenium_session import open_browser_session
from fsa_ui_capture import capture_registry_templates
from fsa_ui_client import UICapturedFSAClient

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


def write_outputs(rows: list[dict], raw_results: list[dict], summary: dict) -> None:
    if rows:
        fields = list(rows[0].keys())
        with (OUT / "fsa_1000.csv").open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, delimiter=";")
            w.writeheader()
            w.writerows(rows)

    (OUT / "fsa_1000_raw.json").write_text(
        json.dumps(raw_results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> int:
    inns = load_inns()
    pilot_inn = inns[0]

    print("Шаг 1/3: открываю рабочую FSA-сессию в Chrome/Edge...", flush=True)
    driver, browser = open_browser_session(
        wait_seconds=int(os.getenv("FSA_BROWSER_WAIT", "30"))
    )
    (OUT / "browser_session_debug.json").write_text(
        json.dumps(browser.debug, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(
        "Сессия браузера: "
        f"cookies={len(browser.cookies)}, "
        f"authorization={'YES' if browser.debug.get('authorization_captured') else 'NO'}",
        flush=True,
    )

    try:
        print("Шаг 2/3: перехватываю реальные поисковые запросы интерфейса FSA.", flush=True)
        cert_templates = capture_registry_templates(
            driver,
            "CERTIFICATE",
            pilot_inn,
            max_wait_seconds=int(os.getenv("FSA_CAPTURE_WAIT", "150")),
            idle_after_capture_seconds=int(os.getenv("FSA_CAPTURE_IDLE", "30")),
        )
        decl_templates = capture_registry_templates(
            driver,
            "DECLARATION",
            pilot_inn,
            max_wait_seconds=int(os.getenv("FSA_CAPTURE_WAIT", "150")),
            idle_after_capture_seconds=int(os.getenv("FSA_CAPTURE_IDLE", "30")),
        )

        templates_debug = {
            "pilot_inn_masked": "{PILOT_INN}",
            "certificates": [t.safe_dict(pilot_inn) for t in cert_templates],
            "declarations": [t.safe_dict(pilot_inn) for t in decl_templates],
        }
        (OUT / "captured_search_templates.json").write_text(
            json.dumps(templates_debug, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        client = UICapturedFSAClient(
            driver=driver,
            replay_headers=browser.headers,
            pilot_inn=pilot_inn,
            certificate_templates=cert_templates,
            declaration_templates=decl_templates,
        )

        rows: list[dict] = []
        raw_results: list[dict] = []
        status_counts = Counter()

        print(
            "Шаг 3/3: запускаю 1 000 ИНН по перехваченным шаблонам. "
            "Браузер не закрывайте.",
            flush=True,
        )

        for n, inn in enumerate(inns, 1):
            result = client.search_inn(inn)
            raw_results.append(result)
            row = aggregate_search(result)
            rows.append(row)
            status_counts[row["ФСА статус"]] += 1

            if n <= 5 or n % 10 == 0 or n == len(inns):
                extra = ""
                if row["ФСА статус"] in (STATUS_UNAVAILABLE, STATUS_ERROR):
                    extra = f" | last_error={row['ФСА ошибка'][:500]}"
                print(f"[{n}/{len(inns)}] {dict(status_counts)}{extra}", flush=True)

            if n == 1 and row["ФСА статус"] in (STATUS_UNAVAILABLE, STATUS_ERROR):
                summary = {
                    "input_rows": len(inns),
                    "processed_rows": 1,
                    "status_counts": dict(status_counts),
                    "first_error": row["ФСА ошибка"],
                    "browser_session": browser.debug,
                    "captured_templates": templates_debug,
                    "transport": "selenium_ui_captured_fetch",
                }
                write_outputs(rows, raw_results, summary)
                print("\nОстановлено после первого ИНН.", flush=True)
                print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
                return 3

            time.sleep(float(os.getenv("FSA_INN_DELAY", "0.20")))

        summary = {
            "input_rows": len(inns),
            "processed_rows": len(rows),
            "status_counts": dict(status_counts),
            "with_documents": sum(int(r["ФСА документы всего"] or 0) > 0 for r in rows),
            "with_active_documents": sum(int(r["ФСА действующие"] or 0) > 0 for r in rows),
            "manufacturer": sum(int(r["ФСА manufacturer"] or 0) > 0 for r in rows),
            "applicant": sum(int(r["ФСА applicant"] or 0) > 0 for r in rows),
            "importer": sum(int(r["ФСА importer"] or 0) > 0 for r in rows),
            "browser_session": browser.debug,
            "captured_templates": templates_debug,
            "transport": "selenium_ui_captured_fetch",
        }
        write_outputs(rows, raw_results, summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
        print("\nГотово: output_fsa_1000\\fsa_1000.csv", flush=True)
        return 0
    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
