#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reusable Rosaccreditation (FSA) client for certificate/declaration enrichment.

Fail-soft by design: network / geo / auth blocks become SOURCE_UNAVAILABLE,
never NOT_FOUND.

Optional env vars:
  FSA_PROXY_URL       HTTP/SOCKS proxy URL (RU egress is useful for pub.fsa.gov.ru)
  FSA_TOKEN           bearer token if one is already available
  FSA_COOKIE          raw Cookie header if one is already available
  FSA_TIMEOUT         request timeout, default 25 sec
  FSA_PAGE_SIZE       list endpoint page size, default 100
  FSA_MAX_DETAILS     maximum detail cards per INN/doc type, default 50
  FSA_CERT_INN_COLUMNS comma-separated list-search columns to try
  FSA_DECL_INN_COLUMNS comma-separated list-search columns to try
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Iterable

import requests

BASE = "https://pub.fsa.gov.ru"
CERT_LIST = f"{BASE}/api/v1/rss/common/certificates/get"
CERT_DETAIL = f"{BASE}/api/v1/rss/common/certificates/{{id}}"
DECL_LIST = f"{BASE}/api/v1/rds/common/declarations/get"
DECL_DETAIL = f"{BASE}/api/v1/rds/common/declarations/{{id}}"

STATUS_FOUND = "FOUND"
STATUS_NOT_FOUND = "NOT_FOUND"
STATUS_UNAVAILABLE = "SOURCE_UNAVAILABLE"
STATUS_ERROR = "ERROR"

# FSA frontend field names have changed over time. We try several likely
# variants; detail-card verification below prevents fuzzy false positives.
DEFAULT_CERT_COLUMNS = (
    "applicantInn", "applicantINN", "manufacturerInn", "manufacturerINN",
)
DEFAULT_DECL_COLUMNS = (
    "applicantInn", "applicantINN", "manufacturerInn", "manufacturerINN",
)


class SourceUnavailable(RuntimeError):
    pass


def _digits(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _norm_inn(value: Any) -> str:
    d = _digits(value)
    return d if len(d) in (10, 12) else ""


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return " | ".join(x for x in (_text(v) for v in value) if x)
    if isinstance(value, dict):
        return " | ".join(x for x in (_text(v) for v in value.values()) if x)
    return str(value).strip()


def _parse_dt(value: Any) -> datetime | None:
    s = _text(value)
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    for parser in (
        lambda x: datetime.fromisoformat(x),
        lambda x: datetime.strptime(x[:10], "%Y-%m-%d"),
        lambda x: datetime.strptime(x[:10], "%d.%m.%Y"),
    ):
        try:
            return parser(s)
        except Exception:
            pass
    return None


def _is_active(detail: dict[str, Any], item: dict[str, Any]) -> bool:
    status_blob = " ".join(
        _text(x).lower()
        for x in (
            detail.get("status"), detail.get("statusName"), detail.get("idStatus"),
            item.get("status"), item.get("statusName"), item.get("idStatus"),
        )
        if x not in (None, "")
    )
    if any(x in status_blob for x in ("прекращ", "аннулир", "приостанов", "недейств")):
        return False
    end = (
        _parse_dt(detail.get("endDate"))
        or _parse_dt(detail.get("declEndDate"))
        or _parse_dt(detail.get("certificateEndDate"))
        or _parse_dt(item.get("endDate"))
        or _parse_dt(item.get("declEndDate"))
    )
    if end:
        return end.date() >= date.today()
    return any(x in status_blob for x in ("действ", "active", "valid"))


def _walk(obj: Any) -> Iterable[tuple[str, Any]]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k), v
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def _collect_inn_context(detail: dict[str, Any], target_inn: str) -> set[str]:
    """Infer target role from the object/path in which its INN appears."""
    roles: set[str] = set()

    def visit(obj: Any, path: tuple[str, ...] = ()) -> None:
        if isinstance(obj, dict):
            vals = [_norm_inn(v) for v in obj.values() if not isinstance(v, (dict, list))]
            if target_inn in vals:
                p = " ".join(x.lower() for x in path + tuple(str(k) for k in obj.keys()))
                if any(x in p for x in ("manufact", "изготов", "producer", "производ")):
                    roles.add("MANUFACTURER")
                if any(x in p for x in ("applicant", "заявител")):
                    roles.add("APPLICANT")
                if any(x in p for x in ("import", "импортер", "импорт")):
                    roles.add("IMPORTER")
            for k, v in obj.items():
                visit(v, path + (str(k),))
        elif isinstance(obj, list):
            for v in obj:
                visit(v, path)

    visit(detail)

    for key, role in (
        ("manufacturer", "MANUFACTURER"),
        ("manufacturers", "MANUFACTURER"),
        ("applicant", "APPLICANT"),
        ("importer", "IMPORTER"),
    ):
        val = detail.get(key)
        if val is not None:
            inns = {_norm_inn(v) for _, v in _walk(val)}
            if target_inn in inns:
                roles.add(role)
    return roles


def _product_text(detail: dict[str, Any], item: dict[str, Any]) -> str:
    candidates: list[str] = []
    for key in (
        "productFullName", "productIdentificationName", "productName",
        "fullName", "product", "products",
    ):
        if key in detail:
            candidates.append(_text(detail.get(key)))
        if key in item:
            candidates.append(_text(item.get(key)))
    prod = detail.get("product")
    if isinstance(prod, dict):
        for key in ("fullName", "name", "identificationName", "description"):
            candidates.append(_text(prod.get(key)))
    clean: list[str] = []
    seen: set[str] = set()
    for x in candidates:
        x = re.sub(r"\s+", " ", x).strip()
        if x and x not in seen:
            seen.add(x)
            clean.append(x)
    return " | ".join(clean)[:4000]


@dataclass
class DocumentEvidence:
    registry: str
    doc_id: str
    number: str = ""
    roles: set[str] = field(default_factory=set)
    active: bool = False
    reg_date: str = ""
    end_date: str = ""
    product: str = ""
    url: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "registry": self.registry,
            "id": self.doc_id,
            "number": self.number,
            "roles": sorted(self.roles),
            "active": self.active,
            "reg_date": self.reg_date,
            "end_date": self.end_date,
            "product": self.product,
            "url": self.url,
        }


class FSAClient:
    def __init__(self) -> None:
        self.timeout = float(os.getenv("FSA_TIMEOUT", "25"))
        self.page_size = int(os.getenv("FSA_PAGE_SIZE", "100"))
        self.max_details = int(os.getenv("FSA_MAX_DETAILS", "50"))
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Origin": BASE,
            "Referer": f"{BASE}/rss/certificate",
        })
        token = os.getenv("FSA_TOKEN", "").strip()
        self.session.headers["Authorization"] = f"Bearer {token}" if token else "Bearer null"
        cookie = os.getenv("FSA_COOKIE", "").strip()
        if cookie:
            self.session.headers["Cookie"] = cookie
        proxy = os.getenv("FSA_PROXY_URL", "").strip()
        if proxy:
            self.session.proxies.update({"http": proxy, "https": proxy})
        self._bootstrapped = False

    def bootstrap(self) -> None:
        """Try the same empty-login bootstrap used by the public frontend."""
        if self._bootstrapped:
            return
        self._bootstrapped = True
        try:
            r = self.session.post(
                f"{BASE}/login",
                json={"username": "", "password": ""},
                timeout=self.timeout,
            )
            auth = r.headers.get("Authorization", "").strip()
            if auth:
                self.session.headers["Authorization"] = auth
            else:
                try:
                    payload = r.json()
                except Exception:
                    payload = {}
                token = None
                if isinstance(payload, dict):
                    token = payload.get("token") or payload.get("access_token") or payload.get("accessToken")
                if token:
                    self.session.headers["Authorization"] = f"Bearer {token}"
        except requests.RequestException:
            # The list endpoint can still be reachable with Bearer null / cookies.
            pass

    def _post(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.bootstrap()
        try:
            r = self.session.post(url, json=payload, timeout=self.timeout)
        except (requests.Timeout, requests.ConnectionError) as e:
            raise SourceUnavailable(f"{type(e).__name__}: {e}") from e
        if r.status_code in (401, 403, 429, 451, 502, 503, 504):
            raise SourceUnavailable(f"HTTP {r.status_code}")
        r.raise_for_status()
        try:
            return r.json()
        except Exception as e:
            raise RuntimeError(f"Non-JSON response from {url}: {r.text[:200]!r}") from e

    def _get(self, url: str) -> dict[str, Any]:
        self.bootstrap()
        try:
            r = self.session.get(url, timeout=self.timeout)
        except (requests.Timeout, requests.ConnectionError) as e:
            raise SourceUnavailable(f"{type(e).__name__}: {e}") from e
        if r.status_code in (401, 403, 429, 451, 502, 503, 504):
            raise SourceUnavailable(f"HTTP {r.status_code}")
        r.raise_for_status()
        try:
            return r.json()
        except Exception as e:
            raise RuntimeError(f"Non-JSON response from {url}: {r.text[:200]!r}") from e

    @staticmethod
    def _columns(env_name: str, defaults: tuple[str, ...]) -> tuple[str, ...]:
        raw = os.getenv(env_name, "").strip()
        if not raw:
            return defaults
        return tuple(x.strip() for x in raw.split(",") if x.strip())

    def _search_list(self, list_url: str, inn: str, columns: tuple[str, ...]) -> tuple[list[dict[str, Any]], str]:
        """Try candidate frontend search columns and deduplicate returned IDs."""
        by_id: dict[str, dict[str, Any]] = {}
        successful_columns: list[str] = []
        last_bad_request = ""

        for column in columns:
            payload = {
                "size": self.page_size,
                "page": 0,
                "filter": {"columnsSearch": [{"column": column, "search": inn}]},
                "columnsSort": [{"column": "date", "sort": "DESC"}],
            }
            try:
                data = self._post(list_url, payload)
            except requests.HTTPError as e:
                status = getattr(e.response, "status_code", None)
                if status in (400, 404, 422):
                    last_bad_request = f"{column}:HTTP{status}"
                    continue
                raise

            if not isinstance(data, dict) or "items" not in data:
                continue
            successful_columns.append(column)
            items = data.get("items") or []
            if not isinstance(items, list):
                items = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                doc_id = str(item.get("id") or item.get("documentId") or "")
                if doc_id:
                    by_id[doc_id] = item

        if not successful_columns and last_bad_request:
            raise RuntimeError(f"No accepted FSA search column ({last_bad_request})")
        return list(by_id.values()), ",".join(successful_columns)

    def _detail_evidence(self, registry: str, item: dict[str, Any], inn: str) -> DocumentEvidence | None:
        doc_id = str(item.get("id") or item.get("documentId") or "")
        if not doc_id:
            return None
        if registry == "CERTIFICATE":
            detail_url = CERT_DETAIL.format(id=doc_id)
            public_url = f"{BASE}/rss/certificate/view/{doc_id}/baseInfo"
        else:
            detail_url = DECL_DETAIL.format(id=doc_id)
            public_url = f"{BASE}/rds/declaration/view/{doc_id}/common"

        detail = self._get(detail_url)
        all_inns = {_norm_inn(v) for _, v in _walk(detail)}
        if inn not in all_inns:
            return None

        roles = _collect_inn_context(detail, inn)
        number = _text(detail.get("number") or detail.get("declNumber") or detail.get("certificateNumber") or item.get("number"))
        reg_date = _text(detail.get("date") or detail.get("declDate") or detail.get("regDate") or item.get("date") or item.get("declDate"))
        end_date = _text(detail.get("endDate") or detail.get("declEndDate") or item.get("endDate") or item.get("declEndDate"))
        return DocumentEvidence(
            registry=registry,
            doc_id=doc_id,
            number=number,
            roles=roles,
            active=_is_active(detail, item),
            reg_date=reg_date,
            end_date=end_date,
            product=_product_text(detail, item),
            url=public_url,
        )

    def search_inn(self, inn: str) -> dict[str, Any]:
        inn = _norm_inn(inn)
        if not inn:
            raise ValueError("INN must contain 10 or 12 digits")

        result: dict[str, Any] = {
            "inn": inn,
            "status": STATUS_NOT_FOUND,
            "source_error": "",
            "certificate_search_columns": "",
            "declaration_search_columns": "",
            "documents": [],
        }
        try:
            cert_items, cert_cols = self._search_list(
                CERT_LIST, inn, self._columns("FSA_CERT_INN_COLUMNS", DEFAULT_CERT_COLUMNS)
            )
            decl_items, decl_cols = self._search_list(
                DECL_LIST, inn, self._columns("FSA_DECL_INN_COLUMNS", DEFAULT_DECL_COLUMNS)
            )
            result["certificate_search_columns"] = cert_cols
            result["declaration_search_columns"] = decl_cols

            docs: list[DocumentEvidence] = []
            for registry, items in (("CERTIFICATE", cert_items), ("DECLARATION", decl_items)):
                for item in items[: self.max_details]:
                    ev = self._detail_evidence(registry, item, inn)
                    if ev:
                        docs.append(ev)
                    time.sleep(0.05)

            result["documents"] = [d.as_dict() for d in docs]
            result["status"] = STATUS_FOUND if docs else STATUS_NOT_FOUND
            return result
        except SourceUnavailable as e:
            result["status"] = STATUS_UNAVAILABLE
            result["source_error"] = str(e)
            return result
        except Exception as e:
            result["status"] = STATUS_ERROR
            result["source_error"] = f"{type(e).__name__}: {e}"
            return result


def aggregate_search(result: dict[str, Any]) -> dict[str, Any]:
    docs = result.get("documents") or []
    certs = [d for d in docs if d.get("registry") == "CERTIFICATE"]
    decls = [d for d in docs if d.get("registry") == "DECLARATION"]
    active = [d for d in docs if d.get("active")]
    manufacturer = [d for d in docs if "MANUFACTURER" in (d.get("roles") or [])]
    applicant = [d for d in docs if "APPLICANT" in (d.get("roles") or [])]
    importer = [d for d in docs if "IMPORTER" in (d.get("roles") or [])]

    products: list[str] = []
    urls: list[str] = []
    latest_dt: datetime | None = None
    for d in docs:
        product = str(d.get("product") or "").strip()
        if product and product not in products:
            products.append(product)
        url = str(d.get("url") or "").strip()
        if url:
            urls.append(url)
        dt = _parse_dt(d.get("reg_date"))
        if dt and (latest_dt is None or dt > latest_dt):
            latest_dt = dt

    role_set = sorted({role for d in docs for role in (d.get("roles") or [])})
    return {
        "ИНН": result.get("inn", ""),
        "ФСА статус": result.get("status", ""),
        "ФСА ошибка": result.get("source_error", ""),
        "ФСА сертификаты": len(certs),
        "ФСА декларации": len(decls),
        "ФСА документы всего": len(docs),
        "ФСА действующие": len(active),
        "ФСА manufacturer": len(manufacturer),
        "ФСА applicant": len(applicant),
        "ФСА importer": len(importer),
        "ФСА роли": ",".join(role_set),
        "ФСА последняя регистрация": latest_dt.isoformat() if latest_dt else "",
        "ФСА продукция": " || ".join(products)[:12000],
        "ФСА evidence URLs": " || ".join(urls)[:12000],
        "ФСА cert search columns": result.get("certificate_search_columns", ""),
        "ФСА decl search columns": result.get("declaration_search_columns", ""),
    }
