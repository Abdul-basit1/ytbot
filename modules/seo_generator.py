"""
UpperCut — SEO Generator
Uses GPT-4o-mini to generate optimized titles, descriptions, and tags
in Urdu + English for maximum YouTube discoverability.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Dict, List

from loguru import logger
from openai import OpenAI

from config import OPENAI_API_KEY, OPENAI_MODEL

client = OpenAI(api_key=OPENAI_API_KEY)


@dataclass
class SEOResult:
    """Container for all SEO metadata."""
    title_urdu: str = ""
    title_english: str = ""
    description: str = ""
    tags: List[str] = field(default_factory=list)
    hashtags: List[str] = field(default_factory=list)
    playlist_category: str = ""
    cost_usd: float = 0.0


SYSTEM_PROMPT = """آپ YouTube SEO ماہر ہیں۔ آپ کا کام ایسا میٹا ڈیٹا بنانا ہے جو:
1. YouTube سرچ میں اوپر آئے
2. لوگوں کو کلک کرنے پر مجبور کرے
3. پاکستان اور بھارت کے سامعین کے لیے ہو

ہمیشہ JSON فارمیٹ میں جواب دیں:
{
    "title_urdu": "اردو ٹائٹل (60 حروف سے کم، جذباتی ہک + تجسس)",
    "title_english": "English title variant",
    "description": "500 الفاظ کی تفصیل — اردو + انگریزی مکس، keywords سے بھرپور",
    "tags": ["tag1", "tag2", "...35 ٹیگز — عام + مخصوص + زبان کے ٹیگز"],
    "hashtags": ["#hashtag1", "#hashtag2", "...10-15 ہیش ٹیگز"],
    "playlist_category": "playlist نام"
}

ٹائٹل فارمولا: [جذبات] + [موضوع] + [تجسس]
مثال: "حیران کن! بھارت نے پاکستان کو کیا پیغام دیا؟ 😱"
"""


def generate(topic: Dict, script_result, channel_config: dict) -> SEOResult:
    """
    Generate full SEO metadata for a video.

    Args:
        topic: topic dict
        script_result: ScriptResult with script text
        channel_config: parsed YAML channel config

    Returns:
        SEOResult with all metadata fields.
    """
    topic_text = topic.get("text", "")
    seo_cfg = channel_config.get("seo", {})
    default_tags = seo_cfg.get("default_tags", [])

    # Extract a brief summary from the script for context
    script_snippet = script_result.text[:500] if hasattr(script_result, "text") else ""

    user_prompt = f"""موضوع: {topic_text}

اسکرپٹ خلاصہ: {script_snippet}

چینل: UpperCut (پاکستان اور بھارت — اردو)
اس ویڈیو کے لیے مکمل YouTube SEO میٹا ڈیٹا بنائیں۔
35 ٹیگز دیں (اردو، انگریزی، ہندی مکس)۔
10-15 ہیش ٹیگز دیں۔
صرف JSON میں جواب دیں۔"""

    logger.info(f"Generating SEO metadata for: {topic_text[:50]}...")

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=2000,
            response_format={"type": "json_object"},
        )

        usage = response.usage
        cost = (usage.prompt_tokens * 0.15 / 1_000_000) + (usage.completion_tokens * 0.60 / 1_000_000)

        data = json.loads(response.choices[0].message.content)

        # Merge default tags with generated tags
        tags = data.get("tags", [])
        for dt in default_tags:
            if dt not in tags:
                tags.append(dt)

        result = SEOResult(
            title_urdu=data.get("title_urdu", topic_text)[:60],
            title_english=data.get("title_english", topic_text)[:60],
            description=data.get("description", ""),
            tags=tags[:50],  # YouTube limit is 500 chars total, keep it safe
            hashtags=data.get("hashtags", [])[:15],
            playlist_category=data.get("playlist_category", "Trending"),
            cost_usd=round(cost, 6),
        )

        logger.info(
            f"SEO generated: title='{result.title_urdu[:40]}...', "
            f"{len(result.tags)} tags, cost=${cost:.4f}"
        )
        return result

    except Exception as e:
        logger.error(f"SEO generation failed: {e}")
        # Fallback minimal SEO
        return SEOResult(
            title_urdu=topic_text[:60],
            title_english=topic_text[:60],
            description=topic_text,
            tags=default_tags,
            hashtags=["#Pakistan", "#Trending", "#Urdu"],
            playlist_category="Trending",
        )


def generate_shorts_seo(topic: Dict, channel_config: dict) -> SEOResult:
    """Generate SEO metadata specifically for YouTube Shorts."""
    topic_text = topic.get("text", "")

    prompt = f"""موضوع: {topic_text}

YouTube Shorts ویڈیو کے لیے SEO بنائیں:
- مختصر اردو ٹائٹل (40 حروف)
- مختصر description (100 الفاظ)
- 15 ٹیگز
- 5 ہیش ٹیگز (#Shorts ضرور شامل کریں)
صرف JSON میں جواب دیں۔"""

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_tokens=1000,
            response_format={"type": "json_object"},
        )

        usage = response.usage
        cost = (usage.prompt_tokens * 0.15 / 1_000_000) + (usage.completion_tokens * 0.60 / 1_000_000)
        data = json.loads(response.choices[0].message.content)

        hashtags = data.get("hashtags", [])
        if "#Shorts" not in hashtags:
            hashtags.insert(0, "#Shorts")

        return SEOResult(
            title_urdu=data.get("title_urdu", topic_text)[:40],
            title_english=data.get("title_english", topic_text)[:40],
            description=data.get("description", ""),
            tags=data.get("tags", [])[:15],
            hashtags=hashtags,
            playlist_category="Shorts",
            cost_usd=round(cost, 6),
        )
    except Exception as e:
        logger.error(f"Shorts SEO generation failed: {e}")
        return SEOResult(
            title_urdu=topic_text[:40],
            tags=["#Shorts", "#Pakistan", "#Trending"],
            hashtags=["#Shorts"],
            playlist_category="Shorts",
        )
