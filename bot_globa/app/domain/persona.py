"""Versioned MVP persona definitions independent from persistence and prompts."""

from dataclasses import dataclass
from enum import StrEnum


class PersonaEngine(StrEnum):
    SYMBOLIC = "symbolic"
    REFLECTIVE = "reflective"
    ASTROLOGY = "astrology"


class PersonaInput(StrEnum):
    QUESTION = "question"
    OPTIONAL_CONTEXT = "optional_context"
    BIRTH_DATE = "birth_date"
    BIRTH_PLACE = "birth_place"
    BIRTH_TIME = "birth_time"


class UnknownBirthTimePolicy(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    OMIT_HOUSES_AND_ASCENDANT = "omit_houses_and_ascendant"


@dataclass(frozen=True, slots=True)
class PersonaDefinition:
    code: str
    display_name: str
    description: str
    engine: PersonaEngine
    supported_topics: tuple[str, ...]
    required_inputs: tuple[PersonaInput, ...]
    optional_inputs: tuple[PersonaInput, ...]
    engine_version: str
    prompt_version: str
    schema_version: str
    requires_calculation_engine: bool = False
    unknown_birth_time_policy: UnknownBirthTimePolicy = UnknownBirthTimePolicy.NOT_APPLICABLE

    def __post_init__(self) -> None:
        if not self.code or self.code != self.code.lower() or " " in self.code:
            raise ValueError("persona code must be a non-empty lowercase identifier")
        if len(set(self.supported_topics)) != len(self.supported_topics):
            raise ValueError(f"duplicate supported topic for persona {self.code}")
        if PersonaInput.QUESTION not in self.required_inputs:
            raise ValueError(f"persona {self.code} must require a question")
        overlap = set(self.required_inputs).intersection(self.optional_inputs)
        if overlap:
            raise ValueError(f"persona {self.code} has overlapping required and optional inputs")
        if self.engine is PersonaEngine.ASTROLOGY:
            if not self.requires_calculation_engine:
                raise ValueError("astrology persona must require a calculation engine")
            if PersonaInput.BIRTH_DATE not in self.required_inputs:
                raise ValueError("astrology persona must require a birth date")
            if PersonaInput.BIRTH_PLACE not in self.required_inputs:
                raise ValueError("astrology persona must require a birth place")
            if (
                self.unknown_birth_time_policy
                is not UnknownBirthTimePolicy.OMIT_HOUSES_AND_ASCENDANT
            ):
                raise ValueError("astrology persona must define the unknown birth-time policy")
        elif self.requires_calculation_engine:
            raise ValueError("only an astrology persona may require a calculation engine")


MVP_PERSONAS: tuple[PersonaDefinition, ...] = (
    PersonaDefinition(
        code="tarot_reader",
        display_name="Таролог",
        description="Symbolic cards, possible scenarios and one practical next step.",
        engine=PersonaEngine.SYMBOLIC,
        supported_topics=("love", "work", "decision", "repeating_pattern", "general_forecast"),
        required_inputs=(PersonaInput.QUESTION,),
        optional_inputs=(PersonaInput.OPTIONAL_CONTEXT,),
        engine_version="symbolic-v1",
        prompt_version="tarot-reader-v2",
        schema_version="reading-result-v1",
    ),
    PersonaDefinition(
        code="love_oracle",
        display_name="Любовный оракул",
        description="Reflective relationship reading focused on distance, boundaries and choices.",
        engine=PersonaEngine.SYMBOLIC,
        supported_topics=("love", "communication", "boundaries", "choice", "repeating_pattern"),
        required_inputs=(PersonaInput.QUESTION,),
        optional_inputs=(PersonaInput.OPTIONAL_CONTEXT,),
        engine_version="symbolic-v1",
        prompt_version="love-oracle-v1",
        schema_version="reading-result-v1",
    ),
    PersonaDefinition(
        code="mystical_psychologist",
        display_name="Мистический психолог",
        description="Archetypes and recurring patterns without diagnosis or therapy claims.",
        engine=PersonaEngine.REFLECTIVE,
        supported_topics=("decision", "repeating_pattern", "self_reflection", "work", "love"),
        required_inputs=(PersonaInput.QUESTION,),
        optional_inputs=(PersonaInput.OPTIONAL_CONTEXT,),
        engine_version="reflective-v1",
        prompt_version="mystical-psychologist-v1",
        schema_version="reading-result-v1",
    ),
    PersonaDefinition(
        code="astrologer",
        display_name="Астролог",
        description="Horoscope interpretation based only on a structured astrology calculation.",
        engine=PersonaEngine.ASTROLOGY,
        supported_topics=("natal_profile", "week_forecast", "month_forecast", "decision", "love"),
        required_inputs=(
            PersonaInput.QUESTION,
            PersonaInput.BIRTH_DATE,
            PersonaInput.BIRTH_PLACE,
        ),
        optional_inputs=(PersonaInput.OPTIONAL_CONTEXT, PersonaInput.BIRTH_TIME),
        engine_version="astrology-calculation-v1",
        prompt_version="astrologer-v1",
        schema_version="astrology-reading-result-v1",
        requires_calculation_engine=True,
        unknown_birth_time_policy=UnknownBirthTimePolicy.OMIT_HOUSES_AND_ASCENDANT,
    ),
)

_PERSONAS_BY_CODE = {persona.code: persona for persona in MVP_PERSONAS}
if len(_PERSONAS_BY_CODE) != len(MVP_PERSONAS):
    raise RuntimeError("MVP persona codes must be unique")


def persona_definition(code: str) -> PersonaDefinition | None:
    """Return one immutable persona definition by stable code."""
    return _PERSONAS_BY_CODE.get(code)


def enabled_persona_definitions() -> tuple[PersonaDefinition, ...]:
    """Return the complete versioned MVP registry in stable order."""
    return MVP_PERSONAS
