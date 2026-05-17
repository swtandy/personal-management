"""
Tests for the MCP tool functions in mcp_server.py.

Mocks at the github_client function level — tests verify correct arguments
are passed down and that output is formatted as co-work would receive it.
"""

import json
import pytest
from unittest.mock import patch, MagicMock, call

from conftest import make_issue


# ---------------------------------------------------------------------------
# list_issues
# ---------------------------------------------------------------------------

class TestListIssues:
    def test_empty_repo(self):
        with patch("mcp_server.get_all", return_value=[]):
            from mcp_server import list_issues
            result = list_issues("owner/repo", state="open")
        assert "No open issues" in result

    def test_formats_number_state_title(self):
        with patch("mcp_server.get_all", return_value=[make_issue(7, "Fix the thing")]):
            from mcp_server import list_issues
            result = list_issues("owner/repo")
        assert "#7" in result
        assert "Fix the thing" in result
        assert "[open]" in result

    def test_shows_labels(self):
        with patch("mcp_server.get_all", return_value=[make_issue(1, "T", labels=["bug", "urgent"])]):
            from mcp_server import list_issues
            result = list_issues("owner/repo")
        assert "bug" in result
        assert "urgent" in result

    def test_pull_requests_excluded(self):
        pr = make_issue(1, "PR title")
        pr["pull_request"] = {"url": "https://..."}
        with patch("mcp_server.get_all", return_value=[pr]):
            from mcp_server import list_issues
            result = list_issues("owner/repo")
        assert "No open issues" in result

    def test_passes_state_param(self):
        with patch("mcp_server.get_all", return_value=[]) as mock_get_all:
            from mcp_server import list_issues
            list_issues("owner/repo", state="closed")
        call_params = mock_get_all.call_args[1]["params"]
        assert call_params["state"] == "closed"


# ---------------------------------------------------------------------------
# create_issue
# ---------------------------------------------------------------------------

class TestCreateIssue:
    def test_returns_number_and_url(self):
        created = {**make_issue(42, "New issue"), "html_url": "https://github.com/owner/repo/issues/42"}
        with patch("mcp_server.post", return_value=created):
            from mcp_server import create_issue
            result = create_issue("owner/repo", "New issue")
        assert "#42" in result
        assert "https://github.com/owner/repo/issues/42" in result

    def test_passes_labels(self):
        created = make_issue(1, "T")
        with patch("mcp_server.post", return_value=created) as mock_post:
            from mcp_server import create_issue
            create_issue("owner/repo", "T", labels=["bug", "deck"])
        payload = mock_post.call_args[0][1]
        assert payload["labels"] == ["bug", "deck"]

    def test_passes_body(self):
        created = make_issue(1, "T")
        with patch("mcp_server.post", return_value=created) as mock_post:
            from mcp_server import create_issue
            create_issue("owner/repo", "T", body="Some detail")
        payload = mock_post.call_args[0][1]
        assert payload["body"] == "Some detail"


# ---------------------------------------------------------------------------
# update_issue
# ---------------------------------------------------------------------------

class TestUpdateIssue:
    def test_no_fields_returns_early(self):
        with patch("mcp_server.patch") as mock_patch:
            from mcp_server import update_issue
            result = update_issue("owner/repo", 1)
        mock_patch.assert_not_called()
        assert "Nothing to update" in result

    def test_only_provided_fields_sent(self):
        updated = {**make_issue(1, "New title"), "state": "open"}
        with patch("mcp_server.patch", return_value=updated) as mock_patch:
            from mcp_server import update_issue
            update_issue("owner/repo", 1, title="New title")
        payload = mock_patch.call_args[0][1]
        assert payload == {"title": "New title"}

    def test_close_via_state(self):
        updated = {**make_issue(1, "T"), "state": "closed"}
        with patch("mcp_server.patch", return_value=updated) as mock_patch:
            from mcp_server import update_issue
            update_issue("owner/repo", 1, state="closed")
        payload = mock_patch.call_args[0][1]
        assert payload["state"] == "closed"


# ---------------------------------------------------------------------------
# add_sub_issue / remove_sub_issue
# ---------------------------------------------------------------------------

class TestSubIssueTools:
    def test_add_sub_issue_looks_up_child_id(self):
        child = make_issue(5, "Child")  # id = 5000
        with patch("mcp_server.get", return_value=child) as mock_get:
            with patch("mcp_server.post", return_value=make_issue(1, "Parent")) as mock_post:
                from mcp_server import add_sub_issue
                add_sub_issue("owner/repo", 1, 5)
        # Verifies the GET was for the child issue
        mock_get.assert_called_once_with("/repos/owner/repo/issues/5")
        # Verifies the POST used the internal id, not the number
        payload = mock_post.call_args[0][1]
        assert payload["sub_issue_id"] == child["id"]

    def test_remove_sub_issue_looks_up_child_id(self):
        child = make_issue(5, "Child")
        with patch("mcp_server.get", return_value=child):
            with patch("mcp_server.delete") as mock_delete:
                from mcp_server import remove_sub_issue
                remove_sub_issue("owner/repo", 1, 5)
        payload = mock_delete.call_args[0][1]
        assert payload["sub_issue_id"] == child["id"]


# ---------------------------------------------------------------------------
# get_issue_tree / print_issue_tree
# ---------------------------------------------------------------------------

class TestIssueTreeTools:
    def _mock_tree(self, issues, sub_map):
        from conftest import make_issue as mi
        def _get_all(path, params=None):
            if path.endswith("/issues"):
                return issues
            for num, subs in sub_map.items():
                if path.endswith(f"/issues/{num}/sub_issues"):
                    return subs
            return []
        return _get_all

    def test_get_issue_tree_returns_valid_json(self):
        issues = [make_issue(1, "Root"), make_issue(2, "Child")]
        sub_map = {1: [make_issue(2, "Child")], 2: []}
        with patch("issue_tree.get_all", side_effect=self._mock_tree(issues, sub_map)):
            from mcp_server import get_issue_tree
            result = get_issue_tree("owner/repo")
        data = json.loads(result)
        assert "tree" in data
        assert "roots" in data
        assert data["roots"] == [1]

    def test_get_issue_tree_tree_is_nested(self):
        issues = [make_issue(1, "Root"), make_issue(2, "Child")]
        sub_map = {1: [make_issue(2, "Child")], 2: []}
        with patch("issue_tree.get_all", side_effect=self._mock_tree(issues, sub_map)):
            from mcp_server import get_issue_tree
            result = get_issue_tree("owner/repo")
        data = json.loads(result)
        assert data["tree"][0]["children"][0]["number"] == 2

    def test_print_issue_tree_ascii_structure(self):
        issues = [make_issue(1, "Root"), make_issue(2, "Child")]
        sub_map = {1: [make_issue(2, "Child")], 2: []}
        with patch("issue_tree.get_all", side_effect=self._mock_tree(issues, sub_map)):
            from mcp_server import print_issue_tree
            result = print_issue_tree("owner/repo")
        lines = result.strip().splitlines()
        # First content line is the root
        root_line = next(l for l in lines if "#1" in l)
        child_line = next(l for l in lines if "#2" in l)
        assert lines.index(root_line) < lines.index(child_line)
        assert child_line.startswith("  ")  # indented


# ---------------------------------------------------------------------------
# migrate_issues
# ---------------------------------------------------------------------------

class TestMigrateIssues:
    def test_dry_run_does_not_post(self):
        issues = [make_issue(1, "T")]
        with patch("mcp_server.get_all", return_value=issues):
            with patch("mcp_server.post") as mock_post:
                from mcp_server import migrate_issues
                result = migrate_issues("owner/src", "owner/dest", dry_run=True)
        mock_post.assert_not_called()
        assert "DRY RUN" in result

    def test_dry_run_lists_issues(self):
        issues = [make_issue(1, "Alpha"), make_issue(2, "Beta")]
        with patch("mcp_server.get_all", return_value=issues):
            from mcp_server import migrate_issues
            result = migrate_issues("owner/src", "owner/dest", dry_run=True)
        assert "Alpha" in result
        assert "Beta" in result

    def test_empty_source_returns_early(self):
        with patch("mcp_server.get_all", return_value=[]):
            from mcp_server import migrate_issues
            result = migrate_issues("owner/src", "owner/dest", dry_run=False)
        assert "No" in result
