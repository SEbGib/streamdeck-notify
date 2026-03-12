"""Render button images for the Stream Deck."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .plugins.base import NotificationState

ASSETS_DIR = Path(__file__).parent.parent / "assets" / "icons"

# Stream Deck MK.2 button size
ICON_SIZE = (72, 72)

# Colors
BG_DEFAULT = "#1A1A2E"
BG_URGENT = "#3D0000"
BADGE_RED = "#FF3B30"
TEXT_WHITE = "#FFFFFF"
TEXT_DIM = "#888888"


def render_button(
    state: NotificationState,
    icon_name: str | None = None,
    label: str = "",
) -> bytes:
    """Generate a button image with icon, label, and notification badge."""
    img = Image.new("RGB", ICON_SIZE, BG_URGENT if state.urgent else BG_DEFAULT)
    draw = ImageDraw.Draw(img)

    # Try to load a custom icon
    icon = _load_icon(icon_name) if icon_name else None

    # Layout: icon top center, label middle, subtitle bottom
    y_offset = 4

    if icon:
        icon_resized = icon.resize((28, 28), Image.LANCZOS)
        x = (ICON_SIZE[0] - 28) // 2
        img.paste(icon_resized, (x, y_offset), icon_resized if icon_resized.mode == "RGBA" else None)
        y_offset += 30

    # Label
    display_label = state.label or label
    if display_label:
        font = _get_font(11)
        bbox = draw.textbbox((0, 0), display_label, font=font)
        text_w = bbox[2] - bbox[0]
        x = (ICON_SIZE[0] - text_w) // 2
        draw.text((x, y_offset), display_label, fill=TEXT_WHITE, font=font)
        y_offset += 14

    # Subtitle
    if state.subtitle:
        font_small = _get_font(9)
        bbox = draw.textbbox((0, 0), state.subtitle, font=font_small)
        text_w = bbox[2] - bbox[0]
        x = (ICON_SIZE[0] - text_w) // 2
        color = BADGE_RED if state.urgent else TEXT_DIM
        draw.text((x, y_offset), state.subtitle, fill=color, font=font_small)

    # Badge (top-right corner)
    if state.count > 0:
        _draw_badge(draw, state.count)

    # Stream Deck displays images mirrored — flip horizontally
    img = img.transpose(Image.FLIP_LEFT_RIGHT)

    # Convert to bytes
    buf = BytesIO()
    img.save(buf, format="BMP")
    return buf.getvalue()


def render_empty() -> bytes:
    """Render an empty/off button."""
    img = Image.new("RGB", ICON_SIZE, "#000000")
    buf = BytesIO()
    img.save(buf, format="BMP")
    return buf.getvalue()


def _draw_badge(draw: ImageDraw.ImageDraw, count: int) -> None:
    """Draw a red notification badge in the top-right corner."""
    text = str(count) if count < 100 else "99+"
    font = _get_font(10)
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    padding = 3
    badge_w = max(text_w + padding * 2, text_h + padding * 2)
    badge_h = text_h + padding * 2

    x = ICON_SIZE[0] - badge_w - 2
    y = 2

    draw.rounded_rectangle(
        [x, y, x + badge_w, y + badge_h],
        radius=badge_h // 2,
        fill=BADGE_RED,
    )
    draw.text(
        (x + (badge_w - text_w) // 2, y + padding - 1),
        text,
        fill=TEXT_WHITE,
        font=font,
    )


def _load_icon(name: str) -> Image.Image | None:
    """Load icon from assets directory."""
    if not name:
        return None
    path = ASSETS_DIR / name
    if path.exists():
        return Image.open(path).convert("RGBA")

    # Try SVG conversion
    svg_path = path.with_suffix(".svg")
    if svg_path.exists():
        try:
            import cairosvg

            png_data = cairosvg.svg2png(url=str(svg_path), output_width=28, output_height=28)
            return Image.open(BytesIO(png_data)).convert("RGBA")
        except ImportError:
            pass

    return None


def _get_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Get a font, falling back to default if system fonts unavailable."""
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    ]
    for fp in font_paths:
        if Path(fp).exists():
            return ImageFont.truetype(fp, size)
    return ImageFont.load_default()
