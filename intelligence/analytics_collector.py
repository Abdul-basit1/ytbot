"""
UpperCut — Analytics Collector (Phase 2: Intelligence Engine)
Fetches per-video performance metrics from YouTube Data API v3
and stores them in the video_analytics table for pattern analysis.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from loguru import logger

from config import get_db, BASE_DIR

TOKEN_PATH = BASE_DIR / "token.json"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]


def _get_youtube_service():
    """Return an authenticated YouTube Data API v3 service."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    if not TOKEN_PATH.exists():
        raise FileNotFoundError("No YouTube token found — run the pipeline first to authenticate")

    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_PATH.write_text(creds.to_json())

    return build("youtube", "v3", credentials=creds)


def _get_analytics_service():
    """Return an authenticated YouTube Analytics API service."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    if not TOKEN_PATH.exists():
        raise FileNotFoundError("No YouTube token found")

    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_PATH.write_text(creds.to_json())

    return build("youtubeAnalytics", "v2", credentials=creds)


# ── Fetch basic stats via Data API ──────────────────────────────────────────

def fetch_video_stats(youtube_video_ids: List[str]) -> List[Dict]:
    """
    Fetch views, likes, comments, and other basic stats for a list of video IDs
    using the YouTube Data API v3 (videos.list endpoint).

    Args:
        youtube_video_ids: list of YouTube video IDs

    Returns:
        List of dicts with stats per video.
    """
    if not youtube_video_ids:
        return []

    youtube = _get_youtube_service()
    results = []

    # YouTube API allows max 50 IDs per request
    for i in range(0, len(youtube_video_ids), 50):
        batch = youtube_video_ids[i:i + 50]
        try:
            response = youtube.videos().list(
                part="statistics,contentDetails",
                id=",".join(batch),
            ).execute()

            for item in response.get("items", []):
                stats = item.get("statistics", {})
                details = item.get("contentDetails", {})
                results.append({
                    "youtube_video_id": item["id"],
                    "views": int(stats.get("viewCount", 0)),
                    "likes": int(stats.get("likeCount", 0)),
                    "dislikes": 0,  # YouTube hid dislike counts
                    "comments": int(stats.get("commentCount", 0)),
                    "duration_iso": details.get("duration", ""),
                })
        except Exception as e:
            logger.error(f"Failed to fetch video stats batch: {e}")

    logger.info(f"Fetched stats for {len(results)}/{len(youtube_video_ids)} videos")
    return results


# ── Fetch advanced analytics ────────────────────────────────────────────────

def fetch_video_analytics(youtube_video_id: str, days_back: int = 28) -> Optional[Dict]:
    """
    Fetch advanced analytics (impressions, CTR, watch time, avg view duration,
    avg view percentage, traffic sources, top countries) for a single video
    using the YouTube Analytics API.

    Args:
        youtube_video_id: the YouTube video ID
        days_back: how many days of data to query

    Returns:
        Dict with analytics data, or None on failure.
    """
    try:
        analytics = _get_analytics_service()
        end_date = datetime.utcnow().strftime("%Y-%m-%d")
        start_date = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")

        # Core metrics
        response = analytics.reports().query(
            ids="channel==MINE",
            startDate=start_date,
            endDate=end_date,
            metrics="views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,"
                    "impressions,impressionClickThroughRate,shares,subscribersGained,subscribersLost",
            filters=f"video=={youtube_video_id}",
        ).execute()

        rows = response.get("rows", [])
        if not rows:
            return None

        row = rows[0]
        result = {
            "youtube_video_id": youtube_video_id,
            "views": int(row[0]),
            "watch_time_minutes": float(row[1]),
            "avg_view_duration_seconds": float(row[2]),
            "avg_view_percentage": float(row[3]),
            "impressions": int(row[4]),
            "ctr": float(row[5]) * 100,  # Convert to percentage
            "shares": int(row[6]),
            "subscribers_gained": int(row[7]),
            "subscribers_lost": int(row[8]),
        }

        # Traffic sources
        traffic = _fetch_traffic_sources(analytics, youtube_video_id, start_date, end_date)
        if traffic:
            result["traffic_source"] = json.dumps(traffic)

        # Top countries
        countries = _fetch_top_countries(analytics, youtube_video_id, start_date, end_date)
        if countries:
            result["top_countries"] = json.dumps(countries)

        return result

    except Exception as e:
        logger.warning(f"Analytics API failed for {youtube_video_id}: {e}")
        return None


def _fetch_traffic_sources(analytics, video_id: str, start: str, end: str) -> Dict:
    """Fetch traffic source breakdown for a video."""
    try:
        response = analytics.reports().query(
            ids="channel==MINE",
            startDate=start,
            endDate=end,
            metrics="views",
            dimensions="insightTrafficSourceType",
            filters=f"video=={video_id}",
            sort="-views",
            maxResults=10,
        ).execute()

        return {row[0]: int(row[1]) for row in response.get("rows", [])}
    except Exception:
        return {}


def _fetch_top_countries(analytics, video_id: str, start: str, end: str) -> Dict:
    """Fetch top countries by views for a video."""
    try:
        response = analytics.reports().query(
            ids="channel==MINE",
            startDate=start,
            endDate=end,
            metrics="views",
            dimensions="country",
            filters=f"video=={video_id}",
            sort="-views",
            maxResults=10,
        ).execute()

        return {row[0]: int(row[1]) for row in response.get("rows", [])}
    except Exception:
        return {}


# ── Collect and persist ─────────────────────────────────────────────────────

def collect_all(channel_id: int, days_back: int = 28) -> int:
    """
    Master collection function: finds all uploaded videos for a channel,
    fetches their stats + analytics, and upserts into video_analytics table.

    Args:
        channel_id: internal channel ID
        days_back: how many days of analytics to query

    Returns:
        Number of videos successfully updated.
    """
    db = get_db()

    # Get all uploaded videos with YouTube IDs
    rows = db.execute(
        "SELECT u.id as upload_id, u.youtube_video_id "
        "FROM uploads u WHERE u.channel_id=? AND u.youtube_video_id IS NOT NULL",
        (channel_id,),
    ).fetchall()
    db.close()

    if not rows:
        logger.info(f"No uploaded videos found for channel {channel_id} — skipping analytics")
        return 0

    video_ids = [r["youtube_video_id"] for r in rows]
    upload_map = {r["youtube_video_id"]: r["upload_id"] for r in rows}

    logger.info(f"Collecting analytics for {len(video_ids)} videos (channel {channel_id})...")

    # Step 1: Bulk fetch basic stats
    basic_stats = fetch_video_stats(video_ids)
    stats_map = {s["youtube_video_id"]: s for s in basic_stats}

    # Step 2: Fetch advanced analytics per video (rate-limited)
    updated = 0
    for vid in video_ids:
        basic = stats_map.get(vid, {})
        advanced = fetch_video_analytics(vid, days_back)

        # Merge basic + advanced
        record = {
            "upload_id": upload_map[vid],
            "channel_id": channel_id,
            "youtube_video_id": vid,
            "views": basic.get("views", 0),
            "likes": basic.get("likes", 0),
            "dislikes": 0,
            "comments": basic.get("comments", 0),
            "shares": 0,
            "watch_time_minutes": 0,
            "avg_view_duration_seconds": 0,
            "avg_view_percentage": 0,
            "impressions": 0,
            "ctr": 0,
            "subscribers_gained": 0,
            "subscribers_lost": 0,
            "traffic_source": None,
            "top_countries": None,
        }

        # Override with advanced data if available
        if advanced:
            for key in advanced:
                record[key] = advanced[key]

        _upsert_analytics(record)
        updated += 1

    # Also update the uploads table views/likes for dashboard compatibility
    _sync_upload_stats(stats_map)

    logger.info(f"Analytics collection complete: {updated}/{len(video_ids)} videos updated")
    return updated


def _upsert_analytics(record: Dict):
    """Insert or update a video_analytics row."""
    db = get_db()
    try:
        # Check if record exists for this video (keep latest)
        existing = db.execute(
            "SELECT id FROM video_analytics WHERE youtube_video_id=? ORDER BY fetched_at DESC LIMIT 1",
            (record["youtube_video_id"],),
        ).fetchone()

        if existing:
            db.execute(
                """UPDATE video_analytics SET
                    views=?, likes=?, dislikes=?, comments=?, shares=?,
                    watch_time_minutes=?, avg_view_duration_seconds=?, avg_view_percentage=?,
                    impressions=?, ctr=?, subscribers_gained=?, subscribers_lost=?,
                    traffic_source=?, top_countries=?, fetched_at=CURRENT_TIMESTAMP
                WHERE id=?""",
                (
                    record["views"], record["likes"], record["dislikes"],
                    record["comments"], record["shares"],
                    record["watch_time_minutes"], record["avg_view_duration_seconds"],
                    record["avg_view_percentage"], record["impressions"], record["ctr"],
                    record["subscribers_gained"], record["subscribers_lost"],
                    record["traffic_source"], record["top_countries"],
                    existing["id"],
                ),
            )
        else:
            db.execute(
                """INSERT INTO video_analytics
                    (upload_id, channel_id, youtube_video_id, views, likes, dislikes,
                     comments, shares, watch_time_minutes, avg_view_duration_seconds,
                     avg_view_percentage, impressions, ctr, subscribers_gained,
                     subscribers_lost, traffic_source, top_countries)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record["upload_id"], record["channel_id"], record["youtube_video_id"],
                    record["views"], record["likes"], record["dislikes"],
                    record["comments"], record["shares"],
                    record["watch_time_minutes"], record["avg_view_duration_seconds"],
                    record["avg_view_percentage"], record["impressions"], record["ctr"],
                    record["subscribers_gained"], record["subscribers_lost"],
                    record["traffic_source"], record["top_countries"],
                ),
            )

        db.commit()
    except Exception as e:
        logger.error(f"Failed to upsert analytics for {record['youtube_video_id']}: {e}")
    finally:
        db.close()


def _sync_upload_stats(stats_map: Dict):
    """Sync basic views/likes back to the uploads table."""
    db = get_db()
    try:
        for yt_id, stats in stats_map.items():
            db.execute(
                "UPDATE uploads SET views=?, likes=? WHERE youtube_video_id=?",
                (stats.get("views", 0), stats.get("likes", 0), yt_id),
            )
        db.commit()
    except Exception as e:
        logger.warning(f"Failed to sync upload stats: {e}")
    finally:
        db.close()
