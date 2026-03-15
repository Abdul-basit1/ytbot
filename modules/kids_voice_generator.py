"""
UpperCut — Kids Voice Generator (KiddoWorld)
Generates cheerful, slow-paced voiceovers for kids content using edge-tts.
Supports English, Hindi, and Spanish with child-appropriate voices.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Dict

from loguru import logger

from config import AUDIO_DIR


# ── Kids voice map ──────────────────────────────────────────────────────────

KIDS_VOICES: Dict[str, Dict[str, str]] = {
    "english": {
        "primary": "en-US-AnaNeural",       # Cheerful girl voice
        "secondary": "en-US-BrianNeural",    # Friendly boy voice
        "narrator": "en-GB-SoniaNeural",     # Warm storyteller voice
    },
    "hindi": {
        "primary": "hi-IN-SwaraNeural",      # Hindi girl voice
    },
    "spanish": {
        "primary": "es-ES-ElviraNeural",     # Spanish girl voice
    },
}

# Kids speech settings — slower and higher pitched for comprehension
KIDS_RATE = "-20%"    # 20% slower than normal
KIDS_PITCH = "+10Hz"  # Slightly higher for cheerful tone


async def _generate_async(
    text: str,
    output_path: Path,
    voice: str,
    rate: str = KIDS_RATE,
    pitch: str = KIDS_PITCH,
) -> float:
    """Generate TTS audio and return duration in seconds."""
    import edge_tts

    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    await communicate.save(str(output_path))

    # Get duration via ffprobe
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
        # Rough estimate: kids speech ~120 wpm
        word_count = len(text.split())
        duration = (word_count / 120) * 60

    return duration


def generate(
    script_text: str,
    language: str = "english",
    voice_type: str = "primary",
    filename: str | None = None,
) -> dict:
    """
    Generate a kids voiceover MP3.

    Args:
        script_text: The script text to convert to speech.
        language: 'english', 'hindi', or 'spanish'.
        voice_type: 'primary', 'secondary', or 'narrator'.
        filename: Optional output filename.

    Returns:
        dict with keys: path (Path), duration_seconds (float), voice (str), language (str)
    """
    if not script_text.strip():
        raise ValueError("Script text is empty")

    # Get voice for language
    lang_voices = KIDS_VOICES.get(language, KIDS_VOICES["english"])
    voice = lang_voices.get(voice_type, lang_voices["primary"])

    # Clean script text — remove animation prompts and cues for TTS
    clean_text = _clean_for_tts(script_text)

    if filename is None:
        filename = f"kids_{language}_{uuid.uuid4().hex[:10]}.mp3"
    output_path = AUDIO_DIR / filename

    logger.info(f"Generating kids voiceover ({language}/{voice}) → {output_path.name}")

    try:
        duration = asyncio.run(_generate_async(clean_text, output_path, voice))
    except Exception as e:
        # Try fallback voice
        fallback_voice = lang_voices.get("narrator") or lang_voices["primary"]
        if fallback_voice != voice:
            logger.warning(f"Primary voice failed ({e}), trying fallback...")
            duration = asyncio.run(_generate_async(clean_text, output_path, fallback_voice))
            voice = fallback_voice
        else:
            raise

    logger.info(f"Kids voiceover generated: {output_path.name}, {duration:.1f}s ({language})")

    return {
        "path": output_path,
        "duration_seconds": round(duration, 2),
        "voice": voice,
        "language": language,
    }


def generate_all_languages(
    scripts: dict,
) -> Dict[str, dict]:
    """
    Generate voiceovers for all languages.

    Args:
        scripts: dict mapping language code to KidsScriptResult

    Returns:
        Dict mapping language to audio result dict.
    """
    audio_files = {}

    for lang, script in scripts.items():
        try:
            audio = generate(script.text, language=lang)
            audio_files[lang] = audio
        except Exception as e:
            logger.error(f"Voice generation failed for {lang}: {e}")

    return audio_files


def _clean_for_tts(text: str) -> str:
    """
    Clean script text for TTS — remove ALL stage directions and animation prompts.
    Only natural spoken words should remain.
    """
    import re

    # Convert sound effects to spoken text FIRST (before removing brackets)
    replacements = {
        "[CLAPPING]": "clap clap clap!",
        "[GIGGLING]": "hee hee hee!",
        "[WOOSH]": "woosh!",
        "[STOMP STOMP]": "stomp stomp!",
        "[CLAP CLAP]": "clap clap!",
        "[CHEERING]": "yay!",
        "[LAUGHING]": "ha ha ha!",
    }
    for marker, spoken in replacements.items():
        text = text.replace(marker, spoken)

    # Remove ALL remaining bracketed content — stage directions, animation prompts, etc.
    # This catches: [ANIMATE: ...], [SHOW RED CIRCLE], [SCENE 1], [INTRO], [MUSIC], etc.
    text = re.sub(r"\[[^\]]*\]", "", text)

    # Remove lines that are purely section headers (e.g. "Scene 1:", "Intro:", "Outro:")
    text = re.sub(r"(?m)^\s*(?:Scene|Section|Intro|Outro|Verse|Chorus|Bridge)\s*\d*\s*:?\s*$", "", text)

    # Clean up extra whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"  +", " ", text)

    return text.strip()
