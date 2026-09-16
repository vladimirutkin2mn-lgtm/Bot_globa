"""Render a public daily horoscope card from the same deterministic editorial snapshot."""

from datetime import date
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from app.services.daily_horoscope_editorial import build_editorial_daily_horoscope

CARD_SIZE = (1200, 1500)
DAILY_SHARE_BASE_PATH = (
    Path(__file__).resolve().parents[1] / "bot" / "assets" / "scenes" / "E-02.jpg"
)
DAILY_SHARE_FONT_PATH = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
DAILY_SHARE_BOLD_FONT_PATH = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")

_BACKGROUND_PANEL = (72, 96, 1128, 870)
_PANEL_FILL = (7, 13, 30, 205)
_PANEL_OUTLINE = (224, 190, 116, 105)
_PRIMARY_TEXT = (251, 247, 237, 255)
_MUTED_TEXT = (220, 216, 207, 255)
_ACCENT_TEXT = (236, 202, 128, 255)


def daily_share_card_theme(forecast_date: date) -> str:
    """Return the exact theme used by the daily horoscope for this date."""

    return build_editorial_daily_horoscope(forecast_date).theme


def load_daily_share_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Load the packaged Cyrillic-capable font used by public share cards."""

    font_path = DAILY_SHARE_BOLD_FONT_PATH if bold else DAILY_SHARE_FONT_PATH
    if not font_path.is_file():
        raise RuntimeError(f"Daily share font is missing: {font_path}")
    return ImageFont.truetype(str(font_path), size=size)


@lru_cache(maxsize=64)
def render_daily_share_card(forecast_date: date) -> bytes:
    """Render one immutable JPEG for a forecast date."""

    snapshot = build_editorial_daily_horoscope(forecast_date)
    with Image.open(DAILY_SHARE_BASE_PATH) as source:
        fitted = ImageOps.fit(
            source.convert("RGB"),
            CARD_SIZE,
            method=Image.Resampling.LANCZOS,
        )

    card = fitted.convert("RGBA")
    overlay = Image.new("RGBA", CARD_SIZE, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.rounded_rectangle(
        _BACKGROUND_PANEL,
        radius=48,
        fill=_PANEL_FILL,
        outline=_PANEL_OUTLINE,
        width=2,
    )
    card = Image.alpha_composite(card, overlay)
    draw = ImageDraw.Draw(card)

    brand_font = load_daily_share_font(72, bold=True)
    date_font = load_daily_share_font(38)
    label_font = load_daily_share_font(30, bold=True)
    footer_font = load_daily_share_font(34, bold=True)

    draw.text((112, 132), "NUMA", font=brand_font, fill=_PRIMARY_TEXT)
    draw.text(
        (112, 236),
        forecast_date.strftime("%d.%m.%Y"),
        font=date_font,
        fill=_MUTED_TEXT,
    )
    draw.text((112, 340), "ТЕМА ДНЯ", font=label_font, fill=_ACCENT_TEXT)

    theme_font, theme_lines = _fit_wrapped_text(
        draw,
        snapshot.theme,
        max_width=920,
        max_lines=4,
    )
    line_height = _line_height(theme_font)
    y = 402
    for line in theme_lines:
        draw.text((112, y), line, font=theme_font, fill=_PRIMARY_TEXT)
        y += line_height

    footer = "ГОРОСКОП НА СЕГОДНЯ  ·  NUMA"
    footer_bbox = draw.textbbox((0, 0), footer, font=footer_font)
    footer_width = footer_bbox[2] - footer_bbox[0]
    draw.text(
        ((CARD_SIZE[0] - footer_width) / 2, 1386),
        footer,
        font=footer_font,
        fill=_PRIMARY_TEXT,
        stroke_width=1,
        stroke_fill=(7, 13, 30, 210),
    )

    output = BytesIO()
    card.convert("RGB").save(output, format="JPEG", quality=88, optimize=True)
    return output.getvalue()


def _fit_wrapped_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    max_width: int,
    max_lines: int,
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    for size in range(66, 39, -2):
        font = load_daily_share_font(size)
        lines = _wrap_text(draw, text, font, max_width=max_width)
        if len(lines) <= max_lines:
            return font, lines

    font = load_daily_share_font(40)
    lines = _wrap_text(draw, text, font, max_width=max_width)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = _ellipsize(draw, lines[-1], font, max_width=max_width)
    return font, lines


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    *,
    max_width: int,
) -> list[str]:
    words = text.split()
    if not words:
        return [""]

    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if _text_width(draw, candidate, font) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _ellipsize(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    *,
    max_width: int,
) -> str:
    suffix = "…"
    candidate = text
    while candidate and _text_width(draw, candidate + suffix, font) > max_width:
        candidate = candidate[:-1].rstrip()
    return candidate + suffix


def _text_width(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return round(bbox[2] - bbox[0])


def _line_height(font: ImageFont.FreeTypeFont) -> int:
    bbox = font.getbbox("Аг")
    return max(58, round(bbox[3] - bbox[1] + 18))
