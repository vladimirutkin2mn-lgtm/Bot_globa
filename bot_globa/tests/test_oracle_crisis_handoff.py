"""Localized crisis handoff contracts without private payload handling."""

from app.domain.oracle_safety import OracleRiskCategory, OracleSafetyAction
from app.services.oracle_crisis_handoff import (
    HandoffResourceKind,
    OracleCrisisHandoffService,
)


def test_russian_self_harm_handoff_stops_mystical_flow() -> None:
    service = OracleCrisisHandoffService()
    handoff = service.build(
        OracleSafetyAction.HANDOFF,
        (OracleRiskCategory.SELF_HARM,),
        locale="ru-RU",
    )
    text = service.render_text(handoff)

    assert handoff.locale == "ru"
    assert handoff.mystical_flow_stopped
    assert "не буду продолжать мистический разбор" in text
    assert "местную экстренную службу" in text
    assert service.crisis_directory_url in text
    assert {resource.kind for resource in handoff.resources} == {
        HandoffResourceKind.LOCAL_EMERGENCY_SERVICES,
        HandoffResourceKind.TRUSTED_PERSON,
        HandoffResourceKind.CRISIS_DIRECTORY,
    }


def test_english_self_harm_handoff_has_neutral_resources() -> None:
    service = OracleCrisisHandoffService()
    handoff = service.build(
        OracleSafetyAction.HANDOFF,
        (OracleRiskCategory.SELF_HARM,),
        locale="en-US",
    )
    text = service.render_text(handoff)

    assert handoff.locale == "en"
    assert "will not continue the mystical reading" in text
    assert "local emergency services" in text
    assert "guarantee" not in text.casefold()


def test_unknown_locale_falls_back_to_english() -> None:
    handoff = OracleCrisisHandoffService().build(
        OracleSafetyAction.HANDOFF,
        (OracleRiskCategory.SELF_HARM,),
        locale="de-DE",
    )

    assert handoff.locale == "en"


def test_violence_handoff_does_not_offer_another_reading() -> None:
    service = OracleCrisisHandoffService()
    handoff = service.build(
        OracleSafetyAction.BLOCK,
        (OracleRiskCategory.VIOLENCE_OR_STALKING,),
        locale="ru",
    )
    text = service.render_text(handoff)

    assert "причинить вред" in text
    assert "новый расклад" not in text.casefold()
    assert handoff.action is OracleSafetyAction.BLOCK


def test_high_stakes_handoff_selects_only_relevant_professionals() -> None:
    service = OracleCrisisHandoffService()
    handoff = service.build(
        OracleSafetyAction.HANDOFF,
        (
            OracleRiskCategory.MEDICAL,
            OracleRiskCategory.LEGAL,
            OracleRiskCategory.FINANCIAL_OR_GAMBLING,
        ),
        locale="ru",
    )

    assert {resource.kind for resource in handoff.resources} == {
        HandoffResourceKind.MEDICAL_PROFESSIONAL,
        HandoffResourceKind.LEGAL_PROFESSIONAL,
        HandoffResourceKind.FINANCIAL_PROFESSIONAL,
    }
    assert all(resource.url is None for resource in handoff.resources)


def test_handoff_api_and_error_metadata_never_accept_private_text() -> None:
    service = OracleCrisisHandoffService()
    marker = "private-question-must-not-leak"
    handoff = service.build(
        OracleSafetyAction.HANDOFF,
        (OracleRiskCategory.MEDICAL,),
        locale="en",
    )

    assert marker not in repr(handoff)
    assert marker not in service.render_text(handoff)
