#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pilot: compare public certificate/declaration evidence from 3 websites.

Sources:
- sootvetstvie.ru (user has permission for scraping)
- s-34.ru public search
- list-org.com public company pages

Design principles:
- first 20 INNs only by default
- slow rate, cache + resume
- no CAPTCHA bypass
- explicit BLOCKED / ERROR / NOT_FOUND states
"""
from __future__ import annotations

import csv
import json
import os
import random
import re
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output_multisource_pilot"
CACHE = OUT / "cache"
OUT.mkdir(exist_ok=True)
CACHE.mkdir(exist_ok=True)

SOOTV_BASE = "https://xn--b1aaibo6aawehcb.xn--p1acf"
S34_BASE = "https://s-34.ru"
LISTORG_BASE = "https://www.list-org.com"

MAX_INNS = int(os.getenv("PILOT_INNS", "100"))
MAX_DETAILS = int(os.getenv("PILOT_MAX_DETAILS", "8"))
S34_ROLE_CHECK_LIMIT = int(os.getenv("S34_ROLE_CHECK_LIMIT", "5"))
RUN_LISTORG = os.getenv("RUN_LISTORG", "0") == "1"
MIN_DELAY = float(os.getenv("PILOT_MIN_DELAY", "2.0"))
MAX_DELAY = float(os.getenv("PILOT_MAX_DELAY", "4.0"))


def pause() -> None:
    time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))


def clean_inn(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def load_inns() -> list[str]:
    inns: list[str] = []
    for i in range(1, 5):
        p = ROOT / f"inns_1000.part{i}"
        if not p.exists():
            continue
        inns.extend(clean_inn(x) for x in p.read_text(encoding="utf-8").splitlines())
    inns = [x for x in inns if len(x) in (10, 12)]
    seen, out = set(), []
    for x in inns:
        if x not in seen:
            seen.add(x)
            out.append(x)
    if not out:
        raise RuntimeError("No INNs found in inns_1000.part1..4")
    return out[:MAX_INNS]


def start_driver():
    opts = webdriver.ChromeOptions()
    opts.add_argument("--start-maximized")
    try:
        d = webdriver.Chrome(options=opts)
        d.set_page_load_timeout(60)
        return d
    except Exception as chrome_exc:
        eopts = webdriver.EdgeOptions()
        eopts.add_argument("--start-maximized")
        try:
            d = webdriver.Edge(options=eopts)
            d.set_page_load_timeout(60)
            return d
        except Exception as edge_exc:
            raise RuntimeError(f"Cannot start Chrome/Edge. Chrome={chrome_exc}; Edge={edge_exc}") from edge_exc


def cache_path(source: str, inn: str) -> Path:
    return CACHE / f"{source}_{inn}.json"


def load_cache(source: str, inn: str) -> dict[str, Any] | None:
    p = cache_path(source, inn)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_cache(source: str, inn: str, data: dict[str, Any]) -> None:
    cache_path(source, inn).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def body_text(driver) -> str:
    try:
        return driver.find_element(By.TAG_NAME, "body").text
    except Exception:
        return ""


def exact_inn_role_from_text(text: str, inn: str) -> set[str]:
    """Best-effort role extraction from rendered detail page text."""
    roles: set[str] = set()
    low = text.lower()
    pos = text.find(inn)
    if pos < 0:
        return roles
    before = low[max(0, pos - 1000):pos]
    # last major heading before INN
    if before.rfind("изготовител") > before.rfind("заявител"):
        roles.add("MANUFACTURER")
    elif before.rfind("заявител") >= 0:
        roles.add("APPLICANT")
    return roles


def product_excerpt(text: str) -> str:
    low = text.lower()
    for needle in ("продукция", "общее наименование продукции"):
        i = low.find(needle)
        if i >= 0:
            chunk = re.sub(r"\s+", " ", text[i:i+1000]).strip()
            return chunk[:1000]
    return ""


def find_soot_search_input(driver):
    selectors = [
        "input[placeholder*='ИНН/ОГРН']",
        "input[placeholder*='ИНН']",
        "input[placeholder*='Номер']",
    ]
    for sel in selectors:
        for el in driver.find_elements(By.CSS_SELECTOR, sel):
            try:
                if el.is_displayed():
                    return el
            except Exception:
                pass
    raise RuntimeError("SOOTVETSTVIE search input not found")


def soot_detail_evidence(text: str, inn: str) -> dict[str, Any]:
    """Only accept a detail page if the target INN is literally present."""
    if inn not in text:
        return {"valid": False, "roles": [], "active": False, "product": ""}

    roles: set[str] = set()
    low = text.lower()
    pos = text.find(inn)
    around_before = low[max(0, pos - 1800):pos]
    if around_before.rfind("заявител") >= 0:
        roles.add("APPLICANT")
    if around_before.rfind("изготовител") > around_before.rfind("заявител"):
        roles.add("MANUFACTURER")

    # The site explicitly tells us when applicant and manufacturer are the
    # same legal entity. This is much stronger than guessing from names.
    if "совпадает с заявителем: да" in low and "APPLICANT" in roles:
        roles.add("MANUFACTURER")

    active = (
        "ДЕЙСТВУЕТ" in text
        and not any(x in text for x in ("АРХИВНЫЙ", "ПРЕКРАЩЕН", "ПРЕКРАЩЁН", "АННУЛИРОВАН"))
    )

    product = ""
    marker = "НАИМЕНОВАНИЕ ПРОДУКЦИИ"
    i = text.find(marker)
    if i >= 0:
        chunk = re.sub(r"\s+", " ", text[i + len(marker):i + len(marker) + 1200]).strip()
        # Stop at the next common section if possible.
        cut = len(chunk)
        for stop in ("Маркировка продукции", "КОД ТН ВЭД", "Коды ТН ВЭД", "Технические регламенты", "Документы"):
            j = chunk.find(stop)
            if j >= 0:
                cut = min(cut, j)
        product = chunk[:cut].strip()[:1000]
    if not product:
        product = product_excerpt(text)

    return {
        "valid": True,
        "roles": sorted(roles),
        "active": active,
        "product": product,
    }


def scrape_sootvetstvie(driver, inn: str) -> dict[str, Any]:
    source = "SOOTVETSTVIE"
    cached = load_cache(source + "_V2", inn)
    if cached:
        return cached

    row = {
        "inn": inn, "source": source, "status": "NOT_FOUND",
        "documents": 0, "candidate_documents": 0,
        "certificates": 0, "declarations": 0,
        "roles": [], "active_docs": 0, "same_as_applicant_docs": 0,
        "other_manufacturer_docs": 0,
        "products": [], "urls": [],
        "company_url": "", "error": "",
    }
    try:
        # Always start from a clean documents page and use the site's own
        # search box. Direct ?q= navigation can leave stale SPA state.
        driver.get(f"{SOOTV_BASE}/documents")
        time.sleep(2.5)
        try:
            inp = find_soot_search_input(driver)
            inp.click()
            inp.clear()
            inp.send_keys(inn)
            inp.send_keys(Keys.ENTER)
            time.sleep(4)
        except Exception:
            # Some sessions render a compact/alternate layout without the
            # visible search input. Fall back to the site's public q= route,
            # but keep strict INN verification on every detail page below.
            # about:blank + cache-buster prevents stale SPA state carrying
            # results from the previous company into the next one.
            driver.get("about:blank")
            time.sleep(0.3)
            cb = int(time.time() * 1000)
            driver.get(f"{SOOTV_BASE}/documents?q={inn}&cb={cb}")
            time.sleep(4)

        anchors = driver.find_elements(By.CSS_SELECTOR, "a[href]")
        candidates: list[str] = []
        for a in anchors:
            href = (a.get_attribute("href") or "").split("#", 1)[0]
            if "/declarations/" in href or "/certificates/" in href:
                if href not in candidates:
                    candidates.append(href)

        row["candidate_documents"] = len(candidates)

        valid_urls: list[str] = []
        roles: set[str] = set()
        products: list[str] = []
        active = 0
        same = 0
        other = 0

        for url in candidates[:MAX_DETAILS]:
            pause()
            driver.get(url)
            time.sleep(1.3)
            txt = body_text(driver)
            ev = soot_detail_evidence(txt, inn)
            if not ev["valid"]:
                continue

            valid_urls.append(url)
            roles |= set(ev["roles"])
            if ev["active"]:
                active += 1
            if ev["product"] and ev["product"] not in products:
                products.append(ev["product"])

            low = txt.lower()
            if "совпадает с заявителем: да" in low:
                same += 1
            elif "совпадает с заявителем: нет" in low:
                other += 1

        row["urls"] = valid_urls
        row["documents"] = len(valid_urls)
        row["declarations"] = sum("/declarations/" in u for u in valid_urls)
        row["certificates"] = sum("/certificates/" in u for u in valid_urls)
        row["roles"] = sorted(roles)
        row["active_docs"] = active
        row["same_as_applicant_docs"] = same
        row["other_manufacturer_docs"] = other
        row["products"] = products[:8]
        row["status"] = "FOUND" if valid_urls else "NOT_FOUND_VERIFIED"

    except Exception as e:
        row["status"] = "ERROR"
        row["error"] = f"{type(e).__name__}: {e}"

    save_cache(source + "_V2", inn, row)
    return row


def find_s34_inn_input(driver):
    # Prefer inputs near the visible "ИНН Заявителя" label.
    candidates = driver.find_elements(
        By.XPATH,
        "//*[contains(translate(normalize-space(.), 'иннзаявителя', 'ИННЗАЯВИТЕЛЯ'), 'ИНН ЗАЯВИТЕЛЯ')]/following::input[1]"
    )
    if candidates:
        return candidates[0]
    # Fallback: visible text inputs, try the first empty one.
    for el in driver.find_elements(By.CSS_SELECTOR, "input"):
        try:
            if el.is_displayed() and (el.get_attribute("type") or "text") in ("text", "search", ""):
                return el
        except Exception:
            pass
    raise RuntimeError("S-34 applicant INN input not found")


def click_text_button(driver, texts: tuple[str, ...]) -> bool:
    for text in texts:
        els = driver.find_elements(By.XPATH, f"//button[contains(normalize-space(.), '{text}')]")
        for el in els:
            try:
                if el.is_displayed():
                    el.click()
                    return True
            except Exception:
                continue
    return False


def scrape_s34_mode(driver, inn: str, mode: str) -> dict[str, Any]:
    driver.get(S34_BASE + "/")
    time.sleep(2.5)

    if mode == "CERTIFICATE":
        click_text_button(driver, ("Сертификаты", "Certificates"))
    else:
        click_text_button(driver, ("Декларации", "Declarations"))
    time.sleep(1)

    inp = find_s34_inn_input(driver)
    inp.click()
    inp.clear()
    inp.send_keys(inn)

    if not click_text_button(driver, ("Найти", "Search")):
        inp.send_keys(Keys.ENTER)
    time.sleep(3)

    txt = body_text(driver)
    if "Записи не найдены" in txt or "Records not found" in txt:
        return {"rows": [], "error": ""}

    rows = []
    # Semantic tables first.
    for tr in driver.find_elements(By.CSS_SELECTOR, "table tr"):
        try:
            cells = [re.sub(r"\s+", " ", td.text).strip() for td in tr.find_elements(By.CSS_SELECTOR, "td")]
        except Exception:
            cells = []
        if len(cells) >= 4 and any(inn in c for c in cells[:3]):
            links = []
            for a in tr.find_elements(By.CSS_SELECTOR, "a[href]"):
                h = a.get_attribute("href") or ""
                if h and h not in links:
                    links.append(h)
            rows.append({"cells": cells, "links": links})

    # Grid fallback: S-34 sometimes renders rows as a JS grid rather than
    # a classic HTML table. Preserve cell boundaries whenever possible.
    if not rows:
        for a in driver.find_elements(By.CSS_SELECTOR, "a[href]"):
            t = re.sub(r"\s+", " ", a.text).strip()
            href = a.get_attribute("href") or ""
            if not t:
                continue
            if ("ЕАЭС" in t or "RU " in t or "РОСС" in t) and len(t) > 10:
                row_el = None
                for xp in (
                    "./ancestor::*[@role='row'][1]",
                    "./ancestor::*[contains(@class,'row')][1]",
                    "./ancestor::tr[1]",
                    "./parent::*",
                ):
                    try:
                        cand = a.find_element(By.XPATH, xp)
                        if cand is not None and cand.is_displayed():
                            row_el = cand
                            break
                    except Exception:
                        pass

                cells = []
                if row_el is not None:
                    for sel in ("[role='cell']", "td", "[class*='cell']", ":scope > *"):
                        try:
                            vals = [
                                re.sub(r"\s+", " ", x.text).strip()
                                for x in row_el.find_elements(By.CSS_SELECTOR, sel)
                                if x.is_displayed() and re.sub(r"\s+", " ", x.text).strip()
                            ]
                        except Exception:
                            vals = []
                        if len(vals) >= 4:
                            cells = vals
                            break
                    if not cells:
                        txt = re.sub(r"\s+", " ", row_el.text).strip()
                        if txt:
                            cells = [txt]

                rows.append({
                    "cells": cells,
                    "links": [href] if href else [],
                })

    # Deduplicate.
    seen, out = set(), []
    for r in rows:
        key = json.dumps(r, ensure_ascii=False, sort_keys=True)
        if key not in seen:
            seen.add(key)
            out.append(r)
    return {"rows": out, "error": ""}


def s34_check_manufacturer_relation(driver, url: str, inn: str) -> str:
    """Return SAME / OTHER / UNKNOWN from the visible Manufacturer section."""
    if not url:
        return "UNKNOWN"
    try:
        driver.get(url)
        time.sleep(1.2)
        clicked = click_text_button(driver, ("Изготовитель", "Manufacturer"))
        if clicked:
            time.sleep(0.7)
        txt = body_text(driver)
        low = txt.lower()
        if "изготовител" not in low and "manufacturer" not in low:
            return "UNKNOWN"
        return "SAME" if inn in txt else "OTHER"
    except Exception:
        return "UNKNOWN"


def scrape_s34(driver, inn: str) -> dict[str, Any]:
    source = "S34"
    cached = load_cache(source, inn)
    if cached:
        return cached

    row = {
        "inn": inn, "source": source, "status": "NOT_FOUND",
        "documents": 0, "certificates": 0, "declarations": 0,
        "roles": [], "active_docs": "", "same_as_applicant_docs": 0,
        "other_manufacturer_docs": 0, "products": [], "urls": [],
        "company_url": "", "error": "",
    }
    try:
        cert = scrape_s34_mode(driver, inn, "CERTIFICATE")
        pause()
        decl = scrape_s34_mode(driver, inn, "DECLARATION")
        cert_rows, decl_rows = cert["rows"], decl["rows"]

        row["certificates"] = len(cert_rows)
        row["declarations"] = len(decl_rows)
        row["documents"] = len(cert_rows) + len(decl_rows)
        if row["documents"]:
            row["status"] = "FOUND"
            row["roles"] = ["APPLICANT"]

        products, urls = [], []
        same, other = 0, 0

        def norm_company(x: str) -> str:
            x = (x or "").upper()
            x = re.sub(r"[«»\"'.,()]", " ", x)
            x = re.sub(r"\\b(ООО|АО|ПАО|ЗАО|ОАО|ИП)\\b", " ", x)
            return re.sub(r"\\s+", " ", x).strip()

        for r in cert_rows + decl_rows:
            cells = r.get("cells") or []
            # table layout: number, applicant, manufacturer, product...
            if len(cells) >= 4:
                applicant = cells[1]
                manufacturer = cells[2]
                a_norm, m_norm = norm_company(applicant), norm_company(manufacturer)
                if a_norm and m_norm:
                    if a_norm == m_norm:
                        same += 1
                    else:
                        other += 1
                p = cells[3]
                if p and p not in products:
                    products.append(p[:1000])
            elif cells:
                p = cells[0]
                if p and p not in products:
                    products.append(p[:1000])
            for u in r.get("links") or []:
                if u and u not in urls:
                    urls.append(u)

        role_checked = 0
        role_unknown = 0
        if row["documents"] and same == 0 and other == 0:
            for u in urls[:S34_ROLE_CHECK_LIMIT]:
                pause()
                rel = s34_check_manufacturer_relation(driver, u, inn)
                role_checked += 1
                if rel == "SAME":
                    same += 1
                elif rel == "OTHER":
                    other += 1
                else:
                    role_unknown += 1

        row["same_as_applicant_docs"] = same
        row["other_manufacturer_docs"] = other
        row["role_docs_checked"] = role_checked
        row["role_docs_unknown"] = role_unknown
        if same > 0:
            row["roles"] = ["APPLICANT", "MANUFACTURER"]
        row["products"] = products[:8]
        row["urls"] = urls[:30]
    except Exception as e:
        row["status"] = "ERROR"
        row["error"] = f"{type(e).__name__}: {e}"

    save_cache(source, inn, row)
    return row


def scrape_listorg(driver, inn: str) -> dict[str, Any]:
    source = "LIST_ORG"
    cached = load_cache(source, inn)
    if cached:
        return cached

    row = {
        "inn": inn, "source": source, "status": "NOT_FOUND",
        "documents": "", "certificates": "", "declarations": "",
        "roles": [], "active_docs": "", "same_as_applicant_docs": 0,
        "other_manufacturer_docs": 0, "products": [], "urls": [],
        "company_url": "", "error": "",
    }
    try:
        driver.get(f"{LISTORG_BASE}/?search=inn")
        time.sleep(2)
        if "/bot" in driver.current_url or "Проверка, что Вы не робот" in body_text(driver):
            row["status"] = "BLOCKED_CAPTCHA"
            save_cache(source, inn, row)
            return row

        inputs = [x for x in driver.find_elements(By.CSS_SELECTOR, "input") if x.is_displayed()]
        text_inputs = [
            x for x in inputs
            if (x.get_attribute("type") or "text").lower() in ("text", "search", "")
        ]
        if not text_inputs:
            raise RuntimeError("List-Org INN search input not found")

        inp = text_inputs[0]
        inp.clear()
        inp.send_keys(inn)
        inp.send_keys(Keys.ENTER)
        time.sleep(3)

        txt = body_text(driver)
        if "/bot" in driver.current_url or "Проверка, что Вы не робот" in txt:
            row["status"] = "BLOCKED_CAPTCHA"
            save_cache(source, inn, row)
            return row

        # Search results may require clicking a company link.
        if "/company/" not in driver.current_url:
            links = driver.find_elements(By.CSS_SELECTOR, "a[href*='/company/']")
            target = None
            for a in links:
                try:
                    if inn in a.text or inn in a.find_element(By.XPATH, "./ancestor::*[1]").text:
                        target = a
                        break
                except Exception:
                    continue
            if target is None and links:
                target = links[0]
            if target is not None:
                href = target.get_attribute("href")
                driver.get(href)
                time.sleep(2.5)
                txt = body_text(driver)

        row["company_url"] = driver.current_url if "/company/" in driver.current_url else ""

        if inn not in txt:
            save_cache(source, inn, row)
            return row

        marker = "Сертификаты соответствия:"
        i = txt.find(marker)
        section = ""
        if i >= 0:
            j = txt.find("Исполнительные производства", i + len(marker))
            section = txt[i + len(marker): j if j >= 0 else i + 3000].strip()

        if section:
            row["status"] = "FOUND"
            # Capture links whose text/href sit around certification section.
            cert_links = []
            for a in driver.find_elements(By.CSS_SELECTOR, "a[href]"):
                t = re.sub(r"\s+", " ", a.text).strip()
                h = a.get_attribute("href") or ""
                if any(x in t for x in ("ЕАЭС", "РОСС", "RU ")) or "cert" in h.lower():
                    if h not in cert_links:
                        cert_links.append(h)
            row["urls"] = cert_links[:20]
            row["certificates"] = len(cert_links) if cert_links else (1 if section else 0)
            row["documents"] = row["certificates"]
            row["products"] = [re.sub(r"\s+", " ", section)[:1500]]
        else:
            row["status"] = "NOT_FOUND"
            row["certificates"] = 0
            row["documents"] = 0

    except Exception as e:
        row["status"] = "ERROR"
        row["error"] = f"{type(e).__name__}: {e}"

    save_cache(source, inn, row)
    return row


def flatten(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "ИНН": row.get("inn", ""),
        "Источник": row.get("source", ""),
        "Статус": row.get("status", ""),
        "Документов": row.get("documents", ""),
        "Сертификатов": row.get("certificates", ""),
        "Деклараций": row.get("declarations", ""),
        "Роли": ",".join(row.get("roles") or []),
        "Действующих": row.get("active_docs", ""),
        "Заявитель=изготовитель": row.get("same_as_applicant_docs", ""),
        "Заявитель≠изготовитель": row.get("other_manufacturer_docs", ""),
        "Кандидатов до верификации": row.get("candidate_documents", ""),
        "S34 role docs checked": row.get("role_docs_checked", ""),
        "S34 role docs unknown": row.get("role_docs_unknown", ""),
        "Продукция": " || ".join(row.get("products") or [])[:6000],
        "URLs": " || ".join(row.get("urls") or [])[:6000],
        "Карточка компании": row.get("company_url", ""),
        "Ошибка": row.get("error", ""),
    }


def write_results(rows: list[dict[str, Any]]) -> None:
    flat = [flatten(x) for x in rows]
    fields = list(flat[0].keys()) if flat else []
    with (OUT / "pilot_results.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter=";")
        w.writeheader()
        w.writerows(flat)

    summary: dict[str, Any] = {}
    for source in ("SOOTVETSTVIE", "S34", "LIST_ORG"):
        rs = [x for x in rows if x.get("source") == source]
        summary[source] = {
            "rows": len(rs),
            "status_counts": dict(Counter(x.get("status") for x in rs)),
            "found": sum(x.get("status") == "FOUND" for x in rs),
            "documents_sum": sum(
                int(x.get("documents") or 0)
                for x in rs
                if str(x.get("documents") or "").isdigit()
            ),
            "companies_with_same_manufacturer": sum(
                int(x.get("same_as_applicant_docs") or 0) > 0 for x in rs
            ),
            "companies_with_other_manufacturer": sum(
                int(x.get("other_manufacturer_docs") or 0) > 0 for x in rs
            ),
        }

    (OUT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("\n=== SUMMARY ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nResults: {OUT / 'pilot_results.csv'}")


def main() -> int:
    inns = load_inns()
    print(f"Pilot INNs: {len(inns)}")
    print("Primary source: S34. SOOTVETSTVIE runs only when S34 is NOT_FOUND.")
    print("List-Org is disabled by default after 0/20 coverage; set RUN_LISTORG=1 to re-test.")
    print("CAPTCHA is never bypassed.")

    driver = start_driver()
    rows: list[dict[str, Any]] = []
    listorg_blocked = False

    try:
        for n, inn in enumerate(inns, 1):
            print(f"\n[{n}/{len(inns)}] INN {inn}", flush=True)

            s34 = scrape_s34(driver, inn)
            rows.append(s34)
            print(
                f"  S34: {s34['status']} docs={s34.get('documents')} "
                f"same={s34.get('same_as_applicant_docs', 0)} "
                f"other={s34.get('other_manufacturer_docs', 0)}",
                flush=True,
            )
            pause()

            if s34["status"] == "FOUND":
                soot = {
                    "inn": inn, "source": "SOOTVETSTVIE",
                    "status": "SKIPPED_S34_FOUND",
                    "documents": "", "certificates": "", "declarations": "",
                    "roles": [], "active_docs": "",
                    "same_as_applicant_docs": 0, "other_manufacturer_docs": 0,
                    "products": [], "urls": [], "company_url": "", "error": "",
                }
            else:
                soot = scrape_sootvetstvie(driver, inn)
                pause()
            rows.append(soot)
            print(f"  SOOTVETSTVIE: {soot['status']} docs={soot.get('documents')}", flush=True)

            if RUN_LISTORG:
                if listorg_blocked:
                    lo = {
                        "inn": inn, "source": "LIST_ORG",
                        "status": "SKIPPED_AFTER_CAPTCHA",
                        "documents": "", "certificates": "", "declarations": "",
                        "roles": [], "active_docs": "",
                        "same_as_applicant_docs": 0, "other_manufacturer_docs": 0,
                        "products": [], "urls": [], "company_url": "", "error": "",
                    }
                else:
                    lo = scrape_listorg(driver, inn)
                    if lo["status"] == "BLOCKED_CAPTCHA":
                        listorg_blocked = True
                rows.append(lo)
                print(f"  LIST_ORG: {lo['status']} docs={lo.get('documents')}", flush=True)

            write_results(rows)

        by_inn = defaultdict(list)
        for r in rows:
            by_inn[r["inn"]].append(r)
        covered = sum(any(x.get("status") == "FOUND" for x in rs) for rs in by_inn.values())
        combined = {
            "input_inns": len(inns),
            "covered_any_source": covered,
            "coverage_pct": round(100 * covered / len(inns), 1) if inns else 0,
        }
        (OUT / "combined_summary.json").write_text(
            json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print("\n=== COMBINED ===")
        print(json.dumps(combined, ensure_ascii=False, indent=2))
        return 0
    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
