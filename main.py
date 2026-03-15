"""
UpperCut — Master Pipeline Runner
Orchestrates the full video creation and upload pipeline.
Runs on a schedule via APScheduler, or once with --test flag.
"""

from __future__ import annotations

import argparse
import json as _json
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml
from apscheduler.schedulers.blocking import BlockingScheduler
from loguru import logger

from config import BASE_DIR, CHANNEL_DIR, get_db, init_database

# ── Pipeline progress tracking ─────────────────────────────────────────────
PROGRESS_FILE = BASE_DIR / "output" / "pipeline_progress.json"


def _update_progress(channel: str, topic: str, step: int, step_name: str,
                     total_steps: int = 12, status: str = "running"):
    """Write current pipeline progress to a JSON file for the dashboard."""
    data = {
        "channel": channel,
        "topic": topic,
        "step": step,
        "step_name": step_name,
        "total_steps": total_steps,
        "status": status,
        "started_at": getattr(_update_progress, "_started", datetime.now().isoformat()),
        "updated_at": datetime.now().isoformat(),
    }
    if step == 1:
        _update_progress._started = datetime.now().isoformat()
        data["started_at"] = _update_progress._started
    try:
        PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
        PROGRESS_FILE.write_text(_json.dumps(data, indent=2))
    except Exception:
        pass

# ── Graceful shutdown ────────────────────────────────────────────────────────
_shutting_down = False


def _handle_signal(signum, frame):
    global _shutting_down
    logger.warning(f"Received signal {signum} — shutting down gracefully...")
    _shutting_down = True


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)


# ── Retry wrapper ────────────────────────────────────────────────────────────
def with_retry(func, description: str, max_retries: int = 3, delays=(120, 300, 600)):
    """
    Execute func() with retry logic. Logs errors and returns None on final failure.
    """
    for attempt in range(max_retries):
        if _shutting_down:
            logger.warning("Shutdown requested — aborting retry")
            return None
        try:
            return func()
        except Exception as e:
            logger.error(f"[Attempt {attempt + 1}/{max_retries}] {description} failed: {e}")
            if attempt < max_retries - 1:
                wait = delays[attempt] if attempt < len(delays) else delays[-1]
                logger.info(f"Retrying in {wait}s...")
                time.sleep(wait)
            else:
                _log_error_to_db(description, str(e))
                logger.error(f"{description} — all retries exhausted")
                return None


def _log_error_to_db(error_type: str, message: str, channel_id: int = 1, video_id: int | None = None):
    """Persist error to the database and send email alert."""
    try:
        db = get_db()
        db.execute(
            "INSERT INTO errors (channel_id, video_id, error_type, error_message) VALUES (?, ?, ?, ?)",
            (channel_id, video_id, error_type, message[:1000]),
        )
        db.commit()
        db.close()
    except Exception:
        pass

    # Send email alert for exhausted retries
    try:
        from alerts.email_alerts import retry_exhausted
        retry_exhausted("UpperCut", error_type, message[:500])
    except Exception:
        pass


# ── Load channel config ─────────────────────────────────────────────────────
def load_channel_config(config_path: Path) -> dict:
    """Load and return a channel YAML config."""
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── Pipeline router ──────────────────────────────────────────────────────────
def run_pipeline(channel_config: dict):
    """Route to the correct pipeline based on channel niche."""
    niche = channel_config.get("channel", {}).get("niche", "")
    if niche == "kids_educational_entertainment":
        run_kids_pipeline(channel_config)
    else:
        run_news_pipeline(channel_config)


# ── News/Trending Pipeline (UpperCut) ────────────────────────────────────────
def run_news_pipeline(channel_config: dict):
    """
    Execute the full video creation pipeline for UpperCut (news/trending):
    1. Fetch trends  2. Pick topic  3. Generate script  4. Voiceover
    5. Fetch footage  6. Assemble video  7. Create short  8. Thumbnails
    9. SEO metadata  10. Upload  11. Save to DB  12. Cleanup
    """
    from modules import trend_fetcher, script_generator, voice_generator
    from modules import footage_fetcher, video_assembler, thumbnail_maker
    from modules import seo_generator, shorts_maker
    from modules.uploader import youtube_uploader

    ch_name = channel_config.get("channel", {}).get("name", "UpperCut")
    logger.info(f"{'='*60}")
    logger.info(f"PIPELINE START — {ch_name} — {datetime.now():%Y-%m-%d %H:%M}")
    logger.info(f"{'='*60}")

    # Get channel_id
    db = get_db()
    row = db.execute("SELECT id FROM channels WHERE name=?", (ch_name,)).fetchone()
    channel_id = row["id"] if row else 1
    db.close()

    # ── Step 1: Fetch trending topics ────────────────────────────────────
    logger.info("Step 1/12: Fetching trending topics...")
    topics = with_retry(
        lambda: trend_fetcher.get_topics(channel_config),
        "Trend fetching",
    )
    if not topics:
        logger.error("No topics fetched — pipeline aborted")
        return

    # ── Step 2: Pick best topic ──────────────────────────────────────────
    topic = trend_fetcher.select_best_topic(topics)
    logger.info(f"Step 2/12: Selected topic — {topic['text'][:60]}")

    # Save topic to DB
    trend_fetcher.save_topics_to_db(topics, channel_id)

    # Mark topic as used
    db = get_db()
    db.execute(
        "UPDATE topics SET used=1 WHERE channel_id=? AND topic_text=?",
        (channel_id, topic["text"]),
    )
    db.commit()

    # Create video record
    db.execute(
        "INSERT INTO videos (channel_id, title, status, format) VALUES (?, ?, 'generating', 'long')",
        (channel_id, topic["text"]),
    )
    db.commit()
    video_row = db.execute("SELECT MAX(id) as id FROM videos").fetchone()
    video_db_id = video_row["id"]
    db.close()

    if _shutting_down:
        return

    # ── Step 3: Generate script ──────────────────────────────────────────
    logger.info("Step 3/12: Generating Urdu script...")
    script = with_retry(
        lambda: script_generator.generate(topic, channel_config),
        "Script generation",
    )
    if not script:
        _update_video_status(video_db_id, "failed")
        return

    # Save script to DB
    db = get_db()
    db.execute("UPDATE videos SET script=?, cost_usd=? WHERE id=?",
               (script.text, script.cost_usd, video_db_id))
    db.commit()
    db.close()

    if _shutting_down:
        return

    # ── Step 4: Generate voiceover ───────────────────────────────────────
    logger.info("Step 4/12: Generating voiceover...")
    audio = with_retry(
        lambda: voice_generator.generate(script.text),
        "Voice generation",
    )
    if not audio:
        _update_video_status(video_db_id, "failed")
        return

    if _shutting_down:
        return

    # ── Step 5: Fetch stock footage ──────────────────────────────────────
    logger.info("Step 5/12: Fetching stock footage...")
    footage = with_retry(
        lambda: footage_fetcher.fetch(script.footage_keywords),
        "Footage fetching",
    )
    if not footage:
        footage = []  # Non-fatal — assembler handles missing footage

    if _shutting_down:
        return

    # ── Step 6: Assemble long-form video ─────────────────────────────────
    logger.info("Step 6/12: Assembling long-form video...")
    video = with_retry(
        lambda: video_assembler.assemble(audio["path"], footage, script),
        "Video assembly",
    )
    if not video:
        _update_video_status(video_db_id, "failed")
        return

    # Add subtitles
    logger.info("Step 6b: Adding subtitles...")
    video_assembler.add_subtitles_to_video(video["path"], audio["path"])

    # Update DB
    db = get_db()
    db.execute(
        "UPDATE videos SET video_path=?, duration_seconds=?, status='rendered' WHERE id=?",
        (str(video["path"]), video["duration_seconds"], video_db_id),
    )
    db.commit()
    db.close()

    if _shutting_down:
        return

    # ── Step 7: Create Shorts ────────────────────────────────────────────
    logger.info("Step 7/12: Creating YouTube Short...")
    short = with_retry(
        lambda: shorts_maker.create(video["path"], video["duration_seconds"]),
        "Shorts creation",
    )

    if _shutting_down:
        return

    # ── Step 8: Generate thumbnails ──────────────────────────────────────
    logger.info("Step 8/12: Creating thumbnails (A/B)...")
    # Use first footage file as background if it's an image
    bg_img = None
    for fp in footage:
        if fp.suffix.lower() in (".jpg", ".jpeg", ".png"):
            bg_img = fp
            break
    thumbnails = with_retry(
        lambda: thumbnail_maker.create(topic, script, bg_img),
        "Thumbnail creation",
    )
    if not thumbnails:
        thumbnails = []

    # Update DB
    if thumbnails:
        db = get_db()
        db.execute("UPDATE videos SET thumbnail_path=? WHERE id=?",
                    (str(thumbnails[0]), video_db_id))
        db.commit()
        db.close()

    if _shutting_down:
        return

    # ── Step 9: Generate SEO metadata ────────────────────────────────────
    logger.info("Step 9/12: Generating SEO metadata...")
    metadata = with_retry(
        lambda: seo_generator.generate(topic, script, channel_config),
        "SEO generation",
    )
    if not metadata:
        _update_video_status(video_db_id, "failed")
        return

    if _shutting_down:
        return

    # ── Step 10: Upload to YouTube ───────────────────────────────────────
    logger.info("Step 10/12: Uploading long-form video to YouTube...")
    yt_video_id = with_retry(
        lambda: youtube_uploader.upload(
            video["path"], metadata,
            thumbnails[0] if thumbnails else None,
        ),
        "YouTube upload (long)",
    )

    shorts_yt_id = None
    if short:
        logger.info("Step 10b: Uploading Short to YouTube...")
        shorts_seo = seo_generator.generate_shorts_seo(topic, channel_config)
        shorts_yt_id = with_retry(
            lambda: youtube_uploader.upload(
                short["path"], shorts_seo,
                thumbnails[1] if len(thumbnails) > 1 else None,
                is_short=True,
            ),
            "YouTube upload (short)",
        )

    # ── Step 11: Save upload records ─────────────────────────────────────
    logger.info("Step 11/12: Saving to database...")
    db = get_db()
    if yt_video_id:
        db.execute(
            "INSERT INTO uploads (video_id, channel_id, youtube_video_id, youtube_url, title, description, tags) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                video_db_id, channel_id, yt_video_id,
                f"https://www.youtube.com/watch?v={yt_video_id}",
                metadata.title_urdu, metadata.description,
                ",".join(metadata.tags),
            ),
        )
        db.execute("UPDATE videos SET status='uploaded' WHERE id=?", (video_db_id,))

        # Add to playlist
        playlist_id = youtube_uploader.ensure_playlist(metadata.playlist_category)
        if playlist_id:
            youtube_uploader.add_to_playlist(yt_video_id, playlist_id)
    else:
        db.execute("UPDATE videos SET status='upload_failed' WHERE id=?", (video_db_id,))

    db.commit()
    db.close()

    # ── Step 12: Cleanup temp files ──────────────────────────────────────
    logger.info("Step 12/12: Cleaning up temporary files...")
    footage_fetcher.cleanup_footage(footage)
    # Keep audio/video in output dirs for debugging — they'll be rotated

    status = "SUCCESS" if yt_video_id else "PARTIAL (upload failed)"
    logger.info(f"{'='*60}")
    logger.info(f"PIPELINE {status} — {topic['text'][:50]}")
    if yt_video_id:
        logger.info(f"YouTube: https://www.youtube.com/watch?v={yt_video_id}")
    if shorts_yt_id:
        logger.info(f"Short:   https://www.youtube.com/watch?v={shorts_yt_id}")
    logger.info(f"{'='*60}")

    # ── Send email alerts ────────────────────────────────────────────
    try:
        from alerts import email_alerts
        if yt_video_id:
            yt_url = f"https://www.youtube.com/watch?v={yt_video_id}"
            shorts_url = f"https://www.youtube.com/watch?v={shorts_yt_id}" if shorts_yt_id else None
            email_alerts.pipeline_success(
                ch_name, topic["text"],
                youtube_url=yt_url, shorts_url=shorts_url,
                duration_mins=video.get("duration_seconds", 0) / 60,
                cost_usd=script.cost_usd,
            )
        else:
            email_alerts.pipeline_failure(ch_name, topic["text"], "Upload failed", "Video upload to YouTube failed after retries")
    except Exception as e:
        logger.debug(f"Alert email skipped: {e}")

    # ── Intelligence Engine: learn from past performance ─────────────
    logger.info("Running Intelligence Engine...")
    try:
        from intelligence import run_intelligence
        strategy = run_intelligence(channel_id)
        if strategy:
            logger.info(f"Strategy updated: upload_time={strategy.get('best_upload_time')}, "
                        f"length={strategy.get('best_video_length')}min")
    except Exception as e:
        logger.warning(f"Intelligence engine failed (non-fatal): {e}")


def _update_video_status(video_id: int, status: str):
    """Update video status in the database."""
    try:
        db = get_db()
        db.execute("UPDATE videos SET status=? WHERE id=?", (status, video_id))
        db.commit()
        db.close()
    except Exception:
        pass


# ── Resume failed/pending kids video ─────────────────────────────────────────

def resume_kids_video(video_id: int, channel_config: dict):
    """
    Resume a failed kids video — skip steps that already have artifacts.
    Reuses: script from DB, audio files on disk, cached animation clips.
    """
    from modules import kids_script_generator, kids_voice_generator
    from modules import image_generator, kids_music_fetcher
    from modules import video_assembler, shorts_maker
    from modules import kids_thumbnail_maker, kids_seo_generator
    from modules.uploader import youtube_uploader

    db = get_db()
    row = db.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone()
    if not row:
        logger.error(f"Resume: video #{video_id} not found")
        db.close()
        return
    video_rec = dict(row)
    channel_id = video_rec["channel_id"]
    title = video_rec["title"]
    db.execute("UPDATE videos SET status='generating' WHERE id=?", (video_id,))
    db.commit()
    db.close()

    ch_name = channel_config.get("channel", {}).get("name", "KiddoWorld")
    topic = {"text": title, "type": "song_rhyme", "concept": "", "source": "retry"}

    logger.info(f"{'='*60}")
    logger.info(f"RESUME VIDEO #{video_id} — {title} — {datetime.now():%Y-%m-%d %H:%M}")
    logger.info(f"{'='*60}")

    # ── Step 2: Generate fresh script (always regenerate for correct content) ──
    _update_progress(ch_name, title, 2, "Generating script")
    logger.info(f"Resume: Generating fresh script for '{title}'")
    scripts = with_retry(
        lambda: kids_script_generator.generate_all_languages(topic, channel_config),
        "Kids script generation",
    )
    if not scripts or "english" not in scripts:
        _update_video_status(video_id, "failed")
        return
    script = scripts["english"]
    db = get_db()
    db.execute("UPDATE videos SET script=?, cost_usd=? WHERE id=?",
               (script.text, script.cost_usd, video_id))
    db.commit()
    db.close()

    if _shutting_down:
        return

    # ── Step 3: Generate fresh voiceover (always fresh for correct content) ──
    _update_progress(ch_name, title, 3, "Generating voiceover")
    logger.info(f"Resume: Generating fresh voice for '{title}'")
    audio = with_retry(
        lambda: kids_voice_generator.generate(script.text, language="english"),
        "Kids voice generation",
    )
    if not audio:
        _update_video_status(video_id, "failed")
        return

    if _shutting_down:
        return

    # ── Step 4: Generate cartoon images (DALL-E 3 + Ken Burns) ─────
    _update_progress(ch_name, title, 4, "Generating images")
    logger.info("Resume: Generating cartoon images (cached = FREE)")
    images = with_retry(
        lambda: image_generator.generate_images_for_script(
            script.animation_prompts,
        ),
        "Image generation",
    )
    if not images:
        images = []

    if _shutting_down:
        return

    # ── Steps 5-12: Same as normal pipeline ────────────────────────
    _update_progress(ch_name, title, 5, "Fetching music")
    logger.info("Kids Step 5/12: Fetching kids music...")
    music_path = with_retry(
        lambda: kids_music_fetcher.fetch_kids_music(
            target_duration_mins=script.estimated_duration_mins
        ),
        "Kids music fetch",
    )

    if _shutting_down:
        return

    _update_progress(ch_name, title, 6, "Assembling video")
    logger.info("Kids Step 6/12: Assembling kids video...")
    video = with_retry(
        lambda: video_assembler.assemble(audio["path"], images, script, kids=True),
        "Kids video assembly",
    )
    if not video:
        _update_video_status(video_id, "failed")
        return

    db = get_db()
    db.execute(
        "UPDATE videos SET video_path=?, duration_seconds=?, status='rendered' WHERE id=?",
        (str(video["path"]), video["duration_seconds"], video_id),
    )
    db.commit()
    db.close()

    if _shutting_down:
        return

    _update_progress(ch_name, title, 7, "Creating Short")
    logger.info("Kids Step 7/12: Creating YouTube Short...")
    short = with_retry(
        lambda: shorts_maker.create(video["path"], video["duration_seconds"], kids=True),
        "Kids Shorts creation",
    )

    if _shutting_down:
        return

    _update_progress(ch_name, title, 8, "Creating thumbnails")
    logger.info("Kids Step 8/12: Creating kids thumbnails...")
    thumbnails = with_retry(
        lambda: kids_thumbnail_maker.create(topic, script),
        "Kids thumbnail creation",
    )
    if not thumbnails:
        thumbnails = []
    if thumbnails:
        db = get_db()
        db.execute("UPDATE videos SET thumbnail_path=? WHERE id=?",
                    (str(thumbnails[0]), video_id))
        db.commit()
        db.close()

    if _shutting_down:
        return

    _update_progress(ch_name, title, 9, "Generating SEO")
    logger.info("Kids Step 9/12: Generating kids SEO metadata...")
    metadata = with_retry(
        lambda: kids_seo_generator.generate(topic, script, channel_config),
        "Kids SEO generation",
    )
    if not metadata:
        _update_video_status(video_id, "failed")
        return

    if _shutting_down:
        return

    _update_progress(ch_name, title, 10, "Uploading to YouTube")
    logger.info("Kids Step 10/12: Uploading to YouTube (made_for_kids=True)...")
    yt_video_id = with_retry(
        lambda: youtube_uploader.upload(
            video["path"], metadata,
            thumbnails[0] if thumbnails else None,
            category="entertainment",
            made_for_kids=True,
        ),
        "YouTube upload (kids long)",
    )

    shorts_yt_id = None
    if short:
        logger.info("Kids Step 10b: Uploading Short...")
        shorts_seo = kids_seo_generator.generate_shorts_seo(topic, channel_config)
        shorts_yt_id = with_retry(
            lambda: youtube_uploader.upload(
                short["path"], shorts_seo,
                thumbnails[1] if len(thumbnails) > 1 else None,
                is_short=True, category="entertainment", made_for_kids=True,
            ),
            "YouTube upload (kids short)",
        )

    _update_progress(ch_name, title, 11, "Saving to database")
    logger.info("Kids Step 11/12: Saving to database...")
    db = get_db()
    if yt_video_id:
        db.execute(
            "INSERT INTO uploads (video_id, channel_id, youtube_video_id, youtube_url, title, description, tags) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (video_id, channel_id, yt_video_id,
             f"https://www.youtube.com/watch?v={yt_video_id}",
             metadata.title, metadata.description, ",".join(metadata.tags)),
        )
        db.execute("UPDATE videos SET status='uploaded' WHERE id=?", (video_id,))
    else:
        db.execute("UPDATE videos SET status='upload_failed' WHERE id=?", (video_id,))
    db.commit()
    db.close()

    _update_progress(ch_name, title, 12, "Cleanup")
    logger.info("Kids Step 12/12: Cleanup...")
    image_generator.cleanup_old_images(days=30)

    status = "SUCCESS" if yt_video_id else "PARTIAL"
    _update_progress(ch_name, title, 12, "Done", status="done" if yt_video_id else "partial")
    logger.info(f"{'='*60}")
    logger.info(f"RESUME {status} — #{video_id} {title[:50]}")
    logger.info(f"{'='*60}")

    try:
        from alerts import email_alerts
        if yt_video_id:
            email_alerts.pipeline_success(ch_name, title, f"https://www.youtube.com/watch?v={yt_video_id}")
    except Exception:
        pass

    # Immediately process next queue item (no 5-min wait)
    logger.info("Checking queue for next video...")
    _release_lock()
    process_queue()


# ── Kids Pipeline (KiddoWorld) ───────────────────────────────────────────────
def run_kids_pipeline(channel_config: dict):
    """
    Execute the kids video creation pipeline for KiddoWorld:
    1. Pick topic  2. Generate script (+ translations)  3. Kids voiceover
    4. Generate animation clips (fal.ai)  5. Fetch kids music
    6. Assemble video  7. Create Short  8. Kids thumbnails
    9. Kids SEO  10. Upload (made_for_kids=True)  11. Save to DB  12. Cleanup
    """
    from modules import kids_script_generator, kids_voice_generator
    from modules import image_generator, kids_music_fetcher
    from modules import video_assembler, shorts_maker
    from modules import kids_thumbnail_maker, kids_seo_generator
    from modules.uploader import youtube_uploader

    ch_name = channel_config.get("channel", {}).get("name", "KiddoWorld")

    # ── Pipeline lock: only one video at a time ────────────────────
    db = get_db()
    generating = db.execute(
        "SELECT COUNT(*) as c FROM videos WHERE status='generating'"
    ).fetchone()["c"]
    if generating > 0:
        logger.info(f"Pipeline locked — {generating} video(s) already generating. Skipping.")
        db.close()
        return
    db.close()

    logger.info(f"{'='*60}")
    logger.info(f"KIDS PIPELINE START — {ch_name} — {datetime.now():%Y-%m-%d %H:%M}")
    logger.info(f"{'='*60}")

    # Get channel_id
    db = get_db()
    row = db.execute("SELECT id FROM channels WHERE name=?", (ch_name,)).fetchone()
    channel_id = row["id"] if row else 2
    db.close()

    # ── Step 1: Pick kids content topic ───────────────────────────────
    _update_progress(ch_name, "", 1, "Picking topic")
    logger.info("Kids Step 1/12: Picking content topic...")
    topic = kids_script_generator.get_kids_topic(channel_config, channel_id)
    logger.info(f"Kids Step 1/12: Selected — {topic['text']}")

    # Save topic to DB
    db = get_db()
    db.execute(
        "INSERT INTO topics (channel_id, topic_text, source, performance_score) VALUES (?, ?, ?, ?)",
        (channel_id, topic["text"], topic.get("source", "evergreen"), topic.get("score", 80)),
    )
    db.execute(
        "UPDATE topics SET used=1 WHERE channel_id=? AND topic_text=?",
        (channel_id, topic["text"]),
    )
    db.commit()

    # Create video record
    db.execute(
        "INSERT INTO videos (channel_id, title, status, format) VALUES (?, ?, 'generating', 'long')",
        (channel_id, topic["text"]),
    )
    db.commit()
    video_row = db.execute("SELECT MAX(id) as id FROM videos").fetchone()
    video_db_id = video_row["id"]
    db.close()

    if _shutting_down:
        return

    # ── Step 2: Generate kids script (English + translations) ─────────
    _update_progress(ch_name, topic["text"], 2, "Generating script")
    logger.info("Kids Step 2/12: Generating kids script...")
    scripts = with_retry(
        lambda: kids_script_generator.generate_all_languages(topic, channel_config),
        "Kids script generation",
    )
    if not scripts or "english" not in scripts:
        _update_video_status(video_db_id, "failed")
        return

    script = scripts["english"]

    # Save script to DB
    db = get_db()
    db.execute("UPDATE videos SET script=?, cost_usd=? WHERE id=?",
               (script.text, script.cost_usd, video_db_id))
    db.commit()
    db.close()

    if _shutting_down:
        return

    # ── Step 3: Generate kids voiceover ───────────────────────────────
    _update_progress(ch_name, topic["text"], 3, "Generating voiceover")
    logger.info("Kids Step 3/12: Generating kids voiceover...")
    audio = with_retry(
        lambda: kids_voice_generator.generate(script.text, language="english"),
        "Kids voice generation",
    )
    if not audio:
        _update_video_status(video_db_id, "failed")
        return

    if _shutting_down:
        return

    # ── Step 4: Generate cartoon images (DALL-E 3) ───────────────────
    _update_progress(ch_name, topic["text"], 4, "Generating images")
    logger.info("Kids Step 4/12: Generating cartoon images (DALL-E 3)...")

    images = with_retry(
        lambda: image_generator.generate_images_for_script(
            script.animation_prompts,
        ),
        "Image generation",
    )
    if not images:
        images = []  # Non-fatal — assembler uses fallback backgrounds

    if _shutting_down:
        return

    # ── Step 5: Fetch kids background music ───────────────────────────
    _update_progress(ch_name, topic["text"], 5, "Fetching music")
    logger.info("Kids Step 5/12: Fetching kids music...")
    music_path = with_retry(
        lambda: kids_music_fetcher.fetch_kids_music(
            target_duration_mins=script.estimated_duration_mins
        ),
        "Kids music fetch",
    )

    if _shutting_down:
        return

    # ── Step 6: Assemble kids video ───────────────────────────────────
    _update_progress(ch_name, topic["text"], 6, "Assembling video")
    logger.info("Kids Step 6/12: Assembling kids video...")
    video = with_retry(
        lambda: video_assembler.assemble(audio["path"], images, script, kids=True),
        "Kids video assembly",
    )
    if not video:
        _update_video_status(video_db_id, "failed")
        return

    # Update DB
    db = get_db()
    db.execute(
        "UPDATE videos SET video_path=?, duration_seconds=?, status='rendered' WHERE id=?",
        (str(video["path"]), video["duration_seconds"], video_db_id),
    )
    db.commit()
    db.close()

    if _shutting_down:
        return

    # ── Step 7: Create Kids Shorts ────────────────────────────────────
    _update_progress(ch_name, topic["text"], 7, "Creating Short")
    logger.info("Kids Step 7/12: Creating YouTube Short...")
    short = with_retry(
        lambda: shorts_maker.create(video["path"], video["duration_seconds"], kids=True),
        "Kids Shorts creation",
    )

    if _shutting_down:
        return

    # ── Step 8: Generate kids thumbnails ──────────────────────────────
    _update_progress(ch_name, topic["text"], 8, "Creating thumbnails")
    logger.info("Kids Step 8/12: Creating kids thumbnails (A/B)...")
    thumbnails = with_retry(
        lambda: kids_thumbnail_maker.create(topic, script),
        "Kids thumbnail creation",
    )
    if not thumbnails:
        thumbnails = []

    if thumbnails:
        db = get_db()
        db.execute("UPDATE videos SET thumbnail_path=? WHERE id=?",
                    (str(thumbnails[0]), video_db_id))
        db.commit()
        db.close()

    if _shutting_down:
        return

    # ── Step 9: Generate kids SEO metadata ────────────────────────────
    _update_progress(ch_name, topic["text"], 9, "Generating SEO")
    logger.info("Kids Step 9/12: Generating kids SEO metadata...")
    metadata = with_retry(
        lambda: kids_seo_generator.generate(topic, script, channel_config),
        "Kids SEO generation",
    )
    if not metadata:
        _update_video_status(video_db_id, "failed")
        return

    if _shutting_down:
        return

    # ── Step 10: Upload to YouTube (COPPA: made_for_kids=True) ───────
    _update_progress(ch_name, topic["text"], 10, "Uploading to YouTube")
    logger.info("Kids Step 10/12: Uploading to YouTube (made_for_kids=True)...")
    yt_video_id = with_retry(
        lambda: youtube_uploader.upload(
            video["path"], metadata,
            thumbnails[0] if thumbnails else None,
            category="entertainment",
            made_for_kids=True,
        ),
        "YouTube upload (kids long)",
    )

    shorts_yt_id = None
    if short:
        logger.info("Kids Step 10b: Uploading Short...")
        shorts_seo = kids_seo_generator.generate_shorts_seo(topic, channel_config)
        shorts_yt_id = with_retry(
            lambda: youtube_uploader.upload(
                short["path"], shorts_seo,
                thumbnails[1] if len(thumbnails) > 1 else None,
                is_short=True,
                category="entertainment",
                made_for_kids=True,
            ),
            "YouTube upload (kids short)",
        )

    # ── Step 11: Save upload records ──────────────────────────────────
    _update_progress(ch_name, topic["text"], 11, "Saving to database")
    logger.info("Kids Step 11/12: Saving to database...")
    db = get_db()
    if yt_video_id:
        db.execute(
            "INSERT INTO uploads (video_id, channel_id, youtube_video_id, youtube_url, title, description, tags) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                video_db_id, channel_id, yt_video_id,
                f"https://www.youtube.com/watch?v={yt_video_id}",
                metadata.title, metadata.description,
                ",".join(metadata.tags),
            ),
        )
        db.execute("UPDATE videos SET status='uploaded' WHERE id=?", (video_db_id,))

        playlist_id = youtube_uploader.ensure_playlist(metadata.playlist_category)
        if playlist_id:
            youtube_uploader.add_to_playlist(yt_video_id, playlist_id)
    else:
        db.execute("UPDATE videos SET status='upload_failed' WHERE id=?", (video_db_id,))

    db.commit()
    db.close()

    # ── Step 12: Cleanup ──────────────────────────────────────────────
    _update_progress(ch_name, topic["text"], 12, "Cleanup")
    logger.info("Kids Step 12/12: Cleanup...")
    image_generator.cleanup_old_images(days=30)

    status = "SUCCESS" if yt_video_id else "PARTIAL (upload failed)"
    _update_progress(ch_name, topic["text"], 12, "Done", status="done" if yt_video_id else "partial")
    logger.info(f"{'='*60}")
    logger.info(f"KIDS PIPELINE {status} — {topic['text'][:50]}")
    if yt_video_id:
        logger.info(f"YouTube: https://www.youtube.com/watch?v={yt_video_id}")
    if shorts_yt_id:
        logger.info(f"Short:   https://www.youtube.com/watch?v={shorts_yt_id}")
    logger.info(f"{'='*60}")

    # Send email alerts
    try:
        from alerts import email_alerts
        if yt_video_id:
            yt_url = f"https://www.youtube.com/watch?v={yt_video_id}"
            shorts_url = f"https://www.youtube.com/watch?v={shorts_yt_id}" if shorts_yt_id else None
            email_alerts.pipeline_success(
                ch_name, topic["text"],
                youtube_url=yt_url, shorts_url=shorts_url,
                duration_mins=video.get("duration_seconds", 0) / 60,
                cost_usd=script.cost_usd,
            )
        else:
            email_alerts.pipeline_failure(ch_name, topic["text"], "Upload failed", "Kids video upload failed after retries")
    except Exception as e:
        logger.debug(f"Alert email skipped: {e}")

    # Intelligence Engine
    try:
        from intelligence import run_intelligence
        run_intelligence(channel_id)
    except Exception as e:
        logger.warning(f"Intelligence engine failed (non-fatal): {e}")

    # Immediately process next queue item (no 5-min wait)
    logger.info("Checking queue for next video...")
    _release_lock()
    process_queue()


# ── Queue System ─────────────────────────────────────────────────────────────

import os
import shutil

LOCK_FILE = Path("/tmp/uppercut_pipeline.lock")
QUEUE_PAUSED_FILE = BASE_DIR / "output" / ".queue_paused"


def _is_pipeline_busy() -> bool:
    """Check if another video is currently being processed."""
    if LOCK_FILE.exists():
        # Stale lock check — if lock is older than 3 hours, remove it
        try:
            age_hours = (time.time() - LOCK_FILE.stat().st_mtime) / 3600
            if age_hours > 3:
                logger.warning(f"Removing stale lock file ({age_hours:.1f}h old)")
                LOCK_FILE.unlink()
                return False
        except Exception:
            pass
        return True
    return False


def _acquire_lock(queue_id: int) -> bool:
    """Create lock file. Returns True on success."""
    if _is_pipeline_busy():
        return False
    try:
        LOCK_FILE.write_text(str(queue_id))
        return True
    except Exception:
        return False


def _release_lock():
    """Remove lock file."""
    try:
        LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def _reset_stuck_videos():
    """Reset any stuck 'generating' videos to 'failed' on startup."""
    db = get_db()
    stuck = db.execute(
        "UPDATE videos SET status='failed' WHERE status='generating'"
    ).rowcount
    db.commit()
    db.close()
    _release_lock()
    if stuck:
        logger.warning(f"Reset {stuck} stuck 'generating' video(s) to 'failed'")


def add_to_queue(channel_name: str, fmt: str = "long", topic: str | None = None,
                 priority: int = 5, video_id: int | None = None):
    """Add a new video to the processing queue."""
    db = get_db()
    ch = db.execute("SELECT id FROM channels WHERE name=?", (channel_name,)).fetchone()
    if not ch:
        logger.error(f"Channel not found: {channel_name}")
        db.close()
        return

    if not topic:
        # Auto-pick a topic
        from modules import kids_script_generator
        import yaml as _yaml
        for f in CHANNEL_DIR.glob("kiddoworld*.yaml"):
            if not f.name.startswith("._"):
                with open(f) as fh:
                    cfg = _yaml.safe_load(fh)
                t = kids_script_generator.get_kids_topic(cfg, ch["id"])
                topic = t["text"]
                break
        if not topic:
            topic = f"Auto topic {datetime.now():%H:%M}"

    db.execute(
        "INSERT INTO queue (channel_id, video_id, topic, format, priority) VALUES (?, ?, ?, ?, ?)",
        (ch["id"], video_id, topic, fmt, priority),
    )
    db.commit()
    db.close()
    logger.info(f"Queued: {topic} (format={fmt}, priority={priority})")


def process_queue():
    """Process one item from queue. Only runs if pipeline is not busy."""
    if QUEUE_PAUSED_FILE.exists():
        logger.debug("Queue paused — skipping")
        return

    if _is_pipeline_busy():
        logger.debug("Pipeline busy — skipping queue check")
        return

    _reset_stuck_videos()

    db = get_db()

    # First check for retries (priority 8+)
    retries = db.execute(
        "SELECT id, channel_id FROM videos WHERE status='retry' ORDER BY id ASC LIMIT 1"
    ).fetchone()
    db.close()

    if retries:
        if not _acquire_lock(-1):
            return
        try:
            kiddo_cfg = _load_kiddoworld_config()
            if kiddo_cfg:
                logger.info(f"Processing retry: video #{retries['id']}")
                resume_kids_video(retries["id"], kiddo_cfg)
        except Exception as e:
            logger.error(f"Retry failed for video #{retries['id']}: {e}")
            _update_video_status(retries["id"], "failed")
        finally:
            _release_lock()
        return

    # Then check queue
    db = get_db()
    item = db.execute(
        "SELECT * FROM queue WHERE status='waiting' ORDER BY priority DESC, created_at ASC LIMIT 1"
    ).fetchone()

    if not item:
        db.close()
        return

    # Mark as processing
    db.execute("UPDATE queue SET status='processing', started_at=CURRENT_TIMESTAMP WHERE id=?",
               (item["id"],))
    db.commit()
    db.close()

    if not _acquire_lock(item["id"]):
        # Another process grabbed it
        db2 = get_db()
        db2.execute("UPDATE queue SET status='waiting' WHERE id=?", (item["id"],))
        db2.commit()
        db2.close()
        return

    try:
        kiddo_cfg = _load_kiddoworld_config()
        if kiddo_cfg:
            if item["video_id"]:
                # Retry existing video
                resume_kids_video(item["video_id"], kiddo_cfg)
            else:
                # New video
                run_kids_pipeline(kiddo_cfg)

        db3 = get_db()
        db3.execute("UPDATE queue SET status='completed', completed_at=CURRENT_TIMESTAMP WHERE id=?",
                     (item["id"],))
        db3.commit()
        db3.close()
    except Exception as e:
        logger.error(f"Queue item #{item['id']} failed: {e}")
        db3 = get_db()
        db3.execute("UPDATE queue SET status='failed', retry_count=retry_count+1 WHERE id=?",
                     (item["id"],))
        db3.commit()
        db3.close()
    finally:
        _release_lock()


def _load_kiddoworld_config() -> dict | None:
    """Load KiddoWorld channel config."""
    for f in CHANNEL_DIR.glob("kiddoworld*.yaml"):
        if not f.name.startswith("._"):
            return load_channel_config(f)
    return None


# ── Storage Cleanup ──────────────────────────────────────────────────────────

def cleanup_old_files():
    """Delete old generated files to save disk space."""
    import glob

    now = time.time()
    deleted = 0

    # Generated images — delete after 30 days
    img_dir = BASE_DIR / "output" / "images"
    if img_dir.exists():
        for f in img_dir.glob("img_*"):
            if (now - f.stat().st_mtime) > 30 * 86400:
                f.unlink()
                deleted += 1

    # Audio files — delete after 7 days
    audio_dir = BASE_DIR / "output" / "audio"
    for f in audio_dir.glob("*.mp3"):
        if (now - f.stat().st_mtime) > 7 * 86400:
            f.unlink()
            deleted += 1

    # Assembled videos — delete after 30 days (YouTube has the copy)
    video_dir = BASE_DIR / "output" / "videos"
    for f in video_dir.glob("*.mp4"):
        if (now - f.stat().st_mtime) > 30 * 86400:
            f.unlink()
            deleted += 1
            # Clear local path in DB but keep the record
            db = get_db()
            db.execute("UPDATE videos SET video_path=NULL WHERE video_path LIKE ?",
                       (f"%{f.name}",))
            db.commit()
            db.close()

    # Footage — delete after 7 days
    footage_dir = BASE_DIR / "output" / "footage"
    for f in footage_dir.glob("*"):
        if f.is_file() and (now - f.stat().st_mtime) > 7 * 86400:
            f.unlink()
            deleted += 1

    if deleted:
        logger.info(f"Cleanup: deleted {deleted} old files")

    # Check disk space
    check_disk_space()


def check_disk_space():
    """Alert if disk usage > 80%."""
    total, used, free = shutil.disk_usage("/")
    usage_pct = (used / total) * 100
    free_gb = free / (1024**3)
    logger.info(f"Disk: {usage_pct:.1f}% used, {free_gb:.1f} GB free")
    if usage_pct > 80:
        try:
            from alerts.email_alerts import low_api_balance
            low_api_balance("disk_space", f"{usage_pct:.1f}% used — only {free_gb:.1f} GB free")
        except Exception:
            pass


# ── Daily Schedule ───────────────────────────────────────────────────────────

def _send_daily_summary():
    """Gather stats and send a daily summary email for each channel."""
    try:
        from alerts import email_alerts

        db = get_db()
        channels = db.execute("SELECT id, name FROM channels WHERE is_active=1").fetchall()
        today = datetime.now().strftime("%Y-%m-%d")

        for ch in channels:
            ch_id, ch_name = ch["id"], ch["name"]
            videos_made = db.execute(
                "SELECT COUNT(*) as c FROM videos WHERE channel_id=? AND DATE(created_at)=?",
                (ch_id, today),
            ).fetchone()["c"]
            videos_uploaded = db.execute(
                "SELECT COUNT(*) as c FROM uploads WHERE channel_id=? AND DATE(uploaded_at)=?",
                (ch_id, today),
            ).fetchone()["c"]
            total_views = db.execute(
                "SELECT COALESCE(SUM(views),0) as v FROM uploads WHERE channel_id=?",
                (ch_id,),
            ).fetchone()["v"]
            total_cost = db.execute(
                "SELECT COALESCE(SUM(cost_usd),0) as c FROM videos WHERE channel_id=? AND DATE(created_at)=?",
                (ch_id, today),
            ).fetchone()["c"]
            errors_count = db.execute(
                "SELECT COUNT(*) as c FROM errors WHERE channel_id=? AND DATE(created_at)=? AND resolved=0",
                (ch_id, today),
            ).fetchone()["c"]
            top_row = db.execute(
                "SELECT title FROM uploads WHERE channel_id=? ORDER BY views DESC LIMIT 1",
                (ch_id,),
            ).fetchone()
            top_video = top_row["title"] if top_row else "N/A"

            email_alerts.daily_summary(ch_name, {
                "videos_made": videos_made,
                "videos_uploaded": videos_uploaded,
                "total_views": total_views,
                "total_cost": total_cost,
                "errors": errors_count,
                "top_video": top_video,
            })

        db.close()
    except Exception as e:
        logger.warning(f"Daily summary email failed: {e}")


def start_scheduler():
    """Start the APScheduler with queue-based video processing."""
    _reset_stuck_videos()

    # Process queue immediately on startup (before scheduler blocks)
    logger.info("Running initial queue check...")
    try:
        process_queue()
    except Exception as e:
        logger.warning(f"Initial queue check failed: {e}")

    scheduler = BlockingScheduler(timezone="America/New_York")

    # Queue processor — check every 5 minutes
    scheduler.add_job(process_queue, "interval", minutes=5, id="queue_processor")

    # KiddoWorld schedule — 2 long + 3 shorts per day
    scheduler.add_job(lambda: add_to_queue("KiddoWorld", "long"),
                      "cron", hour=10, minute=0, id="kiddo_long_1")
    scheduler.add_job(lambda: add_to_queue("KiddoWorld", "long"),
                      "cron", hour=16, minute=0, id="kiddo_long_2")
    scheduler.add_job(lambda: add_to_queue("KiddoWorld", "short"),
                      "cron", hour=9, minute=0, id="kiddo_short_1")
    scheduler.add_job(lambda: add_to_queue("KiddoWorld", "short"),
                      "cron", hour=13, minute=0, id="kiddo_short_2")
    scheduler.add_job(lambda: add_to_queue("KiddoWorld", "short"),
                      "cron", hour=19, minute=0, id="kiddo_short_3")

    # Daily summary at 11 PM
    scheduler.add_job(_send_daily_summary, "cron", hour=23, minute=0, id="daily_summary")

    # Daily cleanup at midnight
    scheduler.add_job(cleanup_old_files, "cron", hour=0, minute=0, id="daily_cleanup")

    logger.info("Scheduler started:")
    logger.info("  Queue processor: every 5 minutes")
    logger.info("  KiddoWorld: 2 long (10:00, 16:00) + 3 short (09:00, 13:00, 19:00)")
    logger.info("  Daily summary: 23:00 | Cleanup: 00:00")
    logger.info("  Timezone: America/New_York")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        _release_lock()
        logger.info("Scheduler stopped")


# ── CLI ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="UpperCut YouTube Automation")
    parser.add_argument("--test", action="store_true", help="Run pipeline once and exit")
    parser.add_argument("--channel", type=str, help="Specific channel YAML to run")
    parser.add_argument("--init-db", action="store_true", help="Initialize database only")
    parser.add_argument("--intelligence", action="store_true", help="Run intelligence engine only")
    parser.add_argument("--dashboard", action="store_true", help="Start the web dashboard")
    parser.add_argument("--port", type=int, default=None, help="Dashboard port (default: 8080)")
    parser.add_argument("--queue-add", type=str, help="Add topic to queue manually")
    args = parser.parse_args()

    # Always initialize database
    init_database()

    if args.init_db:
        logger.info("Database initialized. Exiting.")
        return

    if args.intelligence:
        logger.info("Running Intelligence Engine (standalone)...")
        from intelligence import run_intelligence
        db = get_db()
        channels = db.execute("SELECT id, name FROM channels WHERE is_active=1").fetchall()
        db.close()
        for ch in channels:
            logger.info(f"Intelligence run for: {ch['name']}")
            run_intelligence(ch["id"])
        logger.info("Intelligence run complete.")
        return

    if args.dashboard:
        logger.info("Starting web dashboard...")
        from dashboard.app import start_dashboard
        start_dashboard(port=args.port)
        return

    if args.queue_add:
        add_to_queue("KiddoWorld", "long", topic=args.queue_add)
        logger.info(f"Added to queue: {args.queue_add}")
        return

    if args.test:
        logger.info("Running in TEST mode (single run)...")
        _reset_stuck_videos()
        if args.channel:
            cfg_path = CHANNEL_DIR / args.channel
        else:
            cfg_files = [f for f in CHANNEL_DIR.glob("*.yaml") if not f.name.startswith("._")]
            if not cfg_files:
                logger.error("No channel config found")
                return
            cfg_path = cfg_files[0]

        config = load_channel_config(cfg_path)
        run_pipeline(config)
    else:
        start_scheduler()


if __name__ == "__main__":
    main()
