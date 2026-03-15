"""
UpperCut — Script Generator
Uses GPT-4o-mini to generate natural conversational Urdu scripts
with section-level footage keywords.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from typing import Dict, List

from loguru import logger
from openai import OpenAI

from config import OPENAI_API_KEY, OPENAI_MODEL, get_db

client = OpenAI(api_key=OPENAI_API_KEY)

# Script styles that rotate across videos
SCRIPT_STYLES = {
    "news_anchor": "آپ ایک تجربہ کار نیوز اینکر ہیں جو بریکنگ نیوز پیش کر رہے ہیں۔ سنجیدہ لیکن دلچسپ انداز میں بات کریں۔",
    "story_narrative": "آپ ایک قصہ گو ہیں جو کہانی سنا رہے ہیں۔ سسپنس اور جذبات کے ساتھ بات کریں جیسے دوستوں کو کہانی سنا رہے ہوں۔",
    "debate": "آپ دونوں طرف کی دلائل پیش کر رہے ہیں۔ سوالات اٹھائیں، مختلف نقطہ نظر بیان کریں، اور سامعین کو سوچنے پر مجبور کریں۔",
}


@dataclass
class ScriptResult:
    """Container for a generated script and its metadata."""
    text: str                                # Full Urdu script
    style: str                               # Which style was used
    sections: List[Dict] = field(default_factory=list)   # [{title, text, keywords}]
    word_count: int = 0
    estimated_duration_mins: float = 0.0
    cost_usd: float = 0.0
    footage_keywords: List[str] = field(default_factory=list)  # Flat list of all keywords


SYSTEM_PROMPT = """آپ UpperCut یوٹیوب چینل کے لیے اسکرپٹ لکھنے والے ماہر ہیں۔

اہم ہدایات:
1. صرف قدرتی پاکستانی بول چال کی اردو استعمال کریں — ترجمہ شدہ یا رسمی اردو نہیں۔
2. ایسے لکھیں جیسے ایک پاکستانی دوست دوسرے دوست کو بتا رہا ہو۔
3. ہر سیکشن کے لیے انگریزی میں stock footage/image سرچ keywords دیں۔
4. پاکستانی اور ہندوستانی ثقافتی حوالے استعمال کریں۔
5. جذباتی ہکس، سسپنس، اور curiosity gaps استعمال کریں۔
6. ہر اسکرپٹ 1200-1500 الفاظ کا ہو (8-10 منٹ ویڈیو)۔

آپ کو JSON فارمیٹ میں جواب دینا ہے:
{
    "sections": [
        {
            "title": "سیکشن کا نام",
            "text": "اسکرپٹ ٹیکسٹ یہاں...",
            "keywords": ["keyword1", "keyword2", "keyword3"]
        }
    ]
}

سیکشن ترتیب:
1. Hook (پہلے 30 سیکنڈ) — حیران کن یا تجسس والا بیان
2. Introduction (1 منٹ) — موضوع کا تعارف
3. Main Point 1 (2 منٹ) — پہلا اہم نکتہ
4. Cliffhanger — 3 منٹ پر سسپنس
5. Main Point 2 (2 منٹ) — دوسرا اہم نکتہ
6. Main Point 3 (2 منٹ) — تیسرا اہم نکتہ
7. Conclusion (1 منٹ) — خلاصہ + لائیک سبسکرائب کی اپیل"""


def generate(topic: Dict, channel_config: dict) -> ScriptResult:
    """
    Generate a full Urdu video script for the given topic.

    Args:
        topic: dict with at least 'text' key (the topic title)
        channel_config: parsed YAML channel config

    Returns:
        ScriptResult with full script, sections, keywords, and cost.
    """
    content_cfg = channel_config.get("content", {})
    styles = content_cfg.get("script_styles", list(SCRIPT_STYLES.keys()))
    chosen_style = random.choice(styles)
    style_instruction = SCRIPT_STYLES.get(chosen_style, SCRIPT_STYLES["story_narrative"])

    topic_text = topic.get("text", "trending topic")

    user_prompt = f"""موضوع: {topic_text}

انداز: {style_instruction}

اس موضوع پر ایک مکمل یوٹیوب ویڈیو اسکرپٹ لکھیں۔
ہدف: 1200-1500 الفاظ، 8-10 منٹ ویڈیو۔
یاد رکھیں: قدرتی پاکستانی اردو، جذباتی ہکس، اور ہر سیکشن کے لیے انگریزی footage keywords۔
صرف JSON فارمیٹ میں جواب دیں۔"""

    logger.info(f"Generating script for: {topic_text[:50]}... (style: {chosen_style})")

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.85,
            max_tokens=4000,
            response_format={"type": "json_object"},
        )

        # Calculate cost (GPT-4o-mini pricing: $0.15/1M input, $0.60/1M output)
        usage = response.usage
        cost = (usage.prompt_tokens * 0.15 / 1_000_000) + (usage.completion_tokens * 0.60 / 1_000_000)

        raw = response.choices[0].message.content
        data = json.loads(raw)
        sections = data.get("sections", [])

        # Build full text and collect keywords
        full_text = ""
        all_keywords = []
        for sec in sections:
            full_text += sec.get("text", "") + "\n\n"
            all_keywords.extend(sec.get("keywords", []))

        word_count = len(full_text.split())
        # Urdu speech rate: ~130 words per minute
        est_duration = word_count / 130

        result = ScriptResult(
            text=full_text.strip(),
            style=chosen_style,
            sections=sections,
            word_count=word_count,
            estimated_duration_mins=round(est_duration, 1),
            cost_usd=round(cost, 6),
            footage_keywords=list(set(all_keywords)),
        )

        logger.info(
            f"Script generated: {word_count} words, ~{est_duration:.1f} min, "
            f"style={chosen_style}, cost=${cost:.4f}"
        )

        # Track cost in DB
        _track_cost(cost)

        return result

    except Exception as e:
        logger.error(f"Script generation failed: {e}")
        raise


def generate_short_script(topic: Dict, channel_config: dict) -> ScriptResult:
    """Generate a 60-second Shorts script (150-180 words)."""
    topic_text = topic.get("text", "trending topic")

    short_prompt = f"""موضوع: {topic_text}

ایک 60 سیکنڈ کی YouTube Shorts ویڈیو کے لیے اسکرپٹ لکھیں۔
- 150-180 الفاظ
- فوری ہک سے شروع
- ایک ہی اہم نکتہ
- آخر میں "فالو کریں مزید کے لیے"
صرف JSON فارمیٹ میں جواب دیں۔"""

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": short_prompt},
            ],
            temperature=0.85,
            max_tokens=1000,
            response_format={"type": "json_object"},
        )

        usage = response.usage
        cost = (usage.prompt_tokens * 0.15 / 1_000_000) + (usage.completion_tokens * 0.60 / 1_000_000)

        data = json.loads(response.choices[0].message.content)
        sections = data.get("sections", [])
        full_text = "\n".join(s.get("text", "") for s in sections)
        all_keywords = []
        for s in sections:
            all_keywords.extend(s.get("keywords", []))

        _track_cost(cost)

        return ScriptResult(
            text=full_text.strip(),
            style="short",
            sections=sections,
            word_count=len(full_text.split()),
            estimated_duration_mins=1.0,
            cost_usd=round(cost, 6),
            footage_keywords=list(set(all_keywords)),
        )
    except Exception as e:
        logger.error(f"Short script generation failed: {e}")
        raise


def _track_cost(cost_usd: float):
    """Add API cost to the latest video record (if any)."""
    try:
        db = get_db()
        db.execute(
            "UPDATE videos SET cost_usd = cost_usd + ? WHERE id = (SELECT MAX(id) FROM videos)",
            (cost_usd,),
        )
        db.commit()
        db.close()
    except Exception:
        pass  # Non-critical, don't break pipeline
