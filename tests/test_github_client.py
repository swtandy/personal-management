"""
Tests for github_client.py.

Mocks requests.* directly — no network, no credentials needed.
"""

import sys
import pytest
from unittest.mock import patch, MagicMock, call

from conftest import make_response


# ---------------------------------------------------------------------------
# get_all — pagination
# ---------------------------------------------------------------------------

class TestGetAll:
    def test_single_page_no_link_header(self):
        batch = [{"id": 1}, {"id": 2}]
        with patch("github_client.requests.get", return_value=make_response(batch)):
            from github_client import get_all
            result = get_all("/repos/owner/repo/issues")
        assert result == batch

    def test_multi_page_follows_next_link(self):
        page1 = [{"id": 1}]
        page2 = [{"id": 2}]
        responses = [
            make_response(page1, link_next="https://api.github.com/repos/owner/repo/issues?page=2"),
            make_response(page2),
        ]
        with patch("github_client.requests.get", side_effect=responses):
            from github_client import get_all
            result = get_all("/repos/owner/repo/issues")
        assert result == [{"id": 1}, {"id": 2}]

    def test_stops_on_empty_batch(self):
        responses = [
            make_response([{"id": 1}], link_next="https://api.github.com/next"),
            make_response([]),
        ]
        with patch("github_client.requests.get", side_effect=responses):
            from github_client import get_all
            result = get_all("/some/path")
        assert result == [{"id": 1}]

    def test_three_pages(self):
        pages = [[{"id": i}] for i in range(3)]
        responses = [
            make_response(pages[0], link_next="https://api.github.com/page2"),
            make_response(pages[1], link_next="https://api.github.com/page3"),
            make_response(pages[2]),
        ]
        with patch("github_client.requests.get", side_effect=responses):
            from github_client import get_all
            result = get_all("/some/path")
        assert len(result) == 3
        assert [r["id"] for r in result] == [0, 1, 2]


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_404_exits(self):
        with patch("github_client.requests.get", return_value=make_response({"message": "Not Found"}, 404)):
            from github_client import get
            with pytest.raises(SystemExit):
                get("/repos/owner/bad-repo")

    def test_401_exits(self):
        with patch("github_client.requests.get", return_value=make_response({"message": "Bad credentials"}, 401)):
            from github_client import get
            with pytest.raises(SystemExit):
                get("/user")

    def test_500_exits_after_retries(self):
        # All attempts return 500 — should exit after exhausting retries
        with patch("github_client.requests.get", return_value=make_response({}, 500)):
            with patch("github_client.time.sleep"):
                from github_client import get
                with pytest.raises(SystemExit):
                    get("/some/path")

    def test_200_does_not_exit(self):
        with patch("github_client.requests.get", return_value=make_response({"ok": True})):
            from github_client import get
            result = get("/some/path")
        assert result == {"ok": True}


# ---------------------------------------------------------------------------
# post / patch / delete
# ---------------------------------------------------------------------------

class TestMutations:
    def test_post_sends_json(self):
        with patch("github_client.requests.post", return_value=make_response({"number": 1})) as mock_post:
            from github_client import post
            post("/repos/owner/repo/issues", {"title": "Test"})
        _, kwargs = mock_post.call_args
        assert kwargs["json"] == {"title": "Test"}

    def test_patch_sends_json(self):
        with patch("github_client.requests.patch", return_value=make_response({"number": 1})) as mock_patch:
            from github_client import patch as gh_patch
            gh_patch("/repos/owner/repo/issues/1", {"state": "closed"})
        _, kwargs = mock_patch.call_args
        assert kwargs["json"] == {"state": "closed"}

    def test_delete_with_empty_body(self):
        empty_response = make_response(None, 204)
        empty_response.content = b""
        with patch("github_client.requests.delete", return_value=empty_response):
            from github_client import delete
            result = delete("/repos/owner/repo/issues/1/sub_issue", {"sub_issue_id": 999})
        assert result == {}


# ---------------------------------------------------------------------------
# Retry behaviour
# ---------------------------------------------------------------------------

class TestRetry:
    def test_succeeds_after_one_transient_error(self):
        responses = [make_response({}, 500), make_response({"ok": True})]
        with patch("github_client.requests.get", side_effect=responses):
            with patch("github_client.time.sleep"):
                from github_client import get
                result = get("/some/path")
        assert result == {"ok": True}

    def test_succeeds_after_two_transient_errors(self):
        responses = [make_response({}, 503), make_response({}, 502), make_response({"ok": True})]
        with patch("github_client.requests.get", side_effect=responses):
            with patch("github_client.time.sleep"):
                from github_client import get
                result = get("/some/path")
        assert result == {"ok": True}

    def test_retries_exactly_max_times_then_exits(self):
        from github_client import MAX_RETRIES
        # MAX_RETRIES+1 total attempts all fail
        all_fail = [make_response({}, 500)] * (MAX_RETRIES + 1)
        with patch("github_client.requests.get", side_effect=all_fail) as mock_get:
            with patch("github_client.time.sleep"):
                from github_client import get
                with pytest.raises(SystemExit):
                    get("/some/path")
        assert mock_get.call_count == MAX_RETRIES + 1

    def test_does_not_retry_404(self):
        with patch("github_client.requests.get", return_value=make_response({"message": "Not Found"}, 404)) as mock_get:
            from github_client import get
            with pytest.raises(SystemExit):
                get("/bad/path")
        assert mock_get.call_count == 1  # no retries

    def test_does_not_retry_403(self):
        with patch("github_client.requests.get", return_value=make_response({"message": "Forbidden"}, 403)) as mock_get:
            from github_client import get
            with pytest.raises(SystemExit):
                get("/bad/path")
        assert mock_get.call_count == 1

    def test_retries_429(self):
        responses = [make_response({}, 429), make_response({"ok": True})]
        with patch("github_client.requests.get", side_effect=responses) as mock_get:
            with patch("github_client.time.sleep"):
                from github_client import get
                result = get("/some/path")
        assert mock_get.call_count == 2
        assert result == {"ok": True}

    def test_respects_retry_after_header_on_429(self):
        r429 = make_response({}, 429)
        r429.headers = {"Retry-After": "42"}
        responses = [r429, make_response({"ok": True})]
        with patch("github_client.requests.get", side_effect=responses):
            with patch("github_client.time.sleep") as mock_sleep:
                from github_client import get
                get("/some/path")
        mock_sleep.assert_called_once_with(42.0)

    def test_exponential_backoff_increases(self):
        from github_client import MAX_RETRIES
        all_fail = [make_response({}, 500)] * (MAX_RETRIES + 1)
        sleep_calls = []
        with patch("github_client.requests.get", side_effect=all_fail):
            with patch("github_client.random.uniform", return_value=0.0):
                with patch("github_client.time.sleep", side_effect=lambda t: sleep_calls.append(t)):
                    from github_client import get
                    with pytest.raises(SystemExit):
                        get("/some/path")
        # With jitter=0, waits should be 1, 2, 4 (2^0, 2^1, 2^2)
        assert sleep_calls == [1.0, 2.0, 4.0]

    def test_retry_on_post(self):
        responses = [make_response({}, 503), make_response({"number": 1})]
        with patch("github_client.requests.post", side_effect=responses) as mock_post:
            with patch("github_client.time.sleep"):
                from github_client import post
                result = post("/repos/owner/repo/issues", {"title": "T"})
        assert mock_post.call_count == 2
        assert result == {"number": 1}

    def test_retry_on_patch(self):
        responses = [make_response({}, 502), make_response({"number": 1, "state": "closed"})]
        with patch("github_client.requests.patch", side_effect=responses) as mock_patch:
            with patch("github_client.time.sleep"):
                from github_client import patch as gh_patch
                result = gh_patch("/repos/owner/repo/issues/1", {"state": "closed"})
        assert mock_patch.call_count == 2

    def test_get_all_retries_on_transient_error(self):
        responses = [make_response({}, 500), make_response([{"id": 1}])]
        with patch("github_client.requests.get", side_effect=responses) as mock_get:
            with patch("github_client.time.sleep"):
                from github_client import get_all
                result = get_all("/some/path")
        assert mock_get.call_count == 2
        assert result == [{"id": 1}]


# ---------------------------------------------------------------------------
# rate_limit_pause
# ---------------------------------------------------------------------------

class TestRateLimitPause:
    def test_no_sleep_when_plenty_remaining(self):
        rate_data = {"rate": {"remaining": 500, "reset": 9999999999}}
        with patch("github_client.requests.get", return_value=make_response(rate_data)):
            with patch("github_client.time.sleep") as mock_sleep:
                from github_client import rate_limit_pause
                rate_limit_pause(min_remaining=100)
        mock_sleep.assert_not_called()

    def test_sleeps_when_low(self):
        import time as _time
        rate_data = {"rate": {"remaining": 10, "reset": int(_time.time()) + 60}}
        with patch("github_client.requests.get", return_value=make_response(rate_data)):
            with patch("github_client.time.sleep") as mock_sleep:
                from github_client import rate_limit_pause
                rate_limit_pause(min_remaining=100)
        mock_sleep.assert_called_once()
        sleep_duration = mock_sleep.call_args[0][0]
        assert sleep_duration > 0
