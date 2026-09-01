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

DAILY_EDITORIAL_METHOD_VERSION = "solar-sign-daily-v6"

_STORIES = MappingProxyType(
    {
        "инициатива": (
            "Появится шанс начать — выберите один первый шаг.",
            "Сомнения могут тормозить старт — начните с простого действия.",
            "Инициатива привлечёт внимание — заранее решите, чего хотите.",
            "Новый импульс окажется полезным — проверьте его делом.",
            "Решение созреет быстрее обычного — не откладывайте первый шаг.",
            "Ваша активность задаст тон — выберите одну ясную цель.",
        ),
        "деньги": (
            "Финансовая деталь станет заметнее — проверьте условия до обещаний.",
            "Расходы потребуют внимания — отделите необходимое от импульсивного.",
            "Небольшая возможность появится рядом — оцените выгоду без спешки.",
            "Чужие ожидания повлияют на бюджет — держитесь своих цифр.",
        ),
        "общение": (
            "Разговор может изменить планы — задайте прямой вопрос вместо догадок.",
            "В переписке проявится нюанс — перечитайте детали перед ответом.",
            "Вас услышат лучше обычного — говорите коротко и по существу.",
            "Новость потребует реакции — сначала уточните факты, потом решайте.",
        ),
        "дом и семья": (
            "Домашний вопрос напомнит о себе — решите его без напряжения.",
            "Близкий человек удивит реакцией — сначала выслушайте, потом отвечайте.",
            "Беспорядок будет раздражать сильнее — наведите порядок в одном месте.",
            "Семейный разговор станет важнее планов — оставьте время на обсуждение.",
        ),
        "любовь и творчество": (
            "Симпатия проявится яснее — покажите ответный интерес без игр.",
            "В любви станет заметна взаимность — не давите на события.",
            "Творческая идея попросится наружу — дайте ей форму сегодня.",
            "Лёгкость вернётся через спонтанность — оставьте место неожиданному шагу.",
        ),
        "работа и режим": (
            "В работе проявится слабое место — исправьте его до новых задач.",
            "Рутина начнёт утомлять — снимите одну лишнюю обязанность.",
            "Порядок в делах даст эффект — начните с самого срочного.",
            "Темп дня легко перегрузить — оставьте запас между задачами.",
        ),
        "отношения": (
            "В отношениях всплывёт вопрос — сначала дайте человеку договорить.",
            "Чужая реакция скажет больше слов — не додумывайте мотивы.",
            "Честный разговор изменит тон — задайте один прямой вопрос.",
            "Договориться станет проще — назовите, что для вас важно.",
            "Кто-то сделает шаг навстречу — не отвечайте холодом по привычке.",
            "Граница потребует ясности — обозначьте её спокойно и коротко.",
        ),
        "общие деньги": (
            "Общий денежный вопрос потребует ясности — зафиксируйте условия заранее.",
            "Доверие и деньги пересекутся — проговорите, кто за что отвечает.",
            "Чужие ожидания повлияют на решение — отделите обязательства от помощи.",
            "Финансовый выбор покажется срочным — сначала проверьте цифры и сроки.",
        ),
        "обучение и поездки": (
            "Новая информация изменит план — запишите вывод, пока он свежий.",
            "Поездка или обучение даст ориентир — оставьте место возможности.",
            "Полезный факт придёт неожиданно — проверьте источник перед решением.",
            "План прояснится после детали — задайте ещё один уточняющий вопрос.",
        ),
        "карьера": (
            "В карьере появится возможность — покажите результат вместо объяснений.",
            "Профессиональный вопрос сдвинется — инициируйте давно отложенный разговор.",
            "Станет яснее, куда расти — выберите один навык для усиления.",
            "На развилке потянет к привычному — сравните будущую отдачу вариантов.",
            "Ваш вклад заметят быстрее — не прячьте выполненную работу.",
            "Следующий шаг станет понятнее — идите туда, где есть отклик.",
        ),
        "друзья и планы": (
            "Разговор с другом даст новый угол — запишите идею до вечера.",
            "Новое знакомство окажется полезным — задайте вопрос вместо формальности.",
            "Чужой взгляд подсветит слабость плана — поправьте её заранее.",
            "В компании проявится важный человек — замечайте случайные разговоры.",
        ),
        "отдых и завершение": (
            "Усталость станет заметнее — закройте одно дело и остановитесь вовремя.",
            "Пауза окажется полезнее рывка — освободите полчаса без задач.",
            "Старый вопрос снова напомнит о себе — решите, что отпустить.",
            "Тишина поможет увидеть решение — уберите лишний шум ненадолго.",
        ),
    }
)

_GENERAL_STORIES = (
    "День потребует выбора — сделайте один шаг вместо десяти планов.",
    "События прояснятся постепенно — не торопите решение до новых фактов.",
    "Неожиданный вариант окажется полезным — сначала проверьте его на практике.",
    "Суета легко собьёт темп — оставьте запас между важными делами.",
)


def build_editorial_daily_horoscope(forecast_date: date) -> DailyHoroscopeSnapshot:
    """Build one v6 snapshot with compact situation-to-action human-facing forecasts."""

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
