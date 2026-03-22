"""
UpperCut — YouTube Uploader
Handles OAuth 2.0 authentication and video upload via YouTube Data API v3.
Supports multiple channels, playlist management, and quota-aware retries.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List, Optional

from loguru import logger

from config import BASE_DIR, YOUTUBE_CLIENT_SECRETS

# YouTube API scopes
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

TOKEN_PATH = BASE_DIR / "token.json"

# Channel-specific token files
CHANNEL_TOKEN_MAP = {
    "kiddoworld": "token_kiddoworld.json",
    "oddlyperfect": "token_oddlyperfect.json",
}

# YouTube category IDs
CATEGORIES = {
    "news": "25",
    "entertainment": "24",
    "sports": "17",
    "education": "27",
    "people": "22",
    "trending": "25",  # Default: News & Politics
}


def _get_authenticated_service(token_file: str | None = None):
    """
    Build and return an authenticated YouTube API service.
    Uses stored token file, or runs OAuth flow if no token exists.

    Args:
        token_file: Optional token filename (e.g. "token_oddlyperfect.json").
                    Defaults to "token.json" for backward compatibility.
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    token_path = BASE_DIR / (token_file or "token.json")

    creds = None

    # Load existing token
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    # Refresh or run new auth flow
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info(f"Refreshing YouTube OAuth token ({token_path.name})...")
            try:
                creds.refresh(Request())
            except Exception as e:
                logger.warning(f"Token refresh failed: {e}, re-authenticating...")
                creds = None

        if not creds:
            if not token_path.exists():
                logger.error(
                    f"No YouTube token found ({token_path.name})! Run 'python3 authenticate_youtube.py' "
                    "on your Mac first, then deploy token to VPS."
                )
                raise FileNotFoundError(
                    f"{token_path.name} not found — run authenticate_youtube.py locally first"
                )
            # Token file exists but is completely invalid
            raise RuntimeError(
                f"YouTube token ({token_path.name}) is invalid and cannot be refreshed. "
                "Re-run 'python3 authenticate_youtube.py' on your Mac."
            )

        # Save token for future use
        token_path.write_text(creds.to_json())
        logger.info(f"YouTube OAuth token saved ({token_path.name})")

    return build("youtube", "v3", credentials=creds)


def upload(
    video_path: Path,
    seo_result,
    thumbnail_path: Path | None = None,
    is_short: bool = False,
    category: str = "trending",
    privacy: str = "public",
    made_for_kids: bool = False,
    publish_at: str | None = None,
    token_file: str | None = None,
) -> Optional[str]:
    """
    Upload a video to YouTube with full metadata.

    Args:
        video_path: path to the MP4 file
        seo_result: SEOResult with title, description, tags
        thumbnail_path: path to thumbnail JPG (optional)
        is_short: if True, append #Shorts to title
        category: YouTube category key
        privacy: public, private, or unlisted
        made_for_kids: if True, set COPPA compliance flags (REQUIRED for kids content)

    Returns:
        YouTube video ID on success, None on failure.
    """
    from googleapiclient.http import MediaFileUpload

    if not video_path.exists():
        logger.error(f"Video file not found: {video_path}")
        return None

    youtube = _get_authenticated_service(token_file=token_file)

    title = getattr(seo_result, "title_urdu", None) or seo_result.title
    if is_short and "#Shorts" not in title:
        title = f"{title} #Shorts"

    # Build description with hashtags at the end
    description = seo_result.description
    if seo_result.hashtags:
        description += "\n\n" + " ".join(seo_result.hashtags)

    # Sanitize tags — YouTube is VERY strict about these
    import re as _re
    raw_tags = seo_result.tags if seo_result.tags else []
    tags = []
    total_tag_chars = 0
    for t in raw_tags:
        t = str(t).strip()
        # Strip to ASCII only
        t = t.encode("ascii", errors="ignore").decode("ascii").strip()
        # Remove # and quotes
        t = t.replace("#", "").replace("'", "").replace('"', "")
        # Only allow letters, numbers, spaces, hyphens
        t = _re.sub(r"[^a-zA-Z0-9 \-]", "", t).strip()
        # Skip empty or too short
        if len(t) < 2 or len(t) > 30:
            continue
        # YouTube total tag limit ~500 chars
        if total_tag_chars + len(t) > 400:
            break
        tags.append(t)
        total_tag_chars += len(t)

    logger.debug(f"Sanitized tags: {len(tags)} tags, {total_tag_chars} chars")

    category_id = CATEGORIES.get(category, "25")

    # Detect language from SEO result
    default_lang = "ur"
    if hasattr(seo_result, "language"):
        default_lang = seo_result.language
    elif hasattr(seo_result, "title") and not any(
        c in (seo_result.title or "") for c in "اآبپتٹثجچ"
    ):
        default_lang = "en"

    body = {
        "snippet": {
            "title": title[:100],  # YouTube max 100 chars
            "description": description[:5000],  # YouTube max 5000 chars
            "tags": tags,
            "categoryId": category_id,
            "defaultLanguage": default_lang,
            "defaultAudioLanguage": default_lang,
        },
        "status": {
            "privacyStatus": "private" if publish_at else privacy,
            "selfDeclaredMadeForKids": made_for_kids,
            "madeForKids": made_for_kids,
        },
    }

    media = MediaFileUpload(
        str(video_path),
        mimetype="video/mp4",
        resumable=True,
        chunksize=10 * 1024 * 1024,  # 10 MB chunks
    )

    logger.info(f"Uploading to YouTube: {title[:50]}... ({video_path.stat().st_size // (1024*1024)} MB)")

    try:
        request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                progress = int(status.progress() * 100)
                logger.debug(f"Upload progress: {progress}%")

        video_id = response["id"]
        logger.info(f"Upload complete! Video ID: {video_id}")
        logger.info(f"URL: https://www.youtube.com/watch?v={video_id}")

        # Schedule premiere if publish_at is set
        if publish_at:
            try:
                youtube.videos().update(
                    part="status",
                    body={
                        "id": video_id,
                        "status": {
                            "privacyStatus": "private",
                            "publishAt": publish_at,
                            "selfDeclaredMadeForKids": made_for_kids,
                            "madeForKids": made_for_kids,
                        },
                    },
                ).execute()
                logger.info(f"Scheduled premiere at: {publish_at}")
            except Exception as e:
                logger.warning(f"Failed to schedule premiere: {e} — video is private, publish manually")

        # Set thumbnail if provided
        if thumbnail_path and thumbnail_path.exists():
            _set_thumbnail(youtube, video_id, thumbnail_path)

        return video_id

    except Exception as e:
        error_msg = str(e)
        if "quotaExceeded" in error_msg:
            logger.error("YouTube API quota exceeded — will retry tomorrow")
        elif "forbidden" in error_msg.lower():
            logger.error(f"YouTube upload forbidden — check OAuth scopes: {e}")
        else:
            logger.error(f"YouTube upload failed: {e}")
        return None


def _set_thumbnail(youtube, video_id: str, thumbnail_path: Path):
    """Set a custom thumbnail for an uploaded video."""
    from googleapiclient.http import MediaFileUpload

    try:
        media = MediaFileUpload(str(thumbnail_path), mimetype="image/jpeg")
        youtube.thumbnails().set(videoId=video_id, media_body=media).execute()
        logger.info(f"Thumbnail set for video {video_id}")
    except Exception as e:
        logger.warning(f"Failed to set thumbnail: {e}")


def ensure_playlist(playlist_name: str, channel_id: str | None = None) -> Optional[str]:
    """
    Find or create a YouTube playlist by name.
    Returns the playlist ID.
    """
    youtube = _get_authenticated_service()

    try:
        # Search existing playlists
        playlists = youtube.playlists().list(
            part="snippet", mine=True, maxResults=50
        ).execute()

        for pl in playlists.get("items", []):
            if pl["snippet"]["title"].lower() == playlist_name.lower():
                return pl["id"]

        # Create new playlist
        body = {
            "snippet": {
                "title": playlist_name,
                "description": f"UpperCut — {playlist_name}",
            },
            "status": {"privacyStatus": "public"},
        }
        response = youtube.playlists().insert(part="snippet,status", body=body).execute()
        playlist_id = response["id"]
        logger.info(f"Created playlist: {playlist_name} ({playlist_id})")
        return playlist_id

    except Exception as e:
        logger.warning(f"Playlist management failed: {e}")
        return None


def add_to_playlist(video_id: str, playlist_id: str):
    """Add a video to a playlist."""
    youtube = _get_authenticated_service()

    try:
        youtube.playlistItems().insert(
            part="snippet",
            body={
                "snippet": {
                    "playlistId": playlist_id,
                    "resourceId": {"kind": "youtube#video", "videoId": video_id},
                }
            },
        ).execute()
        logger.info(f"Added video {video_id} to playlist {playlist_id}")
    except Exception as e:
        logger.warning(f"Failed to add to playlist: {e}")
