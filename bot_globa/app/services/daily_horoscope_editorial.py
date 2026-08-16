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

DAILY_EDITORIAL_METHOD_VERSION = "solar-sign-daily-v3"

_STORIES = MappingProxyType(
    {
        "инициатива": (
            "Появится повод проявить себя; начните с одного шага",
            "Смелый ход может сдвинуть дело; действуйте без суеты",
            "Сегодня легче заявить о себе; выберите ясную цель",
            "Решение, которое вы откладывали, может созреть сегодня",
            "Инициатива заметнее обычного; используйте момент",
            "Новый импульс стоит проверить делом, а не сомнениями",
        ),
        "деньги": (
            "В деньгах может появиться ясность; не спешите обещать",
            "Финансовая деталь окажется важнее суммы; проверьте условия",
            "Можно увидеть, где теряются ресурсы; сократите лишнее",
            "Небольшая возможность укрепит опору; действуйте практично",
        ),
        "общение": (
            "Один разговор может многое сдвинуть; задайте прямой вопрос",
            "Важная деталь всплывёт в переписке; читайте внимательнее",
            "Слова сегодня весят больше обычного; говорите по существу",
            "Новость может изменить план; оставьте место для манёвра",
        ),
        "дом и семья": (
            "Домашний вопрос попросит внимания; решите его без драм",
            "Разговор с близким снимет напряжение; начните мягко",
            "В доме захочется порядка; одно простое решение поможет",
            "Близкие могут удивить реакцией; не додумывайте за них",
        ),
        "любовь и творчество": (
            "Симпатия может проявиться яснее; не прячьте тёплый знак",
            "Творческая идея попросится наружу; дайте ей форму",
            "В любви важнее взаимность, чем эффектный жест",
            "Лёгкость вернётся через удовольствие; оставьте место спонтанности",
        ),
        "работа и режим": (
            "В работе найдётся простой способ снять лишнюю нагрузку",
            "Рутина покажет слабое место; исправьте его первым",
            "Порядок в делах освободит больше времени, чем кажется",
            "Темп лучше выровнять; не берите на себя всё сразу",
        ),
        "отношения": (
            "В отношениях прояснится важный нюанс; слушайте внимательнее",
            "Чужая реакция скажет больше слов; не торопите вывод",
            "Разговор может изменить тон отношений; говорите прямо",
            "Договориться станет проще, если сначала услышать другую сторону",
            "Кто-то может сделать шаг навстречу; оставьте место ответу",
            "Граница станет заметнее; обозначьте её спокойно",
        ),
        "общие деньги": (
            "Общий денежный вопрос лучше прояснить до новых обещаний",
            "Тема доверия потребует ясности; договоритесь о правилах",
            "Чужие ожидания могут влиять на деньги; отделите своё",
            "Финансовое решение лучше принимать после проверки деталей",
        ),
        "обучение и поездки": (
            "Новая мысль может изменить дальний план; не отвергайте её",
            "Поездка или обучение дадут неожиданный ориентир",
            "Полезная информация придёт не оттуда, откуда вы ждёте",
            "План на будущее станет яснее после одного нового факта",
        ),
        "карьера": (
            "В работе откроется важный рычаг; напомните о своей ценности",
            "Профессиональный вопрос может сдвинуться после разговора",
            "Шанс проявить себя появится без шума; будьте готовы",
            "Рабочая развилка покажет сильный путь; не цепляйтесь за старое",
            "В карьере станет яснее, куда направить усилия",
            "Чья-то оценка может измениться; покажите результат",
        ),
        "друзья и планы": (
            "Разговор с другом может подсказать следующий шаг",
            "Новое знакомство способно дать полезную идею; будьте открыты",
            "Планы на будущее стоит обсудить; чужой взгляд поможет",
            "В компании проявится важный союзник; не пропустите сигнал",
        ),
        "отдых и завершение": (
            "Полезно закрыть то, что незаметно забирает силы",
            "Пауза сегодня продуктивнее рывка; освободите голову",
            "Старый вопрос можно отпустить; не тащите его дальше",
            "Тишина поможет увидеть решение, которое терялось в шуме",
        ),
    }
)

_GENERAL_STORIES = (
    "Один небольшой шаг сегодня окажется важнее длинных раздумий",
    "День подскажет следующий ход; не пытайтесь решить всё сразу",
    "Важная деталь станет яснее, если не торопить события",
    "Стоит оставить место неожиданному варианту; он может пригодиться",
)


def build_editorial_daily_horoscope(forecast_date: date) -> DailyHoroscopeSnapshot:
    """Build one v3 snapshot with concise, non-repetitive human-facing forecasts."""

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
    distinct = f"{candidate}; выберите свой темп"
    used.add(distinct)
    return DailySignForecast(item.sign, distinct)


def _stable_index(forecast_date: date, sign: ZodiacSign, signal: str, size: int) -> int:
    payload = f"{forecast_date.isoformat()}|{sign.value}|{signal}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:4], "big") % size
