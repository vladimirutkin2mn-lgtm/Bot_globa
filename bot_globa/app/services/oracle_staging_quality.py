"""Version snapshot used by the ORA-603 staging quality gate."""

from dataclasses import dataclass

from app.domain.horoscope import (
    ASTROLOGY_READING_SCHEMA_VERSION,
    HOROSCOPE_FACTS_VERSION,
    HOROSCOPE_RENDERER_VERSION,
)
from app.domain.natal_chart import (
    NATAL_CHART_ENGINE_VERSION,
    NATAL_CHART_HOUSE_SYSTEM,
    NATAL_CHART_SCHEMA_VERSION,
)
from app.domain.persona import enabled_persona_definitions

ORACLE_STAGING_GATE_VERSION = "oracle-staging-quality-v1"


@dataclass(frozen=True, slots=True)
class PersonaDeploymentCoordinate:
    """Immutable persona versions that must agree with the staged application."""

    code: str
    engine_version: str
    prompt_version: str
    schema_version: str

    def payload(self) -> dict[str, str]:
        return {
            "code": self.code,
            "engine_version": self.engine_version,
            "prompt_version": self.prompt_version,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class OracleDeploymentSnapshot:
    """Content-free release coordinates for one staged oracle deployment."""

    gate_version: str
    llm_provider: str
    llm_model: str
    personas: tuple[PersonaDeploymentCoordinate, ...]
    natal_chart_schema_version: str
    natal_chart_engine_version: str
    natal_chart_house_system: str
    horoscope_facts_version: str
    horoscope_schema_version: str
    horoscope_renderer_version: str

    def payload(self) -> dict[str, object]:
        return {
            "gate_version": self.gate_version,
            "llm_provider": self.llm_provider,
            "llm_model": self.llm_model,
            "personas": [persona.payload() for persona in self.personas],
            "natal_chart": {
                "schema_version": self.natal_chart_schema_version,
                "engine_version": self.natal_chart_engine_version,
                "house_system": self.natal_chart_house_system,
            },
            "horoscope": {
                "facts_version": self.horoscope_facts_version,
                "schema_version": self.horoscope_schema_version,
                "renderer_version": self.horoscope_renderer_version,
            },
        }


def build_oracle_deployment_snapshot(
    *,
    llm_provider: str,
    llm_model: str,
) -> OracleDeploymentSnapshot:
    """Capture version coordinates without user data or generated content."""

    provider = llm_provider.strip()
    model = llm_model.strip()
    if not provider:
        raise ValueError("oracle staging LLM provider cannot be empty")
    if not model:
        raise ValueError("oracle staging LLM model cannot be empty")

    personas = tuple(
        PersonaDeploymentCoordinate(
            code=persona.code,
            engine_version=persona.engine_version,
            prompt_version=persona.prompt_version,
            schema_version=persona.schema_version,
        )
        for persona in enabled_persona_definitions()
    )
    return OracleDeploymentSnapshot(
        gate_version=ORACLE_STAGING_GATE_VERSION,
        llm_provider=provider,
        llm_model=model,
        personas=personas,
        natal_chart_schema_version=NATAL_CHART_SCHEMA_VERSION,
        natal_chart_engine_version=NATAL_CHART_ENGINE_VERSION,
        natal_chart_house_system=NATAL_CHART_HOUSE_SYSTEM,
        horoscope_facts_version=HOROSCOPE_FACTS_VERSION,
        horoscope_schema_version=ASTROLOGY_READING_SCHEMA_VERSION,
        horoscope_renderer_version=HOROSCOPE_RENDERER_VERSION,
    )


def deployment_mismatches(
    actual: OracleDeploymentSnapshot,
    expected: OracleDeploymentSnapshot,
) -> tuple[str, ...]:
    """Return stable mismatch paths without leaking prompts, outputs or private inputs."""

    issues: list[str] = []
    if actual.gate_version != expected.gate_version:
        issues.append("gate_version")
    if actual.llm_provider != expected.llm_provider:
        issues.append("llm_provider")
    if actual.llm_model != expected.llm_model:
        issues.append("llm_model")
    if actual.personas != expected.personas:
        issues.append("personas")
    if actual.natal_chart_schema_version != expected.natal_chart_schema_version:
        issues.append("natal_chart.schema_version")
    if actual.natal_chart_engine_version != expected.natal_chart_engine_version:
        issues.append("natal_chart.engine_version")
    if actual.natal_chart_house_system != expected.natal_chart_house_system:
        issues.append("natal_chart.house_system")
    if actual.horoscope_facts_version != expected.horoscope_facts_version:
        issues.append("horoscope.facts_version")
    if actual.horoscope_schema_version != expected.horoscope_schema_version:
        issues.append("horoscope.schema_version")
    if actual.horoscope_renderer_version != expected.horoscope_renderer_version:
        issues.append("horoscope.renderer_version")
    return tuple(issues)
