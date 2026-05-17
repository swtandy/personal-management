"""
github_client.py
Base GitHub API client with auth, pagination, retry, and error handling.
All other tools import from here.
"""

import os
import sys
import time
import random
import requests
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the project root (one level up from tools/)
_root = Path(__file__).parent.parent
load_dotenv(_root / ".env")

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
GITHUB_USERNAME = os.environ.get("GITHUB_USERNAME", "swtandy").strip()
BASE_URL = "https://api.github.com"

# Statuses worth retrying — transient server/rate-limit errors only.
# 4xx client errors (except 429) are not retried; they won't change on retry.
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
MAX_RETRIES = 3

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


def _request_with_retry(method, url, **kwargs):
    """
    Call method(url, **kwargs) with up to MAX_RETRIES retries on transient errors.

    Backoff: exponential (2^attempt seconds) + uniform jitter (0–1s).
    For 429 responses, the Retry-After header is used if present.
    Non-retryable errors (4xx except 429) are returned immediately so _check
    can handle them.
    """
    for attempt in range(MAX_RETRIES + 1):
        r = method(url, headers=_headers(), **kwargs)

        # Success or non-retryable error — return immediately
        if r.status_code < 400 or r.status_code not in RETRYABLE_STATUSES:
            return r

        # Retryable error but retries exhausted — return and let _check handle it
        if attempt == MAX_RETRIES:
            break

        if r.status_code == 429 and "Retry-After" in r.headers:
            wait = float(r.headers["Retry-After"])
        else:
            wait = 2 ** attempt + random.uniform(0, 1)

        print(
            f"  [{r.status_code}] retry {attempt + 1}/{MAX_RETRIES} in {wait:.1f}s…",
            file=sys.stderr,
        )
        time.sleep(wait)

    return r


def get(path, params=None):
    """Single GET — path is relative to BASE_URL or a full URL."""
    url = path if path.startswith("http") else f"{BASE_URL}{path}"
    r = _request_with_retry(requests.get, url, params=params or {})
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
        r = _request_with_retry(requests.get, url, params=p)
        _check(r, f"GET {path} page {page}")
        batch = r.json()
        if not batch:
            break
        items.extend(batch)
        if "next" not in r.headers.get("Link", ""):
            break
        page += 1
    return items


def post(path, payload):
    """POST JSON payload."""
    url = path if path.startswith("http") else f"{BASE_URL}{path}"
    r = _request_with_retry(requests.post, url, json=payload)
    _check(r, f"POST {path}")
    return r.json()


def patch(path, payload):
    """PATCH JSON payload."""
    url = path if path.startswith("http") else f"{BASE_URL}{path}"
    r = _request_with_retry(requests.patch, url, json=payload)
    _check(r, f"PATCH {path}")
    return r.json()


def delete(path, payload=None):
    """DELETE with optional JSON payload."""
    url = path if path.startswith("http") else f"{BASE_URL}{path}"
    r = _request_with_retry(requests.delete, url, json=payload or {})
    _check(r, f"DELETE {path}")
    return r.json() if r.content else {}


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
