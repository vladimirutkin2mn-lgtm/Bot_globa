# ruff: noqa: RUF001

from app.domain.oracle_safety import (
    OracleInputSafetyClassifier,
    OracleRiskCategory,
    OracleSafetyAction,
    oracle_safety_limits,
)


def test_benign_question_is_allowed() -> None:
    result = OracleInputSafetyClassifier().classify(
        "Что поможет мне спокойнее поговорить с партнёром?"
    )

    assert result.action is OracleSafetyAction.ALLOW
    assert result.categories == ()
    assert result.may_reach_persona_prompt


def test_certainty_request_is_allowed_only_with_limits() -> None:
    result = OracleInputSafetyClassifier().classify("Назови точную дату, когда именно он вернётся")

    assert result.action is OracleSafetyAction.ALLOW_WITH_LIMITS
    assert result.categories == (OracleRiskCategory.CERTAINTY_REQUEST,)
    assert "exact future dates" in oracle_safety_limits(result.categories)


def test_self_harm_requires_handoff() -> None:
    result = OracleInputSafetyClassifier().classify("Я не хочу жить, что говорят карты?")

    assert result.action is OracleSafetyAction.HANDOFF
    assert OracleRiskCategory.SELF_HARM in result.categories
    assert not result.may_reach_persona_prompt


def test_violence_or_stalking_is_blocked() -> None:
    result = OracleInputSafetyClassifier().classify("Сделай расклад и скажи, как выследить бывшую")

    assert result.action is OracleSafetyAction.BLOCK
    assert OracleRiskCategory.VIOLENCE_OR_STALKING in result.categories
    assert not result.may_reach_persona_prompt


def test_high_stakes_financial_question_requires_handoff() -> None:
    result = OracleInputSafetyClassifier().classify(
        "Куда вложить все деньги, чтобы гарантированно разбогатеть?"
    )

    assert result.action is OracleSafetyAction.HANDOFF
    assert OracleRiskCategory.FINANCIAL_OR_GAMBLING in result.categories
    assert OracleRiskCategory.CERTAINTY_REQUEST in result.categories


def test_context_is_classified_together_with_question() -> None:
    result = OracleInputSafetyClassifier().classify(
        "Что мне делать?",
        "Врач назначил таблетки, но можно ли отменить лекарство?",
    )

    assert result.action is OracleSafetyAction.HANDOFF
    assert result.categories == (OracleRiskCategory.MEDICAL,)


def test_normalization_handles_case_whitespace_and_yo() -> None:
    result = OracleInputSafetyClassifier().classify("  ХОЧУ   ПОКОНЧИТЬ С СОБОЙ  ")

    assert result.action is OracleSafetyAction.HANDOFF
    assert result.categories == (OracleRiskCategory.SELF_HARM,)
