"""
Tests for issue_tree.py — build_issue_tree and format_tree.

Mocks github_client.get_all so no network or credentials are needed.
The mock is keyed on URL path so each API call gets the right fixture data.
"""

import pytest
from unittest.mock import patch

from conftest import make_issue


def make_get_all(issues_by_number, sub_issues_map):
    """
    Return a get_all side_effect function.

    issues_by_number: list of issue dicts returned by the /issues endpoint.
    sub_issues_map: dict mapping issue number → list of sub-issue dicts.
    """
    def _get_all(path, params=None):
        if path.endswith("/issues"):
            return issues_by_number
        for number, subs in sub_issues_map.items():
            if path.endswith(f"/issues/{number}/sub_issues"):
                return subs
        return []
    return _get_all


# ---------------------------------------------------------------------------
# build_issue_tree — structure
# ---------------------------------------------------------------------------

class TestBuildIssueTree:
    def test_no_issues(self):
        with patch("issue_tree.get_all", side_effect=make_get_all([], {})):
            from issue_tree import build_issue_tree
            data = build_issue_tree("owner/repo")
        assert data["total"] == 0
        assert data["roots"] == []
        assert data["tree"] == []

    def test_flat_list_all_roots(self):
        issues = [make_issue(1, "A"), make_issue(2, "B"), make_issue(3, "C")]
        sub_map = {1: [], 2: [], 3: []}
        with patch("issue_tree.get_all", side_effect=make_get_all(issues, sub_map)):
            from issue_tree import build_issue_tree
            data = build_issue_tree("owner/repo")
        assert data["total"] == 3
        assert data["roots"] == [1, 2, 3]
        assert all(n["children"] == [] for n in data["tree"])

    def test_simple_parent_child(self):
        issues = [make_issue(1, "Parent"), make_issue(2, "Child")]
        sub_map = {1: [make_issue(2, "Child")], 2: []}
        with patch("issue_tree.get_all", side_effect=make_get_all(issues, sub_map)):
            from issue_tree import build_issue_tree
            data = build_issue_tree("owner/repo")
        assert data["roots"] == [1]
        assert data["issues"][2]["parent"] == 1
        assert data["issues"][1]["children"] == [2]
        assert len(data["tree"]) == 1
        assert data["tree"][0]["children"][0]["number"] == 2

    def test_deep_chain(self):
        # 1 → 2 → 3
        issues = [make_issue(1, "A"), make_issue(2, "B"), make_issue(3, "C")]
        sub_map = {1: [make_issue(2, "B")], 2: [make_issue(3, "C")], 3: []}
        with patch("issue_tree.get_all", side_effect=make_get_all(issues, sub_map)):
            from issue_tree import build_issue_tree
            data = build_issue_tree("owner/repo")
        assert data["roots"] == [1]
        level2 = data["tree"][0]["children"][0]
        level3 = level2["children"][0]
        assert level2["number"] == 2
        assert level3["number"] == 3
        assert level3["children"] == []

    def test_multiple_children(self):
        # 1 → [2, 3, 4]
        issues = [make_issue(i, str(i)) for i in range(1, 5)]
        sub_map = {
            1: [make_issue(2, "B"), make_issue(3, "C"), make_issue(4, "D")],
            2: [], 3: [], 4: [],
        }
        with patch("issue_tree.get_all", side_effect=make_get_all(issues, sub_map)):
            from issue_tree import build_issue_tree
            data = build_issue_tree("owner/repo")
        assert data["roots"] == [1]
        children = [c["number"] for c in data["tree"][0]["children"]]
        assert children == [2, 3, 4]

    def test_mixed_tree(self):
        # 1 → [2, 4],  2 → [3]
        issues = [make_issue(i, str(i)) for i in range(1, 5)]
        sub_map = {
            1: [make_issue(2, "B"), make_issue(4, "D")],
            2: [make_issue(3, "C")],
            3: [],
            4: [],
        }
        with patch("issue_tree.get_all", side_effect=make_get_all(issues, sub_map)):
            from issue_tree import build_issue_tree
            data = build_issue_tree("owner/repo")
        assert data["roots"] == [1]
        assert data["issues"][3]["parent"] == 2
        assert data["issues"][4]["parent"] == 1

    def test_multiple_root_trees(self):
        # Two independent trees: 1→2 and 3→4
        issues = [make_issue(i, str(i)) for i in range(1, 5)]
        sub_map = {
            1: [make_issue(2, "B")], 2: [],
            3: [make_issue(4, "D")], 4: [],
        }
        with patch("issue_tree.get_all", side_effect=make_get_all(issues, sub_map)):
            from issue_tree import build_issue_tree
            data = build_issue_tree("owner/repo")
        assert data["roots"] == [1, 3]
        assert len(data["tree"]) == 2


# ---------------------------------------------------------------------------
# build_issue_tree — stub handling
# ---------------------------------------------------------------------------

class TestStubHandling:
    def test_sub_issue_not_in_main_fetch_becomes_stub(self):
        # Issue 1 exists in fetch; its sub-issue 99 does not (e.g. different state)
        stub = make_issue(99, "Closed child", state="closed")
        issues = [make_issue(1, "Parent")]
        sub_map = {1: [stub]}
        with patch("issue_tree.get_all", side_effect=make_get_all(issues, sub_map)):
            from issue_tree import build_issue_tree
            data = build_issue_tree("owner/repo")
        assert 99 in data["issues"]
        assert data["issues"][99]["stub"] is True
        assert data["issues"][99]["parent"] == 1
        assert data["issues"][1]["children"] == [99]
        # Stub is NOT a root
        assert 99 not in data["roots"]

    def test_stub_appears_nested_in_tree(self):
        stub = make_issue(99, "Stub child")
        issues = [make_issue(1, "Parent")]
        sub_map = {1: [stub]}
        with patch("issue_tree.get_all", side_effect=make_get_all(issues, sub_map)):
            from issue_tree import build_issue_tree
            data = build_issue_tree("owner/repo")
        tree_children = data["tree"][0]["children"]
        assert len(tree_children) == 1
        assert tree_children[0]["number"] == 99


# ---------------------------------------------------------------------------
# build_issue_tree — issue metadata
# ---------------------------------------------------------------------------

class TestIssueMetadata:
    def test_labels_extracted(self):
        issues = [make_issue(1, "Labelled", labels=["bug", "urgent"])]
        sub_map = {1: []}
        with patch("issue_tree.get_all", side_effect=make_get_all(issues, sub_map)):
            from issue_tree import build_issue_tree
            data = build_issue_tree("owner/repo")
        assert data["issues"][1]["labels"] == ["bug", "urgent"]

    def test_closed_issue_state_preserved(self):
        issues = [make_issue(1, "Done", state="closed")]
        sub_map = {1: []}
        with patch("issue_tree.get_all", side_effect=make_get_all(issues, sub_map)):
            from issue_tree import build_issue_tree
            data = build_issue_tree("owner/repo")
        assert data["issues"][1]["state"] == "closed"

    def test_url_preserved(self):
        issues = [make_issue(1, "Test")]
        sub_map = {1: []}
        with patch("issue_tree.get_all", side_effect=make_get_all(issues, sub_map)):
            from issue_tree import build_issue_tree
            data = build_issue_tree("owner/repo")
        assert data["issues"][1]["url"] == "https://github.com/owner/repo/issues/1"

    def test_children_sorted_ascending(self):
        # Sub-issues returned out of order — children list should be sorted
        issues = [make_issue(i, str(i)) for i in [1, 3, 2]]
        sub_map = {1: [make_issue(3, "C"), make_issue(2, "B")], 2: [], 3: []}
        with patch("issue_tree.get_all", side_effect=make_get_all(issues, sub_map)):
            from issue_tree import build_issue_tree
            data = build_issue_tree("owner/repo")
        assert data["issues"][1]["children"] == [2, 3]


# ---------------------------------------------------------------------------
# format_tree
# ---------------------------------------------------------------------------

class TestFormatTree:
    def _build(self, issues, sub_map):
        from issue_tree import build_issue_tree
        with patch("issue_tree.get_all", side_effect=make_get_all(issues, sub_map)):
            return build_issue_tree("owner/repo")

    def test_flat_no_indentation(self):
        from issue_tree import format_tree
        data = self._build(
            [make_issue(1, "Alpha"), make_issue(2, "Beta")],
            {1: [], 2: []},
        )
        output = format_tree(data)
        lines = output.strip().splitlines()
        assert lines[0].startswith("#1 Alpha")
        assert lines[1].startswith("#2 Beta")
        assert not lines[0].startswith("  ")

    def test_child_indented(self):
        from issue_tree import format_tree
        data = self._build(
            [make_issue(1, "Parent"), make_issue(2, "Child")],
            {1: [make_issue(2, "Child")], 2: []},
        )
        output = format_tree(data)
        lines = output.strip().splitlines()
        assert lines[0].startswith("#1")
        assert lines[1].startswith("  #2")

    def test_deep_indentation(self):
        from issue_tree import format_tree
        data = self._build(
            [make_issue(1, "A"), make_issue(2, "B"), make_issue(3, "C")],
            {1: [make_issue(2, "B")], 2: [make_issue(3, "C")], 3: []},
        )
        output = format_tree(data)
        lines = output.strip().splitlines()
        assert lines[2].startswith("    #3")  # 4 spaces = depth 2

    def test_closed_issue_tagged(self):
        from issue_tree import format_tree
        data = self._build(
            [make_issue(1, "Done", state="closed")],
            {1: []},
        )
        output = format_tree(data)
        assert "[closed]" in output

    def test_open_issue_not_tagged(self):
        from issue_tree import format_tree
        data = self._build([make_issue(1, "Open")], {1: []})
        output = format_tree(data)
        assert "[closed]" not in output

    def test_labels_shown(self):
        from issue_tree import format_tree
        data = self._build([make_issue(1, "Labelled", labels=["epic", "deck"])], {1: []})
        output = format_tree(data)
        assert "epic" in output
        assert "deck" in output
