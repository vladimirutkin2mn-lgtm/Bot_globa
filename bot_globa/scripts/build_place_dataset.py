"""Build the offline birth-place dataset shipped with the bot.

The oracle needs three things about a birth place — coordinates, an IANA timezone and a
name a Russian speaker recognises — and it needs them once per user. Paying a geocoding
API for that volume buys nothing, and sending every birth place to a third party is a
privacy disclosure the product would rather not make. GeoNames publishes all three under
CC BY 4.0, so the lookup can be a file.

This script turns the published dumps into the compact table
`app/providers/geocoding/data/places.tsv.gz`. It is run by hand when the data is refreshed,
never at runtime, and its output is committed so a build never depends on geonames.org.

Usage:
    python scripts/build_place_dataset.py <dump-directory>

The directory must hold the uncompressed dumps:
    cities5000.txt  alternateNamesV2.txt  countryInfo.txt
downloaded from https://download.geonames.org/export/dump/

Attribution required by CC BY 4.0 lives in `docs/place-dataset.md`.
"""

import gzip
import io
import sys
import unicodedata
from collections.abc import Iterator
from pathlib import Path

# GeoNames column positions, zero-based, from the published readme.
_CITY_GEONAME_ID = 0
_CITY_NAME = 1
_CITY_ASCII_NAME = 2
_CITY_LATITUDE = 4
_CITY_LONGITUDE = 5
_CITY_COUNTRY = 8
_CITY_POPULATION = 14
_CITY_TIMEZONE = 17

_ALT_GEONAME_ID = 1
_ALT_LANGUAGE = 2
_ALT_NAME = 3
_ALT_PREFERRED = 4
_ALT_HISTORIC = 7

_COUNTRY_ISO = 0
_COUNTRY_NAME = 4
_COUNTRY_GEONAME_ID = 16

OUTPUT = Path(__file__).resolve().parents[1] / "app/providers/geocoding/data/places.tsv.gz"


def normalize(value: str) -> str:
    """Fold a name to the form both the dataset and a typed query are matched in."""

    return unicodedata.normalize("NFKC", " ".join(value.split())).casefold().replace("ё", "е")


def _text(raw: gzip.GzipFile) -> io.TextIOWrapper:
    return io.TextIOWrapper(raw, encoding="utf-8", newline="\n")


def _rows(path: Path) -> Iterator[list[str]]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("#") or not line.strip():
                continue
            yield line.rstrip("\n").split("\t")


def _russian_names(path: Path, wanted: set[str]) -> dict[str, list[str]]:
    """Collect Russian names per geoname id, the preferred one first.

    The alternate-name dump is hundreds of megabytes, so it is streamed and filtered to
    the ids actually present in the city table.
    """

    names: dict[str, list[str]] = {}
    for row in _rows(path):
        # Trailing empty columns are omitted in the dump, so short rows are padded rather
        # than skipped: a name without a historic flag is simply a current name.
        padded = row + [""] * max(0, _ALT_HISTORIC + 1 - len(row))
        if padded[_ALT_LANGUAGE] != "ru" or padded[_ALT_HISTORIC] == "1":
            continue
        geoname_id = padded[_ALT_GEONAME_ID]
        if geoname_id not in wanted:
            continue
        name = padded[_ALT_NAME].strip()
        if not name:
            continue
        if padded[_ALT_PREFERRED] == "1":
            names.setdefault(geoname_id, []).insert(0, name)
        else:
            names.setdefault(geoname_id, []).append(name)
    return names


def build(dumps: Path) -> int:
    cities = [row for row in _rows(dumps / "cities5000.txt") if len(row) > _CITY_TIMEZONE]
    countries = {
        row[_COUNTRY_ISO]: (row[_COUNTRY_GEONAME_ID], row[_COUNTRY_NAME])
        for row in _rows(dumps / "countryInfo.txt")
        if len(row) > _COUNTRY_GEONAME_ID
    }

    wanted = {row[_CITY_GEONAME_ID] for row in cities}
    wanted.update(geoname_id for geoname_id, _ in countries.values())
    russian = _russian_names(dumps / "alternateNamesV2.txt", wanted)

    country_labels = {
        iso: (russian.get(geoname_id, [english])[0])
        for iso, (geoname_id, english) in countries.items()
    }

    written = 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    # `mtime=0` keeps the archive byte-identical across rebuilds of the same dump, so a
    # regenerated file only shows up in review when the data actually changed.
    with gzip.GzipFile(OUTPUT, "wb", mtime=0) as raw, _text(raw) as out:
        for row in sorted(cities, key=lambda item: int(item[_CITY_GEONAME_ID])):
            geoname_id = row[_CITY_GEONAME_ID]
            local = russian.get(geoname_id, [])
            display_city = local[0] if local else row[_CITY_NAME]
            country = country_labels.get(row[_CITY_COUNTRY], row[_CITY_COUNTRY])
            label = f"{display_city}, {country}"
            if len(label) > 200:  # `GeocodedPlace` refuses longer labels.
                continue
            aliases = sorted(
                {
                    normalize(name)
                    for name in (*local, row[_CITY_NAME], row[_CITY_ASCII_NAME])
                    if name.strip()
                }
            )
            population = row[_CITY_POPULATION] or "0"
            out.write(
                "\t".join(
                    (
                        label,
                        row[_CITY_LATITUDE],
                        row[_CITY_LONGITUDE],
                        row[_CITY_TIMEZONE],
                        population,
                        "|".join(aliases),
                    )
                )
                + "\n"
            )
            written += 1
    return written


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    dumps = Path(sys.argv[1])
    written = build(dumps)
    size = OUTPUT.stat().st_size
    print(f"wrote {written} places to {OUTPUT} ({size / 1_048_576:.1f} MiB)")


if __name__ == "__main__":
    main()
