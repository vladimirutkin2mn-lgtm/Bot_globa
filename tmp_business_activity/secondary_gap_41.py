#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import json
import os
import time
from collections import Counter
from pathlib import Path

import multisource_cert_pilot as m

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output_secondary_gap_41"
OUT.mkdir(exist_ok=True)

INNS = [x.strip() for x in (ROOT / "missing_s34_41.txt").read_text(encoding="utf-8").splitlines() if x.strip()]
RUN_LISTORG = os.getenv("RUN_LISTORG_GAPS", "1") == "1"

def flatten(row):
    return m.flatten(row)

def write(rows):
    flat=[flatten(x) for x in rows]
    fields=list(flat[0].keys()) if flat else []
    with (OUT/"secondary_gap_results.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w=csv.DictWriter(f, fieldnames=fields, delimiter=";")
        w.writeheader(); w.writerows(flat)

    summary={}
    for source in ("SOOTVETSTVIE","LIST_ORG"):
        rs=[x for x in rows if x.get("source")==source]
        summary[source]={
            "rows":len(rs),
            "status_counts":dict(Counter(x.get("status") for x in rs)),
            "found":sum(x.get("status")=="FOUND" for x in rs),
            "documents_sum":sum(int(x.get("documents") or 0) for x in rs if str(x.get("documents") or "").isdigit()),
        }
    covered=len({x["inn"] for x in rows if x.get("status")=="FOUND"})
    summary["COMBINED"]={
        "input_inns":len(INNS),
        "covered_secondary":covered,
        "incremental_coverage_pct_of_41":round(100*covered/len(INNS),1) if INNS else 0,
        "projected_total_coverage_of_100":59+covered,
    }
    (OUT/"secondary_gap_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

def main():
    print(f"Secondary-gap pilot: {len(INNS)} INNs missed by S34.")
    print("SOOTVETSTVIE first, strict target-INN verification. List-Org optional.")
    driver=m.start_driver()
    rows=[]
    listorg_blocked=False
    try:
        for n,inn in enumerate(INNS,1):
            print(f"\n[{n}/{len(INNS)}] {inn}", flush=True)

            soot=m.scrape_sootvetstvie(driver, inn)
            rows.append(soot)
            print(f"  SOOTVETSTVIE: {soot['status']} docs={soot.get('documents')}", flush=True)
            m.pause()

            if RUN_LISTORG:
                if listorg_blocked:
                    lo={
                        "inn":inn,"source":"LIST_ORG","status":"SKIPPED_AFTER_CAPTCHA",
                        "documents":"","certificates":"","declarations":"","roles":[],
                        "active_docs":"","same_as_applicant_docs":0,"other_manufacturer_docs":0,
                        "products":[],"urls":[],"company_url":"","error":"",
                    }
                else:
                    lo=m.scrape_listorg(driver, inn)
                    if lo["status"]=="BLOCKED_CAPTCHA":
                        listorg_blocked=True
                rows.append(lo)
                print(f"  LIST_ORG: {lo['status']} docs={lo.get('documents')}", flush=True)
                m.pause()

            write(rows)

        return 0
    finally:
        try: driver.quit()
        except Exception: pass

if __name__=="__main__":
    raise SystemExit(main())
