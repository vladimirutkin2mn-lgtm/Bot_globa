"""Offline geocoding used by tests and local development.

Deterministic and network-free, so the test suite never depends on a third party. The
table is intentionally small: it is a development aid, not a product data set.
"""

import unicodedata

from app.providers.geocoding.base import GeocodedPlace

_CITIES: tuple[GeocodedPlace, ...] = (
    GeocodedPlace("Москва, Россия", 55.755864, 37.617698, "Europe/Moscow"),
    GeocodedPlace("Санкт-Петербург, Россия", 59.938784, 30.314997, "Europe/Moscow"),
    GeocodedPlace("Новосибирск, Россия", 55.030204, 82.920430, "Asia/Novosibirsk"),
    GeocodedPlace("Екатеринбург, Россия", 56.838011, 60.597465, "Asia/Yekaterinburg"),
    GeocodedPlace("Казань, Россия", 55.796127, 49.106414, "Europe/Moscow"),
    GeocodedPlace("Нижний Новгород, Россия", 56.326797, 44.006516, "Europe/Moscow"),
    GeocodedPlace("Челябинск, Россия", 55.159897, 61.402554, "Asia/Yekaterinburg"),
    GeocodedPlace("Самара, Россия", 53.195878, 50.100202, "Europe/Samara"),
    GeocodedPlace("Ростов-на-Дону, Россия", 47.222078, 39.720349, "Europe/Moscow"),
    GeocodedPlace("Владивосток, Россия", 43.115542, 131.885494, "Asia/Vladivostok"),
    GeocodedPlace("Калининград, Россия", 54.710157, 20.510137, "Europe/Kaliningrad"),
    GeocodedPlace("Красноярск, Россия", 56.010569, 92.852572, "Asia/Krasnoyarsk"),
    GeocodedPlace("Иркутск, Россия", 52.286974, 104.305018, "Asia/Irkutsk"),
    GeocodedPlace("Омск, Россия", 54.989342, 73.368212, "Asia/Omsk"),
    GeocodedPlace("Уфа, Россия", 54.735152, 55.991460, "Asia/Yekaterinburg"),
    GeocodedPlace("Киев, Украина", 50.450100, 30.523400, "Europe/Kyiv"),
    GeocodedPlace("Минск, Беларусь", 53.902284, 27.561831, "Europe/Minsk"),
    GeocodedPlace("Алматы, Казахстан", 43.238949, 76.889709, "Asia/Almaty"),
    GeocodedPlace("Астана, Казахстан", 51.169392, 71.449074, "Asia/Almaty"),
    GeocodedPlace("Ташкент, Узбекистан", 41.299496, 69.240073, "Asia/Tashkent"),
    GeocodedPlace("Тбилиси, Грузия", 41.716667, 44.783333, "Asia/Tbilisi"),
    GeocodedPlace("Ереван, Армения", 40.177200, 44.503200, "Asia/Yerevan"),
    GeocodedPlace("Баку, Азербайджан", 40.409264, 49.867092, "Asia/Baku"),
    GeocodedPlace("Кишинёв, Молдова", 47.010453, 28.863810, "Europe/Chisinau"),
    GeocodedPlace("Бишкек, Киргизия", 42.874621, 74.569762, "Asia/Bishkek"),
    GeocodedPlace("Рига, Латвия", 56.949649, 24.105186, "Europe/Riga"),
    GeocodedPlace("Вильнюс, Литва", 54.687157, 25.279652, "Europe/Vilnius"),
    GeocodedPlace("Таллин, Эстония", 59.436962, 24.753574, "Europe/Tallinn"),
    GeocodedPlace("Берлин, Германия", 52.520008, 13.404954, "Europe/Berlin"),
    GeocodedPlace("Париж, Франция", 48.856613, 2.352222, "Europe/Paris"),
    GeocodedPlace("Лондон, Великобритания", 51.507351, -0.127758, "Europe/London"),
    GeocodedPlace("Мадрид, Испания", 40.416775, -3.703790, "Europe/Madrid"),
    GeocodedPlace("Рим, Италия", 41.902782, 12.496366, "Europe/Rome"),
    GeocodedPlace("Прага, Чехия", 50.075538, 14.437800, "Europe/Prague"),
    GeocodedPlace("Варшава, Польша", 52.229676, 21.012229, "Europe/Warsaw"),
    GeocodedPlace("Стамбул, Турция", 41.008238, 28.978359, "Europe/Istanbul"),
    GeocodedPlace("Дубай, ОАЭ", 25.204849, 55.270783, "Asia/Dubai"),
    GeocodedPlace("Тель-Авив, Израиль", 32.085300, 34.781769, "Asia/Jerusalem"),
    GeocodedPlace("Нью-Йорк, США", 40.712776, -74.005974, "America/New_York"),
    GeocodedPlace("Лос-Анджелес, США", 34.052235, -118.243683, "America/Los_Angeles"),
    GeocodedPlace("Торонто, Канада", 43.653225, -79.383186, "America/Toronto"),
    GeocodedPlace("Пекин, Китай", 39.904200, 116.407396, "Asia/Shanghai"),
    GeocodedPlace("Токио, Япония", 35.689487, 139.691711, "Asia/Tokyo"),
    GeocodedPlace("Бангкок, Таиланд", 13.756331, 100.501765, "Asia/Bangkok"),
)


class StubGeocodingClient:
    """Match a query against a bundled table; never touches the network."""

    def __init__(self, cities: tuple[GeocodedPlace, ...] = _CITIES) -> None:
        self._cities = cities

    async def search(self, query: str, *, limit: int) -> tuple[GeocodedPlace, ...]:
        needle = _normalize(query)
        if not needle:
            return ()
        exact = [city for city in self._cities if _normalize(city.label).startswith(needle)]
        partial = [
            city for city in self._cities if city not in exact and needle in _normalize(city.label)
        ]
        return tuple((exact + partial)[:limit])


def _normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", " ".join(value.split())).casefold().replace("ё", "е")
