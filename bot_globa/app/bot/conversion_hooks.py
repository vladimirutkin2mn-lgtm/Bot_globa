"""Grounded paywall hooks built only from already validated oracle output.

The conversion layer may create curiosity, but it must never invent a secret, danger,
third-party feeling or future event merely to increase purchase intent. It receives only
validated scenarios plus application-owned copy and deliberately withholds conditions
that are already part of the paid result.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from app.bot.typography import quote


class HookScenario(Protocol):
    """The read-only scenario surface shared by Reading and Astrology results."""

    @property
    def scenario(self) -> str: ...

    @property
    def conditions(self) -> Sequence[str]: ...


@dataclass(frozen=True, slots=True)
class ConversionHookCopy:
    """Persona/spread voice around grounded scenario data."""

    branch_title: str
    single_title: str
    scenario_prefix: str
    hidden_conditions_line: str
    alternative_line: str
    unlock_title: str
    unlock_lines: tuple[str, ...]


DEFAULT_READING_HOOK = ConversionHookCopy(
    branch_title="Здесь есть развилка, которую короткий разбор не раскрывает до конца.",
    single_title="Здесь есть одна линия, но важнее понять, при каких условиях она меняется.",
    scenario_prefix="Один из возможных сценариев:",
    hidden_conditions_line=(
        "В короткой версии я не раскрываю условия, которые усиливают или ослабляют эту линию."
    ),
    alternative_line="Есть и другая траектория — она включается при других условиях.",
    unlock_title="После открытия вы увидите:",
    unlock_lines=(
        "что именно поддерживает этот сценарий",
        "что может переключить ситуацию на другую траекторию",
        "какой следующий шаг остаётся в вашей зоне влияния",
    ),
)


def render_grounded_hook(
    scenarios: Sequence[HookScenario],
    copy: ConversionHookCopy,
) -> str:
    """Create an open loop without fabricating information or fear.

    We can safely reveal the existence and wording of one validated scenario while keeping
    its already-generated conditions behind the paid boundary. If the result contains a
    second scenario, the hook may truthfully say that an alternative trajectory exists.
    """

    if not scenarios:
        raise ValueError("conversion hook requires at least one validated scenario")

    first = scenarios[0]
    title = copy.branch_title if len(scenarios) > 1 else copy.single_title
    lines = [f"<b>{quote(title)}</b>", f"{quote(copy.scenario_prefix)} {quote(first.scenario)}"]
    if first.conditions:
        lines.append(quote(copy.hidden_conditions_line))
    if len(scenarios) > 1:
        lines.append(quote(copy.alternative_line))
    lines.append(f"\n<b>{quote(copy.unlock_title)}</b>")
    lines.extend(f"• {quote(line)}" for line in copy.unlock_lines)
    return "\n".join(lines)
