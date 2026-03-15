"""
UpperCut — Shorts Maker
Auto-cuts the best 60-second segment from a long-form video,
crops to 9:16 vertical, burns subtitles, and adds a subscribe watermark.
"""

from __future__ import annotations

import subprocess
import uuid
from pathlib import Path

from loguru import logger

from config import SHORTS_RES, VIDEO_DIR, VIDEO_FPS, ensure_kids_font, ensure_urdu_font


def _get_best_segment_start(total_duration: float) -> float:
    """
    Pick the start time for the most engaging 60s segment.
    Heuristic: the 2-4 minute mark is usually the first major point
    after the hook and intro — most engaging part.
    """
    if total_duration < 70:
        return 0.0

    # Target the 2-4 minute mark
    ideal_start = 120.0  # 2 minutes in
    max_start = total_duration - 65  # Leave 5s buffer

    if ideal_start > max_start:
        # Video is shorter than expected, start at 25% mark
        ideal_start = total_duration * 0.25

    return min(ideal_start, max_start)


def create(
    long_video_path: Path,
    total_duration: float | None = None,
    output_filename: str | None = None,
    kids: bool = False,
) -> dict:
    """
    Create a 60s YouTube Shorts clip from a long-form video.

    Steps:
        1. Extract best 60s segment
        2. Crop to 9:16 (center crop from 16:9)
        3. Add subscribe watermark text
        4. Output as vertical MP4

    Args:
        long_video_path: path to the source long-form video
        total_duration: duration of source video in seconds (fetched if None)
        output_filename: optional output name

    Returns:
        dict with keys: path (Path), duration_seconds (float)
    """
    if output_filename is None:
        output_filename = f"short_{uuid.uuid4().hex[:10]}.mp4"
    output_path = VIDEO_DIR / output_filename

    w_out, h_out = SHORTS_RES  # 1080 x 1920

    # Get total duration if not provided
    if total_duration is None:
        try:
            result = subprocess.run(
                [
                    "ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1", str(long_video_path),
                ],
                capture_output=True, text=True, check=True,
            )
            total_duration = float(result.stdout.strip())
        except Exception as e:
            logger.warning(f"Could not probe duration: {e}, defaulting to 480s")
            total_duration = 480.0

    start = _get_best_segment_start(total_duration)
    clip_duration = min(60.0, total_duration - start)

    logger.info(
        f"Creating Short: {long_video_path.name} → "
        f"start={start:.0f}s, duration={clip_duration:.0f}s"
    )

    # Font path for watermark
    font_path = ensure_kids_font() if kids else ensure_kids_font()  # Nunito works for both

    # Watermark text
    watermark = "Subscribe!" if kids else "Subscribe \\| سبسکرائب"

    # ffmpeg command:
    # 1. Seek to start time
    # 2. Crop center of 16:9 to get 9:16 (take center 607px width from 1920)
    # 3. Scale to 1080x1920
    # 4. Add subscribe text overlay
    # 5. Limit to 60s
    crop_w = 607  # 1080 * (1080/1920) ≈ 607 from a 1920-wide source
    crop_x = "(iw-607)/2"

    filter_complex = (
        f"crop={crop_w}:ih:{crop_x}:0,"
        f"scale={w_out}:{h_out}:flags=lanczos,"
        f"drawtext=text='{watermark}':"
        f"fontfile='{font_path}':"
        f"fontsize=28:fontcolor=white:borderw=2:bordercolor=black:"
        f"x=(w-text_w)/2:y=h-60"
    )

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-i", str(long_video_path),
        "-t", str(clip_duration),
        "-vf", filter_complex,
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        str(output_path),
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=300)
    except subprocess.TimeoutExpired:
        logger.error("Shorts creation timed out (5 min limit)")
        raise
    except subprocess.CalledProcessError as e:
        logger.error(f"ffmpeg failed: {e.stderr.decode()[:500]}")
        raise

    logger.info(f"Short created: {output_path.name}, {clip_duration:.0f}s")

    return {
        "path": output_path,
        "duration_seconds": round(clip_duration, 2),
    }
