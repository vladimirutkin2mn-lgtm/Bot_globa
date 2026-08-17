"""Import the canonical 1909 Roses & Lilies RWS deck from Wikimedia Commons.

This script is intentionally stdlib-only so the asset provenance can be reproduced in CI
without adding application dependencies. It downloads the original Commons JPEG for every
card, verifies public-domain metadata, records the source SHA-1/dimensions, and writes the
files under the stable `rws-78-v1` filenames used by the bot.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time
from urllib.error import HTTPError
import urllib.parse
import urllib.request

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
COMMONS_CATEGORY = (
    "https://commons.wikimedia.org/wiki/"
    "Category:Rider-Waite_tarot_deck_(Roses_%26_Lilies)"
)
USER_AGENT = "NumaTarotAssetImporter/1.0 (Bot_globa; public-domain asset import)"
MAX_CARD_BYTES = 1_000_000
DOWNLOAD_PAUSE_SECONDS = 1.5
MAX_HTTP_ATTEMPTS = 8

ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "app" / "bot" / "assets" / "tarot"
MANIFEST_PATH = ROOT / "docs" / "tarot-rws1909-sources.json"

MAJORS = (
    "Fool",
    "Magician",
    "High Priestess",
    "Empress",
    "Emperor",
    "Hierophant",
    "Lovers",
    "Chariot",
    "Strength",
    "Hermit",
    "Wheel of Fortune",
    "Justice",
    "Hanged Man",
    "Death",
    "Temperance",
    "Devil",
    "Tower",
    "Star",
    "Moon",
    "Sun",
    "Judgement",
    "World",
)
SUITS = ("Cups", "Pentacles", "Swords", "Wands")
COURT_RANKS = {11: "page", 12: "knight", 13: "queen", 14: "king"}


def source_to_local() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for number, name in enumerate(MAJORS):
        mapping[f"RWS1909 - {number:02d} {name}.jpeg"] = f"major_{number:02d}.jpg"
    for suit in SUITS:
        local_suit = suit.casefold()
        for number in range(1, 15):
            if number == 1:
                rank = "ace"
            elif number in COURT_RANKS:
                rank = COURT_RANKS[number]
            else:
                rank = f"{number:02d}"
            mapping[f"RWS1909 - {suit} {number:02d}.jpeg"] = f"{local_suit}_{rank}.jpg"
    assert len(mapping) == 78
    assert len(set(mapping.values())) == 78
    return mapping


def _open_with_backoff(request: urllib.request.Request, *, timeout: int):
    for attempt in range(1, MAX_HTTP_ATTEMPTS + 1):
        try:
            return urllib.request.urlopen(request, timeout=timeout)
        except HTTPError as exc:
            if exc.code != 429 or attempt == MAX_HTTP_ATTEMPTS:
                raise
            retry_after = exc.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                delay = max(5, int(retry_after))
            else:
                delay = min(60, 5 * attempt)
            print(f"Commons rate limit; retrying in {delay}s ({attempt}/{MAX_HTTP_ATTEMPTS})")
            time.sleep(delay)
    raise RuntimeError("unreachable Commons retry state")


def commons_request(params: dict[str, str]) -> dict[str, object]:
    url = f"{COMMONS_API}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with _open_with_backoff(request, timeout=30) as response:
        return json.load(response)


def fetch_metadata(filenames: list[str]) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for start in range(0, len(filenames), 40):
        batch = filenames[start : start + 40]
        payload = commons_request(
            {
                "action": "query",
                "format": "json",
                "formatversion": "2",
                "maxlag": "5",
                "prop": "imageinfo",
                "iiprop": "url|sha1|size|extmetadata",
                "titles": "|".join(f"File:{name}" for name in batch),
            }
        )
        query = payload.get("query")
        if not isinstance(query, dict):
            raise RuntimeError("Commons API returned no query object")
        pages = query.get("pages")
        if not isinstance(pages, list):
            raise RuntimeError("Commons API returned no pages")
        for page in pages:
            if not isinstance(page, dict) or page.get("missing") is True:
                raise RuntimeError(f"Commons file missing: {page!r}")
            title = page.get("title")
            imageinfo = page.get("imageinfo")
            if not isinstance(title, str) or not isinstance(imageinfo, list) or len(imageinfo) != 1:
                raise RuntimeError(f"Unexpected Commons image metadata: {page!r}")
            info = imageinfo[0]
            if not isinstance(info, dict):
                raise RuntimeError(f"Invalid image info for {title}")
            result[title.removeprefix("File:")] = info
    return result


def metadata_value(info: dict[str, object], key: str) -> str:
    ext = info.get("extmetadata")
    if not isinstance(ext, dict):
        return ""
    value = ext.get(key)
    if not isinstance(value, dict):
        return ""
    raw = value.get("value")
    return raw if isinstance(raw, str) else ""


def require_public_domain(filename: str, info: dict[str, object]) -> str:
    candidates = " ".join(
        (
            metadata_value(info, "LicenseShortName"),
            metadata_value(info, "License"),
            metadata_value(info, "UsageTerms"),
        )
    ).casefold()
    if "public domain" not in candidates and "pd" not in candidates:
        raise RuntimeError(f"{filename} is not marked public domain by Commons: {candidates!r}")
    return metadata_value(info, "LicenseShortName") or metadata_value(info, "UsageTerms")


def download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with _open_with_backoff(request, timeout=60) as response:
        payload = response.read(MAX_CARD_BYTES + 1)
    time.sleep(DOWNLOAD_PAUSE_SECONDS)
    return payload


def main() -> None:
    mapping = source_to_local()
    filenames = list(mapping)
    metadata = fetch_metadata(filenames)
    if set(metadata) != set(filenames):
        missing = sorted(set(filenames) - set(metadata))
        extra = sorted(set(metadata) - set(filenames))
        raise RuntimeError(f"Commons metadata mismatch: missing={missing}, extra={extra}")

    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    manifest_cards: list[dict[str, object]] = []

    for source_name, local_name in mapping.items():
        info = metadata[source_name]
        license_name = require_public_domain(source_name, info)
        source_url = info.get("url")
        if not isinstance(source_url, str) or not source_url.startswith("https://upload.wikimedia.org/"):
            raise RuntimeError(f"Unexpected source URL for {source_name}: {source_url!r}")

        payload = download(source_url)
        if len(payload) >= MAX_CARD_BYTES:
            raise RuntimeError(f"{source_name} exceeds the 1 MB Telegram asset budget")
        if not payload.startswith(b"\xff\xd8") or not payload.endswith(b"\xff\xd9"):
            raise RuntimeError(f"{source_name} is not a complete JPEG")

        expected_sha1 = info.get("sha1")
        actual_sha1 = hashlib.sha1(payload).hexdigest()  # noqa: S324 - source integrity, not security
        if not isinstance(expected_sha1, str) or actual_sha1 != expected_sha1:
            raise RuntimeError(
                f"SHA-1 mismatch for {source_name}: expected={expected_sha1!r}, actual={actual_sha1}"
            )

        (ASSET_DIR / local_name).write_bytes(payload)
        manifest_cards.append(
            {
                "local_file": local_name,
                "source_file": source_name,
                "commons_page": info.get("descriptionurl"),
                "original_url": source_url,
                "sha1": actual_sha1,
                "bytes": len(payload),
                "width": info.get("width"),
                "height": info.get("height"),
                "license": license_name,
            }
        )
        print(f"{local_name} <- {source_name} ({len(payload)} bytes)")

    installed = sorted(path.name for path in ASSET_DIR.glob("*.jpg"))
    expected = sorted(mapping.values())
    if installed != expected:
        raise RuntimeError("Tarot asset directory contains files outside the canonical 78-card set")

    manifest = {
        "deck": "Rider-Waite-Smith Tarot",
        "edition": "Roses & Lilies",
        "publication_year": 1909,
        "artist": "Pamela Colman Smith",
        "publisher": "Rider Company",
        "source_category": COMMONS_CATEGORY,
        "source_policy": "Original Wikimedia Commons files; Public Domain Mark metadata required",
        "card_count": 78,
        "cards": manifest_cards,
    }
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
