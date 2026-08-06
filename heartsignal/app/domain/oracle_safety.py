"""Deterministic input-risk classification before oracle prompts reach an LLM."""
# ruff: noqa: RUF001

import re
from dataclasses import dataclass
from enum import StrEnum


class OracleRiskCategory(StrEnum):
    SELF_HARM = "self_harm"
    VIOLENCE_OR_STALKING = "violence_or_stalking"
    MEDICAL = "medical"
    LEGAL = "legal"
    FINANCIAL_OR_GAMBLING = "financial_or_gambling"
    CERTAINTY_REQUEST = "certainty_request"


class OracleSafetyAction(StrEnum):
    ALLOW = "allow"
    ALLOW_WITH_LIMITS = "allow_with_limits"
    HANDOFF = "handoff"
    BLOCK = "block"


@dataclass(frozen=True, slots=True)
class OracleInputSafetyResult:
    action: OracleSafetyAction
    categories: tuple[OracleRiskCategory, ...] = ()

    @property
    def may_reach_persona_prompt(self) -> bool:
        return self.action in {
            OracleSafetyAction.ALLOW,
            OracleSafetyAction.ALLOW_WITH_LIMITS,
        }


class OracleInputSafetyClassifier:
    """Conservative lexical gate with no network or model dependency."""

    _SELF_HARM = (
        "хочу умереть",
        "хочу покончить с собой",
        "убить себя",
        "не хочу жить",
        "суицид",
        "suicide",
        "kill myself",
        "end my life",
    )
    _VIOLENCE = (
        "как убить",
        "как отомстить",
        "как причинить вред",
        "как избить",
        "как выследить",
        "как следить за",
        "как преследовать",
        "где он сейчас без его ведома",
        "where are they without consent",
        "how to stalk",
        "how to hurt",
        "how to kill",
    )
    _MEDICAL = (
        "диагноз",
        "беременна ли",
        "есть ли у меня рак",
        "какая у меня болезнь",
        "можно ли отменить лекарство",
        "надо ли принимать лекарство",
        "medical diagnosis",
        "am i pregnant",
        "stop taking medication",
    )
    _LEGAL = (
        "юридический совет",
        "как выиграть суд",
        "что сказать в суде",
        "как скрыться от полиции",
        "как избежать наказания",
        "legal advice",
        "win the court case",
        "avoid the police",
    )
    _FINANCIAL = (
        "куда вложить все деньги",
        "брать ли кредит",
        "поставить все деньги",
        "какую ставку сделать",
        "выиграю ли в казино",
        "купить ли эту акцию",
        "invest all my money",
        "should i take a loan",
        "bet all my money",
        "which stock should i buy",
    )
    _CERTAINTY = (
        "точно ли",
        "гарантированно",
        "назови точную дату",
        "когда именно",
        "что он точно думает",
        "что она точно чувствует",
        "will definitely",
        "exact date",
        "guarantee that",
        "what are they thinking exactly",
    )

    def classify(self, question: str, context: str | None = None) -> OracleInputSafetyResult:
        text = self._normalize(" ".join(part for part in (question, context) if part))
        categories: list[OracleRiskCategory] = []
        if self._contains(text, self._SELF_HARM):
            categories.append(OracleRiskCategory.SELF_HARM)
        if self._contains(text, self._VIOLENCE):
            categories.append(OracleRiskCategory.VIOLENCE_OR_STALKING)
        if self._contains(text, self._MEDICAL):
            categories.append(OracleRiskCategory.MEDICAL)
        if self._contains(text, self._LEGAL):
            categories.append(OracleRiskCategory.LEGAL)
        if self._contains(text, self._FINANCIAL):
            categories.append(OracleRiskCategory.FINANCIAL_OR_GAMBLING)
        if self._contains(text, self._CERTAINTY):
            categories.append(OracleRiskCategory.CERTAINTY_REQUEST)

        unique = tuple(dict.fromkeys(categories))
        if OracleRiskCategory.SELF_HARM in unique:
            return OracleInputSafetyResult(OracleSafetyAction.HANDOFF, unique)
        if OracleRiskCategory.VIOLENCE_OR_STALKING in unique:
            return OracleInputSafetyResult(OracleSafetyAction.BLOCK, unique)
        if any(
            category in unique
            for category in (
                OracleRiskCategory.MEDICAL,
                OracleRiskCategory.LEGAL,
                OracleRiskCategory.FINANCIAL_OR_GAMBLING,
            )
        ):
            return OracleInputSafetyResult(OracleSafetyAction.HANDOFF, unique)
        if OracleRiskCategory.CERTAINTY_REQUEST in unique:
            return OracleInputSafetyResult(OracleSafetyAction.ALLOW_WITH_LIMITS, unique)
        return OracleInputSafetyResult(OracleSafetyAction.ALLOW)

    @staticmethod
    def _contains(text: str, phrases: tuple[str, ...]) -> bool:
        return any(phrase in text for phrase in phrases)

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"\s+", " ", value.casefold().replace("ё", "е")).strip()


def oracle_safety_limits(
    categories: tuple[OracleRiskCategory, ...],
) -> str:
    """Return a payload-free policy reminder for allowed limited requests."""

    if OracleRiskCategory.CERTAINTY_REQUEST not in categories:
        return ""
    return (
        "Do not claim certainty, guaranteed outcomes, exact future dates, or privileged "
        "knowledge of another person's thoughts. Frame the reading as reflection and "
        "conditional possibilities."
    )
