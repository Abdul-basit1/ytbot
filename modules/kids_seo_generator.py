"""
UpperCut — Kids SEO Generator (KiddoWorld)
Generates YouTube SEO metadata optimized for children's content:
kids-friendly titles, descriptions, tags, and hashtags.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from typing import Dict, List

from loguru import logger
from openai import OpenAI

from config import OPENAI_API_KEY, OPENAI_MODEL

client = OpenAI(api_key=OPENAI_API_KEY)


# ── Title formulas ──────────────────────────────────────────────────────────

KIDS_TITLE_FORMULAS = [
    "{topic} | Kids Songs | KiddoWorld",
    "Learn {concept} for Kids | Fun Learning | KiddoWorld",
    "{topic} | Nursery Rhymes | KiddoWorld",
    "The {concept} Song for Children | KiddoWorld",
    "{topic} for Toddlers | KiddoWorld",
    "{concept} Song | Educational Videos for Kids | KiddoWorld",
]

KIDS_DEFAULT_DESCRIPTION = """Welcome to KiddoWorld!

{video_description}

KiddoWorld brings you fun, colorful, and educational videos for children aged 2-8. \
Our videos help kids learn through songs, stories, and colorful animations!

Subscribe for new videos every day!

#KidsVideo #NurseryRhymes #KidsSongs #ChildrensContent #KiddoWorld #LearnWithMe #KidsEducation #CartoonForKids
"""


@dataclass
class KidsSEOResult:
    """Container for kids SEO metadata."""
    title: str = ""
    description: str = ""
    tags: List[str] = field(default_factory=list)
    hashtags: List[str] = field(default_factory=list)
    playlist_category: str = ""
    cost_usd: float = 0.0


# ── System prompt ───────────────────────────────────────────────────────────

KIDS_SEO_SYSTEM_PROMPT = """You are a YouTube SEO expert specializing in children's content.

Your job is to create metadata that:
1. Ranks high in YouTube Kids search
2. Appeals to parents browsing for their children
3. Uses child-safe, age-appropriate language
4. Includes both broad and specific keywords

IMPORTANT: This is children's content. No clickbait. No misleading titles.
Keep everything wholesome, educational, and fun.

Always respond in JSON format:
{
    "title": "Catchy, clear title under 70 chars — include 'for Kids' or similar",
    "description": "400-500 word description: what kids will learn, age range, channel info",
    "tags": ["30-40 tags — mix of broad (kids songs) and specific (abc alphabet song)"],
    "hashtags": ["#KidsVideo", "#NurseryRhymes", "...10-15 hashtags"],
    "playlist_category": "category name"
}
"""


def generate(topic: Dict, script_result, channel_config: dict) -> KidsSEOResult:
    """
    Generate full SEO metadata for a kids video.

    Args:
        topic: topic dict with 'text' and optionally 'concept'
        script_result: KidsScriptResult with script text
        channel_config: parsed channel YAML

    Returns:
        KidsSEOResult with all metadata fields.
    """
    topic_text = topic.get("text", "")
    concept = topic.get("concept", "")
    seo_cfg = channel_config.get("seo", {})
    default_tags = seo_cfg.get("default_tags", [])

    script_snippet = script_result.text[:400] if hasattr(script_result, "text") else ""

    user_prompt = f"""Topic: {topic_text}
Concept: {concept}
Channel: KiddoWorld (Kids 2-8, global English-speaking audience)

Script snippet: {script_snippet}

Create complete YouTube SEO metadata for this kids video.
Include 30-40 tags (mix of: kids songs, nursery rhymes, educational, specific topic tags).
10-15 hashtags.
Only respond in JSON."""

    logger.info(f"Generating kids SEO for: {topic_text[:50]}...")

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": KIDS_SEO_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.6,
            max_tokens=2000,
            response_format={"type": "json_object"},
        )

        usage = response.usage
        cost = (usage.prompt_tokens * 0.15 / 1_000_000) + (usage.completion_tokens * 0.60 / 1_000_000)

        data = json.loads(response.choices[0].message.content)

        # Merge default tags
        raw_tags = data.get("tags", [])
        for dt in default_tags:
            if dt not in raw_tags:
                raw_tags.append(dt)

        # Sanitize tags for YouTube API:
        # YouTube is very strict — only allow simple alphanumeric + spaces
        import re as _re
        tags = []
        total_chars = 0
        for t in raw_tags:
            # Strip to ASCII-safe characters only
            t = str(t).strip()
            t = t.replace("#", "").replace("'", "").replace('"', "")
            t = t.replace("\u2019", "").replace("\u2018", "")  # Smart quotes
            # Remove any non-ASCII characters
            t = t.encode("ascii", errors="ignore").decode("ascii").strip()
            # Remove special chars except letters, numbers, spaces, hyphens
            t = _re.sub(r"[^a-zA-Z0-9 \-]", "", t).strip()
            if not t or len(t) < 2:
                continue
            t = t[:30]
            if total_chars + len(t) > 400:  # Conservative buffer
                break
            tags.append(t)
            total_chars += len(t)

        result = KidsSEOResult(
            title=data.get("title", topic_text)[:70],
            description=data.get("description", ""),
            tags=tags,
            hashtags=data.get("hashtags", [])[:15],
            playlist_category=data.get("playlist_category", "Kids Songs"),
            cost_usd=round(cost, 6),
        )

        logger.info(f"Kids SEO generated: title='{result.title[:40]}...', {len(result.tags)} tags")
        _track_cost(cost)
        return result

    except Exception as e:
        logger.error(f"Kids SEO generation failed: {e}")
        # Fallback
        title = random.choice(KIDS_TITLE_FORMULAS).format(
            topic=topic_text[:30], concept=concept or topic_text[:20]
        )
        return KidsSEOResult(
            title=title[:70],
            description=KIDS_DEFAULT_DESCRIPTION.format(video_description=topic_text),
            tags=default_tags + ["kids songs", "nursery rhymes", "kids learning", topic_text.lower()],
            hashtags=["#KidsVideo", "#NurseryRhymes", "#KiddoWorld", "#KidsSongs"],
            playlist_category="Kids Songs",
        )


def generate_shorts_seo(topic: Dict, channel_config: dict) -> KidsSEOResult:
    """Generate SEO metadata specifically for kids YouTube Shorts."""
    topic_text = topic.get("text", "")
    concept = topic.get("concept", "")

    prompt = f"""Topic: {topic_text}
Concept: {concept}

YouTube Shorts for kids channel KiddoWorld:
- Short catchy title (40 chars max)
- Brief description (100 words)
- 15 tags
- 5 hashtags (#Shorts MUST be included)
Only respond in JSON."""

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": KIDS_SEO_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.6,
            max_tokens=1000,
            response_format={"type": "json_object"},
        )

        usage = response.usage
        cost = (usage.prompt_tokens * 0.15 / 1_000_000) + (usage.completion_tokens * 0.60 / 1_000_000)
        data = json.loads(response.choices[0].message.content)

        hashtags = data.get("hashtags", [])
        if "#Shorts" not in hashtags:
            hashtags.insert(0, "#Shorts")

        _track_cost(cost)

        return KidsSEOResult(
            title=data.get("title", topic_text)[:40],
            description=data.get("description", ""),
            tags=data.get("tags", [])[:15],
            hashtags=hashtags,
            playlist_category="Kids Shorts",
            cost_usd=round(cost, 6),
        )

    except Exception as e:
        logger.error(f"Kids Shorts SEO failed: {e}")
        return KidsSEOResult(
            title=f"{topic_text[:30]} #Shorts",
            tags=["#Shorts", "#KidsVideo", "#KiddoWorld"],
            hashtags=["#Shorts", "#KidsVideo", "#KiddoWorld"],
            playlist_category="Kids Shorts",
        )


def _track_cost(cost_usd: float):
    """Track OpenAI cost."""
    try:
        from config import get_db
        db = get_db()
        db.execute(
            "INSERT INTO cost_tracking (service, operation, cost_usd) VALUES (?, ?, ?)",
            ("openai", "kids_seo", cost_usd),
        )
        db.execute(
            "UPDATE videos SET cost_usd = cost_usd + ? WHERE id = (SELECT MAX(id) FROM videos)",
            (cost_usd,),
        )
        db.commit()
        db.close()
    except Exception:
        pass
