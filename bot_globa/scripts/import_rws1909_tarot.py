"""Install one coherent public-domain Rider-Waite-Smith 1909 art set.

The 56 Minor Arcana already used by Numa came from the 720px Rider-Waite set in
`mixvlad/TarotCards`. This importer intentionally uses that *same* set for all 78 cards so
Major and Minor Arcana cannot drift between different scans/recolourings. Runtime keeps
all files local and never depends on the source repository.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import urllib.request

SOURCE_REPOSITORY = "https://github.com/mixvlad/TarotCards"
SOURCE_DIRECTORY = "tarot/rider-waite/720px"
SOURCE_RAW_BASE = (
    "https://raw.githubusercontent.com/mixvlad/TarotCards/main/tarot/rider-waite/720px"
)
SOURCE_DOCUMENTATION = "https://github.com/mixvlad/TarotCards/blob/main/README.md"
MAX_CARD_BYTES = 1_000_000
USER_AGENT = "NumaTarotAssetImporter/2.0 (Bot_globa; public-domain RWS 1909 art)"

ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "app" / "bot" / "assets" / "tarot"
MANIFEST_PATH = ROOT / "docs" / "tarot-rws1909-sources.json"

MAJOR_SOURCE_NAMES = (
    "00_Fool.jpg",
    "01_Magician.jpg",
    "02_High_Priestess.jpg",
    "03_Empress.jpg",
    "04_Emperor.jpg",
    "05_Hierophant.jpg",
    "06_Lovers.jpg",
    "07_Chariot.jpg",
    "08_Strength.jpg",
    "09_Hermit.jpg",
    "10_Wheel_of_Fortune.jpg",
    "11_Justice.jpg",
    "12_Hanged_Man.jpg",
    "13_Death.jpg",
    "14_Temperance.jpg",
    "15_Devil.jpg",
    "16_Tower.jpg",
    "17_Star.jpg",
    "18_Moon.jpg",
    "19_Sun.jpg",
    "20_Judgement.jpg",
    "21_World.jpg",
)
SUIT_SOURCE_PREFIX = {
    "cups": "Cups",
    "pentacles": "Pents",
    "swords": "Swords",
    "wands": "Wands",
}
COURT_RANKS = {11: "page", 12: "knight", 13: "queen", 14: "king"}


def source_to_local() -> dict[str, str]:
    mapping: dict[str, str] = {
        source_name: f"major_{number:02d}.jpg"
        for number, source_name in enumerate(MAJOR_SOURCE_NAMES)
    }
    for local_suit, source_prefix in SUIT_SOURCE_PREFIX.items():
        for number in range(1, 15):
            if number == 1:
                rank = "ace"
            elif number in COURT_RANKS:
                rank = COURT_RANKS[number]
            else:
                rank = f"{number:02d}"
            mapping[f"{source_prefix}{number:02d}.jpg"] = f"{local_suit}_{rank}.jpg"
    assert len(mapping) == 78
    assert len(set(mapping.values())) == 78
    return mapping


def download(source_name: str) -> bytes:
    url = f"{SOURCE_RAW_BASE}/{source_name}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read(MAX_CARD_BYTES + 1)


def main() -> None:
    mapping = source_to_local()
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    manifest_cards: list[dict[str, object]] = []

    for source_name, local_name in mapping.items():
        payload = download(source_name)
        if len(payload) > MAX_CARD_BYTES:
            raise RuntimeError(f"{source_name} exceeds the 1 MB Telegram asset budget")
        if not payload.startswith(b"\xff\xd8") or not payload.endswith(b"\xff\xd9"):
            raise RuntimeError(f"{source_name} is not a complete JPEG")

        digest = hashlib.sha1(payload, usedforsecurity=False).hexdigest()
        (ASSET_DIR / local_name).write_bytes(payload)
        manifest_cards.append(
            {
                "local_file": local_name,
                "source_file": source_name,
                "source_url": f"{SOURCE_RAW_BASE}/{source_name}",
                "sha1": digest,
                "bytes": len(payload),
            }
        )
        print(f"{local_name} <- {source_name} ({len(payload)} bytes, sha1={digest})")

    installed = sorted(path.name for path in ASSET_DIR.glob("*.jpg"))
    expected = sorted(mapping.values())
    if installed != expected:
        raise RuntimeError("Tarot asset directory contains files outside the canonical 78-card set")

    manifest = {
        "deck": "Rider-Waite-Smith Tarot",
        "publication_year": 1909,
        "artist": "Pamela Colman Smith",
        "original_publisher": "Rider & Company",
        "copyright_status": "Public domain original artwork",
        "runtime_variant": "single coherent 720px JPEG set",
        "source_repository": SOURCE_REPOSITORY,
        "source_directory": SOURCE_DIRECTORY,
        "source_documentation": SOURCE_DOCUMENTATION,
        "card_count": 78,
        "cards": manifest_cards,
    }
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
