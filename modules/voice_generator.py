"""
UpperCut — Voice Generator
Generates natural Urdu voiceovers using edge-tts (free, no API key).
"""

from __future__ import annotations

import asyncio
import re
import uuid
from pathlib import Path

import edge_tts
from loguru import logger

from config import AUDIO_DIR, TTS_VOICE_MALE, TTS_VOICE_FEMALE


def _add_pauses(text: str) -> str:
    """Insert SSML-style pauses between sentences for natural delivery."""
    # Add a brief pause after Urdu sentence enders (۔) and standard periods
    text = re.sub(r"۔\s*", "۔ ... ", text)
    text = re.sub(r"\.\s+", ". ... ", text)
    # Slightly longer pause after paragraph breaks
    text = re.sub(r"\n\n+", "\n\n... ... ", text)
    return text


async def _generate_async(
    text: str,
    output_path: Path,
    voice: str,
) -> float:
    """
    Internal async function that calls edge-tts and returns audio duration.
    """
    communicate = edge_tts.Communicate(text, voice, rate="-5%", pitch="+0Hz")
    await communicate.save(str(output_path))

    # Get duration from the generated file using ffprobe
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "quiet", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(output_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        duration = float(stdout.decode().strip())
    except Exception:
        # Rough estimate: Urdu ~130 words/min
        word_count = len(text.split())
        duration = (word_count / 130) * 60

    return duration


def generate(
    script_text: str,
    voice: str = TTS_VOICE_MALE,
    filename: str | None = None,
) -> dict:
    """
    Generate an Urdu voiceover MP3 from script text.

    Args:
        script_text: The Urdu script to convert to speech.
        voice: edge-tts voice ID (default: male Urdu voice).
        filename: Optional output filename. Auto-generated if None.

    Returns:
        dict with keys: path (Path), duration_seconds (float)
    """
    if not script_text.strip():
        raise ValueError("Script text is empty — cannot generate voiceover")

    # Prepare text with natural pauses
    text = _add_pauses(script_text)

    # Output path
    if filename is None:
        filename = f"voice_{uuid.uuid4().hex[:10]}.mp3"
    output_path = AUDIO_DIR / filename

    logger.info(f"Generating voiceover ({voice}) → {output_path.name}")

    try:
        duration = asyncio.run(_generate_async(text, output_path, voice))
    except Exception as e:
        # Try backup voice if primary fails
        if voice == TTS_VOICE_MALE:
            logger.warning(f"Primary voice failed ({e}), trying backup voice...")
            try:
                duration = asyncio.run(_generate_async(text, output_path, TTS_VOICE_FEMALE))
                voice = TTS_VOICE_FEMALE
            except Exception as e2:
                logger.error(f"Backup voice also failed: {e2}")
                raise
        else:
            raise

    logger.info(f"Voiceover generated: {output_path.name}, duration={duration:.1f}s")

    return {
        "path": output_path,
        "duration_seconds": round(duration, 2),
        "voice": voice,
    }


def generate_for_sections(
    sections: list[dict],
    voice: str = TTS_VOICE_MALE,
) -> list[dict]:
    """
    Generate individual audio clips for each script section.
    Useful when you need per-section audio for precise footage alignment.

    Returns:
        List of dicts, each with: path, duration_seconds, section_title
    """
    results = []
    for i, sec in enumerate(sections):
        text = sec.get("text", "")
        title = sec.get("title", f"section_{i}")
        if not text.strip():
            continue
        fname = f"sec_{i:02d}_{uuid.uuid4().hex[:6]}.mp3"
        result = generate(text, voice=voice, filename=fname)
        result["section_title"] = title
        results.append(result)
    return results
