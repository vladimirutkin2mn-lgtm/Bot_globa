"""Regression coverage for keeping generic legal-style disclaimers out of reading UI."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
READING_RENDERER = ROOT / "app" / "bot" / "reading_renderer.py"
HOROSCOPE_RENDERER = ROOT / "app" / "bot" / "horoscope_renderer.py"


def test_generic_reading_disclaimer_is_not_part_of_renderer_copy() -> None:
    source = READING_RENDERER.read_text(encoding="utf-8")

    assert "Это развлекательная практика для рефлексии" not in source
    assert "а не достоверное предсказание или профессиональная консультация" not in source
    assert "DISCLAIMER" not in source


def test_generic_astrology_disclaimer_is_not_part_of_renderer_copy() -> None:
    source = HOROSCOPE_RENDERER.read_text(encoding="utf-8")

    assert "Астрология здесь — развлекательный инструмент" not in source
    assert "а не достоверное предсказание или профессиональная консультация" not in source
    assert "DISCLAIMER" not in source


def test_astrology_technical_limitations_remain_visible() -> None:
    source = HOROSCOPE_RENDERER.read_text(encoding="utf-8")

    assert "Время рождения неизвестно: дома и асцендент не рассчитывались." in source
    assert "Прогноз использует расчётные снимки начала, середины и конца периода." in source
