#!/usr/bin/env python3
"""
Pinterest Pro Downloader — Firefox Add-ons (AMO) Publisher.

Uses Mozilla's AMO API v5 with JWT authentication.

Setup (one-time):
    1. Create credentials at https://addons.mozilla.org/developers/addon/api/key
    2. Save JWT issuer + secret to env vars:
         export AMO_JWT_ISSUER="..."
         export AMO_JWT_SECRET="..."

Usage:
    # Upload new version (auto-detect extension ID from existing listing)
    AMO_JWT_ISSUER=... AMO_JWT_SECRET=... \\
        python3 scripts/publish_firefox.py \\
            --xpi dist/pinterest-pro-downloader-firefox-2.0.0.xpi \\
            --addon-id pinterest-pro-downloader@example.com

    # Or upload as a new addon (first submission):
    AMO_JWT_ISSUER=... AMO_JWT_SECRET=... \\
        python3 scripts/publish_firefox.py \\
            --xpi dist/pinterest-pro-downloader-firefox-2.0.0.xpi \\
            --new \\
            --name "Pinterest Pro Downloader" \\
            --summary "Download high-res Pinterest images"
"""

import argparse
import base64
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# Mozilla AMO API v5
AMO_API_BASE = "https://addons.mozilla.org/api/v5"


def make_jwt(issuer: str, secret: str) -> str:
    """Build a minimal HS256 JWT manually (avoids extra dependency)."""
    import hmac

    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload = {
        "iss": issuer,
        "iat": now,
        "exp": now + 300,  # 5 min
        "jti": hashlib.sha256(f"{issuer}-{now}".encode()).hexdigest()[:16],
    }

    def b64url(d: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(d, separators=(",", ":")).encode()).rstrip(b"=").decode()

    h = b64url(header)
    p = b64url(payload)
    signing_input = f"{h}.{p}".encode()
    sig = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    s = base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
    return f"{h}.{p}.{s}"


def api_request(
    method: str, path: str, *, token: str, data: bytes | None = None, content_type: str = "application/json"
) -> dict:
    url = AMO_API_BASE + path
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"JWT {token}")
    if data is not None:
        req.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        print(f"HTTP {e.code} {e.reason}: {err_body}", file=sys.stderr)
        raise


def upload_new_version(xpi: Path, addon_id: str, token: str) -> dict:
    """Upload a new version to an existing AMO listing."""
    print(f"==> Uploading {xpi.name} to AMO addon {addon_id!r}...")
    data = xpi.read_bytes()
    path = f"/addons/addon/{addon_id}/versions/"
    result = api_request(
        "POST",
        path,
        token=token,
        data=data,
        content_type="application/x-xpinstall",
    )
    print(f"    ✓ Version uploaded: id={result.get('id')} version={result.get('version')}")
    return result


def create_new_addon(xpi: Path, name: str, summary: str, token: str) -> dict:
    """First submission — create addon + upload initial version."""
    print(f"==> Creating new addon '{name}' on AMO...")
    # Step 1: Upload XPI as an upload
    data = xpi.read_bytes()
    upload_result = api_request(
        "POST",
        "/addons/upload/",
        token=token,
        data=data,
        content_type="application/x-xpinstall",
    )
    upload_uuid = upload_result["uuid"]
    print(f"    ✓ Uploaded, uuid={upload_uuid}")

    # Step 2: Create addon from upload
    payload = {
        "upload": upload_uuid,
        "name": name,
        "summary": summary,
        "categories": ["photos"],
        "homepage": "https://github.com/yourusername/pinterest-pro-downloader",
    }
    result = api_request(
        "POST",
        "/addons/addon/",
        token=token,
        data=json.dumps(payload).encode(),
    )
    print(f"    ✓ Addon created: slug={result.get('slug')} guid={result.get('guid')}")
    return result


def main():
    p = argparse.ArgumentParser(description="Publish to Firefox Add-ons (AMO)")
    p.add_argument("--xpi", required=True, type=Path, help="Path to .xpi file")
    p.add_argument("--addon-id", help="Existing AMO addon slug or guid")
    p.add_argument("--new", action="store_true", help="First-time submission")
    p.add_argument("--name", help="Addon name (for new submissions)")
    p.add_argument("--summary", help="Addon summary (for new submissions)")
    args = p.parse_args()

    if not args.xpi.exists():
        sys.exit(f"ERROR: {args.xpi} does not exist")

    issuer = os.environ.get("AMO_JWT_ISSUER")
    secret = os.environ.get("AMO_JWT_SECRET")
    if not issuer or not secret:
        sys.exit("ERROR: Set AMO_JWT_ISSUER and AMO_JWT_SECRET env vars")

    token = make_jwt(issuer, secret)

    if args.new:
        if not args.name or not args.summary:
            sys.exit("ERROR: --new requires --name and --summary")
        create_new_addon(args.xpi, args.name, args.summary, token)
    else:
        if not args.addon_id:
            sys.exit("ERROR: --addon-id required (or use --new)")
        upload_new_version(args.xpi, args.addon_id, token)

    print("\n==> Done! Check https://addons.mozilla.org/developers/addons for review status.")


if __name__ == "__main__":
    main()
