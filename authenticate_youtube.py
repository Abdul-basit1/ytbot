#!/usr/bin/env python3
"""
UpperCut — YouTube OAuth Authentication (run on Mac ONLY)

This script opens a browser to authenticate with Google/YouTube.
Run this ONCE on your Mac, then deploy token.json to VPS.

Usage:
    python3 authenticate_youtube.py

After authentication, token.json is saved in the project root.
Deploy to VPS with: python3 deploy.py
"""

import sys
from pathlib import Path

# Ensure we can import config
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import BASE_DIR, YOUTUBE_CLIENT_SECRETS

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

TOKEN_PATH = BASE_DIR / "token.json"


def main():
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    secrets_path = BASE_DIR / YOUTUBE_CLIENT_SECRETS
    if not secrets_path.exists():
        print(f"ERROR: {secrets_path} not found!")
        print("Download it from Google Cloud Console → APIs & Services → Credentials")
        sys.exit(1)

    # Check if token already exists and is valid
    if TOKEN_PATH.exists():
        try:
            from google.auth.transport.requests import Request
            creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
            if creds.valid:
                print(f"Token already valid! Expires: {creds.expiry}")
                print(f"Saved at: {TOKEN_PATH}")
                return
            if creds.expired and creds.refresh_token:
                print("Token expired, refreshing...")
                creds.refresh(Request())
                TOKEN_PATH.write_text(creds.to_json())
                print(f"Token refreshed! Expires: {creds.expiry}")
                print(f"Saved at: {TOKEN_PATH}")
                return
        except Exception as e:
            print(f"Existing token invalid ({e}), re-authenticating...")

    # Run OAuth flow — opens browser
    print("Opening browser for YouTube authentication...")
    print("Login with the KiddoWorld Gmail account and click 'Allow'")
    print()

    flow = InstalledAppFlow.from_client_secrets_file(str(secrets_path), SCOPES)
    creds = flow.run_local_server(port=8090, prompt="consent")

    # Save token
    TOKEN_PATH.write_text(creds.to_json())

    print()
    print("=" * 50)
    print("  YouTube authentication successful!")
    print(f"  Token saved: {TOKEN_PATH}")
    print()
    print("  Next steps:")
    print("  1. Deploy to VPS: python3 deploy.py")
    print("  2. Token will be uploaded automatically")
    print("=" * 50)


if __name__ == "__main__":
    main()
