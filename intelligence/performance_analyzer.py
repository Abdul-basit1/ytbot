"""
UpperCut — Performance Analyzer (Phase 2: Intelligence Engine)
Analyzes video_analytics data to discover patterns in what drives
views, CTR, watch time, and subscriber growth.

Produces a PerformanceReport that the strategy optimizer consumes.
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from loguru import logger

from config import get_db


@dataclass
class PerformanceReport:
    """Aggregated insights derived from video analytics."""
    channel_id: int
    total_videos_analyzed: int = 0
    # Averages
    avg_views: float = 0
    avg_likes: float = 0
    avg_ctr: float = 0
    avg_watch_time_pct: float = 0
    avg_duration_seconds: float = 0
    # Best performers
    best_upload_hour: Optional[int] = None         # 0-23
    best_upload_day: Optional[int] = None           # 0=Mon, 6=Sun
    best_video_length_mins: Optional[int] = None    # rounded to nearest minute
    best_niche: Optional[str] = None
    best_script_style: Optional[str] = None
    top_keywords: List[str] = field(default_factory=list)
    # Top countries
    top_countries: Dict[str, int] = field(default_factory=dict)
    # Traffic source breakdown
    traffic_sources: Dict[str, int] = field(default_factory=dict)
    # Per-video scores (video_id -> composite score)
    video_scores: Dict[str, float] = field(default_factory=dict)
    # Recommendations (plain text)
    recommendations: List[str] = field(default_factory=list)


def analyze(channel_id: int, min_videos: int = 3) -> Optional[PerformanceReport]:
    """
    Run a full performance analysis for a channel.

    Requires at least `min_videos` with analytics data to produce
    meaningful insights. Returns None if insufficient data.

    Args:
        channel_id: internal channel ID
        min_videos: minimum videos needed before generating insights

    Returns:
        PerformanceReport or None if not enough data.
    """
    db = get_db()

    # Join video_analytics with uploads and videos to get full context
    rows = db.execute("""
        SELECT
            va.youtube_video_id,
            va.views, va.likes, va.comments, va.shares,
            va.watch_time_minutes, va.avg_view_duration_seconds,
            va.avg_view_percentage, va.impressions, va.ctr,
            va.subscribers_gained, va.subscribers_lost,
            va.traffic_source, va.top_countries,
            u.uploaded_at, u.title, u.tags,
            v.duration_seconds, v.script, v.format
        FROM video_analytics va
        JOIN uploads u ON va.upload_id = u.id
        JOIN videos v ON u.video_id = v.id
        WHERE va.channel_id = ?
        ORDER BY va.fetched_at DESC
    """, (channel_id,)).fetchall()

    db.close()

    if len(rows) < min_videos:
        logger.info(
            f"Only {len(rows)} videos with analytics (need {min_videos}) — "
            "skipping analysis for channel {channel_id}"
        )
        return None

    logger.info(f"Analyzing performance for {len(rows)} videos (channel {channel_id})...")

    report = PerformanceReport(channel_id=channel_id, total_videos_analyzed=len(rows))

    # ── Compute basic averages ──────────────────────────────────────────
    views_list = [r["views"] for r in rows]
    likes_list = [r["likes"] for r in rows]
    ctr_list = [r["ctr"] for r in rows if r["ctr"] > 0]
    watch_pct_list = [r["avg_view_percentage"] for r in rows if r["avg_view_percentage"] > 0]

    report.avg_views = statistics.mean(views_list) if views_list else 0
    report.avg_likes = statistics.mean(likes_list) if likes_list else 0
    report.avg_ctr = statistics.mean(ctr_list) if ctr_list else 0
    report.avg_watch_time_pct = statistics.mean(watch_pct_list) if watch_pct_list else 0

    # ── Score each video (composite performance metric) ─────────────────
    report.video_scores = _score_videos(rows, report)

    # ── Find best upload time ───────────────────────────────────────────
    report.best_upload_hour, report.best_upload_day = _best_upload_time(rows, report.video_scores)

    # ── Find best video length ──────────────────────────────────────────
    report.best_video_length_mins = _best_video_length(rows, report.video_scores)

    # ── Find best niche / keywords ──────────────────────────────────────
    report.best_niche, report.top_keywords = _best_topics(rows, report.video_scores)

    # ── Aggregate traffic sources ───────────────────────────────────────
    report.traffic_sources = _aggregate_json_field(rows, "traffic_source")

    # ── Aggregate countries ─────────────────────────────────────────────
    report.top_countries = _aggregate_json_field(rows, "top_countries")

    # ── Generate recommendations ────────────────────────────────────────
    report.recommendations = _generate_recommendations(report)

    logger.info(
        f"Analysis complete: avg_views={report.avg_views:.0f}, avg_ctr={report.avg_ctr:.1f}%, "
        f"best_hour={report.best_upload_hour}, best_length={report.best_video_length_mins}min"
    )

    return report


def _score_videos(rows, report: PerformanceReport) -> Dict[str, float]:
    """
    Compute a composite performance score (0-100) for each video.
    Weights: views 30%, CTR 25%, watch% 25%, engagement 20%
    """
    scores = {}

    # Determine max values for normalization
    max_views = max((r["views"] for r in rows), default=1) or 1
    max_ctr = max((r["ctr"] for r in rows), default=1) or 1
    max_watch = max((r["avg_view_percentage"] for r in rows), default=1) or 1

    for r in rows:
        vid = r["youtube_video_id"]

        views_norm = (r["views"] / max_views) * 100
        ctr_norm = (r["ctr"] / max_ctr) * 100 if r["ctr"] > 0 else 0
        watch_norm = (r["avg_view_percentage"] / max_watch) * 100 if r["avg_view_percentage"] > 0 else 0

        # Engagement rate = (likes + comments + shares) / views
        total_engagement = r["likes"] + r["comments"] + (r["shares"] or 0)
        engagement_rate = (total_engagement / r["views"] * 100) if r["views"] > 0 else 0
        engagement_norm = min(engagement_rate * 10, 100)  # Cap at 100

        score = (
            views_norm * 0.30
            + ctr_norm * 0.25
            + watch_norm * 0.25
            + engagement_norm * 0.20
        )
        scores[vid] = round(score, 2)

    return scores


def _best_upload_time(rows, scores: Dict[str, float]) -> Tuple[Optional[int], Optional[int]]:
    """Find the upload hour and day-of-week that correlates with highest scores."""
    hour_scores = defaultdict(list)
    day_scores = defaultdict(list)

    for r in rows:
        vid = r["youtube_video_id"]
        score = scores.get(vid, 0)
        uploaded_at = r["uploaded_at"]

        if uploaded_at:
            try:
                dt = datetime.fromisoformat(str(uploaded_at).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                try:
                    dt = datetime.strptime(str(uploaded_at), "%Y-%m-%d %H:%M:%S")
                except (ValueError, TypeError):
                    continue

            hour_scores[dt.hour].append(score)
            day_scores[dt.weekday()].append(score)

    best_hour = None
    if hour_scores:
        best_hour = max(hour_scores, key=lambda h: statistics.mean(hour_scores[h]))

    best_day = None
    if day_scores:
        best_day = max(day_scores, key=lambda d: statistics.mean(day_scores[d]))

    return best_hour, best_day


def _best_video_length(rows, scores: Dict[str, float]) -> Optional[int]:
    """Find the video duration range that performs best."""
    # Bucket durations into minute ranges
    length_scores = defaultdict(list)

    for r in rows:
        vid = r["youtube_video_id"]
        duration = r["duration_seconds"]
        if not duration or duration <= 0:
            continue

        mins = round(duration / 60)
        # Bucket into 2-minute ranges: 0-2, 2-4, 4-6, 6-8, 8-10, 10-12, 12+
        bucket = (mins // 2) * 2
        length_scores[bucket].append(scores.get(vid, 0))

    if not length_scores:
        return None

    best_bucket = max(length_scores, key=lambda b: statistics.mean(length_scores[b]))
    return best_bucket + 1  # Return midpoint of the bucket


def _best_topics(rows, scores: Dict[str, float]) -> Tuple[Optional[str], List[str]]:
    """Identify the best-performing topic keywords and niche."""
    keyword_scores = defaultdict(list)

    for r in rows:
        vid = r["youtube_video_id"]
        score = scores.get(vid, 0)
        tags = r["tags"] or ""

        # Parse tags
        for tag in tags.split(","):
            tag = tag.strip().lower()
            if tag and len(tag) > 2 and not tag.startswith("#"):
                keyword_scores[tag].append(score)

        # Also extract words from title
        title = r["title"] or ""
        for word in title.split():
            word = word.strip().lower()
            if len(word) > 3 and word.isalpha():
                keyword_scores[word].append(score)

    if not keyword_scores:
        return None, []

    # Sort keywords by average score, require at least 2 appearances
    ranked = sorted(
        ((kw, statistics.mean(sc)) for kw, sc in keyword_scores.items() if len(sc) >= 2),
        key=lambda x: x[1],
        reverse=True,
    )

    top_keywords = [kw for kw, _ in ranked[:20]]

    # Best niche = top keyword that looks like a category
    NICHE_CANDIDATES = [
        "cricket", "bollywood", "politics", "geopolitics", "sports",
        "entertainment", "news", "viral", "celebrity", "technology",
        "education", "islam", "history", "pakistan", "india",
    ]
    best_niche = None
    for kw, _ in ranked:
        if kw in NICHE_CANDIDATES:
            best_niche = kw
            break

    return best_niche, top_keywords


def _aggregate_json_field(rows, field_name: str) -> Dict[str, int]:
    """Sum up a JSON dict field across all rows."""
    aggregated = defaultdict(int)
    for r in rows:
        raw = r[field_name]
        if raw:
            try:
                data = json.loads(raw) if isinstance(raw, str) else raw
                for key, val in data.items():
                    aggregated[key] += int(val)
            except (json.JSONDecodeError, TypeError):
                continue
    # Return sorted by value descending
    return dict(sorted(aggregated.items(), key=lambda x: x[1], reverse=True)[:10])


def _generate_recommendations(report: PerformanceReport) -> List[str]:
    """Generate plain-text actionable recommendations from the analysis."""
    recs = []

    if report.best_upload_hour is not None:
        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        time_str = f"{report.best_upload_hour:02d}:00"
        rec = f"Upload videos around {time_str} PKT for best performance"
        if report.best_upload_day is not None:
            rec += f" (best day: {day_names[report.best_upload_day]})"
        recs.append(rec)

    if report.best_video_length_mins:
        recs.append(f"Aim for ~{report.best_video_length_mins} minute videos — this length performs best")

    if report.avg_ctr > 0:
        if report.avg_ctr < 3:
            recs.append("CTR is below 3% — improve thumbnails with bolder text and emotional faces")
        elif report.avg_ctr < 5:
            recs.append("CTR is moderate (3-5%) — test more curiosity-gap titles")
        else:
            recs.append(f"CTR is strong at {report.avg_ctr:.1f}% — maintain current thumbnail/title style")

    if report.avg_watch_time_pct > 0:
        if report.avg_watch_time_pct < 30:
            recs.append("Watch time is low (<30%) — add stronger hooks in first 30 seconds and more cliffhangers")
        elif report.avg_watch_time_pct < 50:
            recs.append("Watch time is decent (30-50%) — tighten scripts to reduce drop-off mid-video")
        else:
            recs.append(f"Excellent retention at {report.avg_watch_time_pct:.0f}% — current script style is working")

    if report.best_niche:
        recs.append(f"'{report.best_niche}' content performs best — lean into this niche more")

    if report.top_keywords:
        top5 = ", ".join(report.top_keywords[:5])
        recs.append(f"Top performing keywords: {top5}")

    if report.top_countries:
        top_country = list(report.top_countries.keys())[0] if report.top_countries else None
        if top_country:
            recs.append(f"Primary audience is from {top_country} — tailor cultural references accordingly")

    return recs
