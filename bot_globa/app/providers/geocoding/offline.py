"""Birth-place lookup that never leaves the process.

A birth place is asked for once per user, so a paid geocoding API buys capacity nobody
needs, and every lookup would hand a third party the one fact this product promises to
keep encrypted. The published GeoNames table carries coordinates, an IANA timezone and a
Russian name for every city above five thousand people, which is all the astrologer asks
for — so the lookup is a file, not a request.

Consequences worth knowing: nothing here can time out, be rate limited, or fail because a
vendor is down, and the consent screen no longer has to disclose an outbound call. In
exchange the data is a snapshot, refreshed by `scripts/build_place_dataset.py`, and it
matches names rather than guessing at typos.

Attribution and refresh instructions: `docs/place-dataset.md`.
"""

import gzip
import unicodedata
from bisect import bisect_left
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from app.providers.geocoding.base import GeocodedPlace

DATASET = Path(__file__).parent / "data" / "places.tsv.gz"


@dataclass(frozen=True, slots=True)
class _Place:
    place: GeocodedPlace
    population: int


def normalize(value: str) -> str:
    """Fold a query the same way the dataset folded its names when it was built."""

    return unicodedata.normalize("NFKC", " ".join(value.split())).casefold().replace("ё", "е")


class OfflineGeocodingClient:
    """Resolve a place against the bundled table, best and biggest match first."""

    def __init__(self, dataset: Path = DATASET) -> None:
        self._dataset = dataset

    async def search(self, query: str, *, limit: int) -> tuple[GeocodedPlace, ...]:
        needle = normalize(query)
        if not needle or limit < 1:
            return ()
        index = _load(self._dataset)
        return tuple(place.place for place in index.find(needle)[:limit])


@dataclass(frozen=True, slots=True)
class _Index:
    """Aliases sorted once so a prefix search is a binary search, not a table scan."""

    aliases: tuple[str, ...]
    owners: tuple[tuple[_Place, ...], ...]

    def find(self, needle: str) -> list[_Place]:
        start = bisect_left(self.aliases, needle)
        exact: list[_Place] = []
        prefix: list[_Place] = []
        for position in range(start, len(self.aliases)):
            alias = self.aliases[position]
            if not alias.startswith(needle):
                break
            bucket = exact if alias == needle else prefix
            bucket.extend(self.owners[position])
        # A bigger city is the likelier birth place when several share a name, and an
        # exact name always outranks something that merely starts the same way.
        exact.sort(key=_by_population)
        prefix.sort(key=_by_population)
        seen: set[int] = set()
        found: list[_Place] = []
        for candidate in (*exact, *prefix):
            if id(candidate) in seen:
                continue
            seen.add(id(candidate))
            found.append(candidate)
        return found


def _by_population(place: _Place) -> tuple[int, str]:
    return (-place.population, place.place.label)


@cache
def _load(dataset: Path) -> _Index:
    """Read the table once per process; it is immutable and a few megabytes in memory."""

    owners: dict[str, list[_Place]] = {}
    with gzip.open(dataset, "rt", encoding="utf-8") as rows:
        for row in rows:
            label, latitude, longitude, timezone, population, aliases = row.rstrip("\n").split("\t")
            place = _Place(
                place=GeocodedPlace(
                    label=label,
                    latitude=float(latitude),
                    longitude=float(longitude),
                    timezone=timezone,
                ),
                population=int(population),
            )
            for alias in aliases.split("|"):
                if alias:
                    owners.setdefault(alias, []).append(place)
    ordered = sorted(owners)
    return _Index(
        aliases=tuple(ordered),
        owners=tuple(tuple(owners[alias]) for alias in ordered),
    )
