"""
KiddoWorld — Kids Music Fetcher
Uses pre-downloaded local music tracks (ElevenLabs / royalty-free).
Shuffles and rotates through tracks automatically.
Falls back to generated sine-wave music if no tracks available.
"""

from __future__ import annotations

import os
import random
from pathlib import Path
from typing import Optional

from loguru import logger

from config import DB_PATH, KIDS_MUSIC_DIR


MIN_FILE_SIZE = 50_000  # 50KB minimum for a valid track


def fetch_kids_music(
    mood: str | None = None,
    target_duration_mins: float = 5,
    force_new: bool = False,
) -> Optional[Path]:
    """
    Get a kids music track from local library.
    Rotates through tracks to avoid repetition.

    Args:
        mood: ignored (kept for API compatibility)
        target_duration_mins: ignored (kept for API compatibility)
        force_new: if True, skip recently used filter

    Returns:
        Path to music file, or None if unavailable.
    """
    available = _get_valid_tracks()

    if not available:
        logger.warning(f"No valid music tracks in {KIDS_MUSIC_DIR}")
        # Try generated WAV fallback
        wavs = list(KIDS_MUSIC_DIR.glob("*.wav"))
        wavs = [w for w in wavs if w.stat().st_size > MIN_FILE_SIZE]
        if wavs:
            chosen = random.choice(wavs)
            logger.info(f"Using generated WAV fallback: {chosen.name}")
            return chosen
        return None

    logger.info(f"Music library: {len(available)} tracks available")

    # Get recently used tracks to avoid repetition
    if not force_new:
        recently_used = _get_recently_used(limit=5)
        fresh = [t for t in available if t.name not in recently_used]
        if fresh:
            available = fresh
        else:
            logger.debug("All tracks recently used, resetting rotation")

    selected = random.choice(available)
    _log_usage(selected.name)

    logger.info(f"Music selected: {selected.name} ({selected.stat().st_size // 1024} KB)")
    return selected


def _get_valid_tracks() -> list[Path]:
    """Get list of valid MP3/WAV files from music directory."""
    if not KIDS_MUSIC_DIR.exists():
        KIDS_MUSIC_DIR.mkdir(parents=True, exist_ok=True)
        return []

    tracks = []
    for f in KIDS_MUSIC_DIR.iterdir():
        if f.suffix.lower() not in (".mp3", ".wav"):
            continue
        if f.stat().st_size < MIN_FILE_SIZE:
            continue
        tracks.append(f)

    random.shuffle(tracks)
    return tracks


def _get_recently_used(limit: int = 5) -> list[str]:
    """Get recently used track names from database."""
    import sqlite3
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute(
            "CREATE TABLE IF NOT EXISTS music_usage "
            "(id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "track_name TEXT NOT NULL, "
            "used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )
        conn.commit()
        rows = conn.execute(
            "SELECT track_name FROM music_usage ORDER BY used_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        conn.close()
        return [r[0] for r in rows]
    except Exception as e:
        logger.debug(f"Could not get music history: {e}")
        return []


def _log_usage(track_name: str):
    """Log track usage to database."""
    import sqlite3
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute(
            "CREATE TABLE IF NOT EXISTS music_usage "
            "(id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "track_name TEXT NOT NULL, "
            "used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )
        conn.execute("INSERT INTO music_usage (track_name) VALUES (?)", (track_name,))
        # Keep only last 100 records
        conn.execute(
            "DELETE FROM music_usage WHERE id NOT IN "
            "(SELECT id FROM music_usage ORDER BY used_at DESC LIMIT 100)"
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.debug(f"Could not log music usage: {e}")


def list_tracks() -> list[str]:
    """List all available tracks with sizes."""
    tracks = _get_valid_tracks()
    print(f"\n{'='*50}")
    print(f"KiddoWorld Music Library: {len(tracks)} tracks")
    print(f"{'='*50}")
    for i, t in enumerate(sorted(tracks, key=lambda x: x.name), 1):
        size_kb = t.stat().st_size / 1024
        print(f"{i:2}. {t.name:<45} {size_kb:.0f} KB")
    print(f"{'='*50}\n")
    return [t.name for t in tracks]
