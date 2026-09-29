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

MAX_INNS = int(os.getenv("PILOT_INNS", "20"))
MAX_DETAILS = int(os.getenv("PILOT_MAX_DETAILS", "8"))
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


def scrape_sootvetstvie(driver, inn: str) -> dict[str, Any]:
    source = "SOOTVETSTVIE"
    cached = load_cache(source, inn)
    if cached:
        return cached

    row = {
        "inn": inn, "source": source, "status": "NOT_FOUND",
        "documents": 0, "certificates": 0, "declarations": 0,
        "roles": [], "active_docs": 0, "products": [], "urls": [],
        "company_url": "", "error": "",
    }
    try:
        driver.get(f"{SOOTV_BASE}/documents?q={inn}")
        time.sleep(3)
        anchors = driver.find_elements(By.CSS_SELECTOR, "a[href]")
        urls = []
        for a in anchors:
            href = a.get_attribute("href") or ""
            if "/declarations/" in href or "/certificates/" in href:
                href = href.split("#", 1)[0]
                if href not in urls:
                    urls.append(href)

        row["urls"] = urls
        row["documents"] = len(urls)
        row["declarations"] = sum("/declarations/" in u for u in urls)
        row["certificates"] = sum("/certificates/" in u for u in urls)
        if urls:
            row["status"] = "FOUND"

        roles, products = set(), []
        active = 0
        for url in urls[:MAX_DETAILS]:
            pause()
            driver.get(url)
            time.sleep(1.5)
            txt = body_text(driver)
            roles |= exact_inn_role_from_text(txt, inn)
            if "Действует" in txt or "действует" in txt:
                active += 1
            p = product_excerpt(txt)
            if p and p not in products:
                products.append(p)

        row["roles"] = sorted(roles)
        row["active_docs"] = active
        row["products"] = products[:5]
    except Exception as e:
        row["status"] = "ERROR"
        row["error"] = f"{type(e).__name__}: {e}"

    save_cache(source, inn, row)
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

    # Grid fallback: look for anchors that resemble certificate/declaration numbers.
    if not rows:
        for a in driver.find_elements(By.CSS_SELECTOR, "a[href]"):
            t = re.sub(r"\s+", " ", a.text).strip()
            if not t:
                continue
            if ("ЕАЭС" in t or "RU " in t or "РОСС" in t) and len(t) > 10:
                parent_text = ""
                try:
                    parent_text = a.find_element(By.XPATH, "./ancestor::*[self::tr or @role='row'][1]").text
                except Exception:
                    try:
                        parent_text = a.find_element(By.XPATH, "./parent::*").text
                    except Exception:
                        pass
                rows.append({
                    "cells": [re.sub(r"\s+", " ", parent_text).strip()],
                    "links": [a.get_attribute("href") or ""],
                })

    # Deduplicate.
    seen, out = set(), []
    for r in rows:
        key = json.dumps(r, ensure_ascii=False, sort_keys=True)
        if key not in seen:
            seen.add(key)
            out.append(r)
    return {"rows": out, "error": ""}


def scrape_s34(driver, inn: str) -> dict[str, Any]:
    source = "S34"
    cached = load_cache(source, inn)
    if cached:
        return cached

    row = {
        "inn": inn, "source": source, "status": "NOT_FOUND",
        "documents": 0, "certificates": 0, "declarations": 0,
        "roles": [], "active_docs": "", "products": [], "urls": [],
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
        for r in cert_rows + decl_rows:
            cells = r.get("cells") or []
            # table layout: number, applicant, manufacturer, product...
            if len(cells) >= 4:
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
        row["products"] = products[:5]
        row["urls"] = urls[:20]
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
        "roles": [], "active_docs": "", "products": [], "urls": [],
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
    print("Sources: SOOTVETSTVIE, S34, LIST_ORG")
    print("CAPTCHA is never bypassed; List-Org will be marked BLOCKED_CAPTCHA.")

    driver = start_driver()
    rows: list[dict[str, Any]] = []
    listorg_blocked = False

    try:
        for n, inn in enumerate(inns, 1):
            print(f"\n[{n}/{len(inns)}] INN {inn}", flush=True)

            for fn, source in (
                (scrape_sootvetstvie, "SOOTVETSTVIE"),
                (scrape_s34, "S34"),
            ):
                r = fn(driver, inn)
                rows.append(r)
                print(f"  {source}: {r['status']} docs={r.get('documents')}", flush=True)
                pause()

            if listorg_blocked:
                r = {
                    "inn": inn, "source": "LIST_ORG", "status": "SKIPPED_AFTER_CAPTCHA",
                    "documents": "", "certificates": "", "declarations": "",
                    "roles": [], "active_docs": "", "products": [], "urls": [],
                    "company_url": "", "error": "",
                }
            else:
                r = scrape_listorg(driver, inn)
                if r["status"] == "BLOCKED_CAPTCHA":
                    listorg_blocked = True
            rows.append(r)
            print(f"  LIST_ORG: {r['status']} docs={r.get('documents')}", flush=True)
            pause()

            write_results(rows)

        return 0
    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
