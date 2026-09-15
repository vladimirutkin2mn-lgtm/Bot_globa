#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bulk enrichment of Russian legal entities by INN.
Temporary research utility; outputs CSV/JSON artifacts only.
"""
from __future__ import annotations

import base64
import csv
import gzip
import io
import json
import os
import re
import sys
import time
import zipfile
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

import requests

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
TMP = ROOT / "downloads"
OUT.mkdir(exist_ok=True)
TMP.mkdir(exist_ok=True)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36"
S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept": "*/*"})


def log(msg: str):
    print(time.strftime("[%H:%M:%S]"), msg, flush=True)


def load_inns() -> list[str]:
    parts = sorted(ROOT.glob("inns.b64.*"))
    if not parts:
        raise RuntimeError("INN chunks are missing")
    b64 = "".join(p.read_text(encoding="utf-8").strip() for p in parts)
    raw = gzip.decompress(base64.b64decode(b64)).decode("utf-8")
    inns = [x.strip() for x in raw.splitlines() if re.fullmatch(r"\d{10}", x.strip())]
    if len(inns) != 26357:
        raise RuntimeError(f"Expected 26357 INNs, got {len(inns)}")
    if len(set(inns)) != len(inns):
        raise RuntimeError("Duplicate INNs in input")
    log(f"Loaded {len(inns):,} INNs")
    return inns


def download(url: str, dest: Path, timeout=120, retries=3) -> bool:
    if dest.exists() and dest.stat().st_size > 1024:
        log(f"Using cached {dest.name} ({dest.stat().st_size/1e6:.1f} MB)")
        return True
    for a in range(retries):
        try:
            log(f"Downloading {url}")
            with S.get(url, stream=True, timeout=timeout, allow_redirects=True) as r:
                if r.status_code != 200:
                    log(f"HTTP {r.status_code} for {url}")
                    time.sleep(2 ** a)
                    continue
                total = int(r.headers.get("content-length") or 0)
                with dest.open("wb") as f:
                    got = 0
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)
                            got += len(chunk)
                            if total and got % (200 * 1024 * 1024) < 1024 * 1024:
                                log(f"  {got/1e6:.0f}/{total/1e6:.0f} MB")
            if dest.stat().st_size > 1024:
                return True
        except Exception as e:
            log(f"Download error: {e}")
            time.sleep(2 ** a)
    return False


def resolve_fns_rsmp_url() -> str | None:
    dataset = "7707329152-rsmp"
    # 1) machine-readable metadata
    for host in ("file.nalog.ru", "data.nalog.ru"):
        try:
            u = f"https://{host}/opendata/{dataset}/meta.json"
            r = S.get(u, timeout=30)
            if r.ok:
                meta = r.json()
                dist = meta.get("distribution") or []
                if isinstance(dist, dict): dist = [dist]
                urls = []
                for d in dist:
                    if isinstance(d, dict):
                        x = d.get("downloadURL") or d.get("accessURL") or ""
                        if isinstance(x, str) and x.endswith(".zip"):
                            urls.append(x)
                if urls:
                    return sorted(urls)[-1]
        except Exception as e:
            log(f"FNS meta failed: {e}")
    # 2) public dataset pages
    for u in (
        f"https://www.nalog.gov.ru/opendata/{dataset}/",
        f"https://www.nalog.gov.ru/rn77/opendata/{dataset}/",
        f"https://www.nalog.gov.ru/rn26/opendata/{dataset}/",
    ):
        try:
            r = S.get(u, timeout=40)
            if not r.ok: continue
            links = re.findall(r'https?://(?:file|data)\.nalog\.ru/opendata/7707329152-rsmp/data-[^\"\'\s<>]+?\.zip', r.text, flags=re.I)
            if links:
                def key(x):
                    m = re.search(r"data-(\d{8})", x)
                    return m.group(1) if m else ""
                return sorted(set(links), key=key)[-1]
        except Exception as e:
            log(f"FNS page failed {u}: {e}")
    # 3) recent known snapshots / likely monthly snapshots
    candidates = [
        "data-10092026-structure-12052026.zip",
        "data-10082026-structure-12052026.zip",
        "data-10072026-structure-12052026.zip",
        "data-10062026-structure-12052026.zip",
        "data-10052026-structure-12052026.zip",
    ]
    for name in candidates:
        u = f"https://file.nalog.ru/opendata/{dataset}/{name}"
        try:
            r = S.head(u, timeout=20, allow_redirects=True)
            if r.status_code == 200:
                return u
        except Exception:
            pass
    return None


def local_tag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def attr_any(elem, keys):
    for k, v in elem.attrib.items():
        lk = k.lower()
        if any(x in lk for x in keys) and v not in (None, ""):
            return str(v).strip()
    return ""


def parse_fns_rsmp(zip_path: Path, targets: set[str]) -> dict[str, dict]:
    found: dict[str, dict] = {}
    log(f"Parsing FNS SME registry for {len(targets):,} targets")
    with zipfile.ZipFile(zip_path) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".xml")]
        log(f"FNS ZIP contains {len(names)} XML files")
        for idx, name in enumerate(names, 1):
            try:
                with z.open(name) as fh:
                    for event, elem in ET.iterparse(fh, events=("end",)):
                        if local_tag(elem.tag) != "Документ":
                            continue
                        inn = ""
                        org_name = ""
                        okved = ""
                        employees = ""
                        category = elem.attrib.get("КатСубМСП", "")
                        include_dt = elem.attrib.get("ДатаВклМСП", "")
                        # Search document subtree only when a candidate INN is found.
                        for sub in elem.iter():
                            for ak, av in sub.attrib.items():
                                if ak == "ИННЮЛ" or ak.lower().endswith("иннюл"):
                                    inn = str(av).strip()
                                    break
                            if inn:
                                break
                        if inn in targets:
                            for sub in elem.iter():
                                t = local_tag(sub.tag)
                                if not org_name:
                                    org_name = attr_any(sub, ("наиморг", "наим")) if ("Орг" in t or "МСП" in t) else ""
                                if t in ("СвОКВЭДОсн", "СвОКВЭД") and not okved:
                                    okved = sub.attrib.get("КодОКВЭД", "") or attr_any(sub, ("оквэд",))
                                if not employees:
                                    employees = sub.attrib.get("ССЧР", "") or sub.attrib.get("КолРаб", "")
                            if not employees:
                                employees = elem.attrib.get("ССЧР", "")
                            found[inn] = {
                                "name_fns": org_name,
                                "okved_fns": okved,
                                "msp_category": category,
                                "employees": employees,
                                "msp_included": include_dt,
                                "fns_rsmp": "YES",
                            }
                        elem.clear()
            except Exception as e:
                log(f"FNS XML error {name}: {e}")
            if idx % 50 == 0 or idx == len(names):
                log(f"FNS files {idx}/{len(names)}; matches {len(found):,}")
            if len(found) == len(targets):
                break
    log(f"FNS SME matches: {len(found):,}/{len(targets):,}")
    return found


def download_rosstat() -> Path | None:
    candidates = [
        "https://rosstat.gov.ru/opendata/7708234640-urid/data-20260206T1502-structure-20240206T1002.csv",
        "https://www.rosstat.gov.ru/opendata/7708234640-urid/data-20260206T1502-structure-20240206T1002.csv",
    ]
    dest = TMP / "rosstat_statregister.csv"
    for u in candidates:
        if download(u, dest, timeout=180, retries=2):
            return dest
        if dest.exists(): dest.unlink()
    return None


def norm(s: str) -> str:
    return re.sub(r"[^a-zа-я0-9]+", "", (s or "").lower().replace("ё", "е"))


def detect_encoding(path: Path) -> str:
    b = path.open("rb").read(200000)
    for enc in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            b.decode(enc)
            return enc
        except UnicodeDecodeError:
            pass
    return "cp1251"


def parse_rosstat(path: Path, targets: set[str]) -> dict[str, dict]:
    found = {}
    enc = detect_encoding(path)
    log(f"Parsing Rosstat Statregister ({enc})")
    with path.open("r", encoding=enc, errors="replace", newline="") as f:
        sample = f.read(20000)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=";,\t|")
        except Exception:
            dialect = csv.excel
            dialect.delimiter = ";"
        reader = csv.reader(f, dialect)
        try:
            headers = next(reader)
        except StopIteration:
            return found
        nh = [norm(x) for x in headers]
        log("Rosstat headers: " + " | ".join(headers[:20]))
        def col(preds):
            for i, h in enumerate(nh):
                if any(p in h for p in preds): return i
            return None
        i_inn = col(("inn", "инн"))
        i_name = col(("name", "наим"))
        i_okved = col(("okved", "оквэд"))
        i_opf = col(("okopf", "окопф", "opf"))
        if i_inn is None:
            log("Could not locate INN column in Rosstat CSV")
            return found
        n = 0
        for row in reader:
            n += 1
            if i_inn >= len(row): continue
            inn = re.sub(r"\D", "", row[i_inn])
            if inn not in targets: continue
            found[inn] = {
                "name_rosstat": row[i_name].strip() if i_name is not None and i_name < len(row) else "",
                "okved_rosstat": row[i_okved].strip() if i_okved is not None and i_okved < len(row) else "",
                "opf_rosstat": row[i_opf].strip() if i_opf is not None and i_opf < len(row) else "",
                "rosstat": "YES",
            }
            if len(found) == len(targets): break
            if n % 1_000_000 == 0:
                log(f"Rosstat rows {n:,}; matches {len(found):,}")
    log(f"Rosstat matches: {len(found):,}/{len(targets):,}")
    return found


def classify_okved(code: str):
    code = (code or "").strip().replace(",", ".")
    m = re.match(r"^(\d{2})", code)
    if not m:
        return "НЕ ОПРЕДЕЛЕНО", "REVIEW"
    x = int(m.group(1))
    if 10 <= x <= 33:
        return "ПРОИЗВОДСТВО", "YES"
    if x == 46:
        return "ОПТ", "YES"
    if x == 47:
        return "РОЗНИЦА", "YES"
    if (49 <= x <= 53 or 55 <= x <= 56 or 58 <= x <= 63 or
        69 <= x <= 75 or 77 <= x <= 82 or 85 <= x <= 88 or 90 <= x <= 96):
        return "УСЛУГИ", "YES"
    if 1 <= x <= 3:
        return "СЕЛЬСКОЕ ХОЗЯЙСТВО", "NO"
    if 5 <= x <= 9:
        return "ДОБЫЧА", "NO"
    if 35 <= x <= 39:
        return "ЭНЕРГЕТИКА / ЖКХ", "REVIEW"
    if 41 <= x <= 43:
        return "СТРОИТЕЛЬСТВО", "REVIEW"
    if x == 45:
        return "АВТОТОРГОВЛЯ / РЕМОНТ", "REVIEW"
    if 64 <= x <= 66:
        return "ФИНАНСЫ / СТРАХОВАНИЕ", "NO"
    if x == 68:
        return "НЕДВИЖИМОСТЬ", "REVIEW"
    return "ПРОЧЕЕ", "REVIEW"


def best_value(row, fns_key, ros_key):
    return row.get(fns_key) or row.get(ros_key) or ""


def write_results(inns, data):
    fields = [
        "ИНН", "Наименование", "ОПФ/ОКОПФ", "Основной ОКВЭД", "Тип деятельности",
        "Соответствует policy", "Confidence классификации", "Evidence count",
        "ФНС МСП", "Росстат", "Категория МСП", "ССЧР", "Дата включения МСП",
        "ОКВЭД ФНС", "ОКВЭД Росстат", "Совпадение ОКВЭД источников", "Статус"
    ]
    out_csv = OUT / "business_activity_full.csv"
    stats = Counter()
    with out_csv.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter=";")
        w.writeheader()
        for inn in inns:
            r = data.get(inn, {})
            code = best_value(r, "okved_fns", "okved_rosstat")
            btype, eligible = classify_okved(code)
            sources = int(r.get("fns_rsmp") == "YES") + int(r.get("rosstat") == "YES")
            agree = ""
            if r.get("okved_fns") and r.get("okved_rosstat"):
                agree = "YES" if r["okved_fns"] == r["okved_rosstat"] else "NO"
            confidence = "HIGH" if sources >= 2 and (agree != "NO") else ("MEDIUM" if sources >= 1 and code else "LOW")
            status = "OK" if code else ("FOUND_NO_OKVED" if sources else "NOT_FOUND")
            name = best_value(r, "name_fns", "name_rosstat")
            opf = r.get("opf_rosstat", "")
            row = {
                "ИНН": inn, "Наименование": name, "ОПФ/ОКОПФ": opf,
                "Основной ОКВЭД": code, "Тип деятельности": btype,
                "Соответствует policy": eligible, "Confidence классификации": confidence,
                "Evidence count": sources, "ФНС МСП": r.get("fns_rsmp", "NO"),
                "Росстат": r.get("rosstat", "NO"), "Категория МСП": r.get("msp_category", ""),
                "ССЧР": r.get("employees", ""), "Дата включения МСП": r.get("msp_included", ""),
                "ОКВЭД ФНС": r.get("okved_fns", ""), "ОКВЭД Росстат": r.get("okved_rosstat", ""),
                "Совпадение ОКВЭД источников": agree, "Статус": status,
            }
            w.writerow(row)
            stats[(btype, eligible, confidence, status)] += 1
    summary = {
        "input_rows": len(inns),
        "matched_any": sum(1 for i in inns if data.get(i, {}).get("fns_rsmp") == "YES" or data.get(i, {}).get("rosstat") == "YES"),
        "with_okved": sum(1 for i in inns if best_value(data.get(i, {}), "okved_fns", "okved_rosstat")),
        "breakdown": [
            {"business_type": k[0], "eligible": k[1], "confidence": k[2], "status": k[3], "count": v}
            for k, v in sorted(stats.items(), key=lambda x: (-x[1], x[0]))
        ],
    }
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    log(json.dumps({k:v for k,v in summary.items() if k != "breakdown"}, ensure_ascii=False))
    return summary


def main():
    inns = load_inns()
    targets = set(inns)
    data: dict[str, dict] = {i: {} for i in inns}

    # FNS SME open registry
    fns_url = resolve_fns_rsmp_url()
    log(f"Resolved FNS URL: {fns_url}")
    if fns_url:
        fns_zip = TMP / "fns_rsmp.zip"
        if download(fns_url, fns_zip, timeout=300, retries=3):
            try:
                fns = parse_fns_rsmp(fns_zip, targets)
                for i, r in fns.items(): data[i].update(r)
            except Exception as e:
                log(f"FNS parse fatal: {type(e).__name__}: {e}")

    # Rosstat Statregister; only if downloadable
    ros_path = download_rosstat()
    if ros_path:
        try:
            ros = parse_rosstat(ros_path, targets)
            for i, r in ros.items(): data[i].update(r)
        except Exception as e:
            log(f"Rosstat parse fatal: {type(e).__name__}: {e}")

    write_results(inns, data)


if __name__ == "__main__":
    main()
