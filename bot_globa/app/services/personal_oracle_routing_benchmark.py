"""Offline benchmark for the deterministic `Расскажите Numa` router.

The production router intentionally remains rule-based until measured evidence shows that a
classifier would materially improve it. Cases here are curated Russian user-style questions;
product analytics can append anonymized labeled examples without changing benchmark logic.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from app.bot.persona_flows import LOVE_ORACLE_FLOW, MYSTICAL_PSYCHOLOGIST_FLOW
from app.bot.personal_oracle_handlers import choose_route, needs_route_clarification


@dataclass(frozen=True, slots=True)
class RoutingCase:
    question: str
    expected: str


@dataclass(frozen=True, slots=True)
class RoutingReport:
    total: int
    correct: int
    accuracy: float
    expected_counts: dict[str, int]
    predicted_counts: dict[str, int]
    mistakes: tuple[tuple[str, str, str], ...]


# Seed corpus: deliberately includes short colloquial formulations, mixed intent and cases
# where asking one clarification is preferable to confidently picking a practice.
ROUTING_CASES: tuple[RoutingCase, ...] = (
    RoutingCase("Стоит ли менять работу этой осенью?", "work"),
    RoutingCase("Начальник предложил новую роль, соглашаться?", "work"),
    RoutingCase("Не понимаю, куда двигаться в карьере", "work"),
    RoutingCase("Есть два оффера, какой выбрать?", "work"),
    RoutingCase("Стоит ли увольняться сейчас?", "work"),
    RoutingCase("Проект буксует, что я не замечаю?", "work"),
    RoutingCase("С бизнесом какой-то тупик, куда смотреть?", "work"),
    RoutingCase("Коллега тянет меня вниз, как пойдёт ситуация?", "work"),
    RoutingCase("Получится ли сдвинуть рабочий проект?", "work"),
    RoutingCase("Предложили повышение, но сомневаюсь", "work"),
    RoutingCase("Деньги на работе не устраивают, стоит искать новое место?", "work"),
    RoutingCase("Какой вариант в работе сейчас перспективнее?", "work"),
    RoutingCase("Он меня любит?", "love"),
    RoutingCase("Что между нами происходит?", "love"),
    RoutingCase("Есть ли шанс снова быть с бывшим?", "love"),
    RoutingCase("Она отдалилась после свидания", "love"),
    RoutingCase("Написать ему первой или не стоит?", "love"),
    RoutingCase("Почему девушка стала отвечать холодно?", "love"),
    RoutingCase("Будем ли мы вместе?", "love"),
    RoutingCase("Есть ли будущее у нас двоих?", "love"),
    RoutingCase("Мне нравится парень, но он почти не проявляется", "love"),
    RoutingCase("Бывшая снова написала, чего ждать от этой истории?", "love"),
    RoutingCase("Кажется, между нами есть притяжение, но он молчит", "love"),
    RoutingCase("Что он чувствует ко мне сейчас?", "love"),
    RoutingCase("Она ревнует или мне кажется?", "love"),
    RoutingCase("Стоит ли позвонить ей после ссоры?", "love"),
    RoutingCase("Мы расстались месяц назад, возможен ли ещё контакт?", "love"),
    RoutingCase("Почему я снова выбираю эмоционально недоступных людей?", "reflection"),
    RoutingCase("Почему я каждый раз всё порчу в начале отношений?", "reflection"),
    RoutingCase("У меня постоянно один и тот же сценарий", "reflection"),
    RoutingCase("Почему я боюсь, когда всё начинает получаться?", "reflection"),
    RoutingCase("Снова и снова откладываю важное до последнего", "reflection"),
    RoutingCase("Не могу перестать сравнивать себя с другими", "reflection"),
    RoutingCase("Кажется, я сам себя саботирую", "reflection"),
    RoutingCase("Откуда у меня такой страх перемен?", "reflection"),
    RoutingCase("Почему меня тянет к людям, которые держат дистанцию?", "reflection"),
    RoutingCase("Я опять попал в ту же историю, почему?", "reflection"),
    RoutingCase("Почему я выгораю в каждом новом проекте?", "reflection"),
    RoutingCase("Внутри будто спорят две части меня", "reflection"),
    RoutingCase("Почему мне сложно просить о помощи?", "reflection"),
    RoutingCase("Постоянно хочу всё контролировать и устаю", "reflection"),
    RoutingCase("Не понимаю, чего именно боюсь в этой ситуации", "reflection"),
    RoutingCase("Стоит ли переезжать в другой город?", "decision"),
    RoutingCase("Выбрать стабильность или рискнуть новым вариантом?", "decision"),
    RoutingCase("Есть два пути и оба пугают, что выбрать?", "decision"),
    RoutingCase("Стоит ли соглашаться на поездку?", "decision"),
    RoutingCase("Не могу принять решение по важному вопросу", "decision"),
    RoutingCase("Какой вариант мне сейчас лучше выбрать?", "decision"),
    RoutingCase("Остаться здесь или начать всё заново?", "decision"),
    RoutingCase("Стоит ли делать первый шаг в новом деле?", "decision"),
    RoutingCase("Покупать сейчас или подождать?", "decision"),
    RoutingCase("Какое решение даст мне больше пространства?", "decision"),
    RoutingCase("Что мне сейчас важно увидеть?", "general"),
    RoutingCase("Как пройдёт ближайшее время?", "general"),
    RoutingCase("На что обратить внимание на этой неделе?", "general"),
    RoutingCase("Что сейчас происходит вокруг меня?", "general"),
    RoutingCase("Хочу понять общий вектор ситуации", "general"),
    RoutingCase("Есть ощущение, что что-то меняется", "general"),
    RoutingCase("Что я пока не замечаю?", "general"),
    RoutingCase("Какая тема сейчас для меня главная?", "general"),
    RoutingCase("Что может оказаться неожиданным в ближайшее время?", "general"),
    RoutingCase("Посмотри на мою ситуацию в целом", "general"),
    RoutingCase("Я влюблена в коллегу и не понимаю, что делать с работой", "clarify"),
    RoutingCase("Начальник мне нравится, и я не понимаю его отношение", "clarify"),
    RoutingCase("Люблю его, но почему я снова выбираю такую дистанцию?", "clarify"),
    RoutingCase("Бывший вернулся, и я опять повторяю старый сценарий", "clarify"),
    RoutingCase("У нас отношения и совместный бизнес стали резко меняться", "clarify"),
    RoutingCase("Отношения с коллегой изменились, не понимаю это работа или личное", "clarify"),
    RoutingCase("Парень предложил работать вместе, боюсь смешать любовь и карьеру", "clarify"),
    RoutingCase("Она моя руководительница и между нами явно что-то есть", "clarify"),
    RoutingCase("Люблю человека, но понимаю, что снова себя саботирую", "clarify"),
    RoutingCase("Бывшая зовёт в общий проект, и чувства ещё не прошли", "clarify"),
)


def predict_route(question: str) -> str:
    if needs_route_clarification(question):
        return "clarify"
    choice = choose_route(question)
    if choice.flow is LOVE_ORACLE_FLOW:
        return "love"
    if choice.flow is MYSTICAL_PSYCHOLOGIST_FLOW:
        return "reflection"
    if choice.topic == "work":
        return "work"
    if choice.topic == "decision":
        return "decision"
    return "general"


def evaluate_routing(cases: tuple[RoutingCase, ...] = ROUTING_CASES) -> RoutingReport:
    mistakes: list[tuple[str, str, str]] = []
    expected = Counter(case.expected for case in cases)
    predicted: Counter[str] = Counter()
    for case in cases:
        actual = predict_route(case.question)
        predicted[actual] += 1
        if actual != case.expected:
            mistakes.append((case.question, case.expected, actual))
    correct = len(cases) - len(mistakes)
    return RoutingReport(
        total=len(cases),
        correct=correct,
        accuracy=(correct / len(cases)) if cases else 1.0,
        expected_counts=dict(expected),
        predicted_counts=dict(predicted),
        mistakes=tuple(mistakes),
    )
