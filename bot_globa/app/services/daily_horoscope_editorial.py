"""Editorial layer for the mass daily horoscope.

The astronomy/solar-sign engine decides the shared day theme and the strongest topic per
sign. This module turns those compact machine-friendly signals into short human mini-
forecasts while keeping the Telegram caption bounded and the twelve lines non-repetitive.
"""

import hashlib
from datetime import date
from types import MappingProxyType

from app.domain.natal_chart import ZodiacSign
from app.services.daily_sky import (
    DailyHoroscopeSnapshot,
    DailySignForecast,
    build_daily_horoscope,
)

DAILY_EDITORIAL_METHOD_VERSION = "solar-sign-daily-v5"

_STORIES = MappingProxyType(
    {
        "инициатива": (
            "Первый шаг сегодня важнее идеального плана",
            "Смелое решение сдвинет дело с места. Главное — без суеты",
            "Сегодня проще заявить о себе и выбрать ясную цель",
            "Ответ на отложенный вопрос уже ближе, чем кажется",
            "Инициатива сегодня заметнее обычного. Используйте момент",
            "Новый импульс лучше проверить делом, а не сомнениями",
        ),
        "деньги": (
            "В деньгах станет яснее. С обещаниями лучше не спешить",
            "Сегодня важнее условия, а не сумма. Проверьте детали",
            "Можно заметить, куда незаметно уходят ресурсы",
            "Небольшая возможность укрепит финансовую опору",
        ),
        "общение": (
            "Один прямой вопрос может изменить весь разговор",
            "Важная деталь обнаружится в переписке. Не спешите с выводами",
            "Сегодня легче быть услышанным, если говорить по существу",
            "Новость может поменять планы. Оставьте место для манёвра",
        ),
        "дом и семья": (
            "Домашний вопрос напомнит о себе. Решите его без лишней драмы",
            "Мягкий разговор с близким снимет часть напряжения",
            "Небольшой порядок дома неожиданно разгрузит голову",
            "Реакция близких может удивить. Не додумывайте за них",
        ),
        "любовь и творчество": (
            "Симпатия проявится яснее. Не прячьте тёплый знак",
            "Творческая идея захочет выйти наружу. Дайте ей форму",
            "В любви сегодня важнее взаимность, чем эффектный жест",
            "Лёгкость вернётся, если оставить место спонтанности",
        ),
        "работа и режим": (
            "В работе найдётся способ снять часть лишней нагрузки",
            "Рутина покажет слабое место. Его можно исправить без рывка",
            "Порядок в делах освободит больше времени, чем кажется",
            "Сегодня полезнее выровнять темп, чем пытаться успеть всё",
        ),
        "отношения": (
            "В отношениях прояснится нюанс. Сначала выслушайте",
            "Чужая реакция сегодня скажет больше привычных слов",
            "Один честный разговор заметно изменит тон отношений",
            "Договориться проще, если сначала услышать другую сторону",
            "Кто-то может сделать шаг навстречу. Оставьте место ответу",
            "Там, где вы уступаете, стоит спокойно обозначить границу",
        ),
        "общие деньги": (
            "Общий денежный вопрос лучше прояснить до новых обещаний",
            "В теме доверия сегодня важны ясные договорённости",
            "Чужие ожидания могут влиять на деньги. Отделите своё",
            "Финансовое решение лучше принять после проверки деталей",
        ),
        "обучение и поездки": (
            "Новая мысль способна изменить дальний план",
            "Поездка или обучение дадут неожиданный ориентир",
            "Полезная информация придёт не оттуда, откуда вы ждёте",
            "Одного нового факта хватит, чтобы план стал яснее",
        ),
        "карьера": (
            "Сегодня особенно важно не занижать свою ценность",
            "Разговор поможет сдвинуть давний профессиональный вопрос",
            "Небольшая возможность может стать началом чего-то большего",
            "На развилке не держитесь за старое только из-за вложенных сил",
            "Станет понятнее, куда направить усилия дальше",
            "Ваш результат заметят быстрее, чем длинные объяснения",
        ),
        "друзья и планы": (
            "Разговор с другом неожиданно подскажет следующий шаг",
            "Новое знакомство принесёт идею, которую стоит запомнить",
            "Чужой взгляд поможет увидеть в планах то, что вы пропускали",
            "В компании проявится человек, которого стоит заметить",
        ),
        "отдых и завершение": (
            "Полезно закрыть то, что незаметно забирает силы",
            "Пауза сегодня окажется полезнее ещё одного рывка",
            "Старый вопрос можно наконец оставить в прошлом",
            "Тишина поможет заметить решение, которое терялось в шуме",
        ),
    }
)

_GENERAL_STORIES = (
    "Один небольшой шаг сегодня важнее долгих раздумий",
    "Не пытайтесь решить всё сразу. День подскажет следующий ход",
    "Важная деталь станет яснее, если не торопить события",
    "Оставьте место неожиданному варианту. Он может оказаться кстати",
)


def build_editorial_daily_horoscope(forecast_date: date) -> DailyHoroscopeSnapshot:
    """Build one v5 snapshot with date-rotated, non-repetitive human-facing forecasts."""

    base = build_daily_horoscope(forecast_date)
    used: set[str] = set()
    signs = tuple(_editorialize(item, forecast_date, used) for item in base.signs)
    return DailyHoroscopeSnapshot(
        forecast_date=base.forecast_date,
        sky_digest=base.sky_digest,
        theme=base.theme,
        signs=signs,
        sky_version=base.sky_version,
        methodology_version=DAILY_EDITORIAL_METHOD_VERSION,
    )


def _editorialize(
    item: DailySignForecast,
    forecast_date: date,
    used: set[str],
) -> DailySignForecast:
    topic, separator, _signal = item.text.partition(": ")
    candidates = _STORIES.get(topic, _GENERAL_STORIES) if separator else _GENERAL_STORIES
    rotation_key = topic if separator else "general"
    start = _stable_index(forecast_date, item.sign, rotation_key, len(candidates))
    for offset in range(len(candidates)):
        candidate = candidates[(start + offset) % len(candidates)]
        if candidate not in used:
            used.add(candidate)
            return DailySignForecast(item.sign, candidate)

    # This is only an emergency guard for an unusually concentrated sky. It preserves a
    # meaningful forecast instead of exposing the old mechanical "topic: phrase" format.
    candidate = candidates[start]
    distinct = f"{candidate}. Выберите ритм, который подходит вам."
    used.add(distinct)
    return DailySignForecast(item.sign, distinct)


def _stable_index(forecast_date: date, sign: ZodiacSign, rotation_key: str, size: int) -> int:
    """Advance one slot per civil day while keeping a stable per-sign/topic phase."""

    payload = f"{sign.value}|{rotation_key}".encode()
    phase = int.from_bytes(hashlib.sha256(payload).digest()[:4], "big") % size
    return (phase + forecast_date.toordinal()) % size
