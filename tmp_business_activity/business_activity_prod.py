#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Production collector for certificate/declaration evidence.

Primary source: S-34.
Secondary source: СООТВЕТСТВИЕ.РУС only for S-34 gaps.
List-Org is intentionally excluded from the default production cascade.

Key properties:
- accepts XLSX/CSV/TXT input;
- default limit = 5000 unique INNs;
- SQLite checkpoint after every company;
- safe resume after interruption;
- retries + browser restart;
- browser restart every N companies;
- atomic CSV/JSON snapshots;
- strict separation FOUND / NOT_FOUND / ERROR;
- no CAPTCHA/rate-limit bypass.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import sqlite3
import sys
import time
import traceback
import zipfile
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree as ET

import multisource_cert_pilot as m

DEFAULT_LIMIT = 5000
DONE_STATUSES = {"FOUND", "NOT_FOUND_VERIFIED", "NOT_FOUND"}
RETRY_DELAYS = (3, 8, 20)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_inn(value: Any) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    # Excel may expose a numeric-looking INN with .0.
    if re.fullmatch(r"\d+\.0", s):
        s = s[:-2]
    s = re.sub(r"\D", "", s)
    return s if len(s) in (10, 12) else ""


def dedupe_keep_order(values: Iterable[str], limit: int | None = None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in values:
        inn = normalize_inn(raw)
        if not inn or inn in seen:
            continue
        seen.add(inn)
        out.append(inn)
        if limit and len(out) >= limit:
            break
    return out


def _xlsx_col_index(cell_ref: str) -> int:
    letters = re.match(r"[A-Z]+", cell_ref.upper())
    if not letters:
        return -1
    n = 0
    for ch in letters.group(0):
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _xlsx_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    try:
        raw = zf.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ET.fromstring(raw)
    ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    out: list[str] = []
    for si in root.findall("a:si", ns):
        parts = [t.text or "" for t in si.findall(".//a:t", ns)]
        out.append("".join(parts))
    return out


def _xlsx_sheet_path(zf: zipfile.ZipFile, sheet_name: str) -> str:
    wb_root = ET.fromstring(zf.read("xl/workbook.xml"))
    ns = {
        "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    }
    rel_id = None
    for sh in wb_root.findall("a:sheets/a:sheet", ns):
        if sh.attrib.get("name") == sheet_name:
            rel_id = sh.attrib.get("{%s}id" % ns["r"])
            break
    if not rel_id:
        names = [sh.attrib.get("name", "") for sh in wb_root.findall("a:sheets/a:sheet", ns)]
        raise RuntimeError(f"Sheet {sheet_name!r} not found. Available: {names}")

    rel_root = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rel_ns = {"p": "http://schemas.openxmlformats.org/package/2006/relationships"}
    target = None
    for rel in rel_root.findall("p:Relationship", rel_ns):
        if rel.attrib.get("Id") == rel_id:
            target = rel.attrib.get("Target")
            break
    if not target:
        raise RuntimeError(f"Worksheet relationship not found for {sheet_name!r}")
    target = target.lstrip("/")
    if target.startswith("xl/"):
        return target
    return "xl/" + target


def _xlsx_cell_value(cell: ET.Element, shared: list[str]) -> str:
    main_ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    typ = cell.attrib.get("t", "")
    if typ == "inlineStr":
        return "".join((t.text or "") for t in cell.findall(f".//{{{main_ns}}}t"))
    v = cell.find(f"{{{main_ns}}}v")
    if v is None or v.text is None:
        return ""
    if typ == "s":
        try:
            return shared[int(v.text)]
        except Exception:
            return v.text
    return v.text


def read_xlsx_inns(path: Path, sheet_name: str, header: str, limit: int) -> list[str]:
    with zipfile.ZipFile(path) as zf:
        shared = _xlsx_shared_strings(zf)
        sheet_path = _xlsx_sheet_path(zf, sheet_name)
        root = ET.fromstring(zf.read(sheet_path))
        ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        rows = root.findall("a:sheetData/a:row", ns)
        header_col = None
        data: list[str] = []
        for row in rows:
            cells = row.findall("a:c", ns)
            values: dict[int, str] = {}
            for c in cells:
                idx = _xlsx_col_index(c.attrib.get("r", ""))
                if idx >= 0:
                    values[idx] = _xlsx_cell_value(c, shared).strip()
            if header_col is None:
                for idx, value in values.items():
                    if value.strip() == header:
                        header_col = idx
                        break
                continue
            if header_col in values:
                inn = normalize_inn(values[header_col])
                if inn:
                    data.append(inn)
                    if len(set(data)) >= limit:
                        break
        if header_col is None:
            raise RuntimeError(f"Header {header!r} not found in sheet {sheet_name!r}")
        return dedupe_keep_order(data, limit)


def read_csv_inns(path: Path, header: str, limit: int) -> list[str]:
    raw = path.read_bytes()
    text = None
    for enc in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            pass
    if text is None:
        raise RuntimeError("Could not decode CSV")
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t,")
    except csv.Error:
        dialect = csv.excel
        dialect.delimiter = ";"
    rows = list(csv.reader(text.splitlines(), dialect))
    if not rows:
        return []
    header_idx = None
    for i, value in enumerate(rows[0]):
        if value.strip() == header:
            header_idx = i
            break
    if header_idx is None:
        # Simple one-column CSV/TXT-like file.
        if len(rows[0]) == 1:
            return dedupe_keep_order((r[0] for r in rows), limit)
        raise RuntimeError(f"Header {header!r} not found in CSV")
    return dedupe_keep_order((r[header_idx] for r in rows[1:] if len(r) > header_idx), limit)


def read_txt_inns(path: Path, limit: int) -> list[str]:
    return dedupe_keep_order(path.read_text(encoding="utf-8-sig").splitlines(), limit)


def load_inns(path: Path, sheet: str, header: str, limit: int) -> list[str]:
    ext = path.suffix.lower()
    if ext == ".xlsx":
        return read_xlsx_inns(path, sheet, header, limit)
    if ext in (".csv", ".tsv"):
        return read_csv_inns(path, header, limit)
    if ext in (".txt", ".list"):
        return read_txt_inns(path, limit)
    raise RuntimeError("Supported input formats: .xlsx, .csv, .tsv, .txt")


def evidence_class(row: dict[str, Any] | None) -> str:
    if not row:
        return "NO_CERT_EVIDENCE"
    if row.get("status") != "FOUND":
        return "NO_CERT_EVIDENCE"
    same = int(row.get("same_as_applicant_docs") or 0)
    other = int(row.get("other_manufacturer_docs") or 0)
    if same > 0 and other > 0:
        return "MIXED_PRODUCTION_AND_TRADE"
    if same > 0:
        return "PRODUCTION_STRONG"
    if other > 0:
        return "TRADE_IMPORT_STRONG"
    return "CERT_EVIDENCE_ROLE_UNKNOWN"


class StateDB:
    def __init__(self, path: Path):
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self._init()

    def _init(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS companies (
              inn TEXT PRIMARY KEY,
              input_order INTEGER NOT NULL,
              final_status TEXT NOT NULL DEFAULT 'PENDING',
              final_source TEXT,
              evidence_class TEXT,
              s34_status TEXT,
              soot_status TEXT,
              documents INTEGER,
              same_docs INTEGER,
              other_docs INTEGER,
              active_docs INTEGER,
              products_json TEXT,
              urls_json TEXT,
              last_error TEXT,
              attempts INTEGER NOT NULL DEFAULT 0,
              updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS source_runs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              inn TEXT NOT NULL,
              source TEXT NOT NULL,
              attempt INTEGER NOT NULL,
              status TEXT,
              documents INTEGER,
              error TEXT,
              started_at TEXT,
              finished_at TEXT
            );
            """
        )
        self.conn.commit()

    def seed(self, inns: list[str]) -> None:
        with self.conn:
            for i, inn in enumerate(inns, 1):
                self.conn.execute(
                    "INSERT OR IGNORE INTO companies(inn,input_order) VALUES(?,?)",
                    (inn, i),
                )

    def pending(self, retry_errors: bool = True) -> list[str]:
        statuses = ("PENDING", "ERROR") if retry_errors else ("PENDING",)
        marks = ",".join("?" for _ in statuses)
        cur = self.conn.execute(
            f"SELECT inn FROM companies WHERE final_status IN ({marks}) ORDER BY input_order",
            statuses,
        )
        return [r[0] for r in cur.fetchall()]

    def record_source(self, inn: str, source: str, attempt: int, row: dict[str, Any], started: str) -> None:
        with self.conn:
            self.conn.execute(
                """INSERT INTO source_runs(inn,source,attempt,status,documents,error,started_at,finished_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (
                    inn, source, attempt, row.get("status"), int(row.get("documents") or 0),
                    row.get("error") or "", started, utc_now(),
                ),
            )

    def finish(self, inn: str, s34: dict[str, Any] | None, soot: dict[str, Any] | None, final_status: str, last_error: str = "") -> None:
        winner = s34 if s34 and s34.get("status") == "FOUND" else soot if soot and soot.get("status") == "FOUND" else None
        source = winner.get("source") if winner else ""
        klass = evidence_class(winner)
        documents = int(winner.get("documents") or 0) if winner else 0
        same = int(winner.get("same_as_applicant_docs") or 0) if winner else 0
        other = int(winner.get("other_manufacturer_docs") or 0) if winner else 0
        active = winner.get("active_docs") if winner else 0
        try:
            active = int(active or 0)
        except Exception:
            active = 0
        products = winner.get("products") or [] if winner else []
        urls = winner.get("urls") or [] if winner else []
        with self.conn:
            self.conn.execute(
                """UPDATE companies SET
                   final_status=?, final_source=?, evidence_class=?,
                   s34_status=?, soot_status=?, documents=?, same_docs=?, other_docs=?, active_docs=?,
                   products_json=?, urls_json=?, last_error=?, attempts=attempts+1, updated_at=?
                   WHERE inn=?""",
                (
                    final_status, source, klass,
                    (s34 or {}).get("status", ""), (soot or {}).get("status", ""),
                    documents, same, other, active,
                    json.dumps(products, ensure_ascii=False), json.dumps(urls, ensure_ascii=False),
                    last_error, utc_now(), inn,
                ),
            )

    def rows(self) -> list[dict[str, Any]]:
        self.conn.row_factory = sqlite3.Row
        cur = self.conn.execute("SELECT * FROM companies ORDER BY input_order")
        return [dict(r) for r in cur.fetchall()]

    def close(self) -> None:
        self.conn.close()


def atomic_write_text(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def export_snapshots(db: StateDB, out_dir: Path) -> None:
    rows = db.rows()
    csv_path = out_dir / "business_activity_results.csv"
    tmp_csv = csv_path.with_suffix(".csv.tmp")
    fields = [
        "input_order", "inn", "final_status", "final_source", "evidence_class",
        "s34_status", "soot_status", "documents", "same_docs", "other_docs", "active_docs",
        "products", "urls", "last_error", "attempts", "updated_at",
    ]
    with tmp_csv.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter=";")
        w.writeheader()
        for r in rows:
            w.writerow({
                "input_order": r["input_order"],
                "inn": r["inn"],
                "final_status": r["final_status"],
                "final_source": r["final_source"] or "",
                "evidence_class": r["evidence_class"] or "",
                "s34_status": r["s34_status"] or "",
                "soot_status": r["soot_status"] or "",
                "documents": r["documents"] or 0,
                "same_docs": r["same_docs"] or 0,
                "other_docs": r["other_docs"] or 0,
                "active_docs": r["active_docs"] or 0,
                "products": " || ".join(json.loads(r["products_json"] or "[]")),
                "urls": " || ".join(json.loads(r["urls_json"] or "[]")),
                "last_error": r["last_error"] or "",
                "attempts": r["attempts"] or 0,
                "updated_at": r["updated_at"] or "",
            })
    os.replace(tmp_csv, csv_path)

    status_counts = Counter(r["final_status"] for r in rows)
    evidence_counts = Counter((r["evidence_class"] or "") for r in rows if r["final_status"] == "FOUND")
    source_counts = Counter((r["final_source"] or "") for r in rows if r["final_status"] == "FOUND")
    done = sum(r["final_status"] in ("FOUND", "NOT_FOUND") for r in rows)
    found = status_counts.get("FOUND", 0)
    summary = {
        "total_input": len(rows),
        "processed_final": done,
        "found": found,
        "not_found": status_counts.get("NOT_FOUND", 0),
        "errors": status_counts.get("ERROR", 0),
        "pending": status_counts.get("PENDING", 0),
        "coverage_pct": round(100 * found / len(rows), 1) if rows else 0,
        "status_counts": dict(status_counts),
        "evidence_class_counts": dict(evidence_counts),
        "found_by_source": dict(source_counts),
        "updated_at": utc_now(),
    }
    atomic_write_text(out_dir / "summary.json", json.dumps(summary, ensure_ascii=False, indent=2))


def is_transport_error(row: dict[str, Any]) -> bool:
    if row.get("status") != "ERROR":
        return False
    text = (row.get("error") or "").lower()
    transport_tokens = (
        "webdriver", "timeout", "chrome", "edge", "disconnected", "connection", "session",
        "not reachable", "target window", "tab crashed",
    )
    return any(t in text for t in transport_tokens)


def call_with_retries(driver, source: str, inn: str, attempts: int, db: StateDB) -> tuple[dict[str, Any], bool]:
    fn = m.scrape_s34 if source == "S34" else m.scrape_sootvetstvie
    last: dict[str, Any] = {"inn": inn, "source": source, "status": "ERROR", "error": "not run"}
    restart_needed = False
    for attempt in range(1, attempts + 1):
        started = utc_now()
        try:
            last = fn(driver, inn)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            last = {
                "inn": inn, "source": source, "status": "ERROR", "documents": 0,
                "error": f"{type(exc).__name__}: {exc}",
            }
        db.record_source(inn, source, attempt, last, started)
        if last.get("status") != "ERROR":
            return last, restart_needed
        restart_needed = restart_needed or is_transport_error(last)
        if attempt < attempts:
            delay = RETRY_DELAYS[min(attempt - 1, len(RETRY_DELAYS) - 1)]
            print(f"    {source} attempt {attempt} ERROR; retry in {delay}s: {last.get('error','')[:180]}")
            time.sleep(delay)
    return last, restart_needed


def start_driver_with_retries(attempts: int = 3):
    last_exc = None
    for i in range(1, attempts + 1):
        try:
            return m.start_driver()
        except Exception as exc:
            last_exc = exc
            if i < attempts:
                time.sleep(RETRY_DELAYS[min(i - 1, len(RETRY_DELAYS) - 1)])
    raise RuntimeError(f"Cannot start browser after {attempts} attempts: {last_exc}")


def safe_quit(driver) -> None:
    if driver is None:
        return
    try:
        driver.quit()
    except Exception:
        pass


def restart_driver(driver):
    safe_quit(driver)
    time.sleep(1)
    return start_driver_with_retries()


@contextmanager
def run_lock(path: Path):
    if path.exists():
        raise RuntimeError(
            f"Lock file exists: {path}. If no scraper is running, delete this file and start again."
        )
    path.write_text(f"pid={os.getpid()}\nstarted={utc_now()}\n", encoding="utf-8")
    try:
        yield
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Production certificate evidence collector")
    p.add_argument("--input", required=True, help="Input .xlsx/.csv/.txt")
    p.add_argument("--sheet", default="финал", help="XLSX sheet name")
    p.add_argument("--header", default="ИНН текстом", help="INN column header")
    p.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Max unique INNs; default 5000")
    p.add_argument("--output", default="output_business_activity_prod", help="Output directory")
    p.add_argument("--restart-every", type=int, default=100, help="Restart browser every N processed INNs")
    p.add_argument("--max-attempts", type=int, default=3, help="Attempts per source")
    p.add_argument("--snapshot-every", type=int, default=25, help="Rewrite CSV/summary every N processed")
    p.add_argument("--no-retry-errors", action="store_true", help="Do not retry ERROR rows from previous runs")
    p.add_argument("--dry-run", action="store_true", help="Validate input only; do not open browser")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        raise SystemExit(f"Input file not found: {input_path}")
    if args.limit < 1:
        raise SystemExit("--limit must be >= 1")

    out_dir = Path(args.output).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = out_dir / "cache"
    cache_dir.mkdir(exist_ok=True)

    # Point the tested source module at production cache/output, so cache is
    # isolated from all pilot runs.
    m.OUT = out_dir
    m.CACHE = cache_dir

    inns = load_inns(input_path, args.sheet, args.header, args.limit)
    if not inns:
        raise SystemExit("No valid INNs found in input")
    print(f"Loaded {len(inns)} unique INNs from {input_path.name}")
    print(f"Output: {out_dir}")
    if len(inns) < args.limit:
        print(f"WARNING: input contains only {len(inns)} valid unique INNs; requested limit={args.limit}")

    if args.dry_run:
        print("DRY RUN OK")
        print("First 5 INNs:", ", ".join(inns[:5]))
        return 0

    db = StateDB(out_dir / "checkpoint.sqlite3")
    db.seed(inns)
    export_snapshots(db, out_dir)

    lock_path = out_dir / "RUNNING.lock"
    driver = None
    processed_this_run = 0
    try:
        with run_lock(lock_path):
            pending = db.pending(retry_errors=not args.no_retry_errors)
            print(f"Remaining: {len(pending)} / {len(inns)}")
            if not pending:
                print("Nothing to do. All rows are already finalized.")
                return 0

            driver = start_driver_with_retries()
            started_ts = time.time()
            for pos, inn in enumerate(pending, 1):
                print(f"\n[{pos}/{len(pending)}] INN {inn}")
                restart_after_company = False

                s34, restart1 = call_with_retries(driver, "S34", inn, args.max_attempts, db)
                restart_after_company = restart_after_company or restart1
                print(
                    f"  S34: {s34.get('status')} docs={s34.get('documents',0)} "
                    f"same={s34.get('same_as_applicant_docs',0)} other={s34.get('other_manufacturer_docs',0)}"
                )

                soot = None
                final_status = "ERROR"
                last_error = ""
                if s34.get("status") == "FOUND":
                    final_status = "FOUND"
                elif s34.get("status") == "NOT_FOUND":
                    soot, restart2 = call_with_retries(driver, "SOOTVETSTVIE", inn, args.max_attempts, db)
                    restart_after_company = restart_after_company or restart2
                    print(
                        f"  SOOTVETSTVIE: {soot.get('status')} docs={soot.get('documents',0)} "
                        f"same={soot.get('same_as_applicant_docs',0)} other={soot.get('other_manufacturer_docs',0)}"
                    )
                    if soot.get("status") == "FOUND":
                        final_status = "FOUND"
                    elif soot.get("status") in ("NOT_FOUND", "NOT_FOUND_VERIFIED"):
                        final_status = "NOT_FOUND"
                    else:
                        final_status = "ERROR"
                        last_error = soot.get("error") or "SOOTVETSTVIE error"
                else:
                    final_status = "ERROR"
                    last_error = s34.get("error") or "S34 error"

                db.finish(inn, s34, soot, final_status, last_error)
                processed_this_run += 1

                if processed_this_run % args.snapshot_every == 0:
                    export_snapshots(db, out_dir)
                    elapsed = max(1, time.time() - started_ts)
                    rate = processed_this_run / elapsed * 3600
                    print(f"  Snapshot saved. Run speed: {rate:.1f} companies/hour")

                if restart_after_company or processed_this_run % args.restart_every == 0:
                    reason = "transport error" if restart_after_company else f"scheduled every {args.restart_every}"
                    print(f"  Restart browser ({reason})")
                    driver = restart_driver(driver)

            export_snapshots(db, out_dir)
            print("\nDONE")
            print(f"Results: {out_dir / 'business_activity_results.csv'}")
            print(f"Summary: {out_dir / 'summary.json'}")
            print(f"Checkpoint: {out_dir / 'checkpoint.sqlite3'}")
            return 0

    except KeyboardInterrupt:
        print("\nInterrupted by user. Saving checkpoint/snapshot...")
        export_snapshots(db, out_dir)
        return 130
    except Exception as exc:
        print(f"\nFATAL: {type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc()
        try:
            export_snapshots(db, out_dir)
        except Exception:
            pass
        return 1
    finally:
        safe_quit(driver)
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
