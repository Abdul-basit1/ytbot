"""
UpperCut — Kids Thumbnail Maker (KiddoWorld)
Generates bright, colorful, child-friendly thumbnails with bold text,
gradient backgrounds, and fun decorations (stars, sparkles).
"""

from __future__ import annotations

import math
import random
import uuid
from pathlib import Path
from typing import Dict, List, Tuple

from loguru import logger
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from config import THUMB_DIR, ensure_kids_font

THUMB_W, THUMB_H = 1280, 720

# ── Color palettes ──────────────────────────────────────────────────────────

KIDS_PALETTES = [
    {
        "name": "sunny",
        "bg1": (255, 107, 107),   # Coral red
        "bg2": (255, 217, 61),    # Sunny yellow
        "text": (255, 255, 255),
        "outline": (51, 51, 51),
        "accent": (78, 205, 196),  # Teal
    },
    {
        "name": "ocean",
        "bg1": (69, 183, 209),    # Sky blue
        "bg2": (150, 206, 180),   # Mint green
        "text": (255, 255, 255),
        "outline": (44, 62, 80),
        "accent": (255, 234, 167),  # Light yellow
    },
    {
        "name": "candy",
        "bg1": (232, 67, 147),    # Hot pink
        "bg2": (161, 140, 209),   # Lavender
        "text": (255, 255, 255),
        "outline": (51, 51, 51),
        "accent": (255, 234, 167),
    },
    {
        "name": "forest",
        "bg1": (0, 184, 148),     # Green
        "bg2": (253, 203, 110),   # Warm yellow
        "text": (255, 255, 255),
        "outline": (44, 62, 80),
        "accent": (255, 118, 117),  # Salmon
    },
    {
        "name": "rainbow",
        "bg1": (108, 92, 231),    # Purple
        "bg2": (0, 206, 201),     # Cyan
        "text": (255, 255, 255),
        "outline": (45, 52, 54),
        "accent": (255, 234, 167),
    },
]


def _create_gradient_bg(w: int, h: int, c1: Tuple, c2: Tuple) -> Image.Image:
    """Create a smooth diagonal gradient background."""
    img = Image.new("RGB", (w, h))
    for y in range(h):
        for x in range(w):
            ratio = (x / w + y / h) / 2
            r = int(c1[0] * (1 - ratio) + c2[0] * ratio)
            g = int(c1[1] * (1 - ratio) + c2[1] * ratio)
            b = int(c1[2] * (1 - ratio) + c2[2] * ratio)
            img.putpixel((x, y), (r, g, b))
    return img


def _draw_stars(draw: ImageDraw.Draw, count: int = 12, color: Tuple = (255, 255, 255)):
    """Draw decorative stars scattered around the thumbnail."""
    for _ in range(count):
        x = random.randint(20, THUMB_W - 20)
        y = random.randint(20, THUMB_H - 20)
        size = random.randint(8, 25)

        # Simple 4-pointed star
        points = []
        for i in range(8):
            angle = math.radians(i * 45 - 90)
            r = size if i % 2 == 0 else size // 3
            px = x + r * math.cos(angle)
            py = y + r * math.sin(angle)
            points.append((px, py))

        alpha = random.randint(100, 220)
        star_color = (*color[:3], alpha) if len(color) == 4 else color
        draw.polygon(points, fill=star_color)


def _draw_sparkles(draw: ImageDraw.Draw, count: int = 20, color: Tuple = (255, 255, 255)):
    """Draw small sparkle dots."""
    for _ in range(count):
        x = random.randint(10, THUMB_W - 10)
        y = random.randint(10, THUMB_H - 10)
        size = random.randint(2, 6)
        draw.ellipse([(x - size, y - size), (x + size, y + size)], fill=color)


def _draw_text_with_outline(
    draw: ImageDraw.Draw,
    text: str,
    position: Tuple[int, int],
    font: ImageFont.FreeTypeFont,
    fill: Tuple,
    outline_color: Tuple = (51, 51, 51),
    outline_width: int = 4,
):
    """Draw text with a thick outline for readability on colorful backgrounds."""
    x, y = position
    # Draw outline
    for dx in range(-outline_width, outline_width + 1):
        for dy in range(-outline_width, outline_width + 1):
            if dx * dx + dy * dy <= outline_width * outline_width:
                draw.text((x + dx, y + dy), text, font=font, fill=outline_color)
    # Draw main text
    draw.text((x, y), text, font=font, fill=fill)


def _make_kids_thumbnail(title: str, palette: Dict, variant: str) -> Path:
    """Create a single kids thumbnail variant."""
    font_path = ensure_kids_font()

    # Gradient background
    img = _create_gradient_bg(THUMB_W, THUMB_H, palette["bg1"], palette["bg2"])
    draw = ImageDraw.Draw(img)

    # Add decorations
    _draw_stars(draw, count=15, color=palette["accent"])
    _draw_sparkles(draw, count=25, color=(255, 255, 255))

    # Load fonts
    try:
        font_large = ImageFont.truetype(str(font_path), 80)
        font_small = ImageFont.truetype(str(font_path), 36)
    except Exception:
        font_large = ImageFont.load_default()
        font_small = ImageFont.load_default()

    # Word-wrap title (max ~18 chars per line for kids readability)
    words = title.split()
    lines = []
    current = ""
    for word in words:
        test = current + " " + word if current else word
        if len(test) > 18:
            if current:
                lines.append(current)
            current = word
        else:
            current = test
    if current:
        lines.append(current)

    # Draw title text (centered)
    line_height = 95
    total_height = len(lines) * line_height
    y_start = (THUMB_H - total_height) // 2 - 20

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font_large)
        text_w = bbox[2] - bbox[0]
        x = (THUMB_W - text_w) // 2

        _draw_text_with_outline(
            draw, line,
            (x, y_start + i * line_height),
            font_large,
            fill=palette["text"],
            outline_color=palette["outline"],
            outline_width=5,
        )

    # Channel badge at bottom
    badge_text = "KiddoWorld"
    badge_w = 220
    badge_h = 45
    badge_x = THUMB_W - badge_w - 20
    badge_y = THUMB_H - badge_h - 20

    draw.rounded_rectangle(
        [(badge_x, badge_y), (badge_x + badge_w, badge_y + badge_h)],
        radius=12,
        fill=palette["accent"],
    )
    draw.text(
        (badge_x + 15, badge_y + 5),
        badge_text,
        font=font_small,
        fill=palette["outline"],
    )

    # Save
    filename = f"kids_thumb_{variant}_{uuid.uuid4().hex[:8]}.jpg"
    out_path = THUMB_DIR / filename
    img.save(out_path, "JPEG", quality=95)

    logger.debug(f"Kids thumbnail created: {out_path.name} (variant {variant}, palette {palette['name']})")
    return out_path


def create(
    topic: Dict,
    script_result=None,
    style: str = "bright_cartoon",
) -> List[Path]:
    """
    Generate 2 kids thumbnail variants for A/B testing.

    Args:
        topic: topic dict with 'text' key
        script_result: optional KidsScriptResult (unused for now)
        style: thumbnail style (currently only 'bright_cartoon')

    Returns:
        List of 2 Path objects (variant A and B).
    """
    title = topic.get("text", "KiddoWorld")
    if len(title) > 50:
        title = title[:47] + "..."

    logger.info(f"Creating kids thumbnails (A/B): {title[:40]}...")

    # Pick 2 different palettes
    palettes = random.sample(KIDS_PALETTES, 2)

    thumb_a = _make_kids_thumbnail(title, palettes[0], "A")
    thumb_b = _make_kids_thumbnail(title, palettes[1], "B")

    return [thumb_a, thumb_b]
