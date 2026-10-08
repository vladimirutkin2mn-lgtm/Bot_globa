"""Render a public daily horoscope card from the same deterministic editorial snapshot."""

from datetime import date
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from app.services.daily_horoscope_editorial import build_editorial_daily_horoscope

CARD_SIZE = (1200, 1200)
THUMBNAIL_SIZE = (320, 320)
DAILY_SHARE_BASE_PATH = (
    Path(__file__).resolve().parents[1] / "bot" / "assets" / "scenes" / "E-02.jpg"
)
DAILY_SHARE_FONT_PATH = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
DAILY_SHARE_BOLD_FONT_PATH = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
DAILY_SHARE_SERIF_FONT_PATH = Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf")

_PRIMARY_TEXT = (248, 242, 229, 255)
_MUTED_TEXT = (214, 207, 195, 255)
_ACCENT_TEXT = (229, 190, 116, 255)
_TEXT_SHADOW = (4, 7, 17, 150)
_LEFT_MARGIN = 112
_HEADLINE_MAX_WIDTH = 936
_BOTTOM_SAFE_AREA = 120


def daily_share_card_theme(forecast_date: date) -> str:
    """Return the exact theme used by the daily horoscope for this date."""

    return build_editorial_daily_horoscope(forecast_date).theme


def load_daily_share_font(
    size: int,
    *,
    bold: bool = False,
    serif: bool = False,
) -> ImageFont.FreeTypeFont:
    """Load packaged Cyrillic-capable fonts used by public share cards."""

    if bold and serif:
        raise ValueError("daily share serif font has no bold variant")
    if serif:
        font_path = DAILY_SHARE_SERIF_FONT_PATH
    else:
        font_path = DAILY_SHARE_BOLD_FONT_PATH if bold else DAILY_SHARE_FONT_PATH
    if not font_path.is_file():
        raise RuntimeError(f"Daily share font is missing: {font_path}")
    return ImageFont.truetype(str(font_path), size=size)


@lru_cache(maxsize=64)
def render_daily_share_card(forecast_date: date) -> bytes:
    """Render one immutable premium-editorial baseline JPEG for a forecast date."""

    snapshot = build_editorial_daily_horoscope(forecast_date)
    with Image.open(DAILY_SHARE_BASE_PATH) as source:
        fitted = ImageOps.fit(
            source.convert("RGB"),
            CARD_SIZE,
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )

    card = fitted.convert("RGBA")
    card = Image.alpha_composite(card, _build_readability_overlay())
    draw = ImageDraw.Draw(card)

    brand_font = load_daily_share_font(58, bold=True)
    date_font = load_daily_share_font(30)
    label_font = load_daily_share_font(25, bold=True)

    _draw_tracked_text(
        draw,
        (_LEFT_MARGIN, 88),
        "NUMA",
        brand_font,
        fill=_PRIMARY_TEXT,
        tracking=3,
    )
    draw.text(
        (_LEFT_MARGIN, 176),
        forecast_date.strftime("%d.%m.%Y"),
        font=date_font,
        fill=_MUTED_TEXT,
    )

    label_y = 260
    label_width = _draw_tracked_text(
        draw,
        (_LEFT_MARGIN, label_y),
        "ТЕМА ДНЯ",
        label_font,
        fill=_ACCENT_TEXT,
        tracking=5,
    )
    rule_start = _LEFT_MARGIN + label_width + 36
    draw.line(
        (rule_start, label_y + 17, min(rule_start + 245, 790), label_y + 17),
        fill=(229, 190, 116, 155),
        width=2,
    )

    theme_font, theme_lines = _fit_wrapped_text(
        draw,
        _display_theme(snapshot.theme),
        max_width=_HEADLINE_MAX_WIDTH,
        max_lines=4,
    )
    line_height = _line_height(theme_font)
    y = 326
    for line in theme_lines:
        draw.text(
            (_LEFT_MARGIN, y),
            line,
            font=theme_font,
            fill=_PRIMARY_TEXT,
            stroke_width=1,
            stroke_fill=_TEXT_SHADOW,
        )
        y += line_height

    # Keep the lower part intentionally free of text. The artwork fills the square
    # card edge-to-edge; Telegram receives the same 1:1 geometry in photo metadata.
    assert y < CARD_SIZE[1] - _BOTTOM_SAFE_AREA

    return _encode_baseline_jpeg(card.convert("RGB"), quality=85)


@lru_cache(maxsize=64)
def render_daily_share_thumbnail(forecast_date: date) -> bytes:
    """Render a small dedicated JPEG thumbnail for Telegram inline results."""

    with Image.open(BytesIO(render_daily_share_card(forecast_date))) as source:
        thumbnail = ImageOps.fit(
            source.convert("RGB"),
            THUMBNAIL_SIZE,
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )
    return _encode_baseline_jpeg(thumbnail, quality=72)


def _encode_baseline_jpeg(image: Image.Image, *, quality: int) -> bytes:
    """Encode a conservative baseline JPEG for Telegram's media proxy."""

    output = BytesIO()
    image.save(
        output,
        format="JPEG",
        quality=quality,
        optimize=False,
        progressive=False,
        subsampling=2,
    )
    payload = output.getvalue()
    if not payload.endswith(b"\xff\xd9"):
        raise RuntimeError("daily share JPEG is missing the EOI marker")
    return payload


def _build_readability_overlay() -> Image.Image:
    """Fade a dark veil out before the artwork's crystal centerpiece."""

    overlay = Image.new("RGBA", CARD_SIZE, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    fade_height = 760
    for y in range(fade_height):
        progress = y / (fade_height - 1)
        alpha = round(188 * (1 - progress) ** 1.55)
        draw.line((0, y, CARD_SIZE[0], y), fill=(3, 7, 18, alpha))
    return overlay


def _display_theme(text: str) -> str:
    """Normalize presentation only; editorial source text remains unchanged."""

    stripped = text.strip()
    if not stripped:
        return stripped
    return stripped[0].upper() + stripped[1:]


def _fit_wrapped_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    max_width: int,
    max_lines: int,
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    for size in range(64, 43, -2):
        font = load_daily_share_font(size, serif=True)
        lines = _wrap_text(draw, text, font, max_width=max_width)
        lines = _rebalance_last_line(draw, lines, font, max_width=max_width)
        if len(lines) <= max_lines:
            return font, lines

    font = load_daily_share_font(42, serif=True)
    lines = _wrap_text(draw, text, font, max_width=max_width)
    lines = _rebalance_last_line(draw, lines, font, max_width=max_width)
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


def _rebalance_last_line(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    font: ImageFont.FreeTypeFont,
    *,
    max_width: int,
) -> list[str]:
    """Avoid a lonely final word when one word can move down cleanly."""

    if len(lines) < 2 or len(lines[-1].split()) != 1:
        return lines
    previous_words = lines[-2].split()
    if len(previous_words) < 3:
        return lines
    moved = previous_words[-1]
    candidate_last = f"{moved} {lines[-1]}"
    candidate_previous = " ".join(previous_words[:-1])
    if (
        candidate_previous
        and _text_width(draw, candidate_last, font) <= max_width
        and _text_width(draw, candidate_previous, font) <= max_width
    ):
        return [*lines[:-2], candidate_previous, candidate_last]
    return lines


def _draw_tracked_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    *,
    fill: tuple[int, int, int, int],
    tracking: int,
) -> int:
    """Draw restrained editorial tracking and return the resulting width."""

    x, y = xy
    start_x = x
    for index, character in enumerate(text):
        draw.text((x, y), character, font=font, fill=fill)
        x += _text_width(draw, character, font)
        if index < len(text) - 1:
            x += tracking
    return x - start_x


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
    return max(70, round(bbox[3] - bbox[1] + 22))
