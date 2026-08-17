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

DAILY_EDITORIAL_METHOD_VERSION = "solar-sign-daily-v4"

_STORIES = MappingProxyType(
    {
        "инициатива": (
            "Не ждите идеального момента. Первый шаг сегодня важнее безупречного плана",
            "Смелое решение может сдвинуть дело с места. Главное — не суетиться",
            "Сегодня проще заявить о себе и выбрать одну ясную цель",
            "Ответ на отложенный вопрос уже ближе, чем кажется",
            "Инициатива будет заметнее обычного. Используйте момент спокойно",
            "Новый импульс лучше проверить делом, а не долгими сомнениями",
        ),
        "деньги": (
            "В деньгах станет чуть больше ясности. С обещаниями лучше не спешить",
            "Сегодня важнее условия, а не сама сумма. Проверьте детали",
            "Можно заметить, куда незаметно уходят ресурсы",
            "Небольшая возможность способна укрепить финансовую опору",
        ),
        "общение": (
            "Один прямой вопрос может изменить весь разговор",
            "Важная деталь обнаружится в переписке. Не спешите читать между строк",
            "Сегодня особенно легко быть услышанным, если говорить по существу",
            "Новость может поменять планы. Оставьте немного пространства для манёвра",
        ),
        "дом и семья": (
            "Домашний вопрос напомнит о себе. Лучше решить его без лишней драмы",
            "Мягкий разговор с близким снимет часть напряжения",
            "Небольшой порядок дома неожиданно разгрузит голову",
            "Реакция близких может удивить. Не додумывайте за них",
        ),
        "любовь и творчество": (
            "Симпатия проявится яснее, чем обычно. Не прячьте тёплый знак",
            "Творческая идея захочет выйти наружу. Дайте ей форму",
            "В любви сегодня важнее взаимность, чем эффектный жест",
            "Лёгкость вернётся, если оставить место удовольствию и спонтанности",
        ),
        "работа и режим": (
            "В работе найдётся простой способ снять часть лишней нагрузки",
            "Рутина покажет слабое место. Его можно исправить без большого рывка",
            "Небольшой порядок в делах освободит больше времени, чем кажется",
            "Сегодня полезнее выровнять темп, чем пытаться успеть всё",
        ),
        "отношения": (
            "В отношениях прояснится важный нюанс. Сначала выслушайте, потом отвечайте",
            "Чужая реакция сегодня скажет больше привычных слов",
            "Один честный разговор способен заметно изменить тон отношений",
            "Договориться будет проще, если сначала услышать другую сторону",
            "Кто-то может сделать шаг навстречу. Оставьте место для ответа",
            "Там, где вы обычно уступаете, стоит спокойно обозначить границу",
        ),
        "общие деньги": (
            "Общий денежный вопрос лучше прояснить до новых обещаний",
            "В теме доверия сегодня особенно важны ясные договорённости",
            "Чужие ожидания могут влиять на деньги. Отделите своё от чужого",
            "Финансовое решение лучше принимать после спокойной проверки деталей",
        ),
        "обучение и поездки": (
            "Новая мысль способна заметно изменить дальний план",
            "Поездка или обучение дадут неожиданный ориентир",
            "Полезная информация придёт не оттуда, откуда вы её ждёте",
            "Одного нового факта хватит, чтобы план на будущее стал яснее",
        ),
        "карьера": (
            "Сегодня особенно важно не занижать собственную ценность",
            "Разговор поможет сдвинуть профессиональный вопрос, который давно стоял на месте",
            "Небольшая возможность может оказаться началом чего-то большего",
            "На развилке не держитесь за старый вариант только из-за вложенных сил",
            "Станет понятнее, куда направить усилия в ближайшее время",
            "Ваш результат заметят быстрее, чем длинные объяснения",
        ),
        "друзья и планы": (
            "Разговор с другом может неожиданно подсказать следующий шаг",
            "Новое знакомство принесёт идею, которую стоит запомнить",
            "Чужой взгляд поможет увидеть в планах то, что вы пропускали",
            "В компании может проявиться человек, на которого стоит обратить внимание",
        ),
        "отдых и завершение": (
            "Полезно закрыть то, что незаметно забирает силы",
            "Пауза сегодня окажется продуктивнее ещё одного рывка",
            "Старый вопрос можно наконец оставить в прошлом",
            "Тишина поможет заметить решение, которое терялось в шуме",
        ),
    }
)

_GENERAL_STORIES = (
    "Один небольшой шаг сегодня окажется важнее длинных раздумий",
    "Не пытайтесь решить всё сразу. День сам подскажет следующий ход",
    "Важная деталь станет яснее, если не торопить события",
    "Оставьте место неожиданному варианту. Он может оказаться кстати",
)


def build_editorial_daily_horoscope(forecast_date: date) -> DailyHoroscopeSnapshot:
    """Build one v4 snapshot with concise, non-repetitive human-facing forecasts."""

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
    topic, separator, signal = item.text.partition(": ")
    candidates = _STORIES.get(topic, _GENERAL_STORIES) if separator else _GENERAL_STORIES
    start = _stable_index(forecast_date, item.sign, signal or item.text, len(candidates))
    for offset in range(len(candidates)):
        candidate = candidates[(start + offset) % len(candidates)]
        if candidate not in used:
            used.add(candidate)
            return DailySignForecast(item.sign, candidate)

    # This is only an emergency guard for an unusually concentrated sky. It preserves a
    # meaningful forecast instead of exposing the old mechanical "topic: phrase" format.
    candidate = candidates[start]
    distinct = f"{candidate}. Выберите ритм, который подходит именно вам."
    used.add(distinct)
    return DailySignForecast(item.sign, distinct)


def _stable_index(forecast_date: date, sign: ZodiacSign, signal: str, size: int) -> int:
    payload = f"{forecast_date.isoformat()}|{sign.value}|{signal}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:4], "big") % size
