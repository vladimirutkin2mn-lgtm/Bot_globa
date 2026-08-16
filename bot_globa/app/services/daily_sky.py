"""Deterministic sky snapshot and solar-sign daily horoscope methodology.

Astronomy Engine provides astronomical longitudes. The sign/house interpretation below is
an astrology product convention, not a scientifically validated prediction method. A mass
daily digest deliberately uses only the reader's Sun sign as a twelve-sector approximation;
personal natal transits belong to the astrologer flow instead.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType
from typing import Any

import astronomy

from app.domain.natal_chart import NatalAspectKind, NatalBody, ZodiacSign

DAILY_SKY_VERSION = "daily-sky-v1"
DAILY_SOLAR_METHOD_VERSION = "solar-sign-daily-v1"

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
        1: "себе, инициативе и личному темпу",
        2: "деньгам, ресурсам и ощущению опоры",
        3: "разговорам, документам и коротким делам",
        4: "дому, близким и внутренней устойчивости",
        5: "симпатии, творчеству и удовольствию",
        6: "ритму, работе и бытовым задачам",
        7: "отношениям, договорённостям и обратной связи",
        8: "общим ресурсам, доверию и скрытому напряжению",
        9: "обучению, дальним планам и новому взгляду",
        10: "карьере, видимости и результату",
        11: "друзьям, связям и планам на будущее",
        12: "отдыху, завершению и тому, что лучше не форсировать",
    }
)

_BODY_ACTION = MappingProxyType(
    {
        NatalBody.MOON: "Не принимайте первое чувство за окончательный вывод.",
        NatalBody.MERCURY: "Говорите конкретно и перепроверяйте детали.",
        NatalBody.VENUS: "В отношениях важнее тон и взаимность, чем эффектный жест.",
        NatalBody.MARS: "Энергию лучше направить в один конкретный шаг.",
        NatalBody.JUPITER: "Расширяйте план только там, где уже есть опора.",
        NatalBody.SATURN: "Сначала обязательное, затем всё остальное.",
        NatalBody.URANUS: "Оставьте место неожиданному варианту.",
        NatalBody.NEPTUNE: "Проверяйте впечатление фактом, прежде чем делать вывод.",
        NatalBody.PLUTO: "Не давите на ситуацию: ищите точку реального влияния.",
        NatalBody.SUN: "Выберите одно направление, которому сегодня дадите больше внимания.",
    }
)

_ASPECT_THEME = MappingProxyType(
    {
        NatalAspectKind.CONJUNCTION: "две темы сходятся в одну точку — лучше выбрать главный приоритет",
        NatalAspectKind.SEXTILE: "есть пространство для небольшого шага, который откроет больше возможностей",
        NatalAspectKind.SQUARE: "противоречие лучше заметить заранее, чем пытаться продавить ситуацию",
        NatalAspectKind.TRINE: "то, что уже движется, проще поддержать, чем начинать всё заново",
        NatalAspectKind.OPPOSITION: "важно удержать две стороны ситуации и не выбирать из первого импульса",
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
        forecast_date = payload.get("forecast_date")
        sky_digest = payload.get("sky_digest")
        theme = payload.get("theme")
        sky_version = payload.get("sky_version")
        methodology_version = payload.get("methodology_version")
        if not all(
            isinstance(value, str)
            for value in (forecast_date, sky_digest, theme, sky_version, methodology_version)
        ):
            raise ValueError("invalid daily horoscope snapshot fields")
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
    aspects = _planet_aspects(planets)
    return DailySkySnapshot(forecast_date, planets, aspects)


def build_daily_horoscope(forecast_date: date) -> DailyHoroscopeSnapshot:
    """Turn the calculated sky into one bounded twelve-sign solar horoscope."""

    sky = calculate_daily_sky(forecast_date)
    driver = _driver_aspect(sky)
    theme = _ASPECT_THEME[driver.kind] if driver is not None else (
        "сегодня полезнее держать свой темп и сверять впечатления с фактами"
    )
    action_body = _action_body(driver)
    action = _BODY_ACTION[action_body]
    moon = next(planet for planet in sky.planets if planet.body is NatalBody.MOON)
    signs = tuple(
        DailySignForecast(
            sign,
            f"фокус на {_HOUSE_FOCUS[_solar_house(sign, moon.sign)]}; {action}",
        )
        for sign in ZodiacSign
    )
    return DailyHoroscopeSnapshot(
        forecast_date=forecast_date,
        sky_digest=sky.digest(),
        theme=theme,
        signs=signs,
    )


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


def _action_body(driver: DailySkyAspect | None) -> NatalBody:
    if driver is None:
        return NatalBody.MOON
    return min(
        (driver.first_body, driver.second_body),
        key=lambda body: _BODY_PRIORITY[body],
    )


def _solar_house(sun_sign: ZodiacSign, transit_sign: ZodiacSign) -> int:
    return ((_SIGNS.index(transit_sign) - _SIGNS.index(sun_sign)) % 12) + 1


def _signed_angle(value: float) -> float:
    return (value + 540.0) % 360.0 - 180.0
