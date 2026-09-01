"""Autoresearch edit surface for the mass daily horoscope.

This is intentionally the ONLY implementation file the autonomous research agent may edit.
It is not imported by production delivery. Winners must still be reviewed and promoted
explicitly into the production editorial implementation.
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

RESEARCH_CANDIDATE_VERSION = "v6-exp-004-neutral-openers"

_STORIES = MappingProxyType(
    {
        "инициатива": (
            "Шанс появится внезапно — сделайте первый шаг.",
            "Сомнения тормозят первый шаг — начните с простого.",
            "Инициатива заметна — заранее выберите цель.",
            "Новая возможность появится быстро — проверьте её делом.",
            "Решение созреет быстро — не откладывайте шаг.",
            "Ваша активность задаст тон — выберите одну цель.",
        ),
        "деньги": (
            "В деньгах прояснится деталь — проверьте условия.",
            "Расходы потребуют внимания — уберите лишнее.",
            "Появится финансовый шанс — оцените выгоду без спешки.",
            "Бюджет зависит от вас — держитесь своих цифр.",
        ),
        "общение": (
            "Разговор изменит планы — задайте прямой вопрос.",
            "В переписке всплывёт нюанс — перечитайте детали.",
            "В разговоре вас услышат лучше — говорите по существу.",
            "Новость потребует реакции — сначала уточните факты.",
        ),
        "дом и семья": (
            "Домашний вопрос вернётся — решите его спокойно.",
            "Близкий удивит реакцией — сначала выслушайте.",
            "Домашний беспорядок раздражает — наведите порядок.",
            "Семья потребует внимания — оставьте время на разговор.",
        ),
        "любовь и творчество": (
            "Симпатия станет яснее — покажите ответный интерес.",
            "В любви видна взаимность — не давите на события.",
            "Любовь или творчество дадут импульс — дайте ему форму.",
            "В любви станет легче — оставьте место спонтанности.",
        ),
        "работа и режим": (
            "В работе проявится слабость — исправьте её сразу.",
            "Рабочая рутина утомляет — снимите лишнюю задачу.",
            "В работе порядок даст эффект — начните с самого срочного.",
            "Темп работы легко перегрузить — оставьте запас.",
        ),
        "отношения": (
            "В отношениях всплывёт вопрос — сначала выслушайте.",
            "В отношениях чужая реакция важна — не додумывайте мотивы.",
            "Честный разговор поможет — задайте прямой вопрос.",
            "В отношениях договориться проще — назовите, что для вас важно.",
            "Кто-то шагнёт навстречу — не отвечайте холодом.",
            "Граница в отношениях требует ясности — обозначьте её спокойно.",
        ),
        "общие деньги": (
            "Общие деньги требуют ясности — зафиксируйте условия.",
            "Доверие и деньги пересекутся — проговорите роли.",
            "Чужие финансовые ожидания давят — отделите обязательства.",
            "Денежный выбор кажется срочным — проверьте цифры и сроки.",
        ),
        "обучение и поездки": (
            "Новая информация изменит план — запишите вывод.",
            "Поездка даст ориентир — оставьте место возможности.",
            "В обучении полезный факт удивит — проверьте источник.",
            "Обучение прояснит план — задайте уточняющий вопрос.",
        ),
        "карьера": (
            "В карьере появится шанс — покажите результат.",
            "Карьерный вопрос сдвинется — инициируйте разговор.",
            "Карьерное направление станет яснее — выберите один навык.",
            "На карьерной развилке сравните варианты — оцените отдачу.",
            "Ваш вклад в работе заметят — не прячьте результат.",
            "Следующий карьерный шаг ясен — идите на отклик.",
        ),
        "друзья и планы": (
            "Друг подсветит слабое место в плане — запишите идею.",
            "Новое знакомство полезно — задайте вопрос.",
            "Чужой взгляд подсветит план — поправьте слабость.",
            "Важный человек окажется рядом — замечайте разговоры.",
        ),
        "отдых и завершение": (
            "Усталость станет заметнее — остановитесь вовремя.",
            "Пауза полезнее рывка — освободите время без задач.",
            "Старый вопрос вернётся — решите, что отпустить.",
            "Тишина покажет решение — уберите лишний шум.",
        ),
    }
)

_GENERAL_STORIES = (
    "День потребует выбора — сделайте один ясный шаг.",
    "События прояснятся — не торопите решение.",
    "Неожиданный вариант поможет — проверьте его делом.",
    "Суета собьёт темп — оставьте запас между делами.",
)

_DUPLICATE_OPENERS = (
    "Сейчас",
    "Ваш ход",
    "Точка дня",
    "Главный акцент",
    "Верный темп",
    "Ключевой момент",
    "Полезный фокус",
    "Лучший ход",
    "Точный ориентир",
    "Важный нюанс",
    "Ясный акцент",
    "Личный ориентир",
)


def build_candidate_daily_horoscope(forecast_date: date) -> DailyHoroscopeSnapshot:
    """Build the current research candidate from the immutable astronomy signal."""

    base = build_daily_horoscope(forecast_date)
    used: set[str] = set()
    signs = tuple(_editorialize(item, forecast_date, used) for item in base.signs)
    return DailyHoroscopeSnapshot(
        forecast_date=base.forecast_date,
        sky_digest=base.sky_digest,
        theme=base.theme,
        signs=signs,
        sky_version=base.sky_version,
        methodology_version=f"autoresearch-{RESEARCH_CANDIDATE_VERSION}",
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
    candidate = candidates[start]
    if candidate not in used:
        used.add(candidate)
        return DailySignForecast(item.sign, candidate)

    # Keep each sign's day-to-day rotation independent from earlier signs in the rendering
    # order. If two signs land on the same story today, disambiguate only the later one
    # instead of shifting it to another story and accidentally repeating yesterday's copy.
    sign_index = tuple(ZodiacSign).index(item.sign)
    distinct = f"{_DUPLICATE_OPENERS[sign_index]}: {candidate}"
    used.add(distinct)
    return DailySignForecast(item.sign, distinct)


def _stable_index(forecast_date: date, sign: ZodiacSign, rotation_key: str, size: int) -> int:
    """Advance one slot per civil day while keeping a stable per-sign/topic phase."""

    payload = f"{sign.value}|{rotation_key}".encode()
    phase = int.from_bytes(hashlib.sha256(payload).digest()[:4], "big") % size
    return (phase + forecast_date.toordinal()) % size
