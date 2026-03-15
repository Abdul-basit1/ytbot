"""
UpperCut — Strategy Optimizer (Phase 2: Intelligence Engine)
Takes a PerformanceReport and persists optimized strategy settings
to the strategy table. These settings are then consumed by the
pipeline (trend_fetcher, scheduler, etc.) to improve future videos.
"""

from __future__ import annotations

import json
from typing import Dict, Optional

from loguru import logger

from config import get_db
from intelligence.performance_analyzer import PerformanceReport


def optimize(report: PerformanceReport) -> Dict:
    """
    Convert a PerformanceReport into concrete strategy updates
    and persist them to the strategy table.

    Args:
        report: analyzed performance data

    Returns:
        Dict of the strategy values that were saved.
    """
    if not report or report.total_videos_analyzed == 0:
        logger.info("No performance data — skipping strategy optimization")
        return {}

    channel_id = report.channel_id

    # Build the strategy record
    strategy = {
        "best_upload_time": _format_upload_time(report.best_upload_hour),
        "best_video_length": report.best_video_length_mins or 8,
        "best_niche": report.best_niche,
        "best_thumbnail_style": _infer_thumbnail_style(report),
        "best_script_style": report.best_script_style,
        "top_performing_keywords": json.dumps(report.top_keywords[:15]) if report.top_keywords else None,
        "avg_views": round(report.avg_views, 2),
        "avg_ctr": round(report.avg_ctr, 2),
        "avg_watch_time_pct": round(report.avg_watch_time_pct, 2),
        "recommendation_notes": "\n".join(report.recommendations) if report.recommendations else None,
    }

    _upsert_strategy(channel_id, strategy)

    # Also update the daily analytics summary
    _update_daily_analytics(channel_id, report)

    logger.info(
        f"Strategy optimized for channel {channel_id}: "
        f"upload_time={strategy['best_upload_time']}, "
        f"length={strategy['best_video_length']}min, "
        f"niche={strategy['best_niche']}"
    )

    return strategy


def _format_upload_time(hour: Optional[int]) -> str:
    """Convert hour (0-23) to HH:MM string."""
    if hour is None:
        return "18:00"  # Default prime time in Pakistan
    return f"{hour:02d}:00"


def _infer_thumbnail_style(report: PerformanceReport) -> Optional[str]:
    """
    Infer best thumbnail style from CTR data.
    (In future phases this will compare A/B thumbnail variants.)
    """
    if report.avg_ctr >= 6:
        return "high_contrast_emotional"
    elif report.avg_ctr >= 4:
        return "bold_text_overlay"
    elif report.avg_ctr >= 2:
        return "standard_with_face"
    else:
        return "needs_improvement"


def _upsert_strategy(channel_id: int, strategy: Dict):
    """Insert or update the strategy row for a channel."""
    db = get_db()
    try:
        existing = db.execute(
            "SELECT id FROM strategy WHERE channel_id=?", (channel_id,)
        ).fetchone()

        if existing:
            db.execute(
                """UPDATE strategy SET
                    best_upload_time=?, best_video_length=?, best_niche=?,
                    best_thumbnail_style=?, best_script_style=?,
                    top_performing_keywords=?, avg_views=?, avg_ctr=?,
                    avg_watch_time_pct=?, recommendation_notes=?,
                    last_updated=CURRENT_TIMESTAMP
                WHERE channel_id=?""",
                (
                    strategy["best_upload_time"], strategy["best_video_length"],
                    strategy["best_niche"], strategy["best_thumbnail_style"],
                    strategy["best_script_style"], strategy["top_performing_keywords"],
                    strategy["avg_views"], strategy["avg_ctr"],
                    strategy["avg_watch_time_pct"], strategy["recommendation_notes"],
                    channel_id,
                ),
            )
        else:
            db.execute(
                """INSERT INTO strategy
                    (channel_id, best_upload_time, best_video_length, best_niche,
                     best_thumbnail_style, best_script_style, top_performing_keywords,
                     avg_views, avg_ctr, avg_watch_time_pct, recommendation_notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    channel_id,
                    strategy["best_upload_time"], strategy["best_video_length"],
                    strategy["best_niche"], strategy["best_thumbnail_style"],
                    strategy["best_script_style"], strategy["top_performing_keywords"],
                    strategy["avg_views"], strategy["avg_ctr"],
                    strategy["avg_watch_time_pct"], strategy["recommendation_notes"],
                ),
            )

        db.commit()
    except Exception as e:
        logger.error(f"Failed to upsert strategy for channel {channel_id}: {e}")
    finally:
        db.close()


def _update_daily_analytics(channel_id: int, report: PerformanceReport):
    """Update the daily analytics summary table."""
    from datetime import date

    db = get_db()
    today = date.today().isoformat()

    try:
        existing = db.execute(
            "SELECT id FROM analytics WHERE channel_id=? AND date=?",
            (channel_id, today),
        ).fetchone()

        if existing:
            db.execute(
                """UPDATE analytics SET
                    total_views=?, videos_published=?
                WHERE channel_id=? AND date=?""",
                (
                    int(report.avg_views * report.total_videos_analyzed),
                    report.total_videos_analyzed,
                    channel_id, today,
                ),
            )
        else:
            db.execute(
                """INSERT INTO analytics (channel_id, date, total_views, videos_published)
                VALUES (?, ?, ?, ?)""",
                (
                    channel_id, today,
                    int(report.avg_views * report.total_videos_analyzed),
                    report.total_videos_analyzed,
                ),
            )

        db.commit()
    except Exception as e:
        logger.warning(f"Failed to update daily analytics: {e}")
    finally:
        db.close()


# ── Query helpers (used by other modules) ───────────────────────────────────

def get_strategy(channel_id: int) -> Optional[Dict]:
    """
    Retrieve the current strategy for a channel.
    Returns a dict with all strategy fields, or None if no strategy exists.
    """
    db = get_db()
    try:
        row = db.execute(
            "SELECT * FROM strategy WHERE channel_id=? ORDER BY last_updated DESC LIMIT 1",
            (channel_id,),
        ).fetchone()

        if not row:
            return None

        result = dict(row)

        # Parse JSON fields
        if result.get("top_performing_keywords"):
            try:
                result["top_performing_keywords"] = json.loads(result["top_performing_keywords"])
            except (json.JSONDecodeError, TypeError):
                result["top_performing_keywords"] = []

        return result

    except Exception as e:
        logger.warning(f"Failed to get strategy for channel {channel_id}: {e}")
        return None
    finally:
        db.close()


def get_top_performing_keywords(channel_id: int) -> list:
    """Return the list of top-performing keywords for a channel."""
    strategy = get_strategy(channel_id)
    if strategy and strategy.get("top_performing_keywords"):
        return strategy["top_performing_keywords"]
    return []
