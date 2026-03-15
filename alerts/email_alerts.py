"""
UpperCut — Email Alerts (Phase 4)
Sends SMTP email notifications for pipeline events:
- Pipeline success/failure
- Upload completion with YouTube link
- Errors that exhaust retries
- Low API balance warnings
- Daily summary digest
"""

from __future__ import annotations

import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, List, Optional

from loguru import logger

from config import ALERT_EMAIL, SMTP_EMAIL, SMTP_PASSWORD


def _is_configured() -> bool:
    """Check if email alerts are configured."""
    return bool(ALERT_EMAIL and SMTP_EMAIL and SMTP_PASSWORD)


def _send_email(subject: str, html_body: str, to_email: str | None = None):
    """
    Send an HTML email via SMTP (Gmail-compatible).

    Args:
        subject: email subject line
        html_body: HTML content
        to_email: recipient (defaults to ALERT_EMAIL from config)
    """
    if not _is_configured():
        logger.debug("Email alerts not configured — skipping")
        return

    recipient = to_email or ALERT_EMAIL

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[UpperCut] {subject}"
    msg["From"] = SMTP_EMAIL
    msg["To"] = recipient
    msg.attach(MIMEText(html_body, "html"))

    for attempt in range(2):
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as server:
                server.login(SMTP_EMAIL, SMTP_PASSWORD)
                server.sendmail(SMTP_EMAIL, recipient, msg.as_string())
            logger.info(f"Alert email sent: {subject}")
            return
        except Exception as e:
            if attempt == 0:
                logger.warning(f"Email attempt 1 failed ({e}), retrying...")
                continue
            logger.warning(f"Email failed (non-fatal): {e}")


# ── Alert types ─────────────────────────────────────────────────────────────

def pipeline_success(
    channel_name: str,
    topic: str,
    youtube_url: str | None = None,
    shorts_url: str | None = None,
    duration_mins: float = 0,
    cost_usd: float = 0,
):
    """Send alert when a video pipeline completes successfully."""
    links_html = ""
    if youtube_url:
        links_html += f'<p><strong>Video:</strong> <a href="{youtube_url}">{youtube_url}</a></p>'
    if shorts_url:
        links_html += f'<p><strong>Short:</strong> <a href="{shorts_url}">{shorts_url}</a></p>'

    html = f"""
    <div style="font-family:sans-serif;max-width:600px;margin:0 auto;">
        <div style="background:#00b894;color:white;padding:16px 24px;border-radius:8px 8px 0 0;">
            <h2 style="margin:0;">Pipeline Success</h2>
        </div>
        <div style="background:#1a1d27;color:#e1e4ed;padding:24px;border-radius:0 0 8px 8px;">
            <p><strong>Channel:</strong> {channel_name}</p>
            <p><strong>Topic:</strong> {topic}</p>
            <p><strong>Duration:</strong> {duration_mins:.1f} min</p>
            <p><strong>Cost:</strong> ${cost_usd:.4f}</p>
            {links_html}
            <p style="color:#8b8fa3;font-size:12px;margin-top:16px;">
                {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} PKT
            </p>
        </div>
    </div>
    """
    _send_email(f"Video Uploaded — {topic[:40]}", html)


def pipeline_failure(channel_name: str, topic: str, error_type: str, error_message: str):
    """Send alert when a pipeline run fails."""
    html = f"""
    <div style="font-family:sans-serif;max-width:600px;margin:0 auto;">
        <div style="background:#e17055;color:white;padding:16px 24px;border-radius:8px 8px 0 0;">
            <h2 style="margin:0;">Pipeline Failed</h2>
        </div>
        <div style="background:#1a1d27;color:#e1e4ed;padding:24px;border-radius:0 0 8px 8px;">
            <p><strong>Channel:</strong> {channel_name}</p>
            <p><strong>Topic:</strong> {topic}</p>
            <p><strong>Error Type:</strong> {error_type}</p>
            <p><strong>Error:</strong></p>
            <pre style="background:#0f1117;padding:12px;border-radius:6px;overflow-x:auto;font-size:12px;color:#e17055;">
{error_message[:500]}</pre>
            <p style="color:#8b8fa3;font-size:12px;margin-top:16px;">
                {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} PKT
            </p>
        </div>
    </div>
    """
    _send_email(f"FAILED — {error_type}", html)


def retry_exhausted(channel_name: str, step: str, error_message: str):
    """Send alert when a pipeline step exhausts all retries."""
    html = f"""
    <div style="font-family:sans-serif;max-width:600px;margin:0 auto;">
        <div style="background:#e17055;color:white;padding:16px 24px;border-radius:8px 8px 0 0;">
            <h2 style="margin:0;">Retries Exhausted</h2>
        </div>
        <div style="background:#1a1d27;color:#e1e4ed;padding:24px;border-radius:0 0 8px 8px;">
            <p><strong>Channel:</strong> {channel_name}</p>
            <p><strong>Step:</strong> {step}</p>
            <p><strong>Error:</strong></p>
            <pre style="background:#0f1117;padding:12px;border-radius:6px;overflow-x:auto;font-size:12px;color:#e17055;">
{error_message[:500]}</pre>
            <p>All retry attempts have been exhausted. Manual intervention may be required.</p>
            <p style="color:#8b8fa3;font-size:12px;margin-top:16px;">
                {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} PKT
            </p>
        </div>
    </div>
    """
    _send_email(f"RETRIES EXHAUSTED — {step}", html)


def low_api_balance(service: str, remaining: float, threshold: float):
    """Send alert when an API balance is running low."""
    html = f"""
    <div style="font-family:sans-serif;max-width:600px;margin:0 auto;">
        <div style="background:#fdcb6e;color:#2d3436;padding:16px 24px;border-radius:8px 8px 0 0;">
            <h2 style="margin:0;">Low API Balance Warning</h2>
        </div>
        <div style="background:#1a1d27;color:#e1e4ed;padding:24px;border-radius:0 0 8px 8px;">
            <p><strong>Service:</strong> {service}</p>
            <p><strong>Remaining Balance:</strong> ${remaining:.2f}</p>
            <p><strong>Threshold:</strong> ${threshold:.2f}</p>
            <p>Please top up your API balance to avoid pipeline interruptions.</p>
            <p style="color:#8b8fa3;font-size:12px;margin-top:16px;">
                {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} PKT
            </p>
        </div>
    </div>
    """
    _send_email(f"LOW BALANCE — {service} (${remaining:.2f})", html)


def quota_exceeded(service: str):
    """Send alert when a service quota is exceeded (e.g., YouTube API)."""
    html = f"""
    <div style="font-family:sans-serif;max-width:600px;margin:0 auto;">
        <div style="background:#e17055;color:white;padding:16px 24px;border-radius:8px 8px 0 0;">
            <h2 style="margin:0;">Quota Exceeded</h2>
        </div>
        <div style="background:#1a1d27;color:#e1e4ed;padding:24px;border-radius:0 0 8px 8px;">
            <p><strong>Service:</strong> {service}</p>
            <p>The daily API quota has been exceeded. Uploads will resume when the quota resets (midnight Pacific Time).</p>
            <p style="color:#8b8fa3;font-size:12px;margin-top:16px;">
                {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} PKT
            </p>
        </div>
    </div>
    """
    _send_email(f"QUOTA EXCEEDED — {service}", html)


def daily_summary(channel_name: str, stats: Dict):
    """Send a daily digest summary email."""
    videos_made = stats.get("videos_made", 0)
    videos_uploaded = stats.get("videos_uploaded", 0)
    total_views = stats.get("total_views", 0)
    total_cost = stats.get("total_cost", 0)
    errors_count = stats.get("errors", 0)
    top_video = stats.get("top_video", "N/A")

    status_color = "#00b894" if errors_count == 0 else "#fdcb6e"

    html = f"""
    <div style="font-family:sans-serif;max-width:600px;margin:0 auto;">
        <div style="background:{status_color};color:{'white' if errors_count == 0 else '#2d3436'};padding:16px 24px;border-radius:8px 8px 0 0;">
            <h2 style="margin:0;">Daily Summary — {channel_name}</h2>
        </div>
        <div style="background:#1a1d27;color:#e1e4ed;padding:24px;border-radius:0 0 8px 8px;">
            <table style="width:100%;border-collapse:collapse;">
                <tr>
                    <td style="padding:8px 0;color:#8b8fa3;">Videos Created</td>
                    <td style="padding:8px 0;text-align:right;font-weight:600;">{videos_made}</td>
                </tr>
                <tr>
                    <td style="padding:8px 0;color:#8b8fa3;">Videos Uploaded</td>
                    <td style="padding:8px 0;text-align:right;font-weight:600;">{videos_uploaded}</td>
                </tr>
                <tr>
                    <td style="padding:8px 0;color:#8b8fa3;">Total Views (all time)</td>
                    <td style="padding:8px 0;text-align:right;font-weight:600;">{total_views:,}</td>
                </tr>
                <tr>
                    <td style="padding:8px 0;color:#8b8fa3;">API Cost Today</td>
                    <td style="padding:8px 0;text-align:right;font-weight:600;">${total_cost:.4f}</td>
                </tr>
                <tr>
                    <td style="padding:8px 0;color:#8b8fa3;">Errors</td>
                    <td style="padding:8px 0;text-align:right;font-weight:600;color:{'#e17055' if errors_count > 0 else '#00b894'};">{errors_count}</td>
                </tr>
                <tr>
                    <td style="padding:8px 0;color:#8b8fa3;">Top Video</td>
                    <td style="padding:8px 0;text-align:right;font-weight:600;">{top_video[:40]}</td>
                </tr>
            </table>
            <p style="color:#8b8fa3;font-size:12px;margin-top:16px;">
                {datetime.now().strftime('%Y-%m-%d')} — UpperCut Automation
            </p>
        </div>
    </div>
    """
    _send_email(f"Daily Summary — {videos_uploaded} videos, {errors_count} errors", html)


def intelligence_update(channel_name: str, recommendations: List[str]):
    """Send alert with new intelligence recommendations."""
    recs_html = "".join(
        f'<li style="margin:4px 0;padding:6px;background:rgba(0,184,148,0.08);'
        f'border-left:3px solid #00b894;border-radius:0 4px 4px 0;">{r}</li>'
        for r in recommendations
    )

    html = f"""
    <div style="font-family:sans-serif;max-width:600px;margin:0 auto;">
        <div style="background:#6c5ce7;color:white;padding:16px 24px;border-radius:8px 8px 0 0;">
            <h2 style="margin:0;">Intelligence Update</h2>
        </div>
        <div style="background:#1a1d27;color:#e1e4ed;padding:24px;border-radius:0 0 8px 8px;">
            <p><strong>Channel:</strong> {channel_name}</p>
            <p>The intelligence engine has new recommendations:</p>
            <ul style="list-style:none;padding:0;">{recs_html}</ul>
            <p style="color:#8b8fa3;font-size:12px;margin-top:16px;">
                {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} PKT
            </p>
        </div>
    </div>
    """
    _send_email(f"Intelligence Update — {channel_name}", html)
