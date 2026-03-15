"""
UpperCut — Video Assembler
Combines voiceover, images (Ken Burns slideshow) or video clips,
subtitles, and background music into a final 1080p MP4.
"""

from __future__ import annotations

import random
import uuid
from pathlib import Path
from typing import List, Optional

import numpy as np
from loguru import logger

from config import (
    AUDIO_DIR,
    FONT_DIR,
    KIDS_MUSIC_DIR,
    LONG_FORM_RES,
    MUSIC_DIR,
    TEMPLATE_DIR,
    VIDEO_BITRATE,
    VIDEO_DIR,
    VIDEO_FPS,
    ensure_kids_font,
    ensure_urdu_font,
)

from moviepy import vfx as _vfx


def _loop_clip(clip, duration):
    """Loop a clip to fill the given duration. Works with moviepy 2.x."""
    return clip.with_effects([_vfx.Loop(duration=duration)])


# ── Ken Burns Effect ────────────────────────────────────────────────────────

def _apply_ken_burns(image_path: Path, duration: float, size=(1920, 1080)):
    """
    Apply Ken Burns (zoom + pan) effect using ffmpeg zoompan filter.
    Much faster than Python per-frame processing (~5 sec vs 15 min).
    Returns a moviepy VideoFileClip of the rendered Ken Burns video.
    """
    import subprocess
    import tempfile

    w, h = size
    fps = VIDEO_FPS

    # Random zoom direction
    zoom_in = random.choice([True, False])

    # ffmpeg zoompan filter:
    # z: zoom level over time (1.0 to 1.15 or reverse)
    # d: total frames
    # s: output size
    # x, y: pan position (center)
    total_frames = int(duration * fps)

    if zoom_in:
        # Zoom in: 1.0 → 1.15
        zoom_expr = f"1+0.15*on/{total_frames}"
    else:
        # Zoom out: 1.15 → 1.0
        zoom_expr = f"1.15-0.15*on/{total_frames}"

    # Center the crop as zoom changes
    x_expr = f"iw/2-(iw/zoom/2)"
    y_expr = f"ih/2-(ih/zoom/2)"

    # Output to temp file
    out_path = Path(tempfile.mktemp(suffix=".mp4", dir=str(VIDEO_DIR)))

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", str(image_path),
        "-vf", (
            f"zoompan=z='{zoom_expr}':"
            f"x='{x_expr}':y='{y_expr}':"
            f"d={total_frames}:s={w}x{h}:fps={fps},"
            f"format=yuv420p"
        ),
        "-t", str(duration),
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "23",
        "-an",  # No audio (added later)
        str(out_path),
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=120)
    except subprocess.CalledProcessError as e:
        logger.warning(f"ffmpeg Ken Burns failed: {e.stderr.decode()[:200]}")
        # Fallback: static image (no zoom)
        from moviepy import ImageClip
        return ImageClip(str(image_path)).with_duration(duration).resized((w, h))
    except subprocess.TimeoutExpired:
        logger.warning("ffmpeg Ken Burns timed out — using static image")
        from moviepy import ImageClip
        return ImageClip(str(image_path)).with_duration(duration).resized((w, h))

    # Load the rendered video clip
    from moviepy import VideoFileClip
    clip = VideoFileClip(str(out_path))

    # Store path for cleanup after final render
    if not hasattr(_apply_ken_burns, "_temp_files"):
        _apply_ken_burns._temp_files = []
    _apply_ken_burns._temp_files.append(out_path)

    return clip


# ── Background Music ────────────────────────────────────────────────────────

def _get_bg_music(kids: bool = False) -> Optional[Path]:
    """Return a background music file if available."""
    search_dir = KIDS_MUSIC_DIR if kids else MUSIC_DIR
    tracks = [t for t in search_dir.glob("*.mp3") if t.stat().st_size > 50_000]
    tracks += [t for t in search_dir.glob("*.wav") if t.stat().st_size > 50_000]
    if not tracks and kids:
        tracks = [t for t in MUSIC_DIR.glob("**/*.mp3") if t.stat().st_size > 50_000]
    if not tracks and kids:
        try:
            from modules.kids_music_fetcher import fetch_kids_music
            new_track = fetch_kids_music(force_new=True)
            if new_track and Path(new_track).stat().st_size > 50_000:
                return Path(new_track)
        except Exception:
            pass
    if tracks:
        chosen = random.choice(tracks)
        logger.info(f"Background music: {chosen.name} ({chosen.stat().st_size // 1024} KB)")
        return chosen
    logger.warning(f"No background music found in {search_dir}")
    return None


def _get_intro_clip() -> Optional[Path]:
    intro = TEMPLATE_DIR / "intro.mp4"
    return intro if intro.exists() else None


def _get_outro_clip() -> Optional[Path]:
    outro = TEMPLATE_DIR / "outro.mp4"
    return outro if outro.exists() else None


# ── Main Assembly ───────────────────────────────────────────────────────────

def assemble(
    audio_path: Path,
    footage_paths: List[Path],
    script_result,
    output_filename: str | None = None,
    kids: bool = False,
) -> dict:
    """
    Assemble a long-form video from voiceover + images/clips.

    Images get Ken Burns effect automatically.
    Video clips are resized and looped as needed.

    Args:
        audio_path: Path to the voiceover MP3.
        footage_paths: List of image or video files.
        script_result: ScriptResult object.
        output_filename: Optional output file name.
        kids: If True, use Nunito font and kids-friendly fallbacks.

    Returns:
        dict with keys: path (Path), duration_seconds (float)
    """
    from moviepy import (
        AudioFileClip,
        ColorClip,
        CompositeAudioClip,
        CompositeVideoClip,
        ImageClip,
        VideoFileClip,
        concatenate_videoclips,
    )

    if kids:
        ensure_kids_font()
    else:
        ensure_urdu_font()

    if output_filename is None:
        output_filename = f"long_{uuid.uuid4().hex[:10]}.mp4"
    output_path = VIDEO_DIR / output_filename

    width, height = LONG_FORM_RES
    logger.info(f"Assembling video: {len(footage_paths)} files, audio={audio_path.name}")

    # Load main voiceover audio
    main_audio = AudioFileClip(str(audio_path))
    total_duration = main_audio.duration

    # ── Build visual track ───────────────────────────────────────────────
    visual_clips = []

    # Optional intro
    intro_path = _get_intro_clip()
    if intro_path:
        try:
            intro = VideoFileClip(str(intro_path)).resized((width, height)).subclipped(0, 3)
            visual_clips.append(intro)
        except Exception as e:
            logger.warning(f"Could not load intro: {e}")

    # Divide remaining duration among footage files
    intro_dur = visual_clips[0].duration if visual_clips else 0
    content_duration = total_duration - intro_dur

    if footage_paths:
        clip_duration = content_duration / len(footage_paths)
    else:
        clip_duration = content_duration

    # Bright kids-friendly fallback colors
    KIDS_COLORS = [
        (78, 205, 196),   # teal
        (255, 107, 107),  # coral
        (69, 183, 209),   # sky blue
        (150, 206, 180),  # mint
        (255, 234, 167),  # sunshine
        (162, 155, 254),  # lavender
    ]
    fallback_idx = 0

    for fp in footage_paths:
        try:
            fp = Path(str(fp))
            if not fp.exists():
                raise FileNotFoundError(f"{fp}")

            suffix = fp.suffix.lower()

            if suffix in (".jpg", ".jpeg", ".png", ".webp"):
                # ── Image → Ken Burns slideshow ──────────────────────
                clip = _apply_ken_burns(fp, clip_duration, size=(width, height))
                logger.debug(f"Ken Burns: {fp.name} ({clip_duration:.1f}s)")

            elif suffix in (".mp4", ".mov", ".avi", ".webm"):
                # ── Video clip ───────────────────────────────────────
                clip = VideoFileClip(str(fp))
                if clip.size[0] == 0 or clip.size[1] == 0:
                    raise ValueError(f"Invalid dimensions: {clip.size}")
                clip = clip.resized((width, height))
                if clip.duration < clip_duration:
                    clip = _loop_clip(clip, clip_duration)
                else:
                    clip = clip.subclipped(0, clip_duration)
                logger.debug(f"Video clip: {fp.name} ({clip.duration:.1f}s)")
            else:
                continue

            visual_clips.append(clip)

        except Exception as e:
            logger.warning(f"Could not load {fp.name}: {e} — using colored background")
            color = KIDS_COLORS[fallback_idx % len(KIDS_COLORS)] if kids else (20, 20, 30)
            fallback_idx += 1
            bg = ColorClip(size=(width, height), color=color).with_duration(clip_duration)
            visual_clips.append(bg)

    # If no footage at all, create colored background
    if not visual_clips or (len(visual_clips) == 1 and intro_path):
        logger.warning("No footage — using solid background")
        color = KIDS_COLORS[0] if kids else (20, 20, 30)
        bg = ColorClip(size=(width, height), color=color).with_duration(total_duration)
        visual_clips.append(bg)

    # Optional outro
    outro_path = _get_outro_clip()
    if outro_path:
        try:
            outro = VideoFileClip(str(outro_path)).resized((width, height)).subclipped(0, 3)
            visual_clips.append(outro)
        except Exception as e:
            logger.warning(f"Could not load outro: {e}")

    # Concatenate all visual clips with crossfade
    if len(visual_clips) > 1 and kids:
        # Add 0.5s crossfade between clips for smooth transitions
        try:
            video = concatenate_videoclips(visual_clips, padding=-0.5, method="compose")
        except Exception:
            video = concatenate_videoclips(visual_clips, method="compose")
    else:
        video = concatenate_videoclips(visual_clips, method="compose")

    # Trim to match audio
    if video.duration > total_duration + 6:
        video = video.subclipped(0, total_duration + (3 if outro_path else 0))

    # ── Add background music ────────────────────────────────────────────
    bg_music_path = _get_bg_music(kids=kids)
    if bg_music_path:
        try:
            bg_music = AudioFileClip(str(bg_music_path))
            logger.info(f"Mixing music: {bg_music_path.name} ({bg_music.duration:.1f}s)")
            if bg_music.duration < total_duration:
                bg_music = _loop_clip(bg_music, total_duration)
            else:
                bg_music = bg_music.subclipped(0, total_duration)
            music_vol = 0.20 if kids else 0.12
            bg_music = bg_music.with_volume_scaled(music_vol)

            combined_audio = CompositeAudioClip([main_audio, bg_music])
            video = video.with_audio(combined_audio)
            logger.info(f"Background music mixed at {int(music_vol * 100)}% volume")
        except Exception as e:
            logger.warning(f"Could not add background music: {e}")
            video = video.with_audio(main_audio)
    else:
        video = video.with_audio(main_audio)

    # ── Render ───────────────────────────────────────────────────────────
    logger.info(f"Rendering video → {output_path.name} ({total_duration:.0f}s)")
    video.write_videofile(
        str(output_path),
        fps=VIDEO_FPS,
        codec="libx264",
        audio_codec="aac",
        bitrate=VIDEO_BITRATE,
        preset="medium",
        threads=4,
        logger=None,
    )

    video.close()
    main_audio.close()

    # Cleanup temp Ken Burns video files
    if hasattr(_apply_ken_burns, "_temp_files"):
        for tmp in _apply_ken_burns._temp_files:
            try:
                Path(tmp).unlink(missing_ok=True)
            except Exception:
                pass
        _apply_ken_burns._temp_files.clear()

    logger.info(
        f"Video assembled: {output_path.name}, {total_duration:.0f}s, "
        f"{output_path.stat().st_size // (1024 * 1024)} MB"
    )

    return {
        "path": output_path,
        "duration_seconds": round(total_duration, 2),
    }


# ── Subtitles (Urdu only) ──────────────────────────────────────────────────

def add_subtitles_to_video(video_path: Path, audio_path: Path) -> Path:
    """Burn Urdu subtitles into the video using faster-whisper + ffmpeg."""
    try:
        from faster_whisper import WhisperModel

        logger.info("Transcribing audio for subtitles...")
        model = WhisperModel("base", compute_type="int8")
        segments, _ = model.transcribe(str(audio_path), language="ur")

        srt_path = video_path.with_suffix(".srt")
        with open(srt_path, "w", encoding="utf-8") as f:
            for i, seg in enumerate(segments, 1):
                start = _format_srt_time(seg.start)
                end = _format_srt_time(seg.end)
                f.write(f"{i}\n{start} --> {end}\n{seg.text.strip()}\n\n")

        font_path = ensure_urdu_font()
        output_sub = video_path.with_stem(video_path.stem + "_sub")

        import subprocess
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(video_path), "-vf",
                f"subtitles={srt_path}:force_style='FontName=Noto Nastaliq Urdu,"
                f"FontSize=22,PrimaryColour=&HFFFFFF,OutlineColour=&H000000,"
                f"Outline=2,Alignment=2'",
                "-c:a", "copy", str(output_sub),
            ],
            check=True, capture_output=True,
        )

        video_path.unlink()
        output_sub.rename(video_path)
        srt_path.unlink(missing_ok=True)
        logger.info("Subtitles burned into video")
        return video_path

    except ImportError:
        logger.warning("faster-whisper not available — skipping subtitles")
        return video_path
    except Exception as e:
        logger.warning(f"Subtitle generation failed: {e}")
        return video_path


def _format_srt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
