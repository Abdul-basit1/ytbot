"""
UpperCut — Thumbnail Maker
Generates A/B test thumbnail variants using Pillow with bold Urdu text.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Dict, List, Tuple

from loguru import logger
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from config import THUMB_DIR, ensure_urdu_font

# Thumbnail dimensions (YouTube standard)
THUMB_W, THUMB_H = 1280, 720

# Color palettes for A/B variants
PALETTE_A = {
    "bg": (220, 20, 60),       # Crimson red
    "text": (255, 255, 255),   # White
    "accent": (255, 215, 0),   # Gold
    "shadow": (0, 0, 0),
}
PALETTE_B = {
    "bg": (0, 51, 102),        # Deep blue
    "text": (255, 255, 255),   # White
    "accent": (0, 255, 127),   # Spring green
    "shadow": (0, 0, 0),
}


def _create_gradient_bg(width: int, height: int, color1: Tuple, color2: Tuple) -> Image.Image:
    """Create a vertical gradient background."""
    img = Image.new("RGB", (width, height))
    for y in range(height):
        ratio = y / height
        r = int(color1[0] * (1 - ratio) + color2[0] * ratio)
        g = int(color1[1] * (1 - ratio) + color2[1] * ratio)
        b = int(color1[2] * (1 - ratio) + color2[2] * ratio)
        for x in range(width):
            img.putpixel((x, y), (r, g, b))
    return img


def _draw_text_with_shadow(
    draw: ImageDraw.Draw,
    text: str,
    position: Tuple[int, int],
    font: ImageFont.FreeTypeFont,
    fill: Tuple,
    shadow_color: Tuple = (0, 0, 0),
    shadow_offset: int = 4,
):
    """Draw text with a drop shadow for readability."""
    x, y = position
    # Shadow
    draw.text((x + shadow_offset, y + shadow_offset), text, font=font, fill=shadow_color)
    # Main text
    draw.text((x, y), text, font=font, fill=fill)


def _make_thumbnail(
    title_urdu: str,
    bg_image_path: Path | None,
    palette: Dict,
    variant: str,
) -> Path:
    """Create a single thumbnail variant."""
    font_path = ensure_urdu_font()

    # Start with background
    if bg_image_path and bg_image_path.exists():
        try:
            img = Image.open(bg_image_path).resize((THUMB_W, THUMB_H))
            # Darken background for text readability
            img = img.point(lambda p: int(p * 0.5))
        except Exception:
            img = _create_gradient_bg(THUMB_W, THUMB_H, palette["bg"], (0, 0, 0))
    else:
        img = _create_gradient_bg(THUMB_W, THUMB_H, palette["bg"], (0, 0, 0))

    draw = ImageDraw.Draw(img)

    # Load Urdu font at different sizes
    try:
        font_large = ImageFont.truetype(str(font_path), 72)
        font_small = ImageFont.truetype(str(font_path), 36)
    except Exception:
        font_large = ImageFont.load_default()
        font_small = ImageFont.load_default()

    # Urdu text is RTL — Pillow handles this reasonably with Nastaliq fonts
    # Split title into lines if too long (max ~25 chars per line for Urdu)
    words = title_urdu.split()
    lines = []
    current_line = ""
    for word in words:
        test = current_line + " " + word if current_line else word
        if len(test) > 25:
            lines.append(current_line)
            current_line = word
        else:
            current_line = test
    if current_line:
        lines.append(current_line)

    # Draw title text (centered vertically)
    total_text_height = len(lines) * 90
    y_start = (THUMB_H - total_text_height) // 2

    for i, line in enumerate(lines):
        # Get text width for centering
        bbox = draw.textbbox((0, 0), line, font=font_large)
        text_w = bbox[2] - bbox[0]
        x = (THUMB_W - text_w) // 2

        _draw_text_with_shadow(
            draw, line,
            (x, y_start + i * 90),
            font_large,
            fill=palette["text"],
            shadow_color=palette["shadow"],
            shadow_offset=5,
        )

    # Add channel name badge at bottom
    badge_text = "UpperCut"
    draw.rounded_rectangle(
        [(THUMB_W - 250, THUMB_H - 70), (THUMB_W - 20, THUMB_H - 20)],
        radius=10,
        fill=palette["accent"],
    )
    draw.text((THUMB_W - 230, THUMB_H - 65), badge_text, font=font_small, fill=(0, 0, 0))

    # Save
    filename = f"thumb_{variant}_{uuid.uuid4().hex[:8]}.jpg"
    out_path = THUMB_DIR / filename
    img.save(out_path, "JPEG", quality=95)
    logger.debug(f"Thumbnail created: {out_path.name} (variant {variant})")
    return out_path


def create(
    topic: Dict,
    script_result,
    bg_image_path: Path | None = None,
) -> List[Path]:
    """
    Generate 2 thumbnail variants for A/B testing.

    Args:
        topic: topic dict with 'text' and optionally 'topic_urdu'
        script_result: ScriptResult (used for Urdu title if topic_urdu missing)
        bg_image_path: optional background image (e.g., first footage frame)

    Returns:
        List of 2 Path objects (variant A and variant B thumbnails).
    """
    # Get Urdu title — prefer topic_urdu, fall back to topic text
    title = topic.get("topic_urdu") or topic.get("text", "UpperCut")

    # Truncate to fit thumbnail
    if len(title) > 60:
        title = title[:57] + "..."

    logger.info(f"Creating A/B thumbnails for: {title[:40]}...")

    thumb_a = _make_thumbnail(title, bg_image_path, PALETTE_A, "A")
    thumb_b = _make_thumbnail(title, bg_image_path, PALETTE_B, "B")

    return [thumb_a, thumb_b]
