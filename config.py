"""
UpperCut — Central Configuration
All settings, paths, and constants used across the system.
"""

import os
import sqlite3
from pathlib import Path
from dotenv import load_dotenv
from loguru import logger

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

OUTPUT_DIR      = BASE_DIR / "output"
VIDEO_DIR       = OUTPUT_DIR / "videos"
THUMB_DIR       = OUTPUT_DIR / "thumbnails"
AUDIO_DIR       = OUTPUT_DIR / "audio"
FOOTAGE_DIR     = OUTPUT_DIR / "footage"
LOG_DIR         = OUTPUT_DIR / "logs"
DB_PATH         = BASE_DIR / "database" / "master.db"
FONT_DIR        = BASE_DIR / "assets" / "fonts"
MUSIC_DIR       = BASE_DIR / "assets" / "music"
TEMPLATE_DIR    = BASE_DIR / "assets" / "templates"
CHANNEL_DIR     = BASE_DIR / "channels"

ANIMATION_DIR   = OUTPUT_DIR / "animation"
KIDS_MUSIC_DIR  = BASE_DIR / "assets" / "music" / "kids"

# Ensure all output directories exist
for d in [VIDEO_DIR, THUMB_DIR, AUDIO_DIR, FOOTAGE_DIR, LOG_DIR, ANIMATION_DIR, KIDS_MUSIC_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Logging — loguru writes to console + rotating log file
# ---------------------------------------------------------------------------
logger.add(
    LOG_DIR / "uppercut_{time:YYYY-MM-DD}.log",
    rotation="1 day",
    retention="14 days",
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {name}:{function}:{line} — {message}",
)

# ---------------------------------------------------------------------------
# API Keys & Secrets
# ---------------------------------------------------------------------------
OPENAI_API_KEY          = os.getenv("OPENAI_API_KEY", "")
PEXELS_API_KEY          = os.getenv("PEXELS_API_KEY", "")
PIXABAY_API_KEY         = os.getenv("PIXABAY_API_KEY", "")
YOUTUBE_CLIENT_SECRETS  = os.getenv("YOUTUBE_CLIENT_SECRETS", "client_secrets.json")
FAL_API_KEY             = os.getenv("FAL_API_KEY", "")
os.environ.setdefault("FAL_KEY", FAL_API_KEY)  # fal_client reads FAL_KEY
ALERT_EMAIL             = os.getenv("ALERT_EMAIL", "")
SMTP_EMAIL              = os.getenv("SMTP_EMAIL", "")
SMTP_PASSWORD           = os.getenv("SMTP_PASSWORD", "")
DASHBOARD_SECRET_KEY    = os.getenv("DASHBOARD_SECRET_KEY", "change-me")
DASHBOARD_PORT          = int(os.getenv("DASHBOARD_PORT", "8080"))
DASHBOARD_USERNAME      = os.getenv("DASHBOARD_USERNAME", "admin")
DASHBOARD_PASSWORD      = os.getenv("DASHBOARD_PASSWORD", "changeme")
VPS_IP                  = os.getenv("VPS_IP", "")

# ---------------------------------------------------------------------------
# Video defaults
# ---------------------------------------------------------------------------
LONG_FORM_RES   = (1920, 1080)
SHORTS_RES      = (1080, 1920)
VIDEO_FPS       = 30
VIDEO_BITRATE   = "5000k"
AUDIO_BITRATE   = "192k"

# ---------------------------------------------------------------------------
# TTS voices
# ---------------------------------------------------------------------------
TTS_VOICE_MALE   = "ur-PK-AsadNeural"
TTS_VOICE_FEMALE = "ur-PK-UzmaNeural"

# ---------------------------------------------------------------------------
# OpenAI model
# ---------------------------------------------------------------------------
OPENAI_MODEL = "gpt-4o-mini"

# ---------------------------------------------------------------------------
# Noto Nastaliq Urdu font — auto-downloaded on first run
# ---------------------------------------------------------------------------
URDU_FONT_URLS = [
    "https://github.com/google/fonts/raw/refs/heads/main/ofl/notonastaliqurdu/NotoNastaliqUrdu-Regular.ttf",
    "https://fonts.gstatic.com/s/notonastaliqurdu/v20/LhWNMUPbN-oZdNFcBy1-DJYsEoTq5pudQ9L9ke2xM4E.ttf",
]
URDU_FONT_PATH = FONT_DIR / "NotoNastaliqUrdu-Regular.ttf"


def ensure_urdu_font() -> Path:
    """Download Noto Nastaliq Urdu if not already present. Falls back to Nunito."""
    if URDU_FONT_PATH.exists():
        return URDU_FONT_PATH

    import requests as _req

    URDU_FONT_PATH.parent.mkdir(parents=True, exist_ok=True)
    for url in URDU_FONT_URLS:
        try:
            logger.info(f"Downloading Urdu font from {url[:60]}...")
            resp = _req.get(url, timeout=30)
            resp.raise_for_status()
            URDU_FONT_PATH.write_bytes(resp.content)
            logger.info(f"Urdu font saved: {URDU_FONT_PATH}")
            return URDU_FONT_PATH
        except Exception as e:
            logger.warning(f"Urdu font URL failed: {e}")

    # Fallback to Nunito (always available)
    logger.warning("All Urdu font URLs failed — falling back to Nunito")
    fallback = ensure_kids_font()
    return fallback


# ---------------------------------------------------------------------------
# Nunito font for kids channel — rounded, friendly
# ---------------------------------------------------------------------------
NUNITO_VARIABLE_URL = "https://github.com/google/fonts/raw/main/ofl/nunito/Nunito%5Bwght%5D.ttf"
NUNITO_FONT_PATH = FONT_DIR / "Nunito-Regular.ttf"
NUNITO_BOLD_PATH = FONT_DIR / "Nunito-Bold.ttf"


def ensure_kids_font() -> Path:
    """Download Nunito font for kids channel if not already present."""
    import requests as _req

    # Nunito now ships as a single variable-weight .ttf — use it for both regular and bold
    for path in [NUNITO_FONT_PATH, NUNITO_BOLD_PATH]:
        if not path.exists():
            logger.info(f"Downloading kids font → {path.name}")
            path.parent.mkdir(parents=True, exist_ok=True)
            resp = _req.get(NUNITO_VARIABLE_URL, timeout=60)
            resp.raise_for_status()
            path.write_bytes(resp.content)
            logger.info(f"Font saved: {path}")
    return NUNITO_FONT_PATH


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------
def get_db() -> sqlite3.Connection:
    """Return a connection to the SQLite master database."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_database():
    """Create all tables if they don't already exist."""
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            niche TEXT NOT NULL,
            region TEXT NOT NULL,
            language TEXT NOT NULL,
            youtube_channel_id TEXT,
            is_active BOOLEAN DEFAULT 1,
            daily_long_form INTEGER DEFAULT 1,
            daily_shorts INTEGER DEFAULT 3,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER,
            topic_text TEXT NOT NULL,
            topic_urdu TEXT,
            source TEXT,
            used BOOLEAN DEFAULT 0,
            performance_score REAL DEFAULT 0,
            views INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (channel_id) REFERENCES channels(id)
        );

        CREATE TABLE IF NOT EXISTS videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER,
            topic_id INTEGER,
            title TEXT,
            script TEXT,
            video_path TEXT,
            thumbnail_path TEXT,
            status TEXT DEFAULT 'pending',
            format TEXT DEFAULT 'long',
            duration_seconds INTEGER,
            retry_count INTEGER DEFAULT 0,
            cost_usd REAL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (channel_id) REFERENCES channels(id),
            FOREIGN KEY (topic_id) REFERENCES topics(id)
        );

        CREATE TABLE IF NOT EXISTS uploads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id INTEGER,
            channel_id INTEGER,
            youtube_video_id TEXT,
            youtube_url TEXT,
            title TEXT,
            description TEXT,
            tags TEXT,
            views INTEGER DEFAULT 0,
            likes INTEGER DEFAULT 0,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (video_id) REFERENCES videos(id)
        );

        CREATE TABLE IF NOT EXISTS analytics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER,
            date DATE,
            subscribers INTEGER DEFAULT 0,
            total_views INTEGER DEFAULT 0,
            watch_time_hours REAL DEFAULT 0,
            revenue_usd REAL DEFAULT 0,
            videos_published INTEGER DEFAULT 0,
            FOREIGN KEY (channel_id) REFERENCES channels(id)
        );

        CREATE TABLE IF NOT EXISTS errors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER,
            video_id INTEGER,
            error_type TEXT,
            error_message TEXT,
            retry_count INTEGER DEFAULT 0,
            resolved BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS strategy (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER,
            best_upload_time TEXT DEFAULT '18:00',
            best_video_length INTEGER DEFAULT 8,
            best_niche TEXT,
            best_thumbnail_style TEXT,
            best_script_style TEXT,
            top_performing_keywords TEXT,
            avg_views REAL DEFAULT 0,
            avg_ctr REAL DEFAULT 0,
            avg_watch_time_pct REAL DEFAULT 0,
            recommendation_notes TEXT,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (channel_id) REFERENCES channels(id)
        );

        CREATE TABLE IF NOT EXISTS video_analytics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            upload_id INTEGER,
            channel_id INTEGER,
            youtube_video_id TEXT NOT NULL,
            views INTEGER DEFAULT 0,
            likes INTEGER DEFAULT 0,
            dislikes INTEGER DEFAULT 0,
            comments INTEGER DEFAULT 0,
            shares INTEGER DEFAULT 0,
            watch_time_minutes REAL DEFAULT 0,
            avg_view_duration_seconds REAL DEFAULT 0,
            avg_view_percentage REAL DEFAULT 0,
            impressions INTEGER DEFAULT 0,
            ctr REAL DEFAULT 0,
            subscribers_gained INTEGER DEFAULT 0,
            subscribers_lost INTEGER DEFAULT 0,
            traffic_source TEXT,
            top_countries TEXT,
            fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (upload_id) REFERENCES uploads(id),
            FOREIGN KEY (channel_id) REFERENCES channels(id)
        );

        CREATE INDEX IF NOT EXISTS idx_video_analytics_yt_id ON video_analytics(youtube_video_id);
        CREATE INDEX IF NOT EXISTS idx_video_analytics_channel ON video_analytics(channel_id, fetched_at);

        -- Kids / multi-channel extensions
        CREATE TABLE IF NOT EXISTS cost_tracking (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER,
            video_id INTEGER,
            service TEXT NOT NULL,
            operation TEXT,
            cost_usd REAL DEFAULT 0,
            credits_used REAL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (channel_id) REFERENCES channels(id),
            FOREIGN KEY (video_id) REFERENCES videos(id)
        );

        CREATE INDEX IF NOT EXISTS idx_cost_channel_date ON cost_tracking(channel_id, created_at);

        -- Queue system
        CREATE TABLE IF NOT EXISTS queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER NOT NULL,
            video_id INTEGER,
            topic TEXT NOT NULL,
            format TEXT DEFAULT 'long',
            priority INTEGER DEFAULT 5,
            status TEXT DEFAULT 'waiting',
            retry_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            started_at TIMESTAMP,
            completed_at TIMESTAMP,
            FOREIGN KEY (channel_id) REFERENCES channels(id)
        );

        CREATE INDEX IF NOT EXISTS idx_queue_status ON queue(status, priority DESC, created_at ASC);
    """)
    conn.commit()

    # Seed default channels if table is empty
    row = conn.execute("SELECT COUNT(*) FROM channels").fetchone()
    if row[0] == 0:
        conn.execute(
            "INSERT INTO channels (name, niche, region, language) VALUES (?, ?, ?, ?)",
            ("UpperCut", "general_trending", "PK", "urdu"),
        )
        conn.execute(
            "INSERT INTO channels (name, niche, region, language, daily_long_form, daily_shorts) VALUES (?, ?, ?, ?, ?, ?)",
            ("KiddoWorld", "kids_educational_entertainment", "GLOBAL", "english", 2, 3),
        )
        conn.commit()
        logger.info("Seeded channels: UpperCut, KiddoWorld")
    else:
        # Ensure KiddoWorld exists even if UpperCut was already seeded
        kw = conn.execute("SELECT 1 FROM channels WHERE name='KiddoWorld'").fetchone()
        if not kw:
            conn.execute(
                "INSERT INTO channels (name, niche, region, language, daily_long_form, daily_shorts) VALUES (?, ?, ?, ?, ?, ?)",
                ("KiddoWorld", "kids_educational_entertainment", "GLOBAL", "english", 2, 3),
            )
            conn.commit()
            logger.info("Seeded channel: KiddoWorld")

    # Ensure OddlyPerfect channel exists
    op = conn.execute("SELECT 1 FROM channels WHERE name='OddlyPerfect'").fetchone()
    if not op:
        conn.execute(
            "INSERT INTO channels (id, name, niche, region, language, daily_long_form, daily_shorts) "
            "VALUES (3, 'OddlyPerfect', 'viral_shorts', 'GLOBAL', 'english', 0, 5)",
        )
        conn.commit()
        logger.info("Seeded channel: OddlyPerfect")

    conn.close()
    logger.info("Database initialised ✓")
