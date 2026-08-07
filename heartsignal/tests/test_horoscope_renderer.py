"""Deterministic renderer tests for fact-bound Horoscope results."""

import json

import pytest

from app.domain.horoscope import AstrologyReadingResult
from app.services.horoscope_renderer import HoroscopeRenderError, HoroscopeRenderer
from tests.horoscope_helpers import sample_fact_bundle, valid_horoscope_payload


def test_renderer_adds_exact_fact_labels_without_model_authored_positions() -> None:
    bundle = sample_fact_bundle()
    result = AstrologyReadingResult.model_validate_json(json.dumps(valid_horoscope_payload(bundle)))

    rendered = HoroscopeRenderer().render(result, bundle)

    assert rendered.facts_digest == bundle.digest()
    assert "Асцендент" in rendered.text
    assert "17.000°" in rendered.text
    assert result.interpretations[0].text in rendered.text
    assert "1991-04-17" not in rendered.text


def test_renderer_refuses_result_bound_to_another_fact_bundle() -> None:
    first = sample_fact_bundle()
    second = sample_fact_bundle(exact_time=False)
    result = AstrologyReadingResult.model_validate_json(json.dumps(valid_horoscope_payload(first)))

    with pytest.raises(HoroscopeRenderError, match="digest"):
        HoroscopeRenderer().render(result, second)


def test_share_card_never_expands_chart_coordinates() -> None:
    bundle = sample_fact_bundle()
    result = AstrologyReadingResult.model_validate_json(json.dumps(valid_horoscope_payload(bundle)))

    share = HoroscopeRenderer.share_text(result)

    assert share == "A reflective pattern\nPause, observe, and choose one reversible next step."
    assert "°" not in share
    assert "Асцендент" not in share
