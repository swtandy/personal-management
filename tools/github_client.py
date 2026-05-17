"""
github_client.py
Base GitHub API client with auth, pagination, and error handling.
All other tools import from here.
"""

import os
import sys
import json
import time
import requests
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the project root (one level up from tools/)
_root = Path(__file__).parent.parent
load_dotenv(_root / ".env")

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
GITHUB_USERNAME = os.environ.get("GITHUB_USERNAME", "swtandy").strip()
BASE_URL = "https://api.github.com"

if not GITHUB_TOKEN:
    sys.exit(
        "ERROR: GITHUB_TOKEN not set. Copy .env.example → .env and fill it in."
    )


def _headers():
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }


def _check(response, context=""):
    if response.status_code >= 400:
        try:
            msg = response.json().get("message", response.text)
        except Exception:
            msg = response.text
        print(f"GitHub API error {response.status_code} [{context}]: {msg}", file=sys.stderr)
        sys.exit(1)
    return response


def get(path, params=None):
    """Single GET — path is relative to BASE_URL or a full URL."""
    url = path if path.startswith("http") else f"{BASE_URL}{path}"
    r = requests.get(url, headers=_headers(), params=params or {})
    _check(r, f"GET {path}")
    return r.json()


def get_all(path, params=None):
    """GET with automatic pagination — returns a flat list of all items."""
    url = path if path.startswith("http") else f"{BASE_URL}{path}"
    items = []
    p = dict(params or {})
    p.setdefault("per_page", 100)
    page = 1
    while True:
        p["page"] = page
        r = requests.get(url, headers=_headers(), params=p)
        _check(r, f"GET {path} page {page}")
        batch = r.json()
        if not batch:
            break
        items.extend(batch)
        # Check Link header for next page
        if 'next' not in r.headers.get("Link", ""):
            break
        page += 1
    return items


def post(path, payload):
    """POST JSON payload."""
    url = path if path.startswith("http") else f"{BASE_URL}{path}"
    r = requests.post(url, headers=_headers(), json=payload)
    _check(r, f"POST {path}")
    return r.json()


def patch(path, payload):
    """PATCH JSON payload."""
    url = path if path.startswith("http") else f"{BASE_URL}{path}"
    r = requests.patch(url, headers=_headers(), json=payload)
    _check(r, f"PATCH {path}")
    return r.json()


def rate_limit_pause(min_remaining=100):
    """Check rate limit and sleep if we're running low."""
    info = get("/rate_limit")
    remaining = info["rate"]["remaining"]
    reset_at = info["rate"]["reset"]
    if remaining < min_remaining:
        wait = max(0, reset_at - time.time()) + 5
        print(f"Rate limit low ({remaining} left). Sleeping {wait:.0f}s …")
        time.sleep(wait)
    return remaining
