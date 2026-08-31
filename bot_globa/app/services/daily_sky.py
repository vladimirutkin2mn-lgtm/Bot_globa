"""Deterministic sky snapshot and solar-sign daily horoscope methodology.

Astronomy Engine provides astronomical longitudes. The sign/house interpretation below is
an astrology product convention, not a scientifically validated prediction method. A mass
daily digest deliberately uses only the reader's Sun sign as a twelve-sector approximation;
personal natal transits belong to the astrologer flow instead.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import date, timedelta
from types import MappingProxyType
from typing import Any

import astronomy

from app.domain.natal_chart import NatalAspectKind, NatalBody, ZodiacSign

DAILY_SKY_VERSION = "daily-sky-v1"
DAILY_SOLAR_METHOD_VERSION = "solar-sign-daily-v3"

_TRANSIT_BODIES: tuple[tuple[NatalBody, Any], ...] = (
    (NatalBody.SUN, astronomy.Body.Sun),
    (NatalBody.MOON, astronomy.Body.Moon),
    (NatalBody.MERCURY, astronomy.Body.Mercury),
    (NatalBody.VENUS, astronomy.Body.Venus),
    (NatalBody.MARS, astronomy.Body.Mars),
    (NatalBody.JUPITER, astronomy.Body.Jupiter),
    (NatalBody.SATURN, astronomy.Body.Saturn),
    (NatalBody.URANUS, astronomy.Body.Uranus),
    (NatalBody.NEPTUNE, astronomy.Body.Neptune),
    (NatalBody.PLUTO, astronomy.Body.Pluto),
)
_ASPECTS: tuple[tuple[NatalAspectKind, int, int], ...] = (
    (NatalAspectKind.CONJUNCTION, 0_000, 8_000),
    (NatalAspectKind.SEXTILE, 60_000, 4_000),
    (NatalAspectKind.SQUARE, 90_000, 6_000),
    (NatalAspectKind.TRINE, 120_000, 6_000),
    (NatalAspectKind.OPPOSITION, 180_000, 8_000),
)
_SIGNS = tuple(ZodiacSign)

SIGN_LABELS = MappingProxyType(
    {
        ZodiacSign.ARIES: ("♈", "Овен"),
        ZodiacSign.TAURUS: ("♉", "Телец"),
        ZodiacSign.GEMINI: ("♊", "Близнецы"),
        ZodiacSign.CANCER: ("♋", "Рак"),
        ZodiacSign.LEO: ("♌", "Лев"),
        ZodiacSign.VIRGO: ("♍", "Дева"),
        ZodiacSign.LIBRA: ("♎", "Весы"),
        ZodiacSign.SCORPIO: ("♏", "Скорпион"),
        ZodiacSign.SAGITTARIUS: ("♐", "Стрелец"),
        ZodiacSign.CAPRICORN: ("♑", "Козерог"),
        ZodiacSign.AQUARIUS: ("♒", "Водолей"),
        ZodiacSign.PISCES: ("♓", "Рыбы"),
    }
)

_HOUSE_FOCUS = MappingProxyType(
    {
        1: "инициатива",
        2: "деньги",
        3: "общение",
        4: "дом и семья",
        5: "любовь и творчество",
        6: "работа и режим",
        7: "отношения",
        8: "общие деньги",
        9: "обучение и поездки",
        10: "карьера",
        11: "друзья и планы",
        12: "отдых и завершение",
    }
)

# Lower values mean that a transit is more likely to become the one short story told for
# a sign. Angular and relationship houses are intentionally prominent, while quieter
# sectors can still win through a closer aspect or a faster planet.
_HOUSE_PRIORITY = MappingProxyType(
    {
        1: 0,
        7: 0,
        10: 0,
        4: 1,
        5: 1,
        2: 1,
        8: 1,
        11: 2,
        3: 2,
        6: 2,
        9: 2,
        12: 3,
    }
)

_ASPECT_THEME_VARIANTS = MappingProxyType(
    {
        NatalAspectKind.CONJUNCTION: (
            "главное сегодня собирается в одной точке",
            "лучше выбрать один главный приоритет",
            "силы стоит собрать вокруг самого важного",
            "одна тема дня потребует полного внимания",
        ),
        NatalAspectKind.SEXTILE: (
            "небольшой шаг может открыть больше возможностей",
            "полезный шанс стоит поддержать одним точным действием",
            "важно заметить возможность, пока она рядом",
            "маленькая инициатива может дать заметный результат",
        ),
        NatalAspectKind.SQUARE: (
            "напряжение покажет, что пора изменить",
            "лучше убрать одно главное препятствие, чем бороться со всем сразу",
            "трение дня полезнее превратить в конкретное действие",
            "не стоит форсировать то, что просит точной настройки",
        ),
        NatalAspectKind.TRINE: (
            "проще поддержать то, что уже набирает ход",
            "сегодня стоит опереться на то, что идёт естественно",
            "благоприятный импульс лучше не тормозить лишними сомнениями",
            "сильной стороне дня стоит дать сработать без лишнего давления",
        ),
        NatalAspectKind.OPPOSITION: (
            "важно увидеть обе стороны перед выбором",
            "свои желания стоит сверить с ожиданиями других",
            "баланс между крайностями окажется важнее быстрой победы",
            "рабочий компромисс сегодня сильнее борьбы за своё",
        ),
    }
)
_NEUTRAL_THEME_VARIANTS = (
    "сегодня полезнее держать свой темп и сверять впечатления с фактами",
    "спокойный ритм даст больше, чем попытка ускорить события",
    "лучше оставить запас времени и действовать без суеты",
    "последовательность сегодня полезнее резких поворотов",
)

_SUPPORTIVE_FORECAST = MappingProxyType(
    {
        NatalBody.MOON: "чувства подскажут верный темп",
        NatalBody.MERCURY: "разговор может многое прояснить",
        NatalBody.VENUS: "поддержка может прийти вовремя",
        NatalBody.MARS: "появится энергия для рывка",
        NatalBody.JUPITER: "может открыться новая возможность",
        NatalBody.SATURN: "сложное начнёт складываться",
        NatalBody.URANUS: "неожиданный поворот может помочь",
        NatalBody.NEPTUNE: "интуиция подскажет хороший ход",
        NatalBody.PLUTO: "станет заметен скрытый рычаг",
        NatalBody.SUN: "будет легче проявить себя",
    }
)

_CHALLENGING_FORECAST = MappingProxyType(
    {
        NatalBody.MOON: "эмоции могут сбить с курса",
        NatalBody.MERCURY: "важное легко понять неправильно",
        NatalBody.VENUS: "ожидания могут не совпасть",
        NatalBody.MARS: "спешка может создать лишнее трение",
        NatalBody.JUPITER: "легко взять на себя лишнее",
        NatalBody.SATURN: "обязательства потребуют внимания",
        NatalBody.URANUS: "планы могут резко поменяться",
        NatalBody.NEPTUNE: "впечатление легко принять за факт",
        NatalBody.PLUTO: "борьба за контроль отнимет силы",
        NatalBody.SUN: "желание доказать своё создаст напряжение",
    }
)

_FOCUSED_FORECAST = MappingProxyType(
    {
        NatalBody.MOON: "одна эмоция выйдет на первый план",
        NatalBody.MERCURY: "один разговор станет особенно важным",
        NatalBody.VENUS: "тема симпатии или денег станет ярче",
        NatalBody.MARS: "энергия потребует конкретной цели",
        NatalBody.JUPITER: "масштаб возможности станет яснее",
        NatalBody.SATURN: "главное обязательство потребует решения",
        NatalBody.URANUS: "захочется сменить привычный сценарий",
        NatalBody.NEPTUNE: "мечта или сомнение займут больше внимания",
        NatalBody.PLUTO: "скрытая тема может стать очевидной",
        NatalBody.SUN: "главный приоритет станет яснее",
    }
)

_NEUTRAL_FORECAST = MappingProxyType(
    {
        NatalBody.MOON: "лучше прислушаться к своему состоянию",
        NatalBody.MERCURY: "важная деталь проявится в разговоре",
        NatalBody.VENUS: "взаимность станет лучшим ориентиром",
        NatalBody.MARS: "один ясный шаг даст больше, чем суета",
        NatalBody.JUPITER: "рост потребует понятной опоры",
        NatalBody.SATURN: "сначала стоит закрыть обязательное",
        NatalBody.URANUS: "новый вариант окажется полезным",
        NatalBody.NEPTUNE: "догадку лучше сверить с фактами",
        NatalBody.PLUTO: "ищите точку реального влияния",
        NatalBody.SUN: "выберите один главный приоритет",
    }
)

_BODY_PRIORITY = MappingProxyType(
    {
        NatalBody.MOON: 0,
        NatalBody.MERCURY: 1,
        NatalBody.VENUS: 2,
        NatalBody.MARS: 3,
        NatalBody.SUN: 4,
        NatalBody.JUPITER: 5,
        NatalBody.SATURN: 6,
        NatalBody.URANUS: 7,
        NatalBody.NEPTUNE: 8,
        NatalBody.PLUTO: 9,
    }
)


@dataclass(frozen=True, slots=True)
class DailySkyPlanet:
    body: NatalBody
    longitude_millidegrees: int
    sign: ZodiacSign
    retrograde: bool

    def payload(self) -> dict[str, object]:
        return {
            "body": self.body.value,
            "longitude_millidegrees": self.longitude_millidegrees,
            "sign": self.sign.value,
            "retrograde": self.retrograde,
        }


@dataclass(frozen=True, slots=True)
class DailySkyAspect:
    first_body: NatalBody
    second_body: NatalBody
    kind: NatalAspectKind
    orb_millidegrees: int

    def payload(self) -> dict[str, object]:
        return {
            "first_body": self.first_body.value,
            "second_body": self.second_body.value,
            "kind": self.kind.value,
            "orb_millidegrees": self.orb_millidegrees,
        }


@dataclass(frozen=True, slots=True)
class DailySkySnapshot:
    forecast_date: date
    planets: tuple[DailySkyPlanet, ...]
    aspects: tuple[DailySkyAspect, ...]
    version: str = DAILY_SKY_VERSION

    def __post_init__(self) -> None:
        if self.version != DAILY_SKY_VERSION:
            raise ValueError("unsupported daily sky version")
        if len(self.planets) != len(NatalBody):
            raise ValueError("daily sky must contain every supported body")
        if len({planet.body for planet in self.planets}) != len(self.planets):
            raise ValueError("daily sky contains duplicate bodies")

    def payload(self) -> dict[str, object]:
        return {
            "version": self.version,
            "forecast_date": self.forecast_date.isoformat(),
            "planets": [planet.payload() for planet in self.planets],
            "aspects": [aspect.payload() for aspect in self.aspects],
        }

    def digest(self) -> str:
        encoded = json.dumps(
            self.payload(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class DailySignForecast:
    sign: ZodiacSign
    text: str

    def payload(self) -> dict[str, str]:
        return {"sign": self.sign.value, "text": self.text}


@dataclass(frozen=True, slots=True)
class DailyHoroscopeSnapshot:
    forecast_date: date
    sky_digest: str
    theme: str
    signs: tuple[DailySignForecast, ...]
    sky_version: str = DAILY_SKY_VERSION
    methodology_version: str = DAILY_SOLAR_METHOD_VERSION

    def __post_init__(self) -> None:
        if len(self.signs) != len(ZodiacSign):
            raise ValueError("daily horoscope must contain all twelve signs")
        if tuple(item.sign for item in self.signs) != tuple(ZodiacSign):
            raise ValueError("daily horoscope signs must use canonical zodiac order")

    def payload(self) -> dict[str, object]:
        return {
            "forecast_date": self.forecast_date.isoformat(),
            "sky_digest": self.sky_digest,
            "theme": self.theme,
            "signs": [item.payload() for item in self.signs],
            "sky_version": self.sky_version,
            "methodology_version": self.methodology_version,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> "DailyHoroscopeSnapshot":
        raw_signs = payload.get("signs")
        if not isinstance(raw_signs, list):
            raise ValueError("invalid daily horoscope signs")
        signs: list[DailySignForecast] = []
        for item in raw_signs:
            if not isinstance(item, dict):
                raise ValueError("invalid daily horoscope sign item")
            sign = item.get("sign")
            text = item.get("text")
            if not isinstance(sign, str) or not isinstance(text, str):
                raise ValueError("invalid daily horoscope sign fields")
            signs.append(DailySignForecast(ZodiacSign(sign), text))
        forecast_date = _required_text(payload, "forecast_date")
        sky_digest = _required_text(payload, "sky_digest")
        theme = _required_text(payload, "theme")
        sky_version = _required_text(payload, "sky_version")
        methodology_version = _required_text(payload, "methodology_version")
        return cls(
            forecast_date=date.fromisoformat(forecast_date),
            sky_digest=sky_digest,
            theme=theme,
            signs=tuple(signs),
            sky_version=sky_version,
            methodology_version=methodology_version,
        )


def calculate_daily_sky(forecast_date: date) -> DailySkySnapshot:
    """Calculate a geocentric noon-UTC sky snapshot for one civil date."""

    astro_time = astronomy.Time.Make(
        forecast_date.year,
        forecast_date.month,
        forecast_date.day,
        12,
        0,
        0.0,
    )
    planets = tuple(
        _planet_position(body, engine_body, astro_time) for body, engine_body in _TRANSIT_BODIES
    )
    return DailySkySnapshot(forecast_date, planets, _planet_aspects(planets))


def build_daily_horoscope(forecast_date: date) -> DailyHoroscopeSnapshot:
    """Turn the current sky into a varied but still evidence-bound daily digest."""

    sky = calculate_daily_sky(forecast_date)
    previous_sky = calculate_daily_sky(forecast_date - timedelta(days=1))
    driver = _driver_aspect(sky)
    previous_driver = _driver_aspect(previous_sky)
    theme = _theme_for_date(
        forecast_date,
        driver,
        avoid=_theme_for_date(previous_sky.forecast_date, previous_driver),
    )
    signs = tuple(
        _forecast_for_sign(sky, sign, previous_sky=previous_sky) for sign in ZodiacSign
    )
    return DailyHoroscopeSnapshot(
        forecast_date=forecast_date,
        sky_digest=sky.digest(),
        theme=theme,
        signs=signs,
    )


def _theme_for_date(
    forecast_date: date,
    driver: DailySkyAspect | None,
    *,
    avoid: str | None = None,
) -> str:
    options = (
        _ASPECT_THEME_VARIANTS[driver.kind] if driver is not None else _NEUTRAL_THEME_VARIANTS
    )
    body_offset = 0
    if driver is not None:
        body_offset = _BODY_PRIORITY[driver.first_body] * 3 + _BODY_PRIORITY[driver.second_body]
    index = (forecast_date.toordinal() + body_offset) % len(options)
    if avoid is not None and options[index] == avoid and len(options) > 1:
        index = (index + 1) % len(options)
    return options[index]


def _forecast_for_sign(
    sky: DailySkySnapshot,
    sign: ZodiacSign,
    *,
    previous_sky: DailySkySnapshot | None = None,
) -> DailySignForecast:
    planet, aspect = _sign_driver(sky, sign, previous_sky=previous_sky)
    house = _solar_house(sign, planet.sign)
    return DailySignForecast(
        sign,
        f"{_HOUSE_FOCUS[house]}: {_forecast_phrase(planet.body, aspect)}",
    )


def _sign_driver(
    sky: DailySkySnapshot,
    sign: ZodiacSign,
    *,
    previous_sky: DailySkySnapshot | None = None,
) -> tuple[DailySkyPlanet, DailySkyAspect | None]:
    """Rotate among credible current-day stories instead of pinning a sign to a slow transit."""

    ranked = _rank_sign_drivers(sky, sign)
    candidates = _credible_distinct_house_candidates(ranked, sign)
    chosen = _rotating_candidate(sky.forecast_date, sign, candidates)
    if previous_sky is None or len(candidates) < 2:
        return chosen[1], chosen[2]

    previous_ranked = _rank_sign_drivers(previous_sky, sign)
    previous_candidates = _credible_distinct_house_candidates(previous_ranked, sign)
    previous_chosen = _rotating_candidate(previous_sky.forecast_date, sign, previous_candidates)
    previous_house = _solar_house(sign, previous_chosen[1].sign)
    chosen_house = _solar_house(sign, chosen[1].sign)
    if chosen_house != previous_house:
        return chosen[1], chosen[2]

    # A changing candidate set can occasionally make the daily rotation land on the same
    # house twice. If another credible current-day story exists, prefer the best different
    # house rather than repeating yesterday's topic.
    for candidate in candidates:
        if _solar_house(sign, candidate[1].sign) != previous_house:
            return candidate[1], candidate[2]
    return chosen[1], chosen[2]


def _rank_sign_drivers(
    sky: DailySkySnapshot,
    sign: ZodiacSign,
) -> list[tuple[tuple[int, int, int, int], DailySkyPlanet, DailySkyAspect | None]]:
    ranked: list[tuple[tuple[int, int, int, int], DailySkyPlanet, DailySkyAspect | None]] = []
    for planet in sky.planets:
        aspect = _strongest_aspect_for_body(sky, planet.body)
        house = _solar_house(sign, planet.sign)
        ranked.append(
            (
                (
                    _HOUSE_PRIORITY[house],
                    0 if aspect is not None else 1,
                    aspect.orb_millidegrees if aspect is not None else 99_999,
                    _BODY_PRIORITY[planet.body],
                ),
                planet,
                aspect,
            )
        )
    return sorted(ranked, key=lambda item: item[0])


def _credible_distinct_house_candidates(
    ranked: list[tuple[tuple[int, int, int, int], DailySkyPlanet, DailySkyAspect | None]],
    sign: ZodiacSign,
) -> list[tuple[tuple[int, int, int, int], DailySkyPlanet, DailySkyAspect | None]]:
    """Keep up to three strong stories in distinct houses for product-level variety."""

    best_house_priority = ranked[0][0][0]
    candidates: list[
        tuple[tuple[int, int, int, int], DailySkyPlanet, DailySkyAspect | None]
    ] = []
    seen_houses: set[int] = set()
    fast_bodies = {
        NatalBody.MOON,
        NatalBody.MERCURY,
        NatalBody.VENUS,
        NatalBody.MARS,
        NatalBody.SUN,
    }
    for item in ranked:
        score, planet, aspect = item
        house = _solar_house(sign, planet.sign)
        if score[0] > best_house_priority + 1:
            continue
        if house in seen_houses:
            continue
        if aspect is None and planet.body not in fast_bodies and score[0] > best_house_priority:
            continue
        seen_houses.add(house)
        candidates.append(item)
        if len(candidates) == 3:
            break
    return candidates or [ranked[0]]


def _rotating_candidate(
    forecast_date: date,
    sign: ZodiacSign,
    candidates: list[tuple[tuple[int, int, int, int], DailySkyPlanet, DailySkyAspect | None]],
) -> tuple[tuple[int, int, int, int], DailySkyPlanet, DailySkyAspect | None]:
    index = (forecast_date.toordinal() + _SIGNS.index(sign)) % len(candidates)
    return candidates[index]


def _strongest_aspect_for_body(
    sky: DailySkySnapshot,
    body: NatalBody,
) -> DailySkyAspect | None:
    return next(
        (aspect for aspect in sky.aspects if body in (aspect.first_body, aspect.second_body)),
        None,
    )


def _forecast_phrase(body: NatalBody, aspect: DailySkyAspect | None) -> str:
    if aspect is None:
        return _NEUTRAL_FORECAST[body]
    if aspect.kind in (NatalAspectKind.SEXTILE, NatalAspectKind.TRINE):
        return _SUPPORTIVE_FORECAST[body]
    if aspect.kind in (NatalAspectKind.SQUARE, NatalAspectKind.OPPOSITION):
        return _CHALLENGING_FORECAST[body]
    return _FOCUSED_FORECAST[body]


def _planet_position(body: NatalBody, engine_body: Any, astro_time: Any) -> DailySkyPlanet:
    longitude = _longitude(engine_body, astro_time)
    before = _longitude(engine_body, astro_time.AddDays(-0.5))
    after = _longitude(engine_body, astro_time.AddDays(0.5))
    millidegrees = round(longitude * 1000.0) % 360_000
    return DailySkyPlanet(
        body=body,
        longitude_millidegrees=millidegrees,
        sign=_SIGNS[millidegrees // 30_000],
        retrograde=_signed_angle(after - before) < 0.0,
    )


def _longitude(engine_body: Any, astro_time: Any) -> float:
    vector = astronomy.GeoVector(engine_body, astro_time, True)
    return float(astronomy.Ecliptic(vector).elon) % 360.0


def _planet_aspects(planets: tuple[DailySkyPlanet, ...]) -> tuple[DailySkyAspect, ...]:
    aspects: list[DailySkyAspect] = []
    for index, first in enumerate(planets):
        for second in planets[index + 1 :]:
            separation = abs(first.longitude_millidegrees - second.longitude_millidegrees)
            separation = min(separation, 360_000 - separation)
            kind, exact, maximum_orb = min(
                _ASPECTS,
                key=lambda candidate: abs(separation - candidate[1]),
            )
            orb = abs(separation - exact)
            if orb <= maximum_orb:
                ordered = sorted((first.body, second.body), key=lambda body: body.value)
                aspects.append(DailySkyAspect(ordered[0], ordered[1], kind, orb))
    return tuple(
        sorted(
            aspects,
            key=lambda aspect: (
                aspect.orb_millidegrees,
                min(_BODY_PRIORITY[aspect.first_body], _BODY_PRIORITY[aspect.second_body]),
                aspect.first_body.value,
                aspect.second_body.value,
            ),
        )
    )


def _driver_aspect(sky: DailySkySnapshot) -> DailySkyAspect | None:
    personal = {NatalBody.MOON, NatalBody.MERCURY, NatalBody.VENUS, NatalBody.MARS, NatalBody.SUN}
    return next(
        (
            aspect
            for aspect in sky.aspects
            if aspect.first_body in personal or aspect.second_body in personal
        ),
        sky.aspects[0] if sky.aspects else None,
    )


def _solar_house(sun_sign: ZodiacSign, transit_sign: ZodiacSign) -> int:
    return ((_SIGNS.index(transit_sign) - _SIGNS.index(sun_sign)) % 12) + 1


def _signed_angle(value: float) -> float:
    return (value + 540.0) % 360.0 - 180.0


def _required_text(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError("invalid daily horoscope snapshot field")
    return value
