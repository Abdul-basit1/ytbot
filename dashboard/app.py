"""
UpperCut — Web Dashboard (Phase 3)
FastAPI-based dashboard showing channel stats, video history,
analytics insights, strategy recommendations, and error logs.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List

import secrets
import hashlib

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from config import (
    BASE_DIR,
    DASHBOARD_PASSWORD,
    DASHBOARD_PORT,
    DASHBOARD_SECRET_KEY,
    DASHBOARD_USERNAME,
    get_db,
)

PROGRESS_FILE = BASE_DIR / "output" / "pipeline_progress.json"
LOG_DIR = BASE_DIR / "output" / "logs"

DASHBOARD_DIR = Path(__file__).resolve().parent

app = FastAPI(title="UpperCut Dashboard", docs_url="/api/docs")
app.mount("/static", StaticFiles(directory=DASHBOARD_DIR / "static"), name="static")
app.mount("/output", StaticFiles(directory=BASE_DIR / "output"), name="output")
app.mount("/assets", StaticFiles(directory=BASE_DIR / "assets"), name="assets")
templates = Jinja2Templates(directory=DASHBOARD_DIR / "templates")


# ── Session-based Authentication ───────────────────────────────────────────

def get_current_user(request: Request) -> str:
    """Check session for logged-in user. Redirect to /login if not."""
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return user


def require_login(request: Request) -> str:
    """Dependency that requires login."""
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return user


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Show login form."""
    if request.session.get("user"):
        return RedirectResponse("/", status_code=303)
    error = request.query_params.get("error", "")
    return templates.TemplateResponse("login.html", {"request": request, "error": error})


@app.post("/login")
async def login_submit(request: Request):
    """Process login form."""
    form = await request.form()
    username = form.get("username", "")
    password = form.get("password", "")

    if (secrets.compare_digest(username, DASHBOARD_USERNAME)
            and secrets.compare_digest(password, DASHBOARD_PASSWORD)):
        request.session["user"] = username
        return RedirectResponse("/", status_code=303)
    return RedirectResponse("/login?error=1", status_code=303)


@app.get("/logout")
async def logout(request: Request):
    """Clear session and redirect to login."""
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# Redirect unauthenticated users
from starlette.middleware.base import BaseHTTPMiddleware


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        public_paths = ["/login", "/static/", "/api/docs", "/openapi.json"]
        if any(path.startswith(p) for p in public_paths):
            return await call_next(request)
        try:
            user = request.session.get("user")
        except Exception:
            return RedirectResponse("/login", status_code=303)
        if not user and not path.startswith("/api/"):
            return RedirectResponse("/login", status_code=303)
        if not user and path.startswith("/api/"):
            return HTMLResponse('{"error":"unauthorized"}', status_code=401)
        return await call_next(request)


# Middleware order matters: AuthMiddleware runs first, then SessionMiddleware unwraps session
# Starlette processes in reverse add order, so add Auth first, then Session
app.add_middleware(AuthMiddleware)
app.add_middleware(SessionMiddleware, secret_key=DASHBOARD_SECRET_KEY or "kiddoworld-secret-2024")


# Keep old verify_credentials for backward compatibility with API calls
def verify_credentials(request: Request):
    """Verify user is logged in via session."""
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


# ── Template filters ────────────────────────────────────────────────────────

def _format_number(value):
    """Format large numbers with commas."""
    try:
        return f"{int(value):,}"
    except (ValueError, TypeError):
        return value


def _format_pct(value):
    try:
        return f"{float(value):.1f}%"
    except (ValueError, TypeError):
        return "N/A"


templates.env.filters["fnum"] = _format_number
templates.env.filters["fpct"] = _format_pct


# ── Helper queries ──────────────────────────────────────────────────────────

def _get_channels() -> List[Dict]:
    db = get_db()
    rows = db.execute("SELECT * FROM channels WHERE is_active=1").fetchall()
    db.close()
    return [dict(r) for r in rows]


def _get_channel_stats(channel_id: int) -> Dict:
    db = get_db()
    stats = {}

    # Total videos
    row = db.execute("SELECT COUNT(*) as cnt FROM videos WHERE channel_id=?", (channel_id,)).fetchone()
    stats["total_videos"] = row["cnt"]

    # Uploaded videos
    row = db.execute("SELECT COUNT(*) as cnt FROM uploads WHERE channel_id=?", (channel_id,)).fetchone()
    stats["total_uploads"] = row["cnt"]

    # Total views across all uploads
    row = db.execute("SELECT COALESCE(SUM(views),0) as v FROM uploads WHERE channel_id=?", (channel_id,)).fetchone()
    stats["total_views"] = row["v"]

    # Total likes
    row = db.execute("SELECT COALESCE(SUM(likes),0) as l FROM uploads WHERE channel_id=?", (channel_id,)).fetchone()
    stats["total_likes"] = row["l"]

    # Total cost
    row = db.execute("SELECT COALESCE(SUM(cost_usd),0) as c FROM videos WHERE channel_id=?", (channel_id,)).fetchone()
    stats["total_cost"] = round(row["c"], 2)

    # Errors (unresolved)
    row = db.execute(
        "SELECT COUNT(*) as cnt FROM errors WHERE channel_id=? AND resolved=0", (channel_id,)
    ).fetchone()
    stats["open_errors"] = row["cnt"]

    # Videos today
    today = datetime.now().strftime("%Y-%m-%d")
    row = db.execute(
        "SELECT COUNT(*) as cnt FROM videos WHERE channel_id=? AND DATE(created_at)=?",
        (channel_id, today),
    ).fetchone()
    stats["videos_today"] = row["cnt"]

    db.close()
    return stats


def _get_recent_videos(channel_id: int, limit: int = 20) -> List[Dict]:
    db = get_db()
    rows = db.execute("""
        SELECT v.id, v.title, v.status, v.format, v.duration_seconds, v.cost_usd, v.created_at,
               u.youtube_video_id, u.youtube_url, u.views, u.likes
        FROM videos v
        LEFT JOIN uploads u ON u.video_id = v.id
        WHERE v.channel_id=?
        ORDER BY v.created_at DESC
        LIMIT ?
    """, (channel_id, limit)).fetchall()
    db.close()
    return [dict(r) for r in rows]


def _get_strategy(channel_id: int) -> Dict | None:
    db = get_db()
    row = db.execute(
        "SELECT * FROM strategy WHERE channel_id=? ORDER BY last_updated DESC LIMIT 1",
        (channel_id,),
    ).fetchone()
    db.close()
    if not row:
        return None
    result = dict(row)
    if result.get("top_performing_keywords"):
        try:
            result["top_performing_keywords"] = json.loads(result["top_performing_keywords"])
        except (json.JSONDecodeError, TypeError):
            result["top_performing_keywords"] = []
    return result


def _get_errors(channel_id: int, limit: int = 20) -> List[Dict]:
    db = get_db()
    rows = db.execute(
        "SELECT * FROM errors WHERE channel_id=? ORDER BY created_at DESC LIMIT ?",
        (channel_id, limit),
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


def _get_analytics_history(channel_id: int, days: int = 30) -> List[Dict]:
    db = get_db()
    rows = db.execute(
        "SELECT * FROM analytics WHERE channel_id=? ORDER BY date DESC LIMIT ?",
        (channel_id, days),
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


def _get_cost_summary(channel_id: int) -> Dict:
    """Get monthly cost breakdown by service."""
    db = get_db()
    rows = db.execute(
        "SELECT service, COALESCE(SUM(cost_usd), 0) as total "
        "FROM cost_tracking WHERE created_at > datetime('now', '-30 days') "
        "GROUP BY service ORDER BY total DESC",
    ).fetchall()

    total_month = db.execute(
        "SELECT COALESCE(SUM(cost_usd), 0) as t FROM cost_tracking "
        "WHERE created_at > datetime('now', '-30 days')",
    ).fetchone()["t"]

    db.close()
    return {
        "services": {r["service"]: round(r["total"], 4) for r in rows},
        "total_month": round(total_month, 4),
    }


def _get_top_videos(channel_id: int, limit: int = 10) -> List[Dict]:
    db = get_db()
    rows = db.execute("""
        SELECT va.youtube_video_id, va.views, va.likes, va.ctr,
               va.avg_view_percentage, va.impressions, va.subscribers_gained,
               u.title, u.youtube_url
        FROM video_analytics va
        JOIN uploads u ON va.upload_id = u.id
        WHERE va.channel_id=?
        ORDER BY va.views DESC
        LIMIT ?
    """, (channel_id, limit)).fetchall()
    db.close()
    return [dict(r) for r in rows]


def _default_channel_id(channels: list) -> int:
    """Return the last active channel ID (KiddoWorld is id=2)."""
    if not channels:
        return 1
    # Prefer KiddoWorld (id=2) if it exists
    for ch in channels:
        if ch["name"] == "KiddoWorld":
            return ch["id"]
    return channels[0]["id"]


# ── Pages ───────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, _user: str = Depends(verify_credentials)):
    channels = _get_channels()
    channel_id = int(request.query_params.get("channel") or _default_channel_id(channels))

    stats = _get_channel_stats(channel_id)
    videos = _get_recent_videos(channel_id)
    strategy = _get_strategy(channel_id)
    errors = _get_errors(channel_id, limit=10)
    top_videos = _get_top_videos(channel_id)
    costs = _get_cost_summary(channel_id)

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "channels": channels,
        "active_channel_id": channel_id,
        "stats": stats,
        "videos": videos,
        "strategy": strategy,
        "errors": errors,
        "top_videos": top_videos,
        "costs": costs,
        "now": datetime.now(),
    })


@app.get("/videos", response_class=HTMLResponse)
async def videos_page(request: Request, _user: str = Depends(verify_credentials)):
    channels = _get_channels()
    channel_id = int(request.query_params.get("channel") or _default_channel_id(channels))
    videos = _get_recent_videos(channel_id, limit=100)

    return templates.TemplateResponse("videos.html", {
        "request": request,
        "channels": channels,
        "active_channel_id": channel_id,
        "videos": videos,
    })


@app.get("/analytics", response_class=HTMLResponse)
async def analytics_page(request: Request):
    channels = _get_channels()
    channel_id = int(request.query_params.get("channel") or _default_channel_id(channels))

    db = get_db()

    # All uploaded videos with stats
    videos = [dict(r) for r in db.execute("""
        SELECT u.title, u.views, u.likes, u.youtube_url, u.uploaded_at
        FROM uploads u WHERE u.channel_id=?
        ORDER BY u.views DESC
    """, (channel_id,)).fetchall()]

    # Totals
    row = db.execute("""
        SELECT COUNT(*) as total_videos,
               COALESCE(SUM(views), 0) as total_views,
               COALESCE(SUM(likes), 0) as total_likes
        FROM uploads WHERE channel_id=?
    """, (channel_id,)).fetchone()

    total_cost = db.execute(
        "SELECT COALESCE(SUM(cost_usd), 0) as c FROM videos WHERE channel_id=?", (channel_id,)
    ).fetchone()["c"]

    first_upload = db.execute(
        "SELECT MIN(uploaded_at) as d FROM uploads WHERE channel_id=?", (channel_id,)
    ).fetchone()["d"]

    avg_views = row["total_views"] / row["total_videos"] if row["total_videos"] > 0 else 0

    from datetime import datetime
    channel_age = 0
    if first_upload:
        try:
            first_dt = datetime.fromisoformat(first_upload[:19])
            channel_age = (datetime.now() - first_dt).days
        except Exception:
            channel_age = 0

    totals = {
        "total_videos": row["total_videos"],
        "total_views": row["total_views"],
        "total_likes": row["total_likes"],
        "total_cost": round(total_cost, 2),
        "avg_views": round(avg_views, 1),
        "channel_age_days": max(1, channel_age),
    }

    # Best titles by views
    best_titles = [dict(r) for r in db.execute("""
        SELECT title, views FROM uploads WHERE channel_id=? AND views > 0
        ORDER BY views DESC LIMIT 5
    """, (channel_id,)).fetchall()]

    # Daily upload stats
    daily_stats = [dict(r) for r in db.execute("""
        SELECT DATE(uploaded_at) as date, COUNT(*) as count, COALESCE(SUM(views), 0) as views
        FROM uploads WHERE channel_id=?
        GROUP BY DATE(uploaded_at) ORDER BY date DESC LIMIT 14
    """, (channel_id,)).fetchall()]

    # Get saved insights
    strategy = _get_strategy(channel_id)
    insights = strategy.get("recommendation_notes", "") if strategy else ""

    db.close()

    return templates.TemplateResponse("analytics.html", {
        "request": request,
        "channels": channels,
        "active_channel_id": channel_id,
        "totals": totals,
        "videos": videos,
        "best_titles": best_titles,
        "daily_stats": daily_stats,
        "insights": insights,
    })


@app.get("/errors", response_class=HTMLResponse)
async def errors_page(request: Request, _user: str = Depends(verify_credentials)):
    channels = _get_channels()
    channel_id = int(request.query_params.get("channel") or _default_channel_id(channels))
    errors = _get_errors(channel_id, limit=50)

    return templates.TemplateResponse("errors.html", {
        "request": request,
        "channels": channels,
        "active_channel_id": channel_id,
        "errors": errors,
    })


# ── API endpoints (for AJAX / future mobile app) ───────────────────────────

@app.get("/api/stats/{channel_id}")
async def api_stats(channel_id: int, _user: str = Depends(verify_credentials)):
    return _get_channel_stats(channel_id)


@app.get("/api/videos/{channel_id}")
async def api_videos(channel_id: int, limit: int = 20, _user: str = Depends(verify_credentials)):
    return _get_recent_videos(channel_id, limit)


@app.get("/api/strategy/{channel_id}")
async def api_strategy(channel_id: int, _user: str = Depends(verify_credentials)):
    return _get_strategy(channel_id) or {}


@app.get("/api/errors/{channel_id}")
async def api_errors(channel_id: int, _user: str = Depends(verify_credentials)):
    return _get_errors(channel_id)


@app.get("/api/costs")
async def api_costs(_user: str = Depends(verify_credentials)):
    return _get_cost_summary(0)


@app.post("/api/errors/{error_id}/resolve")
async def api_resolve_error(error_id: int, _user: str = Depends(verify_credentials)):
    db = get_db()
    db.execute("UPDATE errors SET resolved=1 WHERE id=?", (error_id,))
    db.commit()
    db.close()
    return {"status": "resolved"}


@app.post("/api/videos/{video_id}/retry")
async def api_retry_video(video_id: int, _user: str = Depends(verify_credentials)):
    """Reset a failed video and add to queue with high priority."""
    db = get_db()
    row = db.execute("SELECT id, status, channel_id, title FROM videos WHERE id=?", (video_id,)).fetchone()
    if not row:
        db.close()
        raise HTTPException(status_code=404, detail="Video not found")
    if row["status"] not in ("failed", "upload_failed"):
        db.close()
        return {"status": "skipped", "reason": f"Video status is '{row['status']}', not failed"}
    db.execute("UPDATE videos SET status='retry' WHERE id=?", (video_id,))
    db.execute("UPDATE errors SET resolved=1 WHERE channel_id=?", (row["channel_id"],))
    # Add to queue with high priority
    db.execute(
        "INSERT INTO queue (channel_id, video_id, topic, priority, status) VALUES (?, ?, ?, 8, 'waiting')",
        (row["channel_id"], video_id, row["title"] or "Retry"),
    )
    db.commit()
    db.close()
    return {"status": "queued", "video_id": video_id}


@app.get("/api/videos/{video_id}/preview")
async def api_video_preview(video_id: int, _user: str = Depends(verify_credentials)):
    """Return video file URL if it exists locally."""
    db = get_db()
    row = db.execute("SELECT video_path, id FROM videos WHERE id=?", (video_id,)).fetchone()
    db.close()
    if not row or not row["video_path"]:
        # Check uploads for YouTube URL
        db2 = get_db()
        upload = db2.execute("SELECT youtube_url FROM uploads WHERE video_id=?", (video_id,)).fetchone()
        db2.close()
        return {"available": False, "youtube_url": upload["youtube_url"] if upload else None}

    video_path = Path(row["video_path"])
    if video_path.exists():
        return {"available": True, "url": f"/output/videos/{video_path.name}"}
    return {"available": False, "youtube_url": None}


# ── Progress page ──────────────────────────────────────────────────────

def _get_pipeline_progress() -> Dict:
    """Read current pipeline progress from JSON file."""
    try:
        if PROGRESS_FILE.exists():
            return json.loads(PROGRESS_FILE.read_text())
    except Exception:
        pass
    return {"status": "idle", "step": 0, "total_steps": 12, "topic": "", "channel": ""}


def _get_live_log(lines: int = 20) -> list:
    """Read last N lines from the latest pipeline log file."""
    try:
        # Find the most recent log file (loguru rotating logs or PM2 logs)
        candidates = sorted(LOG_DIR.glob("uppercut_*.log"), reverse=True)
        if not candidates:
            candidates = sorted(LOG_DIR.glob("pipeline_error.log"), reverse=True)
        if not candidates:
            candidates = sorted(LOG_DIR.glob("*.log"), reverse=True)
        if candidates:
            text = candidates[0].read_text(errors="replace")
            return text.strip().split("\n")[-lines:]
    except Exception:
        pass
    return []


def _get_all_time_stats() -> Dict:
    """Get all-time video stats across all channels."""
    db = get_db()
    total = db.execute("SELECT COUNT(*) as c FROM videos").fetchone()["c"]
    uploaded = db.execute("SELECT COUNT(*) as c FROM videos WHERE status='uploaded'").fetchone()["c"]
    failed = db.execute("SELECT COUNT(*) as c FROM videos WHERE status='failed'").fetchone()["c"]
    db.close()
    rate = round((uploaded / total * 100), 1) if total > 0 else 0
    return {"total": total, "uploaded": uploaded, "failed": failed, "success_rate": rate}


def _get_today_stats() -> Dict:
    """Get today's video production stats."""
    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    completed = db.execute(
        "SELECT COUNT(*) as c FROM videos WHERE DATE(created_at)=? AND status IN ('uploaded','rendered')",
        (today,),
    ).fetchone()["c"]
    failed = db.execute(
        "SELECT COUNT(*) as c FROM videos WHERE DATE(created_at)=? AND status='failed'",
        (today,),
    ).fetchone()["c"]
    generating = db.execute(
        "SELECT COUNT(*) as c FROM videos WHERE DATE(created_at)=? AND status='generating'",
        (today,),
    ).fetchone()["c"]
    db.close()
    planned = 5  # 2 long + 3 shorts
    total_done = completed + failed
    return {
        "planned": planned,
        "completed": completed,
        "in_progress": generating,
        "failed": failed,
        "remaining": max(0, planned - total_done - generating),
        "pct": round(total_done / planned * 100) if planned > 0 else 0,
    }


@app.get("/progress", response_class=HTMLResponse)
async def progress_page(request: Request, _user: str = Depends(verify_credentials)):
    channels = _get_channels()
    progress = _get_pipeline_progress()
    today = _get_today_stats()
    all_time = _get_all_time_stats()
    log_lines = _get_live_log(20)

    return templates.TemplateResponse("progress.html", {
        "request": request,
        "channels": channels,
        "active_channel_id": int(request.query_params.get("channel", _default_channel_id(channels))),
        "progress": progress,
        "today": today,
        "all_time": all_time,
        "log_lines": log_lines,
    })


@app.get("/queue", response_class=HTMLResponse)
async def queue_page(request: Request, _user: str = Depends(verify_credentials)):
    channels = _get_channels()
    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    # Check queue table for processing items
    processing = [dict(r) for r in db.execute(
        "SELECT * FROM queue WHERE status='processing' ORDER BY started_at DESC"
    ).fetchall()]
    # Also check videos table — if a video is 'generating', it's being processed
    if not processing:
        gen_video = db.execute(
            "SELECT id, title, channel_id, created_at FROM videos WHERE status='generating' LIMIT 1"
        ).fetchone()
        if gen_video:
            processing = [{"id": 0, "topic": gen_video["title"], "format": "long",
                           "priority": 10, "status": "processing",
                           "created_at": gen_video["created_at"],
                           "started_at": gen_video["created_at"]}]
    waiting = [dict(r) for r in db.execute(
        "SELECT * FROM queue WHERE status='waiting' ORDER BY priority DESC, created_at ASC"
    ).fetchall()]
    completed_today = [dict(r) for r in db.execute(
        "SELECT v.id, v.title as topic, 'long' as format, 0 as priority, v.created_at "
        "FROM videos v WHERE v.status='uploaded' AND DATE(v.created_at)=? "
        "ORDER BY v.created_at DESC",
        (today,),
    ).fetchall()]
    failed = [dict(r) for r in db.execute(
        "SELECT * FROM queue WHERE status='failed' AND DATE(created_at)=? ORDER BY created_at DESC",
        (today,),
    ).fetchall()]
    db.close()

    paused = (BASE_DIR / "output" / ".queue_paused").exists()

    return templates.TemplateResponse("queue.html", {
        "request": request,
        "channels": channels,
        "active_channel_id": int(request.query_params.get("channel", _default_channel_id(channels))),
        "processing": processing,
        "waiting": waiting,
        "completed": completed_today,
        "failed": failed,
        "paused": paused,
    })


@app.get("/api/queue")
async def api_queue(_user: str = Depends(verify_credentials)):
    db = get_db()
    items = [dict(r) for r in db.execute(
        "SELECT * FROM queue WHERE status IN ('waiting','processing') ORDER BY priority DESC, created_at ASC"
    ).fetchall()]
    db.close()
    return items


@app.post("/api/queue/pause")
async def api_queue_pause(_user: str = Depends(verify_credentials)):
    (BASE_DIR / "output" / ".queue_paused").write_text("paused")
    return {"status": "paused"}


@app.post("/api/queue/resume")
async def api_queue_resume(_user: str = Depends(verify_credentials)):
    (BASE_DIR / "output" / ".queue_paused").unlink(missing_ok=True)
    return {"status": "resumed"}


@app.delete("/api/queue/{queue_id}")
async def api_queue_remove(queue_id: int, _user: str = Depends(verify_credentials)):
    db = get_db()
    db.execute("DELETE FROM queue WHERE id=? AND status='waiting'", (queue_id,))
    db.commit()
    db.close()
    return {"status": "removed"}


@app.post("/api/queue/{queue_id}/requeue")
async def api_queue_requeue(queue_id: int, _user: str = Depends(verify_credentials)):
    db = get_db()
    db.execute("UPDATE queue SET status='waiting', retry_count=retry_count+1 WHERE id=?", (queue_id,))
    db.commit()
    db.close()
    return {"status": "requeued"}


@app.get("/gallery", response_class=HTMLResponse)
async def gallery_page(request: Request, _user: str = Depends(verify_credentials)):
    """Media gallery — browse all generated images, clips, videos, audio, music."""
    import os
    from datetime import datetime as _dt

    def _scan(directory, extensions):
        items = []
        d = BASE_DIR / directory
        if not d.exists():
            return items
        for f in sorted(d.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if f.suffix.lower() in extensions:
                st = f.stat()
                items.append({
                    "name": f.name,
                    "size_kb": st.st_size // 1024,
                    "size_mb": round(st.st_size / (1024 * 1024), 1),
                    "date": _dt.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
                })
        return items

    images = _scan("output/images", {".png", ".jpg", ".webp"})
    clips = _scan("output/animation", {".mp4"})
    assembled = _scan("output/videos", {".mp4"})
    audio = _scan("output/audio", {".mp3", ".wav"})
    music = _scan("assets/music/kids", {".mp3", ".wav"})

    return templates.TemplateResponse("gallery.html", {
        "request": request,
        "channels": _get_channels(),
        "active_channel_id": 2,
        "images": images,
        "clips": clips,
        "assembled": assembled,
        "audio": audio,
        "music": music,
    })


@app.get("/api/progress")
async def api_progress(_user: str = Depends(verify_credentials)):
    return {
        "progress": _get_pipeline_progress(),
        "today": _get_today_stats(),
        "all_time": _get_all_time_stats(),
        "log_lines": _get_live_log(20),
    }


@app.post("/api/pipeline/restart")
async def api_restart_pipeline(_user: str = Depends(verify_credentials)):
    """
    Restart the pipeline PM2 process.
    Resets any stuck 'generating' video back to 'retry' so it gets re-processed.
    Removes stale lock file.
    """
    import os
    import subprocess

    db = get_db()
    # Reset any stuck generating video to retry (not failed — we want to resume)
    stuck = db.execute(
        "UPDATE videos SET status='retry' WHERE status='generating'"
    ).rowcount
    db.commit()
    db.close()

    # Remove lock file
    lock = "/tmp/uppercut_pipeline.lock"
    if os.path.exists(lock):
        os.remove(lock)

    # Restart pipeline via PM2
    try:
        subprocess.run(
            ["pm2", "restart", "uppercut-pipeline"],
            capture_output=True, timeout=10,
        )
    except Exception as e:
        return {"status": "error", "message": str(e)}

    return {
        "status": "restarted",
        "stuck_videos_reset": stuck,
        "message": f"Pipeline restarted. {stuck} stuck video(s) re-queued for retry.",
    }


# ── Create Video Wizard ────────────────────────────────────────────────────

@app.get("/create", response_class=HTMLResponse)
async def create_page(request: Request, _user: str = Depends(verify_credentials)):
    channels = _get_channels()
    return templates.TemplateResponse("create.html", {
        "request": request,
        "channels": channels,
        "active_channel_id": _default_channel_id(channels),
    })


@app.post("/api/create/suggest-topics")
async def api_suggest_topics(_user: str = Depends(verify_credentials)):
    """Suggest 3 video topics — mix of songs and stories."""
    from openai import OpenAI
    from config import OPENAI_API_KEY
    client = OpenAI(api_key=OPENAI_API_KEY)

    # Check which topics were already used
    db = get_db()
    used = [r["title"] for r in db.execute(
        "SELECT title FROM videos WHERE channel_id=2 ORDER BY created_at DESC LIMIT 50"
    ).fetchall()]
    db.close()

    used_str = ", ".join(used[:20]) if used else "none yet"

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{
            "role": "system",
            "content": (
                "You suggest kids video topics for a YouTube channel called KiddoWorld. "
                "Target: kids aged 2-8. Characters: Sid (curious boy), Kido (playful baby sibling), Mom, Dad. "
                "Suggest 3 topics: 2 songs/rhymes and 1 story. "
                "Already used topics (avoid these): " + used_str + "\n"
                "Return JSON: {\"topics\": [{\"topic\": \"...\", \"type\": \"song|story\", \"description\": \"one line\"}]}"
            ),
        }],
        response_format={"type": "json_object"},
        temperature=0.9,
    )

    data = json.loads(resp.choices[0].message.content)
    return data


@app.post("/api/create/generate-script")
async def api_generate_script(request: Request, _user: str = Depends(verify_credentials)):
    """Generate script with voice text, scene descriptions, and lyrics."""
    body = await request.json()
    topic = body.get("topic", "")
    video_type = body.get("type", "song")

    from openai import OpenAI
    from config import OPENAI_API_KEY
    client = OpenAI(api_key=OPENAI_API_KEY)

    # Load character descriptions
    char_file = BASE_DIR / "channels" / "characters.json"
    characters = ""
    if char_file.exists():
        cdata = json.loads(char_file.read_text())
        for c in cdata.get("characters", []):
            characters += f"- {c['name']} ({c['role']}): {c['visual_prompt'][:100]}\n"

    system_prompt = f"""You write kids video scripts for KiddoWorld YouTube channel.
Target audience: kids aged 2-8.

CHARACTERS (use these in every script):
{characters}

You must return valid JSON with these exact fields:
{{
    "voice_script": "The complete text that will be spoken/sung aloud. ONLY natural speech or lyrics. NO stage directions, NO brackets, NO technical instructions, NO 'musical notes', NO sound effect descriptions. Just pure words a voice actor would say.",
    "scenes": ["Detailed visual description for each scene image. Include character names, actions, setting, colors. Each scene should specify which characters are present and what they are doing. Use the character visual descriptions above for consistency."],
    "lyrics": "If this is a song, write the full song lyrics here (same as voice_script but formatted as lyrics with verses). If story, leave empty string."
}}

RULES:
- voice_script: 200-400 words, simple vocabulary, lots of repetition
- scenes: 6-8 scenes, each is a detailed image prompt for DALL-E
- Every scene MUST mention character names (Sid, Kido, Mom, Dad) and their visual appearance
- {"Write catchy rhyming lyrics with a clear melody structure (verse, chorus, verse, chorus)" if video_type == "song" else "Write an engaging story with a beginning, middle, and end. Use dialogue between characters."}
- Keep everything child-safe, positive, educational
"""

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Create a {'song' if video_type == 'song' else 'story'} about: {topic}"},
        ],
        response_format={"type": "json_object"},
        temperature=0.7,
    )

    data = json.loads(resp.choices[0].message.content)

    # Save to database
    db = get_db()
    db.execute(
        "INSERT INTO videos (channel_id, title, status, format, script, made_for_kids) "
        "VALUES (2, ?, 'draft', 'long', ?, 1)",
        (topic, json.dumps(data)),
    )
    db.commit()
    video_id = db.execute("SELECT MAX(id) as id FROM videos").fetchone()["id"]
    db.close()

    return {
        "video_id": video_id,
        "voice_script": data.get("voice_script", ""),
        "scenes": data.get("scenes", []),
        "lyrics": data.get("lyrics", ""),
    }


from fastapi import UploadFile, File, Form


@app.post("/api/create/upload-audio")
async def api_upload_audio(
    file: UploadFile = File(...),
    video_id: int = Form(...),
    _user: str = Depends(verify_credentials),
):
    """Upload an MP3/WAV song file for a video."""
    import shutil

    audio_dir = BASE_DIR / "output" / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    filename = f"song_{video_id}_{file.filename}"
    filepath = audio_dir / filename

    with open(filepath, "wb") as f:
        shutil.copyfileobj(file.file, f)

    return {"path": str(filepath), "filename": filename, "size_kb": filepath.stat().st_size // 1024}


@app.post("/api/create/generate-images")
async def api_generate_images(request: Request, _user: str = Depends(verify_credentials)):
    """Generate DALL-E 3 images for each scene."""
    body = await request.json()
    video_id = body.get("video_id")
    scenes = body.get("scenes", [])

    from openai import OpenAI
    from config import OPENAI_API_KEY
    import requests as req
    import hashlib

    client = OpenAI(api_key=OPENAI_API_KEY)
    img_dir = BASE_DIR / "output" / "images"
    img_dir.mkdir(parents=True, exist_ok=True)

    # Load character art style
    char_file = BASE_DIR / "channels" / "characters.json"
    style_suffix = ", 2D cartoon illustration, bright vibrant colors, child friendly, Pixar inspired, cute characters, safe for kids"
    if char_file.exists():
        cdata = json.loads(char_file.read_text())
        style_suffix = ", " + cdata.get("art_style", style_suffix)

    images = []
    for i, scene in enumerate(scenes):
        prompt = scene + style_suffix
        prompt_hash = hashlib.md5(prompt.encode()).hexdigest()[:12]

        # Check cache
        cached = list(img_dir.glob(f"img_{prompt_hash}_*.png"))
        if cached:
            images.append({"filename": cached[0].name, "index": i, "cached": True})
            continue

        try:
            resp = client.images.generate(
                model="dall-e-3",
                prompt=prompt[:4000],
                size="1792x1024",
                quality="standard",
                n=1,
            )
            url = resp.data[0].url
            img_data = req.get(url, timeout=60).content
            suffix = hashlib.md5(img_data).hexdigest()[:6]
            filename = f"img_{prompt_hash}_{suffix}.png"
            (img_dir / filename).write_bytes(img_data)
            images.append({"filename": filename, "index": i, "cached": False})
        except Exception as e:
            images.append({"filename": None, "index": i, "error": str(e)})

    return {"images": images, "count": len(images)}


@app.post("/api/create/regenerate-image")
async def api_regenerate_image(request: Request, _user: str = Depends(verify_credentials)):
    """Regenerate a single scene image."""
    body = await request.json()
    scene = body.get("scene", "")
    index = body.get("index", 0)

    from openai import OpenAI
    from config import OPENAI_API_KEY
    import requests as req
    import hashlib

    client = OpenAI(api_key=OPENAI_API_KEY)
    img_dir = BASE_DIR / "output" / "images"

    char_file = BASE_DIR / "channels" / "characters.json"
    style_suffix = ", 2D cartoon illustration, bright vibrant colors, child friendly, Pixar inspired"
    if char_file.exists():
        cdata = json.loads(char_file.read_text())
        style_suffix = ", " + cdata.get("art_style", style_suffix)

    prompt = scene + style_suffix
    resp = client.images.generate(
        model="dall-e-3",
        prompt=prompt[:4000],
        size="1792x1024",
        quality="standard",
        n=1,
    )
    url = resp.data[0].url
    img_data = req.get(url, timeout=60).content
    hsh = hashlib.md5(img_data).hexdigest()[:6]
    phash = hashlib.md5(prompt.encode()).hexdigest()[:12]
    filename = f"img_{phash}_{hsh}.png"
    (img_dir / filename).write_bytes(img_data)

    return {"image": {"filename": filename, "index": index, "cached": False}}


@app.post("/api/create/assemble-video")
async def api_assemble_video(request: Request, _user: str = Depends(verify_credentials)):
    """Assemble video from images + audio + music, return preview URL."""
    body = await request.json()
    video_id = body.get("video_id")
    voice_script = body.get("voice_script", "")
    song_path = body.get("song_path")
    image_filenames = body.get("images", [])

    import subprocess
    import hashlib

    # Generate voice if no song uploaded
    audio_path = None
    if song_path:
        audio_path = Path(song_path)
    else:
        # Generate voice with edge-tts
        from modules.kids_voice_generator import KidsVoiceGenerator
        gen = KidsVoiceGenerator()
        audio_path = Path(gen.generate(voice_script, "english"))

    # Get image paths
    img_dir = BASE_DIR / "output" / "images"
    image_paths = [str(img_dir / f) for f in image_filenames if f]

    if not image_paths:
        return {"error": "No images available for assembly"}

    # Assemble using video_assembler
    from modules.video_assembler import assemble
    video_path = assemble(
        clips_or_images=image_paths,
        audio_path=str(audio_path),
        is_images=True,
    )

    if not video_path or not Path(video_path).exists():
        return {"error": "Video assembly failed"}

    vp = Path(video_path)

    # Update DB
    db = get_db()
    db.execute(
        "UPDATE videos SET status='rendered', video_path=?, duration_seconds=? WHERE id=?",
        (str(vp), 0, video_id),
    )
    db.commit()
    db.close()

    # Generate SEO
    from modules.kids_seo_generator import generate as gen_seo
    import yaml
    with open(BASE_DIR / "channels" / "kiddoworld.yaml") as f:
        cfg = yaml.safe_load(f)

    db2 = get_db()
    row = db2.execute("SELECT title FROM videos WHERE id=?", (video_id,)).fetchone()
    db2.close()
    topic_obj = {"text": row["title"] if row else "Kids Video", "concept": "learning"}
    seo = gen_seo(topic_obj, None, cfg)

    return {
        "video_path": str(vp),
        "video_url": f"/output/videos/{vp.name}",
        "duration": 0,
        "size_mb": round(vp.stat().st_size / (1024 * 1024), 1),
        "seo": {
            "title": seo.title,
            "description": seo.description,
            "tags": seo.tags,
        },
    }


@app.post("/api/create/upload-youtube")
async def api_upload_youtube(request: Request, _user: str = Depends(verify_credentials)):
    """Upload approved video to YouTube."""
    body = await request.json()
    video_id = body.get("video_id")
    title = body.get("title", "")
    description = body.get("description", "")
    tags = body.get("tags", [])

    import re

    db = get_db()
    row = db.execute("SELECT video_path, title FROM videos WHERE id=?", (video_id,)).fetchone()
    if not row or not row["video_path"]:
        db.close()
        return {"error": "Video file not found"}

    video_path = Path(row["video_path"])
    if not video_path.exists():
        db.close()
        return {"error": "Video file missing from disk"}

    # Sanitize tags
    clean_tags = []
    total_chars = 0
    for t in tags:
        t = t.encode("ascii", errors="ignore").decode("ascii").strip()
        t = re.sub(r"[^a-zA-Z0-9 -]", "", t).strip()
        if len(t) < 2 or len(t) > 30:
            continue
        if total_chars + len(t) > 450:
            break
        clean_tags.append(t)
        total_chars += len(t)

    # Build SEO object
    class SEO:
        pass
    seo = SEO()
    seo.title = title[:100]
    seo.description = description
    seo.tags = clean_tags
    seo.hashtags = []
    seo.language = "en"
    seo.playlist_category = "Kids Education"

    # Upload
    from modules.uploader.youtube_uploader import upload
    yt_id = upload(video_path=video_path, seo_result=seo, category="education", made_for_kids=True)

    if not yt_id:
        db.close()
        return {"error": "YouTube upload failed"}

    yt_url = f"https://www.youtube.com/watch?v={yt_id}"

    # Update DB
    db.execute("UPDATE videos SET status='uploaded' WHERE id=?", (video_id,))
    db.execute(
        "INSERT INTO uploads (video_id, channel_id, youtube_video_id, youtube_url, title) "
        "VALUES (?, 2, ?, ?, ?)",
        (video_id, yt_id, yt_url, title),
    )
    db.commit()
    db.close()

    return {"youtube_id": yt_id, "youtube_url": yt_url}


# ── Simplified Upload Flow ─────────────────────────────────────────────────

@app.get("/upload", response_class=HTMLResponse)
async def upload_page(request: Request):
    channels = _get_channels()
    return templates.TemplateResponse("upload.html", {
        "request": request,
        "channels": channels,
        "active_channel_id": _default_channel_id(channels),
    })


@app.post("/api/upload/video")
async def api_upload_video(
    file: UploadFile = File(...),
    title: str = Form(""),
    description: str = Form(""),
    playlist: str = Form("songs"),
    characters: str = Form(""),
    age_group: str = Form("all"),
):
    """Upload a video file and save metadata."""
    import shutil

    vid_dir = BASE_DIR / "output" / "videos"
    vid_dir.mkdir(parents=True, exist_ok=True)

    # Generate unique filename
    suffix = hashlib.md5(f"{title}_{datetime.now().isoformat()}".encode()).hexdigest()[:10]
    ext = Path(file.filename).suffix or ".mp4"
    filename = f"upload_{suffix}{ext}"
    filepath = vid_dir / filename

    with open(filepath, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # Save to DB
    db = get_db()
    db.execute(
        "INSERT INTO videos (channel_id, title, status, format, video_path, script) "
        "VALUES (2, ?, 'uploaded_local', 'long', ?, ?)",
        (title, str(filepath), json.dumps({
            "description": description,
            "playlist": playlist,
            "characters": characters,
            "age_group": age_group,
        })),
    )
    db.commit()
    video_id = db.execute("SELECT MAX(id) as id FROM videos").fetchone()["id"]
    db.close()

    return {
        "video_id": video_id,
        "filename": filename,
        "size_mb": round(filepath.stat().st_size / (1024 * 1024), 1),
        "video_url": f"/output/videos/{filename}",
    }


@app.post("/api/upload/generate-seo")
async def api_generate_seo(request: Request):
    """Generate SEO using analytics learning — titles, description, tags."""
    body = await request.json()
    video_id = body.get("video_id")
    title = body.get("title", "")
    description = body.get("description", "")
    playlist = body.get("playlist", "songs")
    characters = body.get("characters", "")
    age_group = body.get("age_group", "all")

    from openai import OpenAI
    from config import OPENAI_API_KEY
    client = OpenAI(api_key=OPENAI_API_KEY)

    # ── Analytics Learning: Get insights from past performance ──
    db = get_db()
    top_videos = db.execute("""
        SELECT u.title, u.views, u.likes, va.ctr, va.avg_view_percentage
        FROM uploads u
        LEFT JOIN video_analytics va ON u.id = va.upload_id
        WHERE u.channel_id = 2 AND u.views > 0
        ORDER BY u.views DESC LIMIT 10
    """).fetchall()

    # Get best performing title patterns
    best_titles = []
    for v in top_videos:
        if v["title"]:
            best_titles.append(f"'{v['title']}' ({v['views']} views)")

    # Get all used tags and their associated view counts
    recent_seo = db.execute("""
        SELECT v.script, u.views FROM videos v
        JOIN uploads u ON v.id = u.video_id
        WHERE v.channel_id = 2 AND u.views > 0
        ORDER BY u.views DESC LIMIT 10
    """).fetchall()

    # Get strategy recommendations
    strategy = db.execute(
        "SELECT * FROM strategy WHERE channel_id=2 ORDER BY last_updated DESC LIMIT 1"
    ).fetchone()

    db.close()

    analytics_context = ""
    if best_titles:
        analytics_context += "TOP PERFORMING TITLES (learn from these patterns):\n"
        analytics_context += "\n".join(best_titles[:5]) + "\n\n"
    if strategy:
        strategy = dict(strategy)
        analytics_context += f"CHANNEL STRATEGY INSIGHTS:\n"
        if strategy.get("recommendation_notes"):
            analytics_context += strategy["recommendation_notes"] + "\n"
        if strategy.get("top_performing_keywords"):
            analytics_context += f"Best keywords: {strategy['top_performing_keywords']}\n"

    system_prompt = f"""You are a YouTube SEO expert who has grown kids channels to millions of subscribers.
You know exactly what titles, descriptions and tags make kids videos rank #1.

CHANNEL: KiddoWorld (kids aged 2-8)
CHARACTERS: Sid (curious boy), Kido (playful baby), Mom, Dad
PLAYLIST: {playlist}

{analytics_context}

TITLE RULES:
- Stack 2-3 high-volume search phrases separated by |
- ALWAYS include "Nursery Rhymes" or "Kids Songs" for songs, "Stories for Kids" for stories
- ALWAYS end with "KiddoWorld"
- Max 100 characters
- Learn from top performing titles above — use similar patterns

DESCRIPTION RULES:
- First 2 lines packed with search keywords (shown in results)
- Include full video summary
- Include "Watch More KiddoWorld:" section
- End with keyword-rich channel description
- 15-20 hashtags at bottom
- 400-600 words total

TAGS RULES:
- 25-30 tags, ASCII only
- First 5: exact search phrases users type
- Include: nursery rhymes, kids songs, baby songs, toddler songs, KiddoWorld
- Add topic-specific tags
- Learn from what worked before

Return JSON:
{{
    "title": "SEO-optimized title",
    "description": "full description with hashtags",
    "tags": ["tag1", "tag2", ...]
}}"""

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Video topic: {title}\nDescription: {description}\nPlaylist: {playlist}\nCharacters: {characters}\nAge: {age_group}"},
        ],
        response_format={"type": "json_object"},
        temperature=0.7,
    )

    seo = json.loads(resp.choices[0].message.content)
    return seo


@app.post("/api/upload/save-draft")
async def api_save_draft(request: Request):
    """Save video as draft for later publishing."""
    body = await request.json()
    video_id = body.get("video_id")
    if not video_id:
        return {"error": "No video ID"}

    db = get_db()
    # Update video with draft info
    db.execute(
        "UPDATE videos SET status='draft', title=?, format=? WHERE id=?",
        (body.get("title", "Untitled"), body.get("format", "long"), video_id),
    )

    # Save SEO data as JSON in a drafts table
    db.execute("""CREATE TABLE IF NOT EXISTS drafts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        video_id INTEGER NOT NULL,
        title TEXT, description TEXT, playlist TEXT, format TEXT,
        yt_title TEXT, yt_description TEXT, yt_tags TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (video_id) REFERENCES videos(id)
    )""")

    # Remove old draft for same video
    db.execute("DELETE FROM drafts WHERE video_id=?", (video_id,))

    db.execute(
        "INSERT INTO drafts (video_id, title, description, playlist, format, yt_title, yt_description, yt_tags) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (video_id, body.get("title", ""), body.get("description", ""),
         body.get("playlist", ""), body.get("format", "long"),
         body.get("yt_title", ""), body.get("yt_description", ""), body.get("yt_tags", "")),
    )
    db.commit()
    db.close()
    return {"status": "saved", "video_id": video_id}


@app.get("/drafts")
async def drafts_page(request: Request):
    """Show saved drafts."""
    db = get_db()
    db.execute("""CREATE TABLE IF NOT EXISTS drafts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        video_id INTEGER NOT NULL,
        title TEXT, description TEXT, playlist TEXT, format TEXT,
        yt_title TEXT, yt_description TEXT, yt_tags TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (video_id) REFERENCES videos(id)
    )""")
    rows = db.execute(
        "SELECT d.*, v.video_path FROM drafts d "
        "JOIN videos v ON d.video_id=v.id "
        "ORDER BY d.created_at DESC"
    ).fetchall()
    drafts = [dict(r) for r in rows]
    db.close()

    channels = _get_channels()
    return templates.TemplateResponse("drafts.html", {
        "request": request,
        "drafts": drafts,
        "channels": channels,
    })


@app.post("/api/drafts/{draft_id}/delete")
async def api_delete_draft(draft_id: int):
    """Delete a draft."""
    db = get_db()
    db.execute("DELETE FROM drafts WHERE id=?", (draft_id,))
    db.commit()
    db.close()
    return {"status": "deleted"}


@app.post("/api/drafts/{draft_id}/publish")
async def api_publish_draft(draft_id: int, request: Request):
    """Publish a saved draft to YouTube."""
    import re

    db = get_db()
    draft = db.execute("SELECT * FROM drafts WHERE id=?", (draft_id,)).fetchone()
    if not draft:
        db.close()
        return {"error": "Draft not found"}

    video = db.execute("SELECT video_path FROM videos WHERE id=?", (draft["video_id"],)).fetchone()
    if not video or not video["video_path"]:
        db.close()
        return {"error": "Video file not found"}

    video_path = Path(video["video_path"])
    if not video_path.exists():
        db.close()
        return {"error": "Video file missing from disk"}

    video_format = draft["format"] or "long"
    title = draft["yt_title"] or draft["title"] or "KiddoWorld Video"

    if video_format == "short" and "#Shorts" not in title:
        title = title.rstrip() + " #Shorts"

    # Sanitize tags
    clean_tags = []
    total_chars = 0
    for t in (draft["yt_tags"] or "").split(","):
        t = t.encode("ascii", errors="ignore").decode("ascii").strip()
        t = re.sub(r"[^a-zA-Z0-9 -]", "", t).strip()
        if len(t) < 2 or len(t) > 30:
            continue
        if total_chars + len(t) > 450:
            break
        clean_tags.append(t)
        total_chars += len(t)

    class SEOObj:
        pass
    seo = SEOObj()
    seo.title = title[:100]
    seo.description = draft["yt_description"] or ""
    seo.tags = clean_tags
    seo.hashtags = []
    seo.language = "en"
    seo.playlist_category = "Kids Education"

    # Append outro for long-form
    final_video_path = video_path
    if video_format != "short":
        outro_path = Path(BASE_DIR) / "assets" / "templates" / "outro.mp4"
        if outro_path.exists():
            try:
                import subprocess
                merged = video_path.parent / f"final_{video_path.stem}.mp4"
                concat_list = video_path.parent / "concat_list.txt"
                concat_list.write_text(f"file '{video_path}'\nfile '{outro_path}'\n")
                subprocess.run([
                    "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                    "-i", str(concat_list), "-c", "copy", str(merged)
                ], capture_output=True, timeout=120)
                if merged.exists() and merged.stat().st_size > video_path.stat().st_size:
                    final_video_path = merged
                concat_list.unlink(missing_ok=True)
            except Exception:
                pass

    from modules.uploader.youtube_uploader import upload
    yt_id = upload(video_path=final_video_path, seo_result=seo, category="education", made_for_kids=True)

    if not yt_id:
        db.close()
        return {"error": "YouTube upload failed"}

    yt_url = f"https://www.youtube.com/watch?v={yt_id}"
    db.execute("UPDATE videos SET status='uploaded' WHERE id=?", (draft["video_id"],))
    db.execute(
        "INSERT INTO uploads (video_id, channel_id, youtube_video_id, youtube_url, title) "
        "VALUES (?, 2, ?, ?, ?)",
        (draft["video_id"], yt_id, yt_url, title),
    )
    db.execute("DELETE FROM drafts WHERE id=?", (draft_id,))
    db.commit()
    db.close()

    return {"status": "published", "youtube_url": yt_url}


@app.post("/api/upload/publish")
async def api_publish(request: Request):
    """Upload video to YouTube with approved SEO."""
    body = await request.json()
    video_id = body.get("video_id")
    title = body.get("title", "")
    description = body.get("description", "")
    tags = body.get("tags", [])
    create_short = body.get("create_short", True)
    video_format = body.get("format", "long")  # "long" or "short"

    # For Shorts: add #Shorts to title, skip outro, skip auto-short creation
    if video_format == "short":
        if "#Shorts" not in title and "#shorts" not in title:
            title = title.rstrip() + " #Shorts"
        create_short = False

    import re
    from datetime import datetime, timezone, timedelta

    # Calculate optimal premiere time
    # Best slots: 10:00 UTC (India/UK afternoon) or 22:00 UTC (USA evening)
    now = datetime.now(timezone.utc)
    publish_at = None

    if video_format != "short":  # Only schedule long-form, Shorts go live immediately
        slot_10 = now.replace(hour=10, minute=0, second=0, microsecond=0)
        slot_22 = now.replace(hour=22, minute=0, second=0, microsecond=0)

        # Find the next available slot at least 30 min from now
        min_time = now + timedelta(minutes=30)
        candidates = []
        for slot in [slot_10, slot_22]:
            if slot > min_time:
                candidates.append(slot)
            # Also check tomorrow's slots
            tomorrow_slot = slot + timedelta(days=1)
            candidates.append(tomorrow_slot)

        candidates.sort()
        publish_at = candidates[0].strftime("%Y-%m-%dT%H:%M:%S.0Z")
        print(f"Scheduled premiere: {publish_at}")

    db = get_db()
    row = db.execute("SELECT video_path, title FROM videos WHERE id=?", (video_id,)).fetchone()
    if not row or not row["video_path"]:
        db.close()
        return {"error": "Video file not found"}

    video_path = Path(row["video_path"])
    if not video_path.exists():
        db.close()
        return {"error": "Video file missing from disk"}

    # Sanitize tags
    clean_tags = []
    total_chars = 0
    for t in tags:
        t = t.encode("ascii", errors="ignore").decode("ascii").strip()
        t = re.sub(r"[^a-zA-Z0-9 -]", "", t).strip()
        if len(t) < 2 or len(t) > 30:
            continue
        if total_chars + len(t) > 450:
            break
        clean_tags.append(t)
        total_chars += len(t)

    # Build SEO object
    class SEOObj:
        pass
    seo = SEOObj()
    seo.title = title[:100]
    seo.description = description
    seo.tags = clean_tags
    seo.hashtags = []
    seo.language = "en"
    seo.playlist_category = "Kids Education"

    # Append outro to video (skip for Shorts)
    outro_path = Path(BASE_DIR) / "assets" / "templates" / "outro.mp4"
    final_video_path = video_path
    if outro_path.exists() and video_format != "short":
        try:
            import subprocess
            merged = video_path.parent / f"final_{video_path.stem}.mp4"
            # Use ffmpeg concat to append outro (fast, no re-encoding)
            concat_list = video_path.parent / "concat_list.txt"
            concat_list.write_text(f"file '{video_path}'\nfile '{outro_path}'\n")
            subprocess.run([
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", str(concat_list), "-c", "copy", str(merged)
            ], capture_output=True, timeout=120)
            if merged.exists() and merged.stat().st_size > video_path.stat().st_size:
                final_video_path = merged
                print(f"Outro appended: {merged.name}")
            concat_list.unlink(missing_ok=True)
        except Exception as e:
            print(f"Outro append failed: {e} — uploading without outro")

    # Upload to YouTube (with scheduled premiere for long-form)
    from modules.uploader.youtube_uploader import upload
    yt_id = upload(
        video_path=final_video_path,
        seo_result=seo,
        category="education",
        made_for_kids=True,
        publish_at=publish_at,
    )

    if not yt_id:
        db.close()
        return {"error": "YouTube upload failed — check token or tags"}

    yt_url = f"https://www.youtube.com/watch?v={yt_id}"

    # Update DB
    db.execute("UPDATE videos SET status='uploaded' WHERE id=?", (video_id,))
    db.execute(
        "INSERT INTO uploads (video_id, channel_id, youtube_video_id, youtube_url, title) "
        "VALUES (?, 2, ?, ?, ?)",
        (video_id, yt_id, yt_url, title),
    )
    db.commit()

    # Auto-create Short
    short_url = None
    if create_short:
        try:
            from modules.shorts_maker import create as make_short
            short_result = make_short(str(video_path), kids=True)
            short_path = str(short_result["path"]) if short_result else None
            if short_path and Path(short_path).exists():
                short_seo_obj = SEOObj()
                short_seo_obj.title = title[:70] + " #Shorts"
                short_seo_obj.description = description[:200]
                short_seo_obj.tags = clean_tags[:10]
                short_seo_obj.hashtags = []
                short_seo_obj.language = "en"
                short_seo_obj.playlist_category = "Kids Education"
                short_yt_id = upload(
                    video_path=Path(short_path),
                    seo_result=short_seo_obj,
                    category="education",
                    made_for_kids=True,
                )
                if short_yt_id:
                    short_url = f"https://www.youtube.com/watch?v={short_yt_id}"
        except Exception as e:
            short_url = f"Short creation failed: {e}"

    db.close()

    result = {
        "youtube_id": yt_id,
        "youtube_url": yt_url,
        "short_url": short_url,
    }
    if publish_at:
        result["scheduled_at"] = publish_at
        result["message"] = f"Video scheduled as premiere at {publish_at} UTC"
    return result


# ── Analytics Learning System ──────────────────────────────────────────────

@app.post("/api/analytics/collect")
async def api_collect_analytics(request: Request):
    """Pull latest YouTube analytics for all uploaded videos."""
    from modules.uploader.youtube_uploader import _get_authenticated_service

    yt = _get_authenticated_service()
    db = get_db()

    uploads = db.execute(
        "SELECT id, youtube_video_id FROM uploads WHERE channel_id=2 AND youtube_video_id IS NOT NULL"
    ).fetchall()

    updated = 0
    for u in uploads:
        try:
            resp = yt.videos().list(
                part="statistics,contentDetails",
                id=u["youtube_video_id"],
            ).execute()
            if resp.get("items"):
                stats = resp["items"][0]["statistics"]
                views = int(stats.get("viewCount", 0))
                likes = int(stats.get("likeCount", 0))
                comments = int(stats.get("commentCount", 0))

                db.execute(
                    "UPDATE uploads SET views=?, likes=? WHERE id=?",
                    (views, likes, u["id"]),
                )
                updated += 1
        except Exception:
            continue

    db.commit()
    db.close()
    return {"updated": updated, "total": len(uploads)}


@app.post("/api/analytics/generate-insights")
async def api_generate_insights(request: Request):
    """Use AI to analyze performance and generate actionable insights."""
    from openai import OpenAI
    from config import OPENAI_API_KEY
    client = OpenAI(api_key=OPENAI_API_KEY)

    db = get_db()
    videos = [dict(r) for r in db.execute("""
        SELECT u.title, u.views, u.likes, u.uploaded_at
        FROM uploads u WHERE u.channel_id=2
        ORDER BY u.views DESC
    """).fetchall()]
    db.close()

    if not videos:
        return {"insights": "No videos uploaded yet. Upload some videos first to get insights."}

    video_data = "\n".join([
        f"- '{v['title']}': {v['views']} views, {v['likes']} likes (uploaded {v['uploaded_at'][:10] if v['uploaded_at'] else '?'})"
        for v in videos
    ])

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{
            "role": "system",
            "content": (
                "You are a YouTube analytics expert for kids channels. "
                "Analyze the video performance data and provide actionable insights. "
                "Focus on: what's working, what's not, title patterns, upload timing, "
                "content themes, and specific suggestions to grow views and subscribers. "
                "Be specific with data. Keep it under 10 bullet points."
            ),
        }, {
            "role": "user",
            "content": f"Channel: KiddoWorld (kids 2-8)\nVideos:\n{video_data}\n\nAnalyze and give insights.",
        }],
        temperature=0.7,
    )

    insights = resp.choices[0].message.content

    # Save insights to strategy table
    db2 = get_db()
    db2.execute(
        "INSERT OR REPLACE INTO strategy (channel_id, recommendation_notes, last_updated) "
        "VALUES (2, ?, datetime('now'))",
        (insights,),
    )
    db2.commit()
    db2.close()

    return {"insights": insights}


@app.get("/api/analytics/insights")
async def api_analytics_insights(request: Request):
    """Get analytics insights for SEO learning."""
    db = get_db()

    # Top videos by views
    top = [dict(r) for r in db.execute("""
        SELECT u.title, u.views, u.likes, u.youtube_url,
               v.script, v.created_at
        FROM uploads u
        JOIN videos v ON u.video_id = v.id
        WHERE u.channel_id = 2
        ORDER BY u.views DESC LIMIT 10
    """).fetchall()]

    # Total stats
    totals = db.execute("""
        SELECT COUNT(*) as videos,
               COALESCE(SUM(views), 0) as total_views,
               COALESCE(SUM(likes), 0) as total_likes
        FROM uploads WHERE channel_id = 2
    """).fetchone()

    # Views trend (last 7 days uploads)
    recent = [dict(r) for r in db.execute("""
        SELECT u.title, u.views, u.likes, u.uploaded_at
        FROM uploads u WHERE u.channel_id = 2
        ORDER BY u.uploaded_at DESC LIMIT 7
    """).fetchall()]

    db.close()

    return {
        "top_videos": top,
        "totals": dict(totals) if totals else {},
        "recent": recent,
    }


# ── Runner ──────────────────────────────────────────────────────────────────

def start_dashboard(host: str = "0.0.0.0", port: int | None = None):
    """Start the dashboard server."""
    import uvicorn
    uvicorn.run(app, host=host, port=port or DASHBOARD_PORT)
