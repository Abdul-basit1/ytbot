"""
UpperCut — Trend Fetcher
Fetches trending topics from Google Trends (PK + IN) and RSS feeds,
scores them, and returns the top candidates.
"""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timedelta
from typing import Dict, List

import feedparser
import yaml
from loguru import logger
from pytrends.request import TrendReq

from config import get_db, CHANNEL_DIR


# ── Score weights ────────────────────────────────────────────────────────────
# Base weights (used when no intelligence data exists)
W_SEARCH_VOLUME = 0.35
W_RECENCY       = 0.25
W_RELEVANCE     = 0.20
W_NOVELTY       = 0.10
W_INTELLIGENCE  = 0.10  # Bonus from learned performance data

# Keywords that boost relevance for our target audience
RELEVANCE_KEYWORDS = [
    "pakistan", "india", "cricket", "bollywood", "kashmir", "modi",
    "imran", "sharif", "ipl", "psl", "army", "war", "nuclear",
    "china", "afghanistan", "celebrity", "actor", "actress",
    "sports", "match", "world cup", "election", "viral",
]


def _topic_hash(text: str) -> str:
    """Deterministic short hash for deduplication."""
    return hashlib.md5(text.lower().strip().encode()).hexdigest()[:12]


def _is_topic_used(topic_text: str, channel_id: int) -> bool:
    """Check if we already used this topic (or something very similar)."""
    db = get_db()
    h = _topic_hash(topic_text)
    # Check exact match or hash collision (good enough for dedup)
    row = db.execute(
        "SELECT 1 FROM topics WHERE channel_id=? AND (topic_text=? OR topic_text LIKE ?)",
        (channel_id, topic_text, f"%{topic_text[:40]}%"),
    ).fetchone()
    db.close()
    return row is not None


# ── Google Trends ────────────────────────────────────────────────────────────
def fetch_google_trends(regions: List[str]) -> List[Dict]:
    """Fetch today's trending searches from Google Trends for given regions."""
    topics: List[Dict] = []
    try:
        pytrends = TrendReq(hl="ur", tz=300)  # PKT = UTC+5
        for region in regions:
            logger.info(f"Fetching Google Trends for region: {region}")
            try:
                trending = pytrends.trending_searches(pn=region.lower())
                for idx, row in trending.iterrows():
                    title = str(row.values[0]).strip()
                    if title:
                        topics.append({
                            "text": title,
                            "source": f"google_trends_{region}",
                            "search_volume": max(100 - idx * 5, 10),  # Approximate rank-based score
                            "timestamp": datetime.utcnow(),
                        })
            except Exception as e:
                logger.warning(f"Google Trends failed for {region}: {e}")
                continue
    except Exception as e:
        logger.error(f"Google Trends init failed: {e}")
    return topics


# ── RSS Feeds ────────────────────────────────────────────────────────────────
def fetch_rss_topics(feed_urls: List[str]) -> List[Dict]:
    """Parse RSS feeds and extract recent headlines."""
    topics: List[Dict] = []
    for url in feed_urls:
        logger.info(f"Fetching RSS: {url}")
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:10]:  # Top 10 from each feed
                title = entry.get("title", "").strip()
                published = entry.get("published_parsed")
                pub_dt = datetime(*published[:6]) if published else datetime.utcnow()
                if title:
                    topics.append({
                        "text": title,
                        "source": f"rss_{feed.feed.get('title', url)[:30]}",
                        "search_volume": 50,  # Baseline score for RSS items
                        "timestamp": pub_dt,
                    })
        except Exception as e:
            logger.warning(f"RSS feed failed ({url}): {e}")
    return topics


# ── Scoring ──────────────────────────────────────────────────────────────────
def score_topic(topic: Dict, channel_id: int) -> float:
    """Score a topic 0-100 based on volume, recency, relevance, novelty, and learned intelligence."""
    # Search volume component (0-100, already provided)
    vol_score = min(topic.get("search_volume", 0), 100)

    # Recency: higher score for more recent topics
    age_hours = (datetime.utcnow() - topic["timestamp"]).total_seconds() / 3600
    recency_score = max(100 - age_hours * 4, 0)  # Drops ~4 pts per hour

    # Relevance: keyword matching against our target niches
    text_lower = topic["text"].lower()
    matches = sum(1 for kw in RELEVANCE_KEYWORDS if kw in text_lower)
    relevance_score = min(matches * 25, 100)

    # Novelty: penalty if topic was already used
    novelty_score = 0 if _is_topic_used(topic["text"], channel_id) else 100

    # Intelligence: bonus if topic matches historically high-performing keywords
    intel_score = _intelligence_score(text_lower, channel_id)

    final = (
        vol_score * W_SEARCH_VOLUME
        + recency_score * W_RECENCY
        + relevance_score * W_RELEVANCE
        + novelty_score * W_NOVELTY
        + intel_score * W_INTELLIGENCE
    )
    return round(final, 2)


def _intelligence_score(text_lower: str, channel_id: int) -> float:
    """
    Score 0-100 based on how well this topic matches historically
    high-performing keywords from the intelligence engine.
    """
    try:
        from intelligence.strategy_optimizer import get_top_performing_keywords
        top_keywords = get_top_performing_keywords(channel_id)
        if not top_keywords:
            return 0

        matches = sum(1 for kw in top_keywords if kw.lower() in text_lower)
        # Each matching keyword contributes ~20 points, capped at 100
        return min(matches * 20, 100)
    except Exception:
        return 0  # Intelligence not available yet — no penalty


# ── Main entry point ─────────────────────────────────────────────────────────
def get_topics(channel_config: dict, top_n: int = 5) -> List[Dict]:
    """
    Master function: fetch from all sources, deduplicate, score, return top N.

    Args:
        channel_config: parsed YAML channel configuration
        top_n: how many topics to return

    Returns:
        List of topic dicts sorted by score descending.
    """
    trends_cfg = channel_config.get("trends", {})
    regions = trends_cfg.get("regions", ["PK", "IN"])
    rss_urls = trends_cfg.get("rss_feeds", [])

    # Get channel_id from DB
    db = get_db()
    ch_name = channel_config.get("channel", {}).get("name", "UpperCut")
    row = db.execute("SELECT id FROM channels WHERE name=?", (ch_name,)).fetchone()
    channel_id = row["id"] if row else 1
    db.close()

    # Fetch from all sources
    all_topics: List[Dict] = []
    all_topics.extend(fetch_google_trends(regions))
    all_topics.extend(fetch_rss_topics(rss_urls))

    # Deduplicate by text (case-insensitive)
    seen = set()
    unique: List[Dict] = []
    for t in all_topics:
        key = _topic_hash(t["text"])
        if key not in seen:
            seen.add(key)
            unique.append(t)

    # Score each topic
    for t in unique:
        t["score"] = score_topic(t, channel_id)

    # Sort by score descending and return top N
    unique.sort(key=lambda x: x["score"], reverse=True)
    top = unique[:top_n]

    logger.info(f"Trend Fetcher: {len(all_topics)} raw → {len(unique)} unique → returning top {len(top)}")
    for t in top:
        logger.debug(f"  [{t['score']:.1f}] {t['text'][:60]} ({t['source']})")

    return top


def save_topics_to_db(topics: List[Dict], channel_id: int):
    """Persist fetched topics into the database."""
    db = get_db()
    for t in topics:
        db.execute(
            "INSERT INTO topics (channel_id, topic_text, source, performance_score) VALUES (?, ?, ?, ?)",
            (channel_id, t["text"], t.get("source", "unknown"), t.get("score", 0)),
        )
    db.commit()
    db.close()
    logger.info(f"Saved {len(topics)} topics to database")


def select_best_topic(topics: List[Dict]) -> Dict:
    """Pick the single best unused topic from the scored list."""
    if not topics:
        raise ValueError("No topics available — all sources returned empty")
    return topics[0]
