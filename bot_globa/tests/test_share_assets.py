from datetime import date
from io import BytesIO

from PIL import Image, ImageDraw

from app.api.share_assets import (
    DAILY_SHARE_CARD_PATH,
    DAILY_SHARE_CARD_ROUTE,
    DAILY_SHARE_DYNAMIC_LEGACY_ROUTE,
    DAILY_SHARE_DYNAMIC_ROUTE,
    numa_daily_share_card_v5,
)
from app.services.daily_horoscope_editorial import build_editorial_daily_horoscope
from app.services.daily_share_card import (
    CARD_SIZE,
    _display_theme,
    _fit_wrapped_text,
    daily_share_card_theme,
    load_daily_share_font,
    render_daily_share_card,
)


def test_daily_share_card_asset_is_packaged() -> None:
    assert DAILY_SHARE_CARD_ROUTE == "/public/share/numa-daily-v1.jpg"
    assert DAILY_SHARE_CARD_PATH.name == "E-02.jpg"
    assert DAILY_SHARE_CARD_PATH.is_file()
    # Guard against accidentally publishing a cropped thumbnail/fragment as the share card.
    assert DAILY_SHARE_CARD_PATH.stat().st_size > 100_000


def test_dynamic_daily_share_route_is_cache_versioned() -> None:
    assert DAILY_SHARE_DYNAMIC_LEGACY_ROUTE == "/public/share/numa-daily-v3/{forecast_date}.jpg"
    assert DAILY_SHARE_DYNAMIC_ROUTE == "/public/share/numa-daily-v5/{forecast_date}.jpg"


def test_daily_share_fonts_have_real_cyrillic_glyphs() -> None:
    sans = load_daily_share_font(40)
    serif = load_daily_share_font(40, serif=True)

    sans_family, _sans_style = sans.getname()
    serif_family, _serif_style = serif.getname()
    assert sans_family == "DejaVu Sans"
    assert serif_family == "DejaVu Serif"
    # Missing glyphs collapse to the same replacement box. Real Cyrillic glyphs have
    # distinct advances, which protects us from shipping square placeholders again.
    assert serif.getlength("Т") != serif.getlength("Ш")
    assert serif.getlength("я") != serif.getlength("\U0010ffff")


def test_daily_share_theme_presentation_capitalizes_without_rewriting_source() -> None:
    assert _display_theme("лучше убрать препятствие") == "Лучше убрать препятствие"
    assert _display_theme("  Уже готово  ") == "Уже готово"


def test_long_daily_share_theme_fits_within_four_lines() -> None:
    image = Image.new("RGB", CARD_SIZE)
    draw = ImageDraw.Draw(image)
    _font, lines = _fit_wrapped_text(
        draw,
        (
            "Лучше выбрать одно действительно важное препятствие и спокойно разобраться "
            "с ним, чем пытаться одновременно изменить всё вокруг себя"
        ),
        max_width=936,
        max_lines=4,
    )

    assert len(lines) <= 4
    assert len(lines[-1].split()) > 1


def test_dynamic_daily_share_card_is_a_deterministic_full_size_jpeg() -> None:
    forecast_date = date(2026, 9, 15)

    first = render_daily_share_card(forecast_date)
    second = render_daily_share_card(forecast_date)

    assert first == second
    assert len(first) > 50_000
    with Image.open(BytesIO(first)) as image:
        assert image.format == "JPEG"
        assert image.size == CARD_SIZE


def test_dynamic_daily_share_card_changes_with_date() -> None:
    first = render_daily_share_card(date(2026, 9, 15))
    second = render_daily_share_card(date(2026, 9, 16))

    assert first != second


def test_dynamic_card_uses_exact_daily_horoscope_theme() -> None:
    forecast_date = date(2026, 9, 15)

    assert (
        daily_share_card_theme(forecast_date)
        == build_editorial_daily_horoscope(forecast_date).theme
    )


def test_dynamic_daily_share_endpoint_is_immutable_and_public() -> None:
    response = numa_daily_share_card_v5(date(2026, 9, 15))

    assert response.media_type == "image/jpeg"
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert len(response.body) > 50_000
