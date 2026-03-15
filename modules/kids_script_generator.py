"""
UpperCut — Kids Script Generator (KiddoWorld)
Generates cheerful, educational, child-safe scripts using GPT-4o-mini.
Supports multi-language output (English + Hindi + Spanish).
"""

from __future__ import annotations

import json
import re
import random
from dataclasses import dataclass, field
from typing import Dict, List

from loguru import logger
from openai import OpenAI

from config import OPENAI_API_KEY, OPENAI_MODEL, get_db

client = OpenAI(api_key=OPENAI_API_KEY)


# ── Script styles ───────────────────────────────────────────────────────────

KIDS_SCRIPT_STYLES = {
    "song_rhyme": "You are writing a fun, catchy kids song with rhyming lyrics. "
                  "Include musical cues like [CLAP CLAP], [STOMP STOMP]. "
                  "Make it extremely catchy and repetitive.",
    "story_narrative": "You are telling a short bedtime/adventure story for little kids. "
                       "Use a warm, friendly narrator voice. Include character dialogue. "
                       "Keep the plot very simple with a clear happy ending.",
    "educational_lesson": "You are teaching one concept (letter, number, color, shape, animal). "
                          "Use call-and-response: 'Can you say RED? RED! Great job!' "
                          "Repeat the main concept at least 5 times.",
}


# ── System prompt ───────────────────────────────────────────────────────────

KIDS_SCRIPT_SYSTEM_PROMPT = """You are a children's content writer specializing in creating \
engaging, educational, and fun scripts for kids aged 2-8.

CRITICAL: The script has TWO completely separate parts:
1. "voice_text" — ONLY natural speech a child would hear. No brackets, \
no stage directions, no technical instructions, no [CLAPPING], no [SHOW ...], \
no [ANIMATE: ...]. Just warm, fun, spoken words.
2. "animation_prompt" — Scene description for the AI animation generator. \
This is NEVER read aloud.

RULES FOR voice_text:
- Use extremely simple vocabulary (max 3rd grade level)
- Keep sentences very short (5-8 words max)
- Use lots of repetition (kids love it)
- Make it rhyme whenever possible
- Always include a learning element
- End with encouragement: "Great job!", "You did it!", "Yay!"
- Keep total voice_text to 400-600 words for 3-5 min video

ABSOLUTELY FORBIDDEN in voice_text (these will be read aloud by TTS):
- NO square brackets [] of any kind
- NO stage directions like "Scene 1:", "NARRATOR:", "HOST:"
- NO music descriptions like "Musical notes", "Music plays", "Jingle"
- NO emoji descriptions like "musical notes emoji", "clapping emoji"
- NO sound effect names like "Sound effect", "SFX", "whoosh sound"
- NO parenthetical directions like (singing), (cheerfully), (slowly)
- NO technical terms like "fade in", "cut to", "transition"
- ONLY write words that sound natural when spoken aloud to a child

SAFETY - ABSOLUTELY MANDATORY:
- No violence of any kind
- No scary elements
- No adult themes
- No brand mentions
- No political content
- Always positive, encouraging tone
- Diverse and inclusive characters

SCRIPT STRUCTURE:
1. Catchy intro jingle (30 seconds)
2. Main content (2-3 mins)
3. Repetition/review section (1 min)
4. Outro with subscribe prompt (30 seconds)

Return JSON format:
{
    "sections": [
        {
            "title": "Section name",
            "voice_text": "Only natural speech here. No brackets or instructions.",
            "keywords": ["keyword1", "keyword2"],
            "animation_prompt": "Detailed cartoon animation scene description for AI generation"
        }
    ]
}

ANIMATION PROMPTS must always include:
"bright colorful 2D cartoon animation, child-friendly, safe for kids, \
Pixar-inspired, vibrant colors, cute characters, happy cheerful atmosphere, \
no dark themes"
"""


TRANSLATE_SYSTEM_PROMPT = """You translate children's scripts into {language}.

RULES:
- Keep the same simple, cheerful tone
- Maintain sound effects like [CLAPPING] unchanged
- Keep animation prompts in English (don't translate those)
- Keep it natural — not a literal translation
- Maintain rhyming where possible in the target language

Return the same JSON structure with translated text fields only.
"""


# ── Data classes ────────────────────────────────────────────────────────────

@dataclass
class KidsScriptResult:
    """Container for a generated kids script."""
    text: str
    style: str
    language: str = "english"
    sections: List[Dict] = field(default_factory=list)
    word_count: int = 0
    estimated_duration_mins: float = 0.0
    cost_usd: float = 0.0
    animation_prompts: List[str] = field(default_factory=list)
    footage_keywords: List[str] = field(default_factory=list)


# ── Evergreen content bank ──────────────────────────────────────────────────

EVERGREEN_TOPICS = [
    {"text": "ABC Alphabet Song", "type": "song_rhyme", "concept": "alphabet"},
    {"text": "123 Numbers Song - Count to 20", "type": "song_rhyme", "concept": "numbers"},
    {"text": "Learn Colors of the Rainbow", "type": "educational_lesson", "concept": "colors"},
    {"text": "Shapes Song - Circle Square Triangle", "type": "song_rhyme", "concept": "shapes"},
    {"text": "Animal Sounds Song", "type": "song_rhyme", "concept": "animals"},
    {"text": "Wheels on the Bus", "type": "song_rhyme", "concept": "vehicles"},
    {"text": "Old MacDonald Had a Farm", "type": "song_rhyme", "concept": "farm animals"},
    {"text": "Twinkle Twinkle Little Star", "type": "song_rhyme", "concept": "space"},
    {"text": "Head Shoulders Knees and Toes", "type": "song_rhyme", "concept": "body parts"},
    {"text": "If You're Happy and You Know It", "type": "song_rhyme", "concept": "emotions"},
    {"text": "The Little Star - Bedtime Story", "type": "story_narrative", "concept": "kindness"},
    {"text": "Days of the Week Song", "type": "song_rhyme", "concept": "days"},
    {"text": "Months of the Year Song", "type": "song_rhyme", "concept": "months"},
    {"text": "Weather Song for Kids", "type": "educational_lesson", "concept": "weather"},
    {"text": "Good Morning Song", "type": "song_rhyme", "concept": "routine"},
    {"text": "Fruits and Vegetables Song", "type": "educational_lesson", "concept": "food"},
    {"text": "Baby Shark Dance", "type": "song_rhyme", "concept": "sea animals"},
    {"text": "Five Little Ducks", "type": "song_rhyme", "concept": "counting"},
    {"text": "The Friendly Dinosaur Story", "type": "story_narrative", "concept": "friendship"},
    {"text": "Learn Phonics A to Z", "type": "educational_lesson", "concept": "phonics"},
]


def get_kids_topic(channel_config: dict, channel_id: int) -> Dict:
    """
    Pick a kids content topic — either trending or evergreen.
    Checks DB to avoid repeating recently used topics.
    """
    db = get_db()

    # Get recently used topics (last 30 days)
    used = db.execute(
        "SELECT topic_text FROM topics WHERE channel_id=? AND used=1 "
        "AND created_at > datetime('now', '-30 days')",
        (channel_id,),
    ).fetchall()
    used_texts = {r["topic_text"].lower() for r in used}
    db.close()

    # Filter evergreen topics to ones not recently used
    available = [
        t for t in EVERGREEN_TOPICS
        if t["text"].lower() not in used_texts
    ]

    if not available:
        # All used — reset and pick randomly
        available = EVERGREEN_TOPICS

    topic = random.choice(available)
    topic["source"] = "evergreen_bank"
    topic["score"] = 80  # Evergreen content has stable baseline score

    logger.info(f"Kids topic selected: {topic['text']} (type: {topic.get('type', 'general')})")
    return topic


# ── Script cleanup for voice ────────────────────────────────────────────────

def clean_script_for_voice(script_text: str) -> str:
    """Remove all bracketed instructions, stage directions, and technical text.
    Only natural speech remains — this is what gets sent to edge-tts."""
    # Remove everything in square brackets [...]
    clean = re.sub(r'\[.*?\]', '', script_text)
    # Remove everything in curly brackets {...}
    clean = re.sub(r'\{.*?\}', '', clean)
    # Remove everything in parentheses that look like directions (singing), (cheerfully)
    clean = re.sub(r'\([^)]*(?:singing|cheerfully|slowly|loudly|softly|music|sound|clap|stomp)[^)]*\)', '', clean, flags=re.IGNORECASE)
    # Remove lines starting with # (comments)
    clean = re.sub(r'^#.*$', '', clean, flags=re.MULTILINE)
    # Remove stage directions like "Scene 1:", "NARRATOR:", "HOST:", etc.
    clean = re.sub(
        r'^(Scene|SCENE|NARRATOR|HOST|VOICE|CUT TO|FADE|INT\.|EXT\.).*$',
        '', clean, flags=re.MULTILINE,
    )
    # Remove "Section N:" or "Part N:" headers
    clean = re.sub(r'^(Section|Part|Verse|Chorus)\s*\d*\s*[:—\-].*$',
                   '', clean, flags=re.MULTILINE)
    # Remove music/sound descriptions that GPT sometimes adds as plain text
    clean = re.sub(r'(?i)\b(musical?\s*notes?|music\s*plays?|jingle|sound\s*effects?|sfx|♪|♫|🎵|🎶|🎤)\b', '', clean)
    # Remove emoji
    clean = re.sub(r'[\U0001F000-\U0001FFFF]', '', clean)
    # Remove extra blank lines
    clean = re.sub(r'\n\s*\n\s*\n', '\n\n', clean)
    # Remove extra spaces
    clean = re.sub(r'  +', ' ', clean)
    return clean.strip()


# ── Script generation ───────────────────────────────────────────────────────

def generate(topic: Dict, channel_config: dict) -> KidsScriptResult:
    """
    Generate a kids script in English.

    Args:
        topic: dict with 'text', optionally 'type' and 'concept'
        channel_config: parsed channel YAML

    Returns:
        KidsScriptResult with full script, sections, animation prompts.
    """
    content_cfg = channel_config.get("content", {})
    styles = content_cfg.get("script_styles", list(KIDS_SCRIPT_STYLES.keys()))

    # Use topic type if specified, otherwise pick randomly
    chosen_style = topic.get("type", random.choice(styles))
    style_instruction = KIDS_SCRIPT_STYLES.get(chosen_style, KIDS_SCRIPT_STYLES["song_rhyme"])

    topic_text = topic.get("text", "fun kids video")
    concept = topic.get("concept", "")

    user_prompt = f"""Topic: {topic_text}
Concept to teach: {concept}

Style: {style_instruction}

Write a complete kids video script for this topic.
Target: 400-600 words, 3-5 minute video.
Include 4-6 sections with animation prompts for each scene.
Remember: child-safe, cheerful, educational, lots of repetition.
Return ONLY valid JSON."""

    logger.info(f"Generating kids script: {topic_text} (style: {chosen_style})")

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": KIDS_SCRIPT_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.9,
            max_tokens=3000,
            response_format={"type": "json_object"},
        )

        usage = response.usage
        cost = (usage.prompt_tokens * 0.15 / 1_000_000) + (usage.completion_tokens * 0.60 / 1_000_000)

        data = json.loads(response.choices[0].message.content)
        sections = data.get("sections", [])

        full_text = ""
        all_keywords = []
        animation_prompts = []

        for sec in sections:
            # Prefer voice_text (clean speech only), fall back to text
            voice = sec.get("voice_text") or sec.get("text", "")
            full_text += voice + "\n\n"
            all_keywords.extend(sec.get("keywords", []))
            anim = sec.get("animation_prompt", "")
            if anim:
                animation_prompts.append(anim)

        # Final safety pass: remove any remaining brackets/directions
        full_text = clean_script_for_voice(full_text)

        word_count = len(full_text.split())
        est_duration = word_count / 120  # Kids speech is slower: ~120 wpm

        result = KidsScriptResult(
            text=full_text.strip(),
            style=chosen_style,
            language="english",
            sections=sections,
            word_count=word_count,
            estimated_duration_mins=round(est_duration, 1),
            cost_usd=round(cost, 6),
            animation_prompts=animation_prompts,
            footage_keywords=list(set(all_keywords)),
        )

        logger.info(
            f"Kids script generated: {word_count} words, ~{est_duration:.1f} min, "
            f"{len(animation_prompts)} scenes, cost=${cost:.4f}"
        )

        _track_cost(cost, "openai", "kids_script")
        return result

    except Exception as e:
        logger.error(f"Kids script generation failed: {e}")
        raise


def translate_script(
    script: KidsScriptResult,
    target_language: str,
) -> KidsScriptResult:
    """
    Translate an English kids script to another language.

    Args:
        script: the original English KidsScriptResult
        target_language: 'hindi' or 'spanish'

    Returns:
        New KidsScriptResult in the target language.
    """
    lang_names = {"hindi": "Hindi (हिंदी)", "spanish": "Spanish (Español)"}
    lang_display = lang_names.get(target_language, target_language)

    system = TRANSLATE_SYSTEM_PROMPT.format(language=lang_display)

    sections_json = json.dumps({"sections": script.sections}, ensure_ascii=False)

    user_prompt = f"""Translate this children's script into {lang_display}.
Keep animation_prompt fields in English.
Translate only the 'title' and 'text' fields.
Return ONLY valid JSON.

{sections_json}"""

    logger.info(f"Translating kids script to {target_language}...")

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.5,
            max_tokens=3000,
            response_format={"type": "json_object"},
        )

        usage = response.usage
        cost = (usage.prompt_tokens * 0.15 / 1_000_000) + (usage.completion_tokens * 0.60 / 1_000_000)

        data = json.loads(response.choices[0].message.content)
        sections = data.get("sections", [])

        full_text = "\n\n".join(s.get("text", "") for s in sections)

        result = KidsScriptResult(
            text=full_text.strip(),
            style=script.style,
            language=target_language,
            sections=sections,
            word_count=len(full_text.split()),
            estimated_duration_mins=script.estimated_duration_mins,
            cost_usd=round(cost, 6),
            animation_prompts=script.animation_prompts,  # Keep English prompts
            footage_keywords=script.footage_keywords,
        )

        logger.info(f"Translation to {target_language} complete, cost=${cost:.4f}")
        _track_cost(cost, "openai", f"translate_{target_language}")
        return result

    except Exception as e:
        logger.error(f"Translation to {target_language} failed: {e}")
        raise


def generate_all_languages(
    topic: Dict,
    channel_config: dict,
) -> Dict[str, KidsScriptResult]:
    """
    Generate English script + translations for all secondary languages.

    Returns:
        Dict mapping language code to KidsScriptResult.
    """
    # English first
    english_script = generate(topic, channel_config)
    scripts = {"english": english_script}

    # Translate to secondary languages
    secondary = channel_config.get("channel", {}).get("secondary_languages", [])
    for lang in secondary:
        try:
            scripts[lang] = translate_script(english_script, lang)
        except Exception as e:
            logger.warning(f"Skipping {lang} translation: {e}")

    return scripts


def _track_cost(cost_usd: float, service: str = "openai", operation: str = "kids_script"):
    """Track API cost in both videos table and cost_tracking table."""
    try:
        db = get_db()
        # Update latest video cost
        db.execute(
            "UPDATE videos SET cost_usd = cost_usd + ? WHERE id = (SELECT MAX(id) FROM videos)",
            (cost_usd,),
        )
        # Log to cost_tracking
        db.execute(
            "INSERT INTO cost_tracking (service, operation, cost_usd) VALUES (?, ?, ?)",
            (service, operation, cost_usd),
        )
        db.commit()
        db.close()
    except Exception:
        pass
