"""Offline routing evaluation for the rules behind «Расскажите Numa».

The corpus is synthetic and deliberately lives outside production routing. Rules stay cheap and
explainable; a model classifier is justified only if this benchmark shows a material gap.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.bot.personal_oracle_handlers import choose_route, needs_route_clarification

ROUTING_DATASET_VERSION = "personal-oracle-routing-v1"


@dataclass(frozen=True, slots=True)
class RoutingCase:
    case_id: str
    question: str
    expected_persona: str
    expected_topic: str | None = None
    expected_clarification: bool = False


ROUTING_CASES: tuple[RoutingCase, ...] = (
    RoutingCase(
        "love-feelings",
        "Он ко мне что-то чувствует или я себе придумала?",
        "love_oracle",
        "love",
    ),
    RoutingCase(
        "love-distance",
        "Антон стал писать раз в два дня. Что сейчас между нами?",
        "love_oracle",
        "communication",
    ),
    RoutingCase(
        "love-reconnect",
        "Стоит ли первой написать бывшему после месяца тишины?",
        "love_oracle",
        "communication",
    ),
    RoutingCase(
        "love-future",
        "Есть ли у наших отношений будущее?",
        "love_oracle",
        "love",
    ),
    RoutingCase(
        "love-jealousy",
        "Я ревную его, хотя повода почти нет. Что происходит между нами?",
        "love_oracle",
        "love",
        True,
    ),
    RoutingCase(
        "reflection-repeat",
        "Почему я снова выбираю эмоционально недоступных людей?",
        "mystical_psychologist",
        "repeating_pattern",
    ),
    RoutingCase(
        "reflection-delay",
        "Почему я каждый раз откладываю запуск, когда всё почти готово?",
        "mystical_psychologist",
        "repeating_pattern",
    ),
    RoutingCase(
        "reflection-fear",
        "Боюсь говорить о своих идеях и потом злюсь на себя. Почему?",
        "mystical_psychologist",
        "self_reflection",
    ),
    RoutingCase(
        "reflection-loop",
        "У меня опять всё идёт по одному сценарию: сначала загораюсь, потом бросаю",
        "mystical_psychologist",
        "repeating_pattern",
    ),
    RoutingCase(
        "reflection-choice-loop",
        "Почему я не могу перестать сравнивать варианты и выбрать?",
        "mystical_psychologist",
        "self_reflection",
    ),
    RoutingCase(
        "work-offer",
        "Мне предлагают новую работу. Принимать оффер?",
        "tarot_reader",
        "work",
    ),
    RoutingCase(
        "work-boss",
        "Как лучше действовать в конфликте с руководителем?",
        "tarot_reader",
        "work",
    ),
    RoutingCase(
        "work-project",
        "Стоит ли запускать новый проект сейчас?",
        "tarot_reader",
        "work",
    ),
    RoutingCase(
        "money-choice",
        "Стоит ли сейчас тратить деньги на обучение или подождать?",
        "tarot_reader",
        "work",
    ),
    RoutingCase(
        "decision-city",
        "Переезжать в другой город или остаться здесь?",
        "tarot_reader",
        "decision",
    ),
    RoutingCase(
        "decision-two-options",
        "Не могу выбрать между двумя вариантами. Что лучше?",
        "tarot_reader",
        "decision",
    ),
    RoutingCase(
        "decision-trip",
        "Стоит ли соглашаться на эту поездку?",
        "tarot_reader",
        "decision",
    ),
    RoutingCase(
        "general-week",
        "На что мне обратить внимание на этой неделе?",
        "tarot_reader",
        "general_forecast",
    ),
    RoutingCase(
        "general-situation",
        "Что я сейчас не замечаю в своей ситуации?",
        "tarot_reader",
        "general_forecast",
    ),
    RoutingCase(
        "general-next",
        "Что для меня сейчас самое важное?",
        "tarot_reader",
        "general_forecast",
    ),
    RoutingCase(
        "ambiguous-relationship",
        "Хочу понять, что происходит в отношениях",
        "tarot_reader",
        None,
        True,
    ),
    RoutingCase(
        "mixed-love-work",
        "Я влюбилась в коллегу и не понимаю, как это повлияет на работу",
        "love_oracle",
        None,
        True,
    ),
    RoutingCase(
        "mixed-love-pattern",
        "Почему меня снова тянет к человеку, который почти не отвечает?",
        "love_oracle",
        None,
        True,
    ),
    RoutingCase(
        "relationship-work-change",
        "После смены работы отношения дома сильно изменились",
        "tarot_reader",
        None,
        True,
    ),
    RoutingCase(
        "work-not-love",
        "Отношения с начальником ухудшились после нового проекта",
        "tarot_reader",
        "work",
    ),
    RoutingCase(
        "decision-love",
        "Стоит ли заканчивать эти отношения?",
        "love_oracle",
        "love",
    ),
    RoutingCase(
        "communication-love",
        "Ответить ему сейчас или выдержать паузу?",
        "love_oracle",
        "communication",
    ),
    RoutingCase(
        "reflection-burnout",
        "Почему я довожу себя до выгорания перед каждым дедлайном?",
        "mystical_psychologist",
        "self_reflection",
    ),
    RoutingCase(
        "reflection-anxiety",
        "Я тревожусь перед каждой важной встречей. Что за этим стоит?",
        "mystical_psychologist",
        "self_reflection",
    ),
    RoutingCase(
        "work-money",
        "Менять ли работу ради большей зарплаты?",
        "tarot_reader",
        "work",
    ),
    RoutingCase(
        "work-business",
        "Стоит ли закрывать бизнес и идти в найм?",
        "tarot_reader",
        "work",
    ),
    RoutingCase(
        "love-dry-replies",
        "Он отвечает сухо, но сам иногда пишет. Как читать эти сигналы?",
        "love_oracle",
        "communication",
    ),
    RoutingCase(
        "love-together",
        "Будем ли мы вместе или всё уже закончилось?",
        "love_oracle",
        "love",
    ),
    RoutingCase(
        "reflection-self-sabotage",
        "Похоже, я сама саботирую хорошие возможности. Почему?",
        "mystical_psychologist",
        "self_reflection",
    ),
    RoutingCase(
        "general-unclear",
        "Помоги посмотреть на ситуацию со стороны",
        "tarot_reader",
        "general_forecast",
    ),
    RoutingCase(
        "decision-course",
        "Выбрать первый курс или второй?",
        "tarot_reader",
        "decision",
    ),
)


@dataclass(frozen=True, slots=True)
class RoutingEvaluation:
    dataset_version: str
    case_count: int
    persona_accuracy: float
    topic_accuracy: float
    clarification_accuracy: float
    exact_accuracy: float
    failed_case_ids: tuple[str, ...]

    @property
    def classifier_review_recommended(self) -> bool:
        """Escalate only after rules demonstrate a material quality gap."""
        return self.exact_accuracy < 0.90 or self.clarification_accuracy < 0.90


def evaluate_routing(cases: tuple[RoutingCase, ...] = ROUTING_CASES) -> RoutingEvaluation:
    if not cases:
        raise ValueError("routing evaluation requires at least one case")
    persona_ok = 0
    topic_ok = 0
    clarification_ok = 0
    exact_ok = 0
    failures: list[str] = []
    for case in cases:
        choice = choose_route(case.question)
        clarification = needs_route_clarification(case.question)
        actual_persona = choice.flow.persona_code
        matches_persona = actual_persona == case.expected_persona
        matches_topic = case.expected_topic is None or choice.topic == case.expected_topic
        matches_clarification = clarification == case.expected_clarification
        persona_ok += matches_persona
        topic_ok += matches_topic
        clarification_ok += matches_clarification
        if matches_persona and matches_topic and matches_clarification:
            exact_ok += 1
        else:
            failures.append(case.case_id)
    total = len(cases)
    return RoutingEvaluation(
        dataset_version=ROUTING_DATASET_VERSION,
        case_count=total,
        persona_accuracy=persona_ok / total,
        topic_accuracy=topic_ok / total,
        clarification_accuracy=clarification_ok / total,
        exact_accuracy=exact_ok / total,
        failed_case_ids=tuple(failures),
    )
