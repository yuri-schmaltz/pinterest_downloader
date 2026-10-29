#!/usr/bin/env python3
"""
Pinterest Pro Downloader — Chrome Web Store Publisher.

Uses the Chrome Web Store Publish API (v1.1) with OAuth2 authentication.

Setup (one-time):
    1. Pay the $5 developer fee at https://chrome.google.com/webstore/devconsole/
    2. Create OAuth2 credentials at https://console.cloud.google.com/apis/credentials
       - Application type: Desktop app
       - Download the client JSON
    3. Get a refresh token via OAuth2 playground:
       https://developers.google.com/oauthplayground/
       (scope: https://www.googleapis.com/auth/chromewebstore)
    4. Set env vars:
         export CWS_CLIENT_ID="..."
         export CWS_CLIENT_SECRET="..."
         export CWS_REFRESH_TOKEN="..."

Usage:
    # Upload to existing item (auto-targets production/trusted-tester channels)
    CWS_CLIENT_ID=... CWS_CLIENT_SECRET=... CWS_REFRESH_TOKEN=... \\
        python3 scripts/publish_chrome.py \\
            --zip dist/pinterest-pro-downloader-chrome-2.0.0.zip \\
            --item-id aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa

    # First submission (no existing item-id): use Chrome Web Store dashboard instead
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# Chrome Web Store API
CWS_UPLOAD_URL = "https://www.googleapis.com/upload/chromewebstore/v1.1/items"
CWS_PUBLISH_URL = "https://www.googleapis.com/chromewebstore/v1.1/items/{action}"


def get_access_token(client_id: str, client_secret: str, refresh_token: str) -> str:
    """Exchange a refresh token for a short-lived access token."""
    url = "https://oauth2.googleapis.com/token"
    data = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
    ).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())["access_token"]
    except urllib.error.HTTPError as e:
        sys.exit(f"OAuth error {e.code}: {e.read().decode()}")


def upload_zip(zip_path: Path, access_token: str) -> dict:
    """Upload a new package to an existing Chrome Web Store item."""
    print(f"==> Uploading {zip_path.name} to Chrome Web Store...")
    url = f"{CWS_UPLOAD_URL}/appId?appId={urllib.parse.quote_plus(os.environ['CWS_ITEM_ID'])}"
    req = urllib.request.Request(url, data=zip_path.read_bytes(), method="POST")
    req.add_header("Authorization", f"Bearer {access_token}")
    req.add_header("Content-Type", "application/zip")
    req.add_header("x-goog-api-version", "1.1")
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"Upload error {e.code}: {e.read().decode()}")

    if "uploadState" not in result:
        sys.exit(f"Upload failed: {result}")
    print(f"    ✓ Upload state: {result.get('uploadState')}")
    if result.get("uploadState") != "SUCCESS":
        if "itemError" in result:
            for err in result["itemError"]:
                print(f"      ERROR: {err}")
        sys.exit(1)
    return result


def publish_to_channel(action: str, access_token: str) -> dict:
    """Publish the uploaded package to a channel (publish or trustedTester)."""
    url = CWS_PUBLISH_URL.format(action=action)
    req = urllib.request.Request(url, method="POST")
    req.add_header("Authorization", f"Bearer {access_token}")
    req.add_header("x-goog-api-version", "1.1")
    req.add_header("Content-Length", "0")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"Publish error {e.code}: {e.read().decode()}")
    print(f"    ✓ {result.get('status', [])}")
    return result


def main():
    p = argparse.ArgumentParser(description="Publish to Chrome Web Store")
    p.add_argument("--zip", required=True, type=Path, help="Path to .zip file")
    p.add_argument("--item-id", required=True, help="Existing CWS item ID (get from developer dashboard)")
    p.add_argument(
        "--channel",
        choices=["publish", "trustedTester"],
        default="trustedTester",
        help="Target channel. trustedTester recommended first.",
    )
    args = p.parse_args()

    if not args.zip.exists():
        sys.exit(f"ERROR: {args.zip} does not exist")

    client_id = os.environ.get("CWS_CLIENT_ID")
    client_secret = os.environ.get("CWS_CLIENT_SECRET")
    refresh_token = os.environ.get("CWS_REFRESH_TOKEN")
    if not all([client_id, client_secret, refresh_token]):
        sys.exit("ERROR: Set CWS_CLIENT_ID, CWS_CLIENT_SECRET, CWS_REFRESH_TOKEN env vars")

    os.environ["CWS_ITEM_ID"] = args.item_id

    print("==> Exchanging refresh token for access token...")
    access_token = get_access_token(client_id, client_secret, refresh_token)
    print("    ✓ Got access token")

    upload_zip(args.zip, access_token)
    publish_to_channel(args.channel, access_token)

    print("\n==> Done! Check https://chrome.google.com/webstore/devconsole/ for review status.")


if __name__ == "__main__":
    main()
