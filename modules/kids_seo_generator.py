"""
UpperCut — Smart SEO Generator
Learns from YOUR channel's top performers and generates SEO that matches
what actually works. Supports KiddoWorld + OddlyPerfect.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Dict, List

from loguru import logger
from openai import OpenAI

from config import OPENAI_API_KEY, OPENAI_MODEL

client = OpenAI(api_key=OPENAI_API_KEY)


@dataclass
class KidsSEOResult:
    """Container for SEO metadata."""
    title: str = ""
    description: str = ""
    tags: List[str] = field(default_factory=list)
    hashtags: List[str] = field(default_factory=list)
    playlist_category: str = ""
    cost_usd: float = 0.0


# ── Helpers ────────────────────────────────────────────────────────────────

def _sanitize_tags(raw_tags: list, max_count: int = 10) -> List[str]:
    """Clean tags for YouTube API — ASCII only, no special chars."""
    tags = []
    total_chars = 0
    for t in raw_tags[:max_count]:
        t = str(t).strip().replace("#", "").replace("'", "").replace('"', "")
        t = t.replace("\u2019", "").replace("\u2018", "")
        t = t.encode("ascii", errors="ignore").decode("ascii").strip()
        t = re.sub(r"[^a-zA-Z0-9 \-]", "", t).strip()
        if not t or len(t) < 2:
            continue
        t = t[:30]
        if total_chars + len(t) > 400:
            break
        tags.append(t)
        total_chars += len(t)
    return tags


def _get_top_performers(channel: str) -> str:
    """Pull top 5 performing titles from DB to teach GPT what works."""
    try:
        from config import get_db
        db = get_db()
        ch_id = 2 if channel == "kiddoworld" else 3
        rows = db.execute(
            "SELECT title, views FROM uploads WHERE channel_id=? AND views > 0 "
            "ORDER BY views DESC LIMIT 5",
            (ch_id,),
        ).fetchall()
        db.close()
        if rows:
            lines = []
            for r in rows:
                lines.append(f"  \"{r['title']}\" ({r['views']} views)")
            return "YOUR TOP PERFORMING TITLES (copy these patterns!):\n" + "\n".join(lines)
    except Exception:
        pass
    return ""


def _track_cost(cost_usd: float):
    """Track OpenAI cost."""
    try:
        from config import get_db
        db = get_db()
        db.execute(
            "INSERT INTO cost_tracking (service, operation, cost_usd) VALUES (?, ?, ?)",
            ("openai", "seo_generation", cost_usd),
        )
        db.commit()
        db.close()
    except Exception:
        pass


# ── KiddoWorld SEO ─────────────────────────────────────────────────────────

def generate_kids_seo(title: str, description: str, video_format: str = "long") -> KidsSEOResult:
    """
    Generate KiddoWorld SEO that matches YOUR channel's winning patterns.
    """
    top_performers = _get_top_performers("kiddoworld")
    is_short = video_format == "short"

    system_prompt = f"""You are KiddoWorld's SEO specialist. You write titles and descriptions
that get maximum views while staying YouTube monetization compliant.

{top_performers}

RULES YOU MUST FOLLOW:

TITLE (most important):
- Short engaging hook + 1-2 content-specific emojis + " | KiddoWorld"
- Pick emojis that MATCH the topic (🦈 for shark, 🚌 for bus, 🔢 for numbers, 🦕 for dinosaur)
- Include one of: "Nursery Rhymes", "Kids Songs", "Bedtime Stories", or "Learn" for search volume
- Max 80 characters{' + add #Shorts at end' if is_short else ''}
- COPY the patterns from your top performers above
- Example: "Baby Shark Lullaby 🦈💤 | Sleepy Time Songs for Babies | KiddoWorld"

DESCRIPTION (keep it SHORT):
- Line 1: One fun sentence about what happens in the video (use an emoji)
- Line 2: empty
- Line 3: 🔔 Subscribe to KiddoWorld for new kids songs every day!
- Line 4: 🤖 This video was created using AI animation tools.
- Line 5: empty
- Lines 6+: 10-12 hashtags (all lowercase, no spaces in hashtags)
- TOTAL: Under 300 characters. That's it. No essays.

TAGS (minimal):
- Exactly 7-9 tags
- Always: "KiddoWorld", "nursery rhymes", "kids songs"
- Add 4-6 topic-specific tags
- For Shorts add: "short", "short feed"
- ASCII only

Return JSON:
{{
    "title": "short hook + emojis + channel",
    "description": "2 lines + subscribe + AI disclosure + hashtags",
    "tags": ["7-9 tags"]
}}"""

    user_msg = f"Video title: {title}\nDescription: {description}\nFormat: {'Short' if is_short else 'Long-form'}"

    logger.info(f"Generating KiddoWorld SEO: {title[:50]}...")

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.6,
            max_tokens=800,
            response_format={"type": "json_object"},
        )

        usage = response.usage
        cost = (usage.prompt_tokens * 0.15 / 1_000_000) + (usage.completion_tokens * 0.60 / 1_000_000)
        data = json.loads(response.choices[0].message.content)

        result = KidsSEOResult(
            title=data.get("title", title)[:80],
            description=data.get("description", ""),
            tags=_sanitize_tags(data.get("tags", []), max_count=9),
            hashtags=data.get("hashtags", [])[:12],
            playlist_category=data.get("playlist_category", "Kids Songs"),
            cost_usd=round(cost, 6),
        )

        logger.info(f"KiddoWorld SEO: title='{result.title[:40]}...', {len(result.tags)} tags")
        _track_cost(cost)
        return result

    except Exception as e:
        logger.error(f"KiddoWorld SEO failed: {e}")
        emoji = "🎵"
        return KidsSEOResult(
            title=f"{title[:50]} {emoji} | Kids Songs | KiddoWorld",
            description=f"{description[:100]}\n\n🔔 Subscribe to KiddoWorld!\n🤖 This video was created using AI animation tools.\n\n#nurseryrhymes #kidssongs #kiddoworld #babysongs #toddlersongs",
            tags=_sanitize_tags(["KiddoWorld", "nursery rhymes", "kids songs", "baby songs", "toddler songs", title.split()[0] if title else "kids"]),
            playlist_category="Kids Songs",
        )


# ── OddlyPerfect SEO ──────────────────────────────────────────────────────

def generate_trending_seo(title: str, description: str, language: str = "english",
                          category: str = "trending") -> KidsSEOResult:
    """
    Generate OddlyPerfect SEO that matches YOUR channel's winning patterns.
    """
    top_performers = _get_top_performers("oddlyperfect")
    lang_label = "Hindi" if language.lower() in ("hindi", "hi") else "English"

    system_prompt = f"""You write titles for OddlyPerfect YouTube Shorts. Your titles get thousands of views.

{top_performers}

TITLE FORMAT (you MUST use this EXACT structure):
"The [Creative Name] | [Hidden/Abandoned/Secret] [Thing] [Build/Transform] [location] [2 emojis] #shorts #viral"

EXAMPLES OF TITLES THAT GOT 1000+ VIEWS ON THIS CHANNEL:
- "The Hidden Sanctuary | DIY Tree House Build 😱🔥 #shorts #viral"
- "The Coconut House | Luxury Tiny Home Build Inside a Coconut 🥥🏡 #shorts"
- "From Rust to Luxury: Watch This Train Bogie Transformation! 🚂✨ #shorts"

BANNED PHRASES (these get ZERO views):
- "You Won't Believe" — NEVER use this
- "Watch This" — too generic
- "Amazing" — overused
- "Incredible" — overused
- Any generic clickbait

TITLE RULES:
- ALWAYS start with "The [Name]" or "[Subject] [Action]"
- ALWAYS use "|" separator
- ALWAYS include "Build" or "Transformation"
- ALWAYS end with 2 emojis + #shorts #viral
- Max 80 characters
- Pick emojis that MATCH the content exactly

DESCRIPTION:
- Line 1: One specific sentence about what gets built/transformed (include an emoji)
- Line 2: empty
- Line 3: 🤖 Created with AI animation tools.
- Line 4: empty
- Lines 5+: 12 hashtags starting with #shorts #viral #satisfying
- TOTAL: Under 300 characters

TAGS:
- Exactly 7-9 tags
- ALWAYS include: "OddlyPerfect", "short", "short feed", "satisfying", "viral"
- Add 2-4 topic-specific tags
- ASCII only, lowercase

LANGUAGE: {lang_label}

Return JSON:
{{
    "title": "The [Name] | [Action] Build/Transform [emojis] #shorts #viral",
    "description": "1 specific sentence + AI disclosure + 12 hashtags",
    "tags": ["7-9 tags always including satisfying and viral"]
}}"""

    user_msg = f"Video topic: {title}\nWhat happens: {description}\nCategory: {category}\nLanguage: {lang_label}"

    logger.info(f"Generating OddlyPerfect SEO: {title[:50]}...")

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.7,
            max_tokens=600,
            response_format={"type": "json_object"},
        )

        usage = response.usage
        cost = (usage.prompt_tokens * 0.15 / 1_000_000) + (usage.completion_tokens * 0.60 / 1_000_000)
        data = json.loads(response.choices[0].message.content)

        result = KidsSEOResult(
            title=data.get("title", title)[:75],
            description=data.get("description", ""),
            tags=_sanitize_tags(data.get("tags", []), max_count=8),
            hashtags=data.get("hashtags", [])[:12],
            playlist_category=data.get("playlist_category", category),
            cost_usd=round(cost, 6),
        )

        logger.info(f"OddlyPerfect SEO: title='{result.title[:40]}...', {len(result.tags)} tags")
        _track_cost(cost)
        return result

    except Exception as e:
        logger.error(f"OddlyPerfect SEO failed: {e}")
        return KidsSEOResult(
            title=f"{title[:50]} 😱🔥 #shorts",
            description=f"{description[:100]}\n\n🤖 Created with AI animation tools.\n\n#shorts #viral #trending #satisfying #OddlyPerfect",
            tags=_sanitize_tags(["OddlyPerfect", "short", "short feed", "viral", "satisfying", "trending"]),
            playlist_category=category,
        )


# ── Legacy wrapper (used by old pipeline code) ────────────────────────────

def generate(topic: Dict, script_result, channel_config: dict) -> KidsSEOResult:
    """Legacy wrapper for pipeline compatibility."""
    topic_text = topic.get("text", "")
    script_snippet = script_result.text[:200] if hasattr(script_result, "text") else ""
    return generate_kids_seo(title=topic_text, description=script_snippet)


def generate_shorts_seo(topic: Dict, channel_config: dict) -> KidsSEOResult:
    """Legacy wrapper for kids Shorts."""
    topic_text = topic.get("text", "")
    return generate_kids_seo(title=topic_text, description=topic_text, video_format="short")
