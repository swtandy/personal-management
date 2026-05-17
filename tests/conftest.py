"""Shared fixtures and helpers for all tests."""

import pytest


def make_issue(number, title, state="open", labels=None):
    """Minimal GitHub issue dict matching the shape returned by the API."""
    return {
        "number": number,
        "id": number * 1000,
        "title": title,
        "state": state,
        "labels": [{"name": l} for l in (labels or [])],
        "html_url": f"https://github.com/owner/repo/issues/{number}",
    }


def make_response(json_data, status_code=200, link_next=None):
    """Minimal requests.Response-like mock."""
    from unittest.mock import MagicMock
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_data
    r.content = b"..." if json_data else b""
    headers = {}
    if link_next:
        headers["Link"] = f'<{link_next}>; rel="next"'
    r.headers = headers
    return r
