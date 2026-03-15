# UpperCut — YouTube Automation System

Fully automated YouTube channel management: trending topics → Urdu scripts → voiceover → video assembly → upload → self-learning optimization.

## Quick Start (macOS)

```bash
# 1. Install dependencies
brew install python@3.11 ffmpeg

# 2. Setup
cd ~/Desktop/uppercut
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. Configure
# - Fill in .env with your API keys
# - Place client_secrets.json in project root

# 4. Initialize database
python main.py --init-db

# 5. Test run (single pipeline execution)
python main.py --test

# 6. Production mode (runs every 6 hours)
python main.py
```

## CLI Commands

```bash
python main.py                  # Production mode (scheduler)
python main.py --test           # Single pipeline run
python main.py --channel x.yaml # Run specific channel
python main.py --init-db        # Initialize database only
python main.py --intelligence   # Run intelligence engine only
python main.py --dashboard      # Start web dashboard (port 8080)
python main.py --dashboard --port 3000  # Custom port
```

## VPS Deployment (Ubuntu 24.04)

```bash
# Copy project to VPS
scp -r ~/Desktop/uppercut root@95.217.13.249:/opt/

# SSH in and run setup
ssh root@95.217.13.249
cd /opt/uppercut
chmod +x setup.sh
sudo ./setup.sh
```

## Project Structure

```
uppercut/
├── main.py              # Master pipeline runner + CLI
├── config.py            # Settings, paths, database init
├── channels/*.yaml      # Channel configurations
├── modules/             # Phase 1: Core Pipeline
│   ├── trend_fetcher    # Google Trends + RSS + intelligence scoring
│   ├── script_generator # GPT-4o-mini Urdu scripts
│   ├── voice_generator  # edge-tts voiceover
│   ├── footage_fetcher  # Pexels + Pixabay stock footage
│   ├── video_assembler  # moviepy video creation + subtitles
│   ├── thumbnail_maker  # Pillow A/B thumbnails
│   ├── seo_generator    # YouTube SEO metadata (Urdu+English)
│   ├── shorts_maker     # 60s vertical clips
│   └── uploader/        # YouTube Data API upload + playlists
├── intelligence/        # Phase 2: Self-Learning Engine
│   ├── analytics_collector   # YouTube Data + Analytics API stats
│   ├── performance_analyzer  # Pattern detection (time, length, niche)
│   └── strategy_optimizer    # Persists learned strategy to DB
├── dashboard/           # Phase 3: Web Dashboard
│   ├── app.py           # FastAPI app + API endpoints
│   ├── templates/       # Jinja2 HTML (dashboard, videos, analytics, errors)
│   └── static/          # CSS (dark theme)
├── alerts/              # Phase 4: Email Alerts
│   └── email_alerts.py  # SMTP notifications (success, failure, daily digest)
├── assets/              # Fonts, music, templates
├── output/              # Generated content
└── database/            # SQLite database
```

## Phase Overview

| Phase | Name | Description |
|-------|------|-------------|
| 1 | Core Pipeline | Trends → Script → Voice → Video → Upload |
| 2 | Intelligence Engine | YouTube analytics → pattern analysis → strategy optimization → feedback loop |
| 3 | Web Dashboard | FastAPI dashboard with stats, videos, analytics, errors |
| 4 | Email Alerts | SMTP alerts for success, failure, retries, quota, daily digest |

## Intelligence Engine

The self-learning engine runs after every pipeline cycle:

1. **Collect** — Pulls YouTube stats (views, CTR, watch time, impressions) for all uploaded videos
2. **Analyze** — Finds patterns: best upload time, video length, niches, keywords
3. **Optimize** — Updates the strategy table with recommendations
4. **Feedback** — Trend scorer uses learned keywords to pick better topics

Run standalone: `python main.py --intelligence`

## Web Dashboard

Dark-themed dashboard at `http://localhost:8080`:

- **Overview** — Stats cards, strategy, top videos, recent videos, errors
- **Videos** — Full video history with status, views, cost
- **Analytics** — Intelligence insights, daily history, top performers
- **Errors** — Error log with resolve actions
- **API** — JSON endpoints at `/api/stats/{id}`, `/api/videos/{id}`, `/api/strategy/{id}`

## Email Alerts

Configure in `.env`:
```
ALERT_EMAIL=your@email.com
SMTP_EMAIL=sender@gmail.com
SMTP_PASSWORD=your-app-password
```

Alert types:
- Pipeline success (with YouTube links)
- Pipeline failure / retries exhausted
- YouTube quota exceeded
- Daily summary digest (23:55 PKT)

## YouTube OAuth Setup

1. Go to Google Cloud Console
2. Create a project and enable YouTube Data API v3 + YouTube Analytics API
3. Create OAuth 2.0 credentials (Desktop app)
4. Download the JSON and save as `client_secrets.json`
5. On first run, a browser will open for authentication
6. Token is saved to `token.json` for future use

## Adding Channels

Create a new YAML file in `channels/` (copy `uppercut_pk.yaml` as template).
The pipeline automatically picks up all `.yaml` files in that directory.

## Assets

- **Fonts:** Auto-downloaded (Noto Nastaliq Urdu)
- **Music:** Place royalty-free MP3s in `assets/music/`
- **Intro/Outro:** Place 3s MP4 clips in `assets/templates/`
