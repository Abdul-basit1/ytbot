"""
KiddoWorld — Image Generator
Generates cartoon-style images using DALL-E 3 (OpenAI).
Each image matches a section of the script.
Images are displayed as a Ken Burns slideshow in the final video.
Cost: ~$0.04 per image × 8 = ~$0.32 per video (vs $0.70 for fal.ai video clips).
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import List, Optional

import requests
from loguru import logger
from openai import OpenAI

from config import OPENAI_API_KEY, get_db

# Output directory for generated images
IMAGE_DIR = Path(__file__).resolve().parent.parent / "output" / "images"
IMAGE_DIR.mkdir(parents=True, exist_ok=True)

client = OpenAI(api_key=OPENAI_API_KEY)

# Cost per DALL-E 3 image (1024x1024, standard quality)
COST_PER_IMAGE_USD = 0.04

# Style suffix appended to every prompt
STYLE_SUFFIX = (
    ". 2D cartoon illustration style, bright vibrant colors, child friendly, "
    "Pixar inspired, cute rounded characters, no text or letters in image, "
    "white outline on characters, safe for kids aged 2-8, "
    "clean simple background, high quality digital art"
)

# ── Cache ───────────────────────────────────────────────────────────────────

_image_cache: dict[str, Path] = {}


def _prompt_hash(prompt: str) -> str:
    """Short hash for caching by prompt."""
    return hashlib.md5(prompt.lower().strip().encode()).hexdigest()[:12]


def _cached_image(prompt: str) -> Optional[Path]:
    """Check if we already generated an image for this prompt."""
    h = _prompt_hash(prompt)
    if h in _image_cache and _image_cache[h].exists():
        return _image_cache[h]
    # Check disk
    for f in IMAGE_DIR.glob(f"img_{h}_*"):
        if f.suffix.lower() in (".png", ".jpg", ".webp"):
            _image_cache[h] = f
            return f
    return None


# ── DALL-E 3 Generation ────────────────────────────────────────────────────

def generate_image(
    scene_description: str,
    size: str = "1792x1024",  # Landscape for 16:9 video
) -> Optional[Path]:
    """
    Generate a cartoon illustration using DALL-E 3.

    Args:
        scene_description: text description of the scene
        size: '1792x1024' (landscape) or '1024x1792' (portrait for Shorts)

    Returns:
        Local path to downloaded image, or None on failure.
    """
    if not OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY not configured")
        return None

    # Check cache
    cached = _cached_image(scene_description)
    if cached:
        logger.debug(f"Image cache hit: {cached.name}")
        return cached

    # Build prompt with style suffix
    full_prompt = scene_description.strip() + STYLE_SUFFIX

    logger.info(f"Generating image: {scene_description[:60]}...")

    try:
        response = client.images.generate(
            model="dall-e-3",
            prompt=full_prompt,
            size=size,
            quality="standard",
            n=1,
        )

        image_url = response.data[0].url
        if not image_url:
            logger.error("DALL-E 3 returned no image URL")
            return None

        # Download image
        local_path = _download_image(image_url, scene_description)
        if local_path:
            _track_cost(COST_PER_IMAGE_USD)
            logger.info(f"Image saved: {local_path.name} (${COST_PER_IMAGE_USD})")

        return local_path

    except Exception as e:
        logger.error(f"DALL-E 3 image generation failed: {e}")
        return None


def generate_images_for_script(
    animation_prompts: List[str],
    size: str = "1792x1024",
) -> List[Path]:
    """
    Generate images for all scenes in a script.

    Args:
        animation_prompts: list of scene descriptions
        size: image size

    Returns:
        List of local paths to generated images.
    """
    images = []
    total_cost = 0.0

    logger.info(f"Generating {len(animation_prompts)} cartoon images...")

    for i, prompt in enumerate(animation_prompts):
        logger.info(f"  Image {i + 1}/{len(animation_prompts)}: {prompt[:50]}...")

        img = generate_image(prompt, size=size)
        if img:
            images.append(img)
            # Only count cost if not cached
            if not _cached_image(prompt):
                total_cost += COST_PER_IMAGE_USD
        else:
            logger.warning(f"  Image {i + 1} failed — will use fallback in assembly")

    logger.info(
        f"Image generation complete: {len(images)}/{len(animation_prompts)} images, "
        f"cost=${total_cost:.2f}"
    )
    return images


# ── Helpers ─────────────────────────────────────────────────────────────────

def _download_image(url: str, prompt: str) -> Optional[Path]:
    """Download an image from URL and save locally."""
    h = _prompt_hash(prompt)
    filename = f"img_{h}_{uuid.uuid4().hex[:6]}.png"
    out_path = IMAGE_DIR / filename

    try:
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()

        with open(out_path, "wb") as f:
            f.write(resp.content)

        _image_cache[h] = out_path
        return out_path

    except Exception as e:
        logger.error(f"Failed to download image: {e}")
        return None


def _track_cost(cost_usd: float):
    """Log DALL-E cost to cost_tracking table."""
    try:
        db = get_db()
        db.execute(
            "INSERT INTO cost_tracking (service, operation, cost_usd) VALUES (?, ?, ?)",
            ("openai", "dalle3_image", cost_usd),
        )
        db.execute(
            "UPDATE videos SET cost_usd = cost_usd + ? WHERE id = (SELECT MAX(id) FROM videos)",
            (cost_usd,),
        )
        db.commit()
        db.close()
    except Exception:
        pass


def get_monthly_image_cost() -> float:
    """Return total DALL-E image spend in the last 30 days."""
    try:
        db = get_db()
        row = db.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) as total FROM cost_tracking "
            "WHERE service='openai' AND operation='dalle3_image' "
            "AND created_at > datetime('now', '-30 days')",
        ).fetchone()
        db.close()
        return row["total"]
    except Exception:
        return 0.0


def cleanup_old_images(days: int = 30):
    """Delete cached images older than N days."""
    import time
    cutoff = time.time() - (days * 86400)
    deleted = 0
    for f in IMAGE_DIR.glob("img_*"):
        if f.stat().st_mtime < cutoff:
            f.unlink()
            deleted += 1
    if deleted:
        logger.info(f"Cleaned up {deleted} old images")
