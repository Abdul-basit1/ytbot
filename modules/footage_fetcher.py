"""
UpperCut — Footage Fetcher
Downloads stock video clips from Pexels (primary) and Pixabay (fallback).
Caches downloads to avoid redundant fetches.
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Dict, List, Optional

import requests
from loguru import logger

from config import FOOTAGE_DIR, PEXELS_API_KEY, PIXABAY_API_KEY


# ── Cache ────────────────────────────────────────────────────────────────────
_cache: Dict[str, Path] = {}  # keyword_hash → local file path


def _kw_hash(keyword: str) -> str:
    return hashlib.md5(keyword.lower().strip().encode()).hexdigest()[:10]


def _cached(keyword: str) -> Optional[Path]:
    """Return cached file path if we already downloaded for this keyword."""
    h = _kw_hash(keyword)
    if h in _cache and _cache[h].exists():
        return _cache[h]
    # Also check disk
    for f in FOOTAGE_DIR.glob(f"{h}_*"):
        _cache[h] = f
        return f
    return None


# ── Pexels API ───────────────────────────────────────────────────────────────
def _search_pexels_videos(keyword: str, per_page: int = 3) -> List[str]:
    """Search Pexels for video download URLs."""
    if not PEXELS_API_KEY:
        return []
    try:
        resp = requests.get(
            "https://api.pexels.com/videos/search",
            headers={"Authorization": PEXELS_API_KEY},
            params={"query": keyword, "per_page": per_page, "orientation": "landscape"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        urls = []
        for video in data.get("videos", []):
            # Pick the HD file (or best available)
            files = video.get("video_files", [])
            hd = [f for f in files if f.get("quality") == "hd" and f.get("width", 0) >= 1280]
            if hd:
                urls.append(hd[0]["link"])
            elif files:
                urls.append(files[0]["link"])
        return urls
    except Exception as e:
        logger.warning(f"Pexels search failed for '{keyword}': {e}")
        return []


def _search_pexels_images(keyword: str, per_page: int = 3) -> List[str]:
    """Fallback: search Pexels for images if no video found."""
    if not PEXELS_API_KEY:
        return []
    try:
        resp = requests.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": PEXELS_API_KEY},
            params={"query": keyword, "per_page": per_page, "orientation": "landscape"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return [p["src"]["large2x"] for p in data.get("photos", []) if "src" in p]
    except Exception as e:
        logger.warning(f"Pexels image search failed for '{keyword}': {e}")
        return []


# ── Pixabay API ──────────────────────────────────────────────────────────────
def _search_pixabay_videos(keyword: str, per_page: int = 3) -> List[str]:
    """Fallback: search Pixabay for videos."""
    if not PIXABAY_API_KEY:
        return []
    try:
        resp = requests.get(
            "https://pixabay.com/api/videos/",
            params={"key": PIXABAY_API_KEY, "q": keyword, "per_page": per_page},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        urls = []
        for hit in data.get("hits", []):
            vids = hit.get("videos", {})
            # Prefer large, fallback to medium
            for quality in ("large", "medium", "small"):
                if quality in vids and vids[quality].get("url"):
                    urls.append(vids[quality]["url"])
                    break
        return urls
    except Exception as e:
        logger.warning(f"Pixabay search failed for '{keyword}': {e}")
        return []


# ── Download ─────────────────────────────────────────────────────────────────
def _download_file(url: str, keyword: str) -> Optional[Path]:
    """Download a file and save it to the footage directory."""
    h = _kw_hash(keyword)
    ext = ".mp4" if "video" in url or url.endswith(".mp4") else ".jpg"
    filename = f"{h}_{uuid.uuid4().hex[:6]}{ext}"
    out_path = FOOTAGE_DIR / filename

    try:
        resp = requests.get(url, timeout=60, stream=True)
        resp.raise_for_status()
        with open(out_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        _cache[h] = out_path
        logger.debug(f"Downloaded: {out_path.name} ({out_path.stat().st_size // 1024} KB)")
        return out_path
    except Exception as e:
        logger.warning(f"Download failed ({url[:60]}): {e}")
        return None


# ── Main entry point ─────────────────────────────────────────────────────────
def fetch(keywords: List[str], clips_per_keyword: int = 1) -> List[Path]:
    """
    Fetch stock footage for a list of keywords.
    Tries: Pexels video → Pixabay video → Pexels image (fallback).

    Args:
        keywords: list of English search terms
        clips_per_keyword: how many clips to fetch per keyword

    Returns:
        List of local file Paths (videos and/or images).
    """
    logger.info(f"Fetching footage for {len(keywords)} keywords")
    results: List[Path] = []

    for kw in keywords:
        # Check cache first
        cached = _cached(kw)
        if cached:
            logger.debug(f"Cache hit for '{kw}': {cached.name}")
            results.append(cached)
            continue

        downloaded = False

        # Try Pexels videos
        urls = _search_pexels_videos(kw, per_page=clips_per_keyword)
        for url in urls[:clips_per_keyword]:
            path = _download_file(url, kw)
            if path:
                results.append(path)
                downloaded = True
                break

        if downloaded:
            continue

        # Try Pixabay videos
        urls = _search_pixabay_videos(kw, per_page=clips_per_keyword)
        for url in urls[:clips_per_keyword]:
            path = _download_file(url, kw)
            if path:
                results.append(path)
                downloaded = True
                break

        if downloaded:
            continue

        # Fallback to Pexels images
        urls = _search_pexels_images(kw, per_page=clips_per_keyword)
        for url in urls[:clips_per_keyword]:
            path = _download_file(url, kw)
            if path:
                results.append(path)
                break

    logger.info(f"Footage fetcher: {len(results)} files downloaded for {len(keywords)} keywords")
    return results


def cleanup_footage(file_paths: List[Path]):
    """Delete temporary footage files after video assembly."""
    for p in file_paths:
        try:
            if p.exists():
                p.unlink()
                logger.debug(f"Cleaned up: {p.name}")
        except Exception as e:
            logger.warning(f"Failed to delete {p}: {e}")
