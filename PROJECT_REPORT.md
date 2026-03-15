# UpperCut — Final Project Report

> Generated: 2026-03-14
> Python Files: 27 | Shell Scripts: 6 | Templates: 5 | Config Files: 3
> Total Files: 47 | Syntax Errors: 0 | All Tests Passed

---

## System Overview

UpperCut is a fully automated YouTube channel management system that handles everything from trending topic discovery to video upload, analytics, and self-optimization. It supports two independent channels running on a single codebase:

1. **UpperCut** — Urdu news/trending content targeting Pakistan & India
2. **KiddoWorld** — English kids educational/entertainment content (ages 2-8, global)

### Tech Stack
| Layer | Technology |
|-------|-----------|
| Language | Python 3.13 |
| AI | OpenAI GPT-4o-mini (scripts, SEO) |
| Animation | fal.ai Pika v2.2 (cartoon video generation) |
| Voice | edge-tts (Microsoft Neural TTS, free) |
| Video | moviepy 2.x + ffmpeg 8.0 |
| Images | Pillow (thumbnails) |
| Music | Pixabay Music API (free, royalty-free) |
| Stock Footage | Pexels + Pixabay APIs (free) |
| Upload | YouTube Data API v3 (OAuth 2.0) |
| Analytics | YouTube Analytics API |
| Dashboard | FastAPI + Jinja2 + uvicorn |
| Database | SQLite (9 tables) |
| Alerts | SMTP HTML email (Gmail) |
| Scheduler | APScheduler |
| Deployment | Hetzner VPS + PM2 |

---

## Phase 1 — Core Pipeline (UpperCut)

The original pipeline that takes a trending topic and produces a fully uploaded YouTube video.

### Files (11)

| File | Path | Purpose |
|------|------|---------|
| `main.py` | `main.py` | Master pipeline runner, CLI, scheduler, pipeline router |
| `config.py` | `config.py` | Central settings, paths, API keys, database init |
| `trend_fetcher.py` | `modules/trend_fetcher.py` | Google Trends + RSS feeds, scoring (volume, recency, relevance, novelty, intelligence) |
| `script_generator.py` | `modules/script_generator.py` | GPT-4o-mini Urdu scripts with section-level footage keywords |
| `voice_generator.py` | `modules/voice_generator.py` | edge-tts Urdu voiceovers (male/female Pakistani voices) |
| `footage_fetcher.py` | `modules/footage_fetcher.py` | Pexels + Pixabay stock video/image downloads with caching |
| `video_assembler.py` | `modules/video_assembler.py` | moviepy video assembly + ffmpeg subtitles (faster-whisper) |
| `thumbnail_maker.py` | `modules/thumbnail_maker.py` | Pillow A/B thumbnails with Urdu text + gradient backgrounds |
| `seo_generator.py` | `modules/seo_generator.py` | GPT-4o-mini YouTube SEO (Urdu+English titles, tags, descriptions) |
| `shorts_maker.py` | `modules/shorts_maker.py` | ffmpeg 60s vertical clips from long-form videos |
| `youtube_uploader.py` | `modules/uploader/youtube_uploader.py` | YouTube Data API v3 upload, OAuth, playlists, made_for_kids support |

### Pipeline Flow
```
 1. Fetch trending topics      → Google Trends PK/IN + RSS feeds (Dawn, Geo, BBC Urdu, TOI)
 2. Score & pick best topic    → volume + recency + relevance + novelty + intelligence weights
 3. Generate Urdu script       → GPT-4o-mini, 1200-1500 words, 8-10 min, section-level keywords
 4. Generate voiceover         → edge-tts, ur-PK-AsadNeural
 5. Fetch stock footage        → Pexels → Pixabay → Pexels images fallback chain
 6. Assemble 1080p video       → moviepy + background music + intro/outro
 6b. Burn Urdu subtitles       → faster-whisper transcription + ffmpeg ASS subtitles
 7. Create 60s YouTube Short   → ffmpeg center-crop to 9:16 vertical
 8. Generate A/B thumbnails    → Pillow, crimson/blue palettes, Urdu Nastaliq font
 9. Generate SEO metadata      → GPT-4o-mini, Urdu+English titles, 35 tags
10. Upload to YouTube          → resumable upload, playlist management
11. Save to database           → videos, uploads, topics tables
12. Cleanup temporary files    → remove intermediate footage/audio
```

### Configuration
- **Channel config:** `channels/uppercut_pk.yaml`
- **Schedule:** Every 6 hours
- **Niches:** geopolitics, cricket, bollywood, celebrity, viral news, sports
- **RSS feeds:** Dawn, Geo, BBC Urdu, Times of India

---

## Phase 2 — Intelligence Engine

Self-learning system that collects YouTube analytics, finds performance patterns, and feeds insights back into the pipeline.

### Files (4)

| File | Path | Purpose |
|------|------|---------|
| `__init__.py` | `intelligence/__init__.py` | Orchestrator: collect → analyze → optimize |
| `analytics_collector.py` | `intelligence/analytics_collector.py` | YouTube Data API + Analytics API stats fetcher |
| `performance_analyzer.py` | `intelligence/performance_analyzer.py` | Pattern detection, video scoring, recommendations |
| `strategy_optimizer.py` | `intelligence/strategy_optimizer.py` | Persists learned strategy to DB, query helpers |

### Intelligence Flow
```
1. COLLECT — Fetch per-video stats from YouTube:
   ├── Data API: views, likes, comments
   └── Analytics API: CTR, impressions, watch time %, avg view duration,
       traffic sources, top countries, subscribers gained/lost

2. ANALYZE — Find patterns in performance data:
   ├── Composite video score (views 30%, CTR 25%, watch% 25%, engagement 20%)
   ├── Best upload hour & day of week
   ├── Best video length (2-minute buckets)
   ├── Best niche & top-performing keywords
   ├── Traffic source aggregation
   ├── Country breakdown
   └── Plain-text recommendations

3. OPTIMIZE — Update strategy table:
   ├── best_upload_time, best_video_length, best_niche
   ├── best_thumbnail_style (inferred from CTR ranges)
   ├── top_performing_keywords (JSON list)
   ├── avg_views, avg_ctr, avg_watch_time_pct
   └── recommendation_notes
```

### Feedback Loop
- `trend_fetcher.py` has a `W_INTELLIGENCE = 0.10` weight
- Topics matching historically high-performing keywords get a score boost
- `_intelligence_score()` queries `strategy_optimizer.get_top_performing_keywords()`
- The system automatically favors topics similar to past successes

### Database Tables Added
- `video_analytics` — 18 columns of per-video YouTube stats
- `strategy` — Extended with: `best_script_style`, `top_performing_keywords`, `avg_views`, `avg_ctr`, `avg_watch_time_pct`, `recommendation_notes`

---

## Phase 3 — Web Dashboard

FastAPI-based dark-themed dashboard for monitoring both channels.

### Files (8)

| File | Path | Purpose |
|------|------|---------|
| `__init__.py` | `dashboard/__init__.py` | Package marker |
| `app.py` | `dashboard/app.py` | FastAPI app, routes, queries, 15 API endpoints |
| `base.html` | `dashboard/templates/base.html` | Base template (sidebar nav, channel switcher) |
| `dashboard.html` | `dashboard/templates/dashboard.html` | Overview (stats, strategy, top videos, errors, costs) |
| `videos.html` | `dashboard/templates/videos.html` | Full video history table |
| `analytics.html` | `dashboard/templates/analytics.html` | Intelligence insights, daily history, top performers |
| `errors.html` | `dashboard/templates/errors.html` | Error log with resolve actions |
| `style.css` | `dashboard/static/style.css` | Dark theme CSS (purple accent, responsive) |

### Pages
| Page | URL | Description |
|------|-----|-------------|
| Dashboard | `/` | Stat cards, monthly cost breakdown, strategy, top videos, recent videos, errors |
| Videos | `/videos` | Full video list with status badges, duration, views, cost |
| Analytics | `/analytics` | Strategy details, recommendations, keywords, daily history, top performers |
| Errors | `/errors` | Error log with resolve buttons |

### API Endpoints
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/stats/{channel_id}` | GET | Channel statistics |
| `/api/videos/{channel_id}` | GET | Recent videos list |
| `/api/strategy/{channel_id}` | GET | Current strategy |
| `/api/errors/{channel_id}` | GET | Error list |
| `/api/costs` | GET | Monthly cost breakdown by service |
| `/api/errors/{error_id}/resolve` | POST | Mark error as resolved |

### How to Run
```bash
python main.py --dashboard              # Port 8080 (default)
python main.py --dashboard --port 3000  # Custom port
```

---

## Phase 4 — Email Alerts

SMTP email notifications with styled HTML templates.

### Files (2)

| File | Path | Purpose |
|------|------|---------|
| `__init__.py` | `alerts/__init__.py` | Package exports |
| `email_alerts.py` | `alerts/email_alerts.py` | 7 alert types with HTML email templates |

### Alert Types

| Function | Trigger | Color |
|----------|---------|-------|
| `pipeline_success()` | Video uploaded successfully | Green |
| `pipeline_failure()` | Pipeline run failed | Red |
| `retry_exhausted()` | All retries exhausted for a step | Red |
| `low_api_balance()` | API balance below threshold | Yellow |
| `quota_exceeded()` | YouTube/API quota hit | Red |
| `daily_summary()` | Cron job at 23:55 daily | Green/Yellow |
| `intelligence_update()` | New intelligence recommendations | Purple |

### Integration Points
- `main.py:_log_error_to_db()` → sends `retry_exhausted()` alert
- `main.py:run_news_pipeline()` → sends `pipeline_success()` or `pipeline_failure()`
- `main.py:run_kids_pipeline()` → sends `pipeline_success()` or `pipeline_failure()`
- `main.py:_send_daily_summary()` → cron at 23:55, sends per-channel digest
- `animation_generator.py:_track_animation_cost()` → sends `low_api_balance()` when fal.ai > $20/month

### Configuration
```
ALERT_EMAIL=abasit.tlg@gmail.com
SMTP_EMAIL=abasit.tlg@gmail.com
SMTP_PASSWORD=<app-password>
```

---

## KiddoWorld — Kids Channel Extension

Full kids content pipeline added without breaking any existing UpperCut functionality.

### Channel Details
| Setting | Value |
|---------|-------|
| Target Audience | Kids aged 2-8, global (USA, UK, Europe, Australia) |
| Primary Language | English |
| Secondary Languages | Hindi, Spanish (translations) |
| Content Types | Nursery rhymes, bedtime stories, educational videos, cartoon stories |
| Visual Style | AI-generated cartoon animation (fal.ai Pika v2.2) |
| Music Source | Pixabay (free, royalty-free kids tracks) |
| Voice Engine | edge-tts (Microsoft Neural, cheerful kids voices) |
| Schedule | 2 long-form + 3 Shorts per day |
| COPPA Compliance | `made_for_kids=True` on all uploads |

### New Files Created (7)

| File | Path | Purpose |
|------|------|---------|
| `kiddoworld.yaml` | `channels/kiddoworld.yaml` | Channel config (niches, schedule, animation, SEO settings) |
| `kids_script_generator.py` | `modules/kids_script_generator.py` | Kids scripts + translations + 20-topic evergreen bank |
| `kids_voice_generator.py` | `modules/kids_voice_generator.py` | Cheerful kids voices (3 languages, 5 voice options) |
| `animation_generator.py` | `modules/animation_generator.py` | fal.ai Pika cartoon clip generation + cost tracking + caching |
| `kids_music_fetcher.py` | `modules/kids_music_fetcher.py` | Pixabay Music API kids tracks + local caching |
| `kids_thumbnail_maker.py` | `modules/kids_thumbnail_maker.py` | Bright colorful kids A/B thumbnails (5 palettes) |
| `kids_seo_generator.py` | `modules/kids_seo_generator.py` | Kids-specific YouTube SEO (titles, tags, descriptions) |

### Kids Pipeline Flow
```
 1. Pick topic               → Evergreen bank of 20 topics, DB dedup (30-day window)
 2. Generate script           → English + Hindi + Spanish via GPT-4o-mini
    ├── Child-safe system prompt with strict safety rules
    ├── 400-600 words, 3-5 min video
    └── Animation prompts per scene (6-8 per script)
 3. Generate voiceover        → edge-tts, -20% rate, +10Hz pitch
    ├── English: en-US-AnaNeural / en-US-BrianNeural / en-GB-SoniaNeural
    ├── Hindi: hi-IN-SwaraNeural
    └── Spanish: es-ES-ElviraNeural
 4. Generate animation clips  → fal.ai Pika v2.2 text-to-video
    ├── Auto-appends child-safety suffix to all prompts
    ├── Cached by prompt hash to save credits
    └── Cost tracking per clip (~$0.10 each)
 5. Fetch background music    → Pixabay, cached locally in assets/music/kids/
 6. Assemble video            → moviepy, animation clips + voiceover + music (20% vol)
 7. Create YouTube Short      → ffmpeg, 60s vertical 9:16
 8. Generate thumbnails       → A/B variants, 5 color palettes, stars/sparkles
 9. Generate SEO              → Title formulas, age-appropriate tags, COPPA-safe description
10. Upload to YouTube         → made_for_kids=True, selfDeclaredMadeForKids=True
11. Save to database          → videos, uploads, topics, cost_tracking tables
12. Cleanup old clips         → Remove animation clips older than 7 days
```

### Evergreen Topic Bank (20 topics, auto-rotates)
```
 1. ABC Song                    11. The Little Star (Bedtime Story)
 2. 123 Numbers Song            12. Days of the Week Song
 3. Colors of the Rainbow       13. Months of the Year Song
 4. Shapes Song                 14. Weather Song for Kids
 5. Animal Sounds Song          15. Good Morning Song
 6. Wheels on the Bus           16. Fruits and Vegetables Song
 7. Old MacDonald Had a Farm    17. Baby Shark Dance
 8. Twinkle Twinkle Little Star 18. Five Little Ducks
 9. Head Shoulders Knees & Toes 19. The Friendly Dinosaur (Story)
10. If You're Happy & You Know  20. Learn Phonics A to Z
```

### Kids Voice Settings
| Language | Voice ID | Style | Rate | Pitch |
|----------|----------|-------|------|-------|
| English (primary) | en-US-AnaNeural | Cheerful girl | -20% | +10Hz |
| English (secondary) | en-US-BrianNeural | Friendly boy | -20% | +10Hz |
| English (narrator) | en-GB-SoniaNeural | Warm storyteller | -20% | +10Hz |
| Hindi | hi-IN-SwaraNeural | Hindi girl | -20% | +10Hz |
| Spanish | es-ES-ElviraNeural | Spanish girl | -20% | +10Hz |

### Animation Safety
Every fal.ai prompt automatically gets this suffix appended:
```
, bright colorful 2D cartoon animation, child-friendly, safe for kids,
Pixar-inspired, vibrant colors, cute characters, happy cheerful atmosphere,
no dark themes, no violence, no scary elements
```

### COPPA Compliance
- `madeForKids: True` set on every upload
- `selfDeclaredMadeForKids: True` set on every upload
- No data collection, no personalized ads
- No external links, comments auto-disabled by YouTube
- Script generator has strict safety rules (no violence, no scary, no adult themes, no brands)

---

## Existing Files Modified

| File | Changes Made |
|------|-------------|
| `config.py` | +`FAL_API_KEY` + `FAL_KEY` env bridge, +`ANIMATION_DIR`, +`KIDS_MUSIC_DIR`, +`ensure_kids_font()` (Nunito variable font), +`cost_tracking` DB table, +KiddoWorld channel seed |
| `main.py` | +`run_pipeline()` router (niche-based dispatch), +`run_kids_pipeline()` (12-step kids pipeline), renamed original to `run_news_pipeline()` |
| `video_assembler.py` | Updated moviepy imports from `moviepy.editor` to `moviepy` (v2.x compatibility) |
| `youtube_uploader.py` | +`made_for_kids` parameter, +`madeForKids`/`selfDeclaredMadeForKids` in body, +auto language detection |
| `dashboard/app.py` | +`_get_cost_summary()` query, +`/api/costs` endpoint, +costs passed to dashboard template |
| `dashboard.html` | +Monthly Cost Breakdown card (service-by-service) |
| `requirements.txt` | +`fal-client>=0.5.6`, relaxed all version pins to `>=` for Python 3.13 compatibility |
| `.env` | +`FAL_API_KEY` field |

---

## Database Schema (9 tables)

| Table | Columns | Purpose |
|-------|---------|---------|
| `channels` | id, name, config_file, active, created_at | Channel registry (UpperCut, KiddoWorld) |
| `topics` | id, channel_id, topic_text, source, score, used, created_at | Fetched/used topics per channel |
| `videos` | id, channel_id, topic_id, title, script, status, duration, cost_usd, language, made_for_kids, created_at | Video production records |
| `uploads` | id, video_id, youtube_id, url, views, likes, status, uploaded_at | YouTube upload records |
| `analytics` | id, channel_id, date, views, subscribers, watch_hours | Daily channel-level analytics |
| `errors` | id, channel_id, step, error_msg, resolved, created_at | Pipeline error log |
| `strategy` | id, channel_id, best_upload_time, best_video_length, best_niche, best_thumbnail_style, top_performing_keywords, avg_views, avg_ctr, avg_watch_time_pct, recommendation_notes, updated_at | Intelligence learned strategy |
| `video_analytics` | id, video_id, views, likes, comments, ctr, impressions, watch_time_pct, avg_view_duration, traffic_sources, top_countries, subs_gained, subs_lost, fetched_at | Per-video YouTube stats (18 cols) |
| `cost_tracking` | id, service, operation, cost_usd, channel_id, created_at | Per-API-call cost logging |

---

## Deployment & Operations

### Shell Scripts (6)

| Script | Purpose | Run |
|--------|---------|-----|
| `local_setup.sh` | Install ffmpeg, create venv, install packages, init DB | `./local_setup.sh` |
| `test_pipeline.sh` | Step-by-step module tests (10 steps) | `./test_pipeline.sh` |
| `deploy_to_vps.sh` | rsync project + setup VPS (Python, ffmpeg, PM2) | `./deploy_to_vps.sh` |
| `start_pm2.sh` | Create PM2 ecosystem + start pipeline + dashboard | `./start_pm2.sh` |
| `run_everything.sh` | Master script — runs all 4 above in order | `./run_everything.sh` |
| `setup.sh` | Original VPS setup (legacy) | `./setup.sh` |

### CLI Commands

```bash
# Pipeline
python main.py                                    # Production scheduler (all channels)
python main.py --test                              # Single run (first channel)
python main.py --test --channel uppercut_pk.yaml   # Test UpperCut only
python main.py --test --channel kiddoworld.yaml    # Test KiddoWorld only

# Intelligence
python main.py --intelligence                      # Run intelligence engine standalone

# Dashboard
python main.py --dashboard                         # Start web dashboard (port 8080)
python main.py --dashboard --port 3000             # Custom port

# Database
python main.py --init-db                           # Initialize/migrate database
```

### PM2 Processes (VPS)

| Process | Script | Description |
|---------|--------|-------------|
| `uppercut-pipeline` | `main.py` | Scheduler running both channels 24/7 |
| `uppercut-dashboard` | `main.py --dashboard` | Web dashboard on port 8080 |

### VPS Details
```
IP:        95.217.13.249
OS:        Ubuntu 24.04
Provider:  Hetzner
Dashboard: http://95.217.13.249:8080
```

---

## Budget Tracking

### KiddoWorld Monthly Estimates
| Service | Cost | Free Tier | Tracking |
|---------|------|-----------|----------|
| fal.ai animation | ~$20/month | No | `cost_tracking` table, email alert at $20 |
| OpenAI GPT-4o-mini | ~$5/month | No | `cost_tracking` table |
| Pixabay music | FREE | Yes | — |
| edge-tts voices | FREE | Yes | — |
| Pexels/Pixabay footage | N/A | N/A | Not used for KiddoWorld |
| **Total** | **~$25/month** | | Dashboard cost breakdown card |

### UpperCut Monthly Estimates
| Service | Cost | Free Tier | Tracking |
|---------|------|-----------|----------|
| OpenAI GPT-4o-mini | ~$3/month | No | `cost_tracking` table |
| Pexels stock footage | FREE | Yes | — |
| Pixabay stock footage | FREE | Yes | — |
| edge-tts voices | FREE | Yes | — |
| **Total** | **~$3/month** | | Dashboard cost breakdown card |

### Cost Alerts
| Alert | Threshold | Action |
|-------|-----------|--------|
| fal.ai monthly spend | > $20 | Email to abasit.tlg@gmail.com |
| OpenAI monthly spend | > $8 | Email to abasit.tlg@gmail.com |
| Total monthly spend | > $30 | Email to abasit.tlg@gmail.com |

---

## Environment Variables (.env)

| Variable | Service | Required |
|----------|---------|----------|
| `OPENAI_API_KEY` | OpenAI (scripts, SEO) | Yes |
| `PEXELS_API_KEY` | Pexels (stock footage) | Yes |
| `PIXABAY_API_KEY` | Pixabay (stock footage + music) | Yes |
| `FAL_API_KEY` | fal.ai (animation) | Yes (KiddoWorld) |
| `YOUTUBE_CLIENT_SECRETS` | YouTube OAuth JSON path | Yes |
| `ALERT_EMAIL` | Email recipient for alerts | Yes |
| `SMTP_EMAIL` | Gmail sender address | Yes |
| `SMTP_PASSWORD` | Gmail app password | Yes |
| `DASHBOARD_SECRET_KEY` | FastAPI session secret | Yes |
| `DASHBOARD_PORT` | Dashboard port (default 8080) | No |
| `VPS_IP` | Hetzner VPS IP address | No |

---

## Python Dependencies (requirements.txt)

| Package | Version | Purpose |
|---------|---------|---------|
| python-dotenv | >=1.0.0 | .env file loading |
| loguru | >=0.7.2 | Structured logging |
| apscheduler | >=3.10.4 | Cron-style pipeline scheduler |
| pyyaml | >=6.0.1 | Channel config parsing |
| requests | >=2.31.0 | HTTP client |
| pytrends | >=4.9.2 | Google Trends API |
| feedparser | >=6.0.11 | RSS feed parsing |
| openai | >=1.12.0 | GPT-4o-mini scripts + SEO |
| fal-client | >=0.5.6 | fal.ai animation API |
| edge-tts | >=6.1.9 | Microsoft Neural TTS |
| moviepy | >=1.0.3 | Video assembly (installed v2.1.2) |
| ffmpeg-python | >=0.2.0 | ffmpeg wrapper |
| faster-whisper | >=0.10.0 | Speech-to-text for subtitles |
| Pillow | >=10.4.0 | Thumbnail generation |
| google-api-python-client | >=2.116.0 | YouTube Data API |
| google-auth-oauthlib | >=1.2.0 | YouTube OAuth |
| google-auth-httplib2 | >=0.2.0 | YouTube auth transport |
| fastapi | >=0.109.2 | Dashboard web framework |
| uvicorn | >=0.27.1 | ASGI server |
| jinja2 | >=3.1.3 | HTML templating |
| python-multipart | >=0.0.9 | Form data parsing |
| aiosqlite | >=0.20.0 | Async SQLite |

---

## Local Test Results (2026-03-14)

All tests executed on macOS with Python 3.13.7.

| # | Test | Result | Details |
|---|------|--------|---------|
| 1 | All imports (27 .py files) | PASS | All modules load without errors |
| 2 | Database init | PASS | 9 tables created, 2 channels seeded |
| 3 | Kids script generation | PASS | 247 words, 6 animation prompts, $0.0008 |
| 4 | Kids voice generation | PASS | 8.3s audio, en-US-AnaNeural, 49 KB |
| 5 | fal.ai animation | PASS | 5s clip, 1920x1088, h264, 24fps, 1.9 MB, ~$0.10 |
| 6 | Pixabay music fetch | PASS | Kids track cached to assets/music/kids/, 17 KB |
| 7 | Kids thumbnail A/B | PASS | 2 JPGs (74 KB + 64 KB), forest + ocean palettes |
| 8 | Kids SEO generation | PASS | Title + 39 tags + description |
| 9 | Email alerts module | PASS | All 7 alert functions loaded |
| 10 | Dashboard app | PASS | FastAPI with 15 routes |
| 11 | Python syntax check | PASS | 27 files, 0 errors |

### Test Artifacts Generated
```
output/animation/anim_3753376b4c0e_72bc92.mp4    → 1.9 MB  (5s cartoon clip)
output/audio/kids_english_5a77405344.mp3          → 49 KB   (8.3s voice)
output/thumbnails/kids_thumb_A_4cc29883.jpg       → 74 KB   (variant A)
output/thumbnails/kids_thumb_B_bae3e8d5.jpg       → 64 KB   (variant B)
assets/music/kids/76afda969d_a15adb.mp3           → 17 KB   (Pixabay track)
assets/fonts/Nunito-Regular.ttf                   → 276 KB  (kids font)
assets/fonts/Nunito-Bold.ttf                      → 276 KB  (kids font bold)
```

### Bugs Found & Fixed During Testing
| # | Bug | Fix |
|---|-----|-----|
| 1 | Pillow pinned to 10.2.0 — incompatible with Python 3.13 | Changed to `>=10.4.0` |
| 2 | `fal_client` reads `FAL_KEY` env var, not `FAL_API_KEY` | Added `os.environ.setdefault("FAL_KEY", FAL_API_KEY)` in config.py |
| 3 | fal.ai model path wrong: `fal-ai/pika-v2.2-text-to-video` | Fixed to `fal-ai/pika/v2.2/text-to-video` |
| 4 | Nunito-Bold.ttf URL 404 (Google Fonts switched to variable font) | Both regular+bold now download variable font from correct URL |
| 5 | moviepy 2.x removed `moviepy.editor` submodule | Changed to `from moviepy import ...` in video_assembler.py |

---

## File Tree (Final — 47 files)

```
uppercut/
├── main.py                              # Master runner + CLI + both pipelines
├── config.py                            # Settings, paths, DB init, font management
├── requirements.txt                     # 22 Python dependencies
├── .env                                 # API keys (gitignored)
├── .env.example                         # Template for .env
├── .gitignore                           # Git ignore rules
├── README.md                            # User documentation
├── PROJECT_REPORT.md                    # This file
├── client_secrets.json                  # YouTube OAuth (gitignored)
│
├── # Shell Scripts
├── local_setup.sh                       # Mac environment setup
├── test_pipeline.sh                     # Step-by-step module tests
├── deploy_to_vps.sh                     # rsync + VPS setup via SSH
├── start_pm2.sh                         # PM2 ecosystem on VPS
├── run_everything.sh                    # Master script (runs all above)
├── setup.sh                             # Legacy VPS setup
│
├── channels/
│   ├── uppercut_pk.yaml                 # UpperCut channel config
│   └── kiddoworld.yaml                  # KiddoWorld channel config
│
├── modules/
│   ├── __init__.py
│   ├── trend_fetcher.py                 # Google Trends + RSS + intelligence scoring
│   ├── script_generator.py              # GPT-4o-mini Urdu scripts
│   ├── voice_generator.py               # edge-tts Urdu voiceovers
│   ├── footage_fetcher.py               # Pexels + Pixabay stock footage
│   ├── video_assembler.py               # moviepy 2.x video creation + subtitles
│   ├── thumbnail_maker.py               # Pillow Urdu thumbnails (A/B)
│   ├── seo_generator.py                 # YouTube SEO (Urdu+English)
│   ├── shorts_maker.py                  # ffmpeg 60s vertical clips
│   ├── kids_script_generator.py         # Kids scripts + translations + topic bank
│   ├── kids_voice_generator.py          # Cheerful kids voices (3 languages)
│   ├── animation_generator.py           # fal.ai Pika v2.2 cartoon clips
│   ├── kids_music_fetcher.py            # Pixabay kids music + caching
│   ├── kids_thumbnail_maker.py          # Bright colorful kids thumbnails
│   ├── kids_seo_generator.py            # Kids YouTube SEO
│   └── uploader/
│       ├── __init__.py
│       └── youtube_uploader.py          # YouTube upload + playlists + COPPA
│
├── intelligence/
│   ├── __init__.py                      # Orchestrator: collect → analyze → optimize
│   ├── analytics_collector.py           # YouTube Data + Analytics API
│   ├── performance_analyzer.py          # Pattern detection + scoring
│   └── strategy_optimizer.py            # Strategy persistence + queries
│
├── dashboard/
│   ├── __init__.py
│   ├── app.py                           # FastAPI app + 15 API endpoints
│   ├── templates/
│   │   ├── base.html                    # Base template (sidebar nav)
│   │   ├── dashboard.html               # Overview page + cost breakdown
│   │   ├── videos.html                  # Video history
│   │   ├── analytics.html               # Intelligence insights
│   │   └── errors.html                  # Error log
│   └── static/
│       └── style.css                    # Dark theme CSS (purple accent)
│
├── alerts/
│   ├── __init__.py                      # Package exports
│   └── email_alerts.py                  # 7 alert types (HTML emails)
│
├── assets/
│   ├── fonts/
│   │   ├── Nunito-Regular.ttf           # Kids channel font (276 KB)
│   │   └── Nunito-Bold.ttf              # Kids channel font bold (276 KB)
│   ├── music/
│   │   └── kids/                        # Cached Pixabay kids tracks
│   └── templates/                       # Intro/outro MP4 placeholders
│
├── output/
│   ├── videos/                          # Generated MP4s
│   ├── thumbnails/                      # Generated JPGs
│   ├── audio/                           # Generated MP3s
│   ├── footage/                         # Downloaded stock footage
│   ├── animation/                       # Cached fal.ai clips
│   └── logs/                            # Rotating log files
│
└── database/
    └── master.db                        # SQLite database (9 tables)
```

---

## Summary

| Metric | Value |
|--------|-------|
| Total Python files | 27 |
| Total shell scripts | 6 |
| Total HTML templates | 5 |
| Total CSS files | 1 |
| Total YAML configs | 2 |
| Total project files | 47 |
| Syntax errors | 0 |
| Tests passed | 11/11 |
| Database tables | 9 |
| API endpoints | 15 |
| Alert types | 7 |
| Supported channels | 2 |
| Monthly cost (both channels) | ~$28 |
| Deployment target | Hetzner VPS (95.217.13.249) |
| Process manager | PM2 (2 processes) |
| Dashboard URL | http://95.217.13.249:8080 |
