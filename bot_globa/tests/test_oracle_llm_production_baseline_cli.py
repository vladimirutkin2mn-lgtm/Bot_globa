"""Budget-safety coverage for the production LLM baseline command."""

import pytest

from app.cli.oracle_llm_autoresearch import _reserved_upper_bound_usd
from app.research.oracle_llm_dataset import ORACLE_RESEARCH_CASES


def test_reserved_upper_bound_covers_every_fixed_dataset_case() -> None:
    assert len(ORACLE_RESEARCH_CASES) == 12
    assert _reserved_upper_bound_usd(25_000) == 0.3


@pytest.mark.parametrize("value", [0, -1])
def test_reserved_upper_bound_refuses_unconfigured_reservation(value: int) -> None:
    with pytest.raises(ValueError, match="must be positive"):
        _reserved_upper_bound_usd(value)
