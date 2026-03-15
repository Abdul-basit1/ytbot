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

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

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

security = HTTPBasic()


def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    """Verify username and password against .env values."""
    correct_username = secrets.compare_digest(
        credentials.username.encode("utf8"),
        DASHBOARD_USERNAME.encode("utf8"),
    )
    correct_password = secrets.compare_digest(
        credentials.password.encode("utf8"),
        DASHBOARD_PASSWORD.encode("utf8"),
    )
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


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
    channel_id = int(request.query_params.get("channel", _default_channel_id(channels)))

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
    channel_id = int(request.query_params.get("channel", _default_channel_id(channels)))
    videos = _get_recent_videos(channel_id, limit=100)

    return templates.TemplateResponse("videos.html", {
        "request": request,
        "channels": channels,
        "active_channel_id": channel_id,
        "videos": videos,
    })


@app.get("/analytics", response_class=HTMLResponse)
async def analytics_page(request: Request, _user: str = Depends(verify_credentials)):
    channels = _get_channels()
    channel_id = int(request.query_params.get("channel", _default_channel_id(channels)))
    history = _get_analytics_history(channel_id)
    strategy = _get_strategy(channel_id)
    top_videos = _get_top_videos(channel_id)

    return templates.TemplateResponse("analytics.html", {
        "request": request,
        "channels": channels,
        "active_channel_id": channel_id,
        "history": history,
        "strategy": strategy,
        "top_videos": top_videos,
    })


@app.get("/errors", response_class=HTMLResponse)
async def errors_page(request: Request, _user: str = Depends(verify_credentials)):
    channels = _get_channels()
    channel_id = int(request.query_params.get("channel", _default_channel_id(channels)))
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


# ── Runner ──────────────────────────────────────────────────────────────────

def start_dashboard(host: str = "0.0.0.0", port: int | None = None):
    """Start the dashboard server."""
    import uvicorn
    uvicorn.run(app, host=host, port=port or DASHBOARD_PORT)
