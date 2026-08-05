"""Idempotent persistence synchronization for versioned persona definitions."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.reading_models import Persona
from app.domain.persona import PersonaDefinition, enabled_persona_definitions


@dataclass(frozen=True, slots=True)
class PersonaSyncResult:
    created: int
    updated: int
    unchanged: int


class PersonaRegistryService:
    """Synchronize only managed MVP personas while preserving unknown records."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def sync_mvp_personas(self) -> PersonaSyncResult:
        definitions = enabled_persona_definitions()
        managed_codes = tuple(definition.code for definition in definitions)
        async with self._sessions.begin() as session:
            existing = {
                persona.code: persona
                for persona in await session.scalars(
                    select(Persona).where(Persona.code.in_(managed_codes)).with_for_update()
                )
            }
            created = 0
            updated = 0
            unchanged = 0
            for definition in definitions:
                persona = existing.get(definition.code)
                if persona is None:
                    session.add(self._new_persona(definition))
                    created += 1
                    continue
                if self._apply_definition(persona, definition):
                    updated += 1
                else:
                    unchanged += 1
            await session.flush()
        return PersonaSyncResult(created=created, updated=updated, unchanged=unchanged)

    @staticmethod
    def _new_persona(definition: PersonaDefinition) -> Persona:
        return Persona(
            code=definition.code,
            display_name=definition.display_name,
            prompt_version=definition.prompt_version,
            schema_version=definition.schema_version,
            enabled=True,
        )

    @staticmethod
    def _apply_definition(persona: Persona, definition: PersonaDefinition) -> bool:
        desired = {
            "display_name": definition.display_name,
            "prompt_version": definition.prompt_version,
            "schema_version": definition.schema_version,
            "enabled": True,
        }
        changed = any(getattr(persona, field) != value for field, value in desired.items())
        if changed:
            for field, value in desired.items():
                setattr(persona, field, value)
        return changed
