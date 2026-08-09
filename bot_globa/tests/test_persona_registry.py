"""Unit coverage for the versioned MVP persona registry."""

import pytest

from app.domain.persona import (
    MVP_PERSONAS,
    PersonaDefinition,
    PersonaEngine,
    PersonaInput,
    UnknownBirthTimePolicy,
    persona_definition,
)


def test_registry_contains_exactly_four_distinct_mvp_personas() -> None:
    assert tuple(persona.code for persona in MVP_PERSONAS) == (
        "tarot_reader",
        "love_oracle",
        "mystical_psychologist",
        "astrologer",
    )
    assert len({persona.code for persona in MVP_PERSONAS}) == 4
    assert persona_definition("tarot_reader") is MVP_PERSONAS[0]
    assert persona_definition("unknown") is None


def test_astrologer_requires_calculation_and_never_invents_unknown_birth_time_data() -> None:
    astrologer = persona_definition("astrologer")
    assert astrologer is not None
    assert astrologer.engine is PersonaEngine.ASTROLOGY
    assert astrologer.requires_calculation_engine is True
    assert PersonaInput.BIRTH_DATE in astrologer.required_inputs
    assert PersonaInput.BIRTH_PLACE in astrologer.required_inputs
    assert PersonaInput.BIRTH_TIME in astrologer.optional_inputs
    assert astrologer.unknown_birth_time_policy is UnknownBirthTimePolicy.OMIT_HOUSES_AND_ASCENDANT


def test_only_astrologer_requires_calculation_engine() -> None:
    requiring_calculation = [
        persona.code for persona in MVP_PERSONAS if persona.requires_calculation_engine
    ]
    assert requiring_calculation == ["astrologer"]


def test_invalid_astrology_definition_is_rejected() -> None:
    with pytest.raises(ValueError, match="calculation engine"):
        PersonaDefinition(
            code="invalid_astrologer",
            display_name="Invalid",
            description="Invalid fixture",
            engine=PersonaEngine.ASTROLOGY,
            supported_topics=("natal_profile",),
            required_inputs=(
                PersonaInput.QUESTION,
                PersonaInput.BIRTH_DATE,
                PersonaInput.BIRTH_PLACE,
            ),
            optional_inputs=(PersonaInput.BIRTH_TIME,),
            engine_version="astrology-v1",
            prompt_version="invalid-v1",
            schema_version="result-v1",
            requires_calculation_engine=False,
            unknown_birth_time_policy=UnknownBirthTimePolicy.OMIT_HOUSES_AND_ASCENDANT,
        )
