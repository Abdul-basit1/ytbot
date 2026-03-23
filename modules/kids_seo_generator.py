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

KIDS_DEFAULT_DESCRIPTION = """{video_description}

Best nursery rhymes, baby songs, and kids learning videos for toddlers and preschoolers!

📺 Watch More KiddoWorld:
▶ ABC & Alphabet Songs
▶ Numbers & Counting Songs
▶ Colors, Shapes & Animals
▶ Bedtime Stories for Kids
▶ Fun Learning Videos

KiddoWorld creates the best educational cartoon videos for babies, toddlers, and preschool children aged 2-8. Our nursery rhymes, kids songs, and animated stories help children learn letters, numbers, colors, shapes, animals, and more through fun, colorful, and engaging music videos. Every video is designed to be safe, educational, and entertaining for young learners.

🔔 Subscribe to KiddoWorld for NEW videos every day!
👍 Like & Share to help other parents find us!

#nurseryrhymes #kidssongs #babysongs #toddlersongs #kiddoworld #abcsong #learningvideos #educationalvideos #cartoonforkids #childrenssongs #preschool #kindergarten #kidslearning #babysong #toddlerlearning #kidseducation #animatedsongs #kidsvideos #nurseryrhyme #learnwithme
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

KIDS_SEO_SYSTEM_PROMPT = """You are a YouTube SEO expert who has studied channels with 100K+ subscribers \
and knows exactly what makes kids videos go viral.

TITLE RULES (learned from top-performing channels):
- Use an emotional hook + topic + #shorts (for Shorts)
- Add 1-2 emojis at the end (🎵 🌟 🔥 ✨ 🎶 🐾 🚌)
- Include "Nursery Rhymes" or "Kids Songs" for search volume
- End with channel name "KiddoWorld"
- Max 90 characters
- For Shorts: always include #shorts at the end
- WINNING EXAMPLES:
  "Baby Shark Bedtime Lullaby 🦈🌙 | Nursery Rhymes | KiddoWorld #shorts"
  "Wheels on the Bus Go Round! 🚌✨ | Kids Songs | KiddoWorld"
  "The Friendly Dinosaur Adventure 🦕🌟 | Bedtime Stories | KiddoWorld #shorts"

DESCRIPTION RULES:
- First line = emotional hook that makes parents click
- Second line = keyword-rich summary
- Keep it SHORT (200-400 chars body text)
- Then add 15-20 hashtags at the bottom
- EXAMPLE:
  "Your kids will LOVE singing along! 🎵
  The best nursery rhymes and baby songs for toddlers and preschoolers.

  🔔 Subscribe to KiddoWorld for new videos every day!

  #nurseryrhymes #kidssongs #babysongs #toddlersongs #kiddoworld
  #kidsvideo #preschool #babysong #cartoon #learnwithme
  #educational #kidslearning #bedtimesongs #childrensmusic"

TAGS RULES (keep it minimal like top channels):
- Only 8-12 tags (NOT 25-30)
- Always include: "KiddoWorld", "nursery rhymes", "kids songs"
- Add 3-5 topic-specific tags
- Add "short", "short feed" for Shorts
- ASCII only, no special characters, no hashtags in tags

Always respond in JSON:
{
    "title": "hook with emojis + topic + channel #shorts",
    "description": "short hook + hashtag heavy (200-400 chars + 15 hashtags)",
    "tags": ["8-12 tags only"],
    "hashtags": ["15-20 hashtags for description"],
    "playlist_category": "category"
}
"""


# ── OddlyPerfect SEO (trending/facts/current affairs) ─────────────────────

TRENDING_SEO_SYSTEM_PROMPT = """You are a YouTube SEO expert who has studied viral Shorts channels \
with 100K+ subscribers getting millions of views on trending content.

TITLE RULES (from channels with 3M+ view Shorts):
- Start with a BOLD hook or claim in quotes
- Add emojis that trigger curiosity (😳🔥👑💀)
- ALWAYS include #shorts #youtubeshorts at the end
- Ask a question OR make a shocking statement
- 70-95 characters
- WINNING EXAMPLES:
  "The Angry Chef Who Accidentally Created Biryani 😳🔥 #shorts #youtubeshorts"
  "What If India Attacks Pakistan? 💀🔥 #shorts #viral"
  "This Pool Was Built in 24 Hours! 😱 #shorts #satisfying"
  "कैसे बनी Chicken Korma की असली कहानी? 👑🍗 #shorts #food"

DESCRIPTION RULES:
- First line = same hook as title (expanded)
- Keep body SHORT (150-300 chars)
- 10-15 hashtags at the bottom
- Mix of broad + topic-specific hashtags
- EXAMPLE:
  "The angry Mughal chef was ordered to create a dish with no bones...
  What happened next changed Indian cuisine forever! 🔥

  #shorts #youtubeshorts #trending #viral #food #history
  #facts #amazingfacts #foodhistory #indianfood"

TAGS RULES:
- Only 5-10 tags (minimal!)
- Always include: "short", "short feed", "viral"
- Add "OddlyPerfect" channel name
- Add 3-5 topic-specific tags
- ASCII only

LANGUAGE: Generate in {language} (Hindi or English based on input)

Always respond in JSON:
{
    "title": "bold hook + emojis + #shorts #youtubeshorts",
    "description": "short hook + 10-15 hashtags (150-300 chars)",
    "tags": ["5-10 minimal tags"],
    "hashtags": ["10-15 hashtags"],
    "playlist_category": "category"
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


def generate_trending_seo(title: str, description: str, language: str = "english",
                          category: str = "trending") -> KidsSEOResult:
    """
    Generate SEO for OddlyPerfect channel (trending/facts/current affairs).
    Optimized based on Animation_Waala's proven SEO patterns.
    """
    lang_label = "Hindi" if language.lower() in ("hindi", "hi") else "English"
    prompt = TRENDING_SEO_SYSTEM_PROMPT.replace("{language}", lang_label)

    user_msg = f"""Video Title/Topic: {title}
Description: {description}
Language: {lang_label}
Category: {category}
Channel: OddlyPerfect

Generate viral YouTube Shorts SEO for this trending/facts video.
Make the title emotionally compelling with emojis and #shorts.
Keep tags minimal (5-10 only).
Add 10-15 hashtags in description.
Only respond in JSON."""

    logger.info(f"Generating OddlyPerfect SEO: {title[:50]}...")

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.7,
            max_tokens=1500,
            response_format={"type": "json_object"},
        )

        usage = response.usage
        cost = (usage.prompt_tokens * 0.15 / 1_000_000) + (usage.completion_tokens * 0.60 / 1_000_000)
        data = json.loads(response.choices[0].message.content)

        # Sanitize tags
        import re as _re
        raw_tags = data.get("tags", [])
        # Always include channel name and basics
        for base_tag in ["OddlyPerfect", "short", "short feed", "viral"]:
            if base_tag not in raw_tags:
                raw_tags.append(base_tag)

        tags = []
        total_chars = 0
        for t in raw_tags:
            t = str(t).strip().replace("#", "").replace("'", "").replace('"', "")
            t = t.encode("ascii", errors="ignore").decode("ascii").strip()
            t = _re.sub(r"[^a-zA-Z0-9 \-]", "", t).strip()
            if not t or len(t) < 2:
                continue
            t = t[:30]
            if total_chars + len(t) > 400:
                break
            tags.append(t)
            total_chars += len(t)

        result = KidsSEOResult(
            title=data.get("title", title)[:95],
            description=data.get("description", ""),
            tags=tags,
            hashtags=data.get("hashtags", [])[:20],
            playlist_category=data.get("playlist_category", category),
            cost_usd=round(cost, 6),
        )

        logger.info(f"OddlyPerfect SEO: title='{result.title[:40]}...', {len(result.tags)} tags")
        _track_cost(cost)
        return result

    except Exception as e:
        logger.error(f"OddlyPerfect SEO failed: {e}")
        return KidsSEOResult(
            title=f"{title[:60]} 😳🔥 #shorts",
            description=f"{description[:200]}\n\n#shorts #viral #trending #facts #OddlyPerfect",
            tags=["OddlyPerfect", "short", "short feed", "viral", "trending", "facts"],
            hashtags=["#shorts", "#viral", "#trending", "#facts", "#OddlyPerfect"],
            playlist_category=category,
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
