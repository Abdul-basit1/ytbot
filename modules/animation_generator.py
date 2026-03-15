"""
UpperCut — Animation Generator (KiddoWorld)
Generates cartoon animation clips using fal.ai Pika API.
Tracks credit usage and caches generated clips.
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Dict, List, Optional

import requests
from loguru import logger

from config import ANIMATION_DIR, FAL_API_KEY, get_db

# Cost per fal.ai video generation (approximate, varies by duration/resolution)
COST_PER_CLIP_USD = 0.10  # ~$0.10 per 5-second clip

# Mandatory safety suffix for all animation prompts
SAFETY_SUFFIX = (
    ", bright colorful 2D cartoon animation, child-friendly, safe for kids, "
    "Pixar-inspired, vibrant colors, cute characters, happy cheerful atmosphere, "
    "no dark themes, no violence, no scary elements"
)

# ── Cache ───────────────────────────────────────────────────────────────────

_clip_cache: Dict[str, Path] = {}


def _prompt_hash(prompt: str) -> str:
    """Short hash for caching by prompt."""
    return hashlib.md5(prompt.lower().strip().encode()).hexdigest()[:12]


def _cached_clip(prompt: str) -> Optional[Path]:
    """Check if we already generated a clip for this prompt."""
    h = _prompt_hash(prompt)
    if h in _clip_cache and _clip_cache[h].exists():
        return _clip_cache[h]
    # Check disk
    for f in ANIMATION_DIR.glob(f"anim_{h}_*"):
        _clip_cache[h] = f
        return f
    return None


# ── fal.ai API ──────────────────────────────────────────────────────────────

def generate_cartoon_clip(
    scene_description: str,
    duration: int = 5,
    aspect_ratio: str = "16:9",
    resolution: str = "1080p",
) -> Optional[Path]:
    """
    Generate an animated cartoon clip using fal.ai Pika model.

    Args:
        scene_description: text description of the scene
        duration: clip duration in seconds (max 10)
        aspect_ratio: '16:9' for landscape, '9:16' for Shorts
        resolution: '720p' or '1080p'

    Returns:
        Local path to the downloaded video clip, or None on failure.
    """
    if not FAL_API_KEY:
        logger.error("FAL_API_KEY not configured — cannot generate animation")
        return None

    # Check cache
    cached = _cached_clip(scene_description)
    if cached:
        logger.debug(f"Animation cache hit: {cached.name}")
        return cached

    # Add safety suffix to prompt
    cartoon_prompt = scene_description.strip() + SAFETY_SUFFIX

    logger.info(f"Generating animation clip ({duration}s, {aspect_ratio}): {scene_description[:60]}...")

    try:
        import fal_client

        handler = fal_client.submit(
            "fal-ai/pika/v2.2/text-to-video",
            arguments={
                "prompt": cartoon_prompt,
                "duration": duration,
                "aspect_ratio": aspect_ratio,
                "resolution": resolution,
            },
        )

        result = handler.get()
        video_url = result["video"]["url"]

        # Download video
        local_path = _download_clip(video_url, scene_description)

        if local_path:
            # Track cost
            _track_animation_cost(COST_PER_CLIP_USD)
            logger.info(f"Animation clip saved: {local_path.name} (${COST_PER_CLIP_USD})")

        return local_path

    except Exception as e:
        logger.error(f"fal.ai animation generation failed: {e}")
        return None


def generate_shorts_clip(
    scene_description: str,
    duration: int = 5,
) -> Optional[Path]:
    """Generate a vertical 9:16 clip for YouTube Shorts."""
    return generate_cartoon_clip(
        scene_description,
        duration=duration,
        aspect_ratio="9:16",
        resolution="1080p",
    )


def generate_clips_for_script(
    animation_prompts: List[str],
    clip_duration: int = 5,
    aspect_ratio: str = "16:9",
) -> List[Path]:
    """
    Generate animation clips for all scenes in a script.

    Args:
        animation_prompts: list of scene descriptions from the script
        clip_duration: duration per clip in seconds
        aspect_ratio: '16:9' or '9:16'

    Returns:
        List of local file paths to generated clips.
    """
    clips = []
    total_cost = 0

    logger.info(f"Generating {len(animation_prompts)} animation clips...")

    for i, prompt in enumerate(animation_prompts):
        logger.info(f"  Clip {i + 1}/{len(animation_prompts)}: {prompt[:50]}...")

        clip = generate_cartoon_clip(prompt, duration=clip_duration, aspect_ratio=aspect_ratio)
        if clip:
            clips.append(clip)
            total_cost += COST_PER_CLIP_USD
        else:
            logger.warning(f"  Clip {i + 1} failed — will use fallback in assembly")

    logger.info(f"Animation generation complete: {len(clips)}/{len(animation_prompts)} clips, cost=${total_cost:.2f}")
    return clips


# ── Helpers ─────────────────────────────────────────────────────────────────

def _download_clip(url: str, prompt: str) -> Optional[Path]:
    """Download a video clip from URL and save locally."""
    h = _prompt_hash(prompt)
    filename = f"anim_{h}_{uuid.uuid4().hex[:6]}.mp4"
    out_path = ANIMATION_DIR / filename

    try:
        resp = requests.get(url, timeout=120, stream=True)
        resp.raise_for_status()

        with open(out_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

        _clip_cache[h] = out_path
        return out_path

    except Exception as e:
        logger.error(f"Failed to download animation clip: {e}")
        return None


def _track_animation_cost(cost_usd: float):
    """Log fal.ai cost to cost_tracking table and check budget alerts."""
    try:
        db = get_db()

        # Log cost
        db.execute(
            "INSERT INTO cost_tracking (service, operation, cost_usd) VALUES (?, ?, ?)",
            ("fal_ai", "animation_clip", cost_usd),
        )

        # Update latest video cost
        db.execute(
            "UPDATE videos SET cost_usd = cost_usd + ? WHERE id = (SELECT MAX(id) FROM videos)",
            (cost_usd,),
        )

        db.commit()

        # Check monthly spend
        row = db.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) as total FROM cost_tracking "
            "WHERE service='fal_ai' AND created_at > datetime('now', '-30 days')",
        ).fetchone()
        monthly_spend = row["total"]

        db.close()

        # Alert if spending is high
        if monthly_spend > 20:
            try:
                from alerts.email_alerts import low_api_balance
                remaining = max(25 - monthly_spend, 0)  # Assume $25 budget
                if remaining < 5:
                    low_api_balance("fal.ai", remaining, 5.0)
            except Exception:
                pass

    except Exception as e:
        logger.debug(f"Cost tracking failed: {e}")


def get_monthly_animation_cost() -> float:
    """Return total fal.ai spend in the last 30 days."""
    try:
        db = get_db()
        row = db.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) as total FROM cost_tracking "
            "WHERE service='fal_ai' AND created_at > datetime('now', '-30 days')",
        ).fetchone()
        db.close()
        return row["total"]
    except Exception:
        return 0.0


def cleanup_old_clips(days: int = 7):
    """Delete cached animation clips older than N days."""
    import time

    cutoff = time.time() - (days * 86400)
    deleted = 0

    for f in ANIMATION_DIR.glob("anim_*.mp4"):
        if f.stat().st_mtime < cutoff:
            f.unlink()
            deleted += 1

    if deleted:
        logger.info(f"Cleaned up {deleted} old animation clips")
