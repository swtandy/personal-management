import os
import unittest
from unittest.mock import Mock, patch

import pytest
pytest.importorskip("tkinter", reason="tkinter/_tkinter not available in this Python install — skipping GUI tests")

os.environ.setdefault("GITHUB_TOKEN", "test-token")

from agents.project_gui import (
    INBOX_ROOT_TITLE,
    IssueKey,
    ProjectIssueGui,
    WHEN_ORDER,
    _comment_tree_text,
    _item_phase,
    _item_when,
    _list_param,
    _repo_matches,
    _root_title_for,
    _sort_key,
    _try_set_issue_parent,
    _try_update_project_field,
    apply_bulk_organize_issues,
    build_capture_issue_body,
    build_bulk_organize_plan,
    build_issue_tree,
    build_project_context,
    build_resume_summary,
    normalize_issue_ref,
)


class _MockVar:
    """Stand-in for ctk.BooleanVar / ctk.StringVar in headless tests."""
    def __init__(self, value):
        self._value = value
    def get(self):
        return self._value
    def set(self, value):
        self._value = value


def _item(number=1, title="Test", labels=None, priority="", status="Backlog",
          state="OPEN", repo="owner/repo", parent=None, parent_repo=""):
    return {
        "number": number, "title": title,
        "labels": labels or [], "priority": priority,
        "status": status, "state": state,
        "repo": repo, "parent": parent, "parent_repo": parent_repo,
        "assignees": [], "url": f"https://github.com/owner/repo/issues/{number}",
    }


def _make_gui(index, children, *, hide_done=True, search="",
              when_filters=None, phase_filters=None, area="All", group_by="When"):
    """Headless ProjectIssueGui with just enough state for filter / visibility tests."""
    gui = ProjectIssueGui.__new__(ProjectIssueGui)
    gui._index = index
    gui._children = children
    gui._items = list(index.values())
    gui._hide_done = _MockVar(hide_done)
    gui._search_var = _MockVar(search)
    gui._area_var = _MockVar(area)
    gui._group_by_var = _MockVar(group_by)
    all_when = ["when:today", "when:this-week", "when:this-month", "when:this-quarter"]
    active_when = set(when_filters or [])
    gui._when_filter_vars = {k: _MockVar(k in active_when) for k in all_when}
    all_phases = ["waiting", "someday", "inbox"]
    active_phases = set(phase_filters or [])
    gui._phase_filter_vars = {k: _MockVar(k in active_phases) for k in all_phases}
    return gui


class _FakeTree:
    """Small Treeview stand-in for asserting inserted parent/child shape."""
    def __init__(self):
        self.nodes = {}
        self.children = {"": []}
        self._counter = 0

    def insert(self, parent, _index, **kwargs):
        self._counter += 1
        item_id = f"I{self._counter}"
        self.nodes[item_id] = {"parent": parent, **kwargs}
        self.children.setdefault(parent, []).append(item_id)
        self.children[item_id] = []
        return item_id


def _attach_fake_tree(gui):
    tree = _FakeTree()
    gui._tree = tree
    gui._item_urls = {}
    gui._item_keys = {}
    gui._comment_group_keys = {}
    gui._loaded_comment_groups = set()
    gui._set_status = lambda *args, **kwargs: None
    return tree


class ProjectGuiTreeTests(unittest.TestCase):
    def test_build_issue_tree_uses_repo_scoped_parent_keys(self):
        parent = {
            "repo": "owner/tasks",
            "number": 1,
            "title": "Parent",
            "status": "Ready",
            "priority": "P2-High",
        }
        child = {
            "repo": "owner/tasks",
            "number": 2,
            "title": "Child",
            "status": "Backlog",
            "priority": "P3-Medium",
            "parent": (1, "Parent"),
            "parent_repo": "owner/tasks",
        }

        _, children = build_issue_tree([child, parent])

        self.assertEqual(children[None], [IssueKey("owner/tasks", 1)])
        self.assertEqual(children[IssueKey("owner/tasks", 1)], [IssueKey("owner/tasks", 2)])

    def test_comment_tree_text_summarizes_comment_for_gui_row(self):
        text = _comment_tree_text({
            "author": "codex",
            "updated_at": "2026-06-03T12:34:56Z",
            "body": "First line\nwith extra whitespace",
        })

        self.assertEqual(text, "2026-06-03 codex: First line with extra whitespace")

    def test_list_param_accepts_commas_or_lists(self):
        self.assertEqual(_list_param("a, b,,c"), ["a", "b", "c"])
        self.assertEqual(_list_param(["a", " b ", ""]), ["a", "b"])

    def test_capture_issue_body_body_only(self):
        self.assertEqual(build_capture_issue_body(body="  Plain context  "), "Plain context")

    def test_capture_issue_body_next_action_only(self):
        body = build_capture_issue_body(next_action="Email Alice")

        self.assertIn("GTD capture item.", body)
        self.assertIn("## Next Action\nEmail Alice", body)
        self.assertNotIn("## Context", body)

    def test_capture_issue_body_next_action_and_waiting_for(self):
        body = build_capture_issue_body(next_action="Send draft", waiting_for="Bob reply")

        self.assertIn("## Next Action\nSend draft", body)
        self.assertIn("## Waiting For\nBob reply", body)

    def test_capture_issue_body_context_and_source(self):
        body = build_capture_issue_body(
            body="Meeting note",
            source_label="Planning email",
            source_text="Raw pasted email",
        )

        self.assertIn("## Context\nMeeting note", body)
        self.assertIn("## Source\nPlanning email", body)
        self.assertIn("```text\nRaw pasted email\n```", body)

    def test_capture_issue_body_source_without_label_uses_default(self):
        body = build_capture_issue_body(source_text="Raw text")

        self.assertIn("## Source\nCaptured source", body)

    def test_capture_issue_body_empty_inputs_return_empty_string(self):
        self.assertEqual(build_capture_issue_body(), "")

    def test_build_project_context_includes_state_and_hierarchy(self):
        item = {
            "status": "This Week",
            "priority": "P2-High",
            "fields": {"Status": "This Week", "Priority": "P2-High"},
        }
        parent = {"repo": "owner/repo", "number": 134, "title": "Parent"}
        children = [{"repo": "owner/repo", "number": 157, "title": "Child"}]

        context = build_project_context("Scott T Tracker", 1, item, parent, children)

        self.assertEqual(context["title"], "Scott T Tracker")
        self.assertEqual(context["number"], 1)
        self.assertEqual(context["status"], "This Week")
        self.assertEqual(context["priority"], "P2-High")
        self.assertEqual(context["parent"], parent)
        self.assertEqual(context["children"], children)

    def test_issue_summaries_include_issue_number_alias_for_resume_context(self):
        gui = ProjectIssueGui.__new__(ProjectIssueGui)
        gui._index = {}
        item = {
            "repo": "owner/repo",
            "number": 156,
            "title": "Resume Me",
            "parent": (134, "Parent"),
            "parent_repo": "owner/repo",
        }

        summary = gui._issue_summary(item)
        parent = gui._parent_summary(item)

        self.assertEqual(summary["number"], 156)
        self.assertEqual(summary["issue_number"], 156)
        self.assertEqual(parent["number"], 134)
        self.assertEqual(parent["issue_number"], 134)

    def test_build_resume_summary_uses_latest_work_log(self):
        latest_work_log = {
            "parsed": {
                "work_completed": ["GTD/Codex issue management system stood up"],
                "current_state": ["Hierarchy reorganized and capture_issue added"],
                "next_steps": ["Review cleanup labels such as gtd:next-action"],
                "blockers_open_questions": ["Whether to create a workflow tooling output stream"],
            }
        }

        summary = build_resume_summary({"body": "Issue body"}, latest_work_log, [], [])

        self.assertEqual(summary["where_we_left_off"], "Hierarchy reorganized and capture_issue added")
        self.assertEqual(summary["next_action"], "Review cleanup labels such as gtd:next-action")
        self.assertEqual(summary["blockers"], ["Whether to create a workflow tooling output stream"])
        self.assertEqual(summary["source"], "latest_work_log")

    def test_build_resume_summary_falls_back_without_work_log(self):
        summary = build_resume_summary(
            {"body": "Issue body first line\nMore"},
            None,
            [],
            ["no structured gtd_mgmt work-log found"],
        )

        self.assertEqual(summary["where_we_left_off"], "Issue body first line")
        self.assertEqual(summary["source"], "issue_context")
        self.assertIn("no structured gtd_mgmt work-log found", summary["warnings"])

    def test_try_update_project_field_returns_ok(self):
        client = Mock()
        warnings = []

        result = _try_update_project_field(client, "project-id", "item-id", {}, "Status", "Ready", warnings)

        self.assertEqual(result, {"requested": "Ready", "result": "ok"})
        self.assertEqual(warnings, [])
        client.update_project_field_by_name.assert_called_once_with("project-id", "item-id", {}, "Status", "Ready")

    def test_try_update_project_field_returns_warning_on_failure(self):
        client = Mock()
        client.update_project_field_by_name.side_effect = ValueError("option not found")
        warnings = []

        result = _try_update_project_field(client, "project-id", "item-id", {}, "Priority", "P2-High", warnings)

        self.assertEqual(result["requested"], "P2-High")
        self.assertEqual(result["result"], "skipped")
        self.assertIn("option not found", result["error"])
        self.assertEqual(warnings, ["Priority skipped: option not found"])

    def test_try_set_issue_parent_returns_warning_on_failure(self):
        client = Mock()
        client.set_issue_parent_by_number.side_effect = RuntimeError("parent missing")
        warnings = []

        result = _try_set_issue_parent(client, "owner/repo", 2, "owner/repo", 1, warnings)

        self.assertEqual(result["result"], "skipped")
        self.assertEqual(result["issue_number"], 1)
        self.assertEqual(warnings, ["Parent skipped: parent missing"])

    def test_apply_capture_issue_continues_after_priority_failure(self):
        client = Mock()
        client.create_issue.return_value = {
            "number": 156,
            "title": "Captured item",
            "html_url": "https://github.com/owner/repo/issues/156",
            "node_id": "issue-node-id",
        }
        client.get_project.return_value = {"id": "project-id"}
        client.add_issue_to_project.return_value = "item-id"
        client.update_project_field_by_name.side_effect = [None, ValueError("option 'P2-High' not found")]
        client.set_issue_parent_by_number.return_value = None

        result = ProjectIssueGui._apply_capture_issue(
            object(),
            client,
            {},
            {
                "repo": "owner/repo",
                "title": "Captured item",
                "status": "Backlog",
                "priority": "P2-High",
                "parent_issue_number": 100,
                "next_action": "Do the thing",
            },
        )

        self.assertEqual(result["issue"]["number"], 156)
        self.assertEqual(result["issue"]["status"], {"requested": "Backlog", "result": "ok"})
        self.assertEqual(result["issue"]["priority"]["requested"], "P2-High")
        self.assertEqual(result["issue"]["priority"]["result"], "skipped")
        self.assertEqual(result["issue"]["parent"], {"repo": "owner/repo", "issue_number": 100, "result": "ok"})
        self.assertIn("Priority skipped", result["warnings"][0])

    def test_apply_create_issue_continues_after_priority_failure(self):
        client = Mock()
        client.create_issue.return_value = {
            "number": 157,
            "title": "Created item",
            "html_url": "https://github.com/owner/repo/issues/157",
            "node_id": "issue-node-id",
        }
        client.get_project.return_value = {"id": "project-id"}
        client.add_issue_to_project.return_value = "item-id"
        client.update_project_field_by_name.side_effect = [None, ValueError("option 'P2-High' not found")]

        result = ProjectIssueGui._apply_create_issue(
            object(),
            client,
            {},
            {"repo": "owner/repo", "title": "Created item", "status": "Backlog", "priority": "P2-High"},
        )

        self.assertEqual(result["issue"]["number"], 157)
        self.assertEqual(result["issue"]["priority"]["result"], "skipped")
        self.assertIn("Priority skipped", result["warnings"][0])

    def test_normalize_issue_ref_accepts_issue_number(self):
        self.assertEqual(normalize_issue_ref({"repo": "owner/repo", "issue_number": "42"}), ("owner/repo", 42))

    def test_bulk_plan_reports_intended_operations_and_failures(self):
        loaded = [
            {"repo": "owner/repo", "number": 1, "title": "One", "item_id": "item-1"},
        ]
        plan = build_bulk_organize_plan(
            [
                {"repo": "owner/repo", "issue_number": 1},
                {"repo": "owner/repo", "issue_number": 1},
                {"repo": "owner/repo", "issue_number": 2},
                {"repo": "", "issue_number": 3},
            ],
            loaded,
            {
                "labels": "gtd:project, domain:eng",
                "status": "Ready",
                "priority": "P2-High",
                "parent_issue_number": 99,
            },
        )

        self.assertEqual(len(plan["planned"]), 1)
        self.assertEqual(plan["planned"][0]["labels"], ["gtd:project", "domain:eng"])
        self.assertEqual(plan["planned"][0]["parent"], {"repo": "owner/repo", "issue_number": 99})
        self.assertEqual(len(plan["failed"]), 3)

    def test_bulk_organize_dry_run_does_not_mutate(self):
        client = Mock()
        result = apply_bulk_organize_issues(
            client,
            [{"repo": "owner/repo", "number": 1, "title": "One", "item_id": "item-1"}],
            {"items": [{"repo": "owner/repo", "issue_number": 1}], "labels": ["x"], "dry_run": True},
        )

        self.assertTrue(result["dry_run"])
        self.assertEqual(len(result["planned"]), 1)
        client.add_labels_to_issue.assert_not_called()

    def test_bulk_organize_continues_after_failure(self):
        client = Mock()
        client.get_project.return_value = {
            "id": "project-id",
            "fields": {"nodes": [{"id": "status-id", "name": "Status", "options": [{"name": "Ready", "id": "ready-id"}]}]},
        }
        client.add_labels_to_issue.side_effect = [Exception("label failed"), None]
        loaded = [
            {"repo": "owner/repo", "number": 1, "title": "One", "item_id": "item-1"},
            {"repo": "owner/repo", "number": 2, "title": "Two", "item_id": "item-2"},
        ]

        result = apply_bulk_organize_issues(
            client,
            loaded,
            {
                "items": [
                    {"repo": "owner/repo", "issue_number": 1},
                    {"repo": "owner/repo", "issue_number": 2},
                ],
                "labels": ["x"],
                "status": "Ready",
                "dry_run": False,
            },
        )

        self.assertFalse(result["dry_run"])
        self.assertEqual(len(result["updated"]), 1)
        self.assertEqual(len(result["failed"]), 1)
        self.assertIn("label failed", result["failed"][0]["error"])


class WhenOrderSortTests(unittest.TestCase):
    def test_today_sorts_before_this_week(self):
        items = [
            _item(1, "Week task", labels=["when:this-week"]),
            _item(2, "Today task", labels=["when:today"]),
        ]
        result = sorted(items, key=_sort_key)
        self.assertEqual(result[0]["number"], 2)

    def test_this_week_sorts_before_this_month(self):
        items = [
            _item(1, "Month task", labels=["when:this-month"]),
            _item(2, "Week task", labels=["when:this-week"]),
        ]
        result = sorted(items, key=_sort_key)
        self.assertEqual(result[0]["number"], 2)

    def test_no_horizon_sorts_last(self):
        items = [
            _item(1, "No horizon"),
            _item(2, "Today task", labels=["when:today"]),
        ]
        result = sorted(items, key=_sort_key)
        self.assertEqual(result[0]["number"], 2)
        self.assertEqual(result[1]["number"], 1)

    def test_priority_breaks_ties_within_same_horizon(self):
        items = [
            _item(1, "Medium", labels=["when:this-week"], priority="P3-Medium"),
            _item(2, "Critical", labels=["when:this-week"], priority="P1-Critical"),
            _item(3, "High", labels=["when:this-week"], priority="P2-High"),
        ]
        result = sorted(items, key=_sort_key)
        self.assertEqual([i["number"] for i in result], [2, 3, 1])

    def test_title_breaks_priority_ties(self):
        items = [
            _item(1, "Beta task", labels=["when:this-week"], priority="P2-High"),
            _item(2, "Alpha task", labels=["when:this-week"], priority="P2-High"),
        ]
        result = sorted(items, key=_sort_key)
        self.assertEqual(result[0]["number"], 2)  # alpha before beta


class ItemWhenTests(unittest.TestCase):
    def test_returns_first_when_label(self):
        self.assertEqual(_item_when(_item(labels=["needs-collaboration", "when:this-week"])), "when:this-week")

    def test_returns_empty_when_no_when_label(self):
        self.assertEqual(_item_when(_item(labels=["needs-collaboration"])), "")

    def test_returns_empty_for_no_labels(self):
        self.assertEqual(_item_when(_item()), "")


class RootTitleTests(unittest.TestCase):
    def test_root_item_returns_own_title(self):
        root = _item(1, "Engineering")
        index, children = build_issue_tree([root])
        self.assertEqual(_root_title_for(IssueKey("owner/repo", 1), index, children), "Engineering")

    def test_child_returns_root_title(self):
        root = _item(1, "Engineering")
        child = _item(2, "Sub-task", parent=(1, "Engineering"), parent_repo="owner/repo")
        index, children = build_issue_tree([root, child])
        self.assertEqual(_root_title_for(IssueKey("owner/repo", 2), index, children), "Engineering")

    def test_deep_descendant_returns_root_title(self):
        root = _item(1, "Engineering")
        mid = _item(2, "Project", parent=(1, "Engineering"), parent_repo="owner/repo")
        leaf = _item(3, "Task", parent=(2, "Project"), parent_repo="owner/repo")
        index, children = build_issue_tree([root, mid, leaf])
        self.assertEqual(_root_title_for(IssueKey("owner/repo", 3), index, children), "Engineering")

    def test_inbox_child_returns_inbox_title(self):
        inbox = _item(165, INBOX_ROOT_TITLE)
        child = _item(200, "Untriaged", parent=(165, INBOX_ROOT_TITLE), parent_repo="owner/repo")
        index, children = build_issue_tree([inbox, child])
        self.assertEqual(_root_title_for(IssueKey("owner/repo", 200), index, children), INBOX_ROOT_TITLE)


class ItemPhaseTests(unittest.TestCase):
    def _phase(self, itm, extra_items=None):
        items = [itm] + (extra_items or [])
        index, children = build_issue_tree(items)
        return _item_phase(IssueKey("owner/repo", itm["number"]), itm, index, children)

    def test_closed_is_done(self):
        self.assertEqual(self._phase(_item(state="CLOSED")), "done")

    def test_waiting_for_label(self):
        self.assertEqual(self._phase(_item(labels=["gtd:waiting-for"])), "waiting")

    def test_someday_maybe_label(self):
        self.assertEqual(self._phase(_item(labels=["gtd:someday-maybe"])), "someday")

    def test_inbox_root_child(self):
        inbox = _item(165, INBOX_ROOT_TITLE)
        child = _item(200, "Untriaged", parent=(165, INBOX_ROOT_TITLE), parent_repo="owner/repo")
        index, children = build_issue_tree([inbox, child])
        key = IssueKey("owner/repo", 200)
        self.assertEqual(_item_phase(key, child, index, children), "inbox")

    def test_has_children_is_project(self):
        parent = _item(1, "Project")
        child = _item(2, "Task", parent=(1, "Project"), parent_repo="owner/repo")
        index, children = build_issue_tree([parent, child])
        key = IssueKey("owner/repo", 1)
        self.assertEqual(_item_phase(key, parent, index, children), "project")

    def test_when_label_is_next_action(self):
        itm = _item(labels=["when:this-week"])
        index, children = build_issue_tree([itm])
        self.assertEqual(_item_phase(IssueKey("owner/repo", 1), itm, index, children), "next-action")

    def test_default_is_inbox(self):
        itm = _item()  # no labels, no children, not under inbox root
        index, children = build_issue_tree([itm])
        self.assertEqual(_item_phase(IssueKey("owner/repo", 1), itm, index, children), "inbox")

    def test_waiting_takes_priority_over_inbox_root(self):
        inbox = _item(165, INBOX_ROOT_TITLE)
        child = _item(200, "Waiting+Inbox", labels=["gtd:waiting-for"],
                      parent=(165, INBOX_ROOT_TITLE), parent_repo="owner/repo")
        index, children = build_issue_tree([inbox, child])
        key = IssueKey("owner/repo", 200)
        self.assertEqual(_item_phase(key, child, index, children), "waiting")


class WhenFilterVisibilityTests(unittest.TestCase):
    def setUp(self):
        self.items = [
            _item(1, "Today task",    labels=["when:today"]),
            _item(2, "Week task",     labels=["when:this-week"]),
            _item(3, "Month task",    labels=["when:this-month"]),
            _item(4, "Quarter task",  labels=["when:this-quarter"]),
            _item(5, "No horizon"),
        ]
        self.index, self.children = build_issue_tree(self.items)

    def _visible(self, gui, number):
        key = IssueKey("owner/repo", number)
        return gui._is_visible_grouped(key, self.index[key])

    def test_this_week_nested_includes_today_and_week(self):
        gui = _make_gui(self.index, self.children, when_filters=["when:this-week"])
        self.assertTrue(self._visible(gui, 1))   # today ≤ this-week
        self.assertTrue(self._visible(gui, 2))   # this-week == this-week
        self.assertFalse(self._visible(gui, 3))  # this-month > this-week
        self.assertFalse(self._visible(gui, 4))  # quarter > this-week
        self.assertFalse(self._visible(gui, 5))  # no horizon

    def test_this_month_includes_today_week_month(self):
        gui = _make_gui(self.index, self.children, when_filters=["when:this-month"])
        self.assertTrue(self._visible(gui, 1))
        self.assertTrue(self._visible(gui, 2))
        self.assertTrue(self._visible(gui, 3))
        self.assertFalse(self._visible(gui, 4))
        self.assertFalse(self._visible(gui, 5))

    def test_this_quarter_includes_all_horizons(self):
        gui = _make_gui(self.index, self.children, when_filters=["when:this-quarter"])
        for n in [1, 2, 3, 4]:
            self.assertTrue(self._visible(gui, n))
        self.assertFalse(self._visible(gui, 5))  # still no horizon

    def test_no_when_filter_shows_all_items(self):
        gui = _make_gui(self.index, self.children, when_filters=[])
        for n in range(1, 6):
            self.assertTrue(self._visible(gui, n))

    def test_hierarchy_parent_visible_when_child_passes_when_filter(self):
        root = _item(10, "[Scott T] Engineering")
        child = _item(11, "Week task", labels=["when:this-week"],
                      parent=(10, "[Scott T] Engineering"), parent_repo="owner/repo")
        index, children = build_issue_tree([root, child])
        gui = _make_gui(index, children, when_filters=["when:this-week"])
        root_key = IssueKey("owner/repo", 10)
        child_key = IssueKey("owner/repo", 11)
        self.assertTrue(gui._is_visible(child_key))
        self.assertTrue(gui._is_visible(root_key))  # visible because child passes

    def test_hierarchy_parent_hidden_when_no_children_pass_when_filter(self):
        root = _item(10, "[Scott T] Engineering")
        child = _item(11, "Quarter task", labels=["when:this-quarter"],
                      parent=(10, "[Scott T] Engineering"), parent_repo="owner/repo")
        index, children = build_issue_tree([root, child])
        gui = _make_gui(index, children, when_filters=["when:this-week"])
        root_key = IssueKey("owner/repo", 10)
        self.assertFalse(gui._is_visible(root_key))

    def test_hierarchy_child_visible_when_parent_passes_when_filter(self):
        root = _item(10, "[Scott T] Engineering")
        project = _item(11, "Week project", labels=["when:this-week"],
                        parent=(10, "[Scott T] Engineering"), parent_repo="owner/repo")
        child = _item(12, "Project child",
                      parent=(11, "Week project"), parent_repo="owner/repo")
        index, children = build_issue_tree([root, project, child])
        gui = _make_gui(index, children, when_filters=["when:this-week"])

        self.assertTrue(gui._is_visible(IssueKey("owner/repo", 10)))
        self.assertTrue(gui._is_visible(IssueKey("owner/repo", 11)))
        self.assertTrue(gui._is_visible(IssueKey("owner/repo", 12)))

    def test_context_keys_include_ancestors_and_descendants_of_match(self):
        root = _item(10, "[Scott T] Engineering")
        project = _item(11, "Week project", labels=["when:this-week"],
                        parent=(10, "[Scott T] Engineering"), parent_repo="owner/repo")
        child = _item(12, "Project child",
                      parent=(11, "Week project"), parent_repo="owner/repo")
        sibling = _item(13, "Sibling",
                        parent=(10, "[Scott T] Engineering"), parent_repo="owner/repo")
        index, children = build_issue_tree([root, project, child, sibling])
        gui = _make_gui(index, children, when_filters=["when:this-week"])

        context_keys = gui._context_keys_for({IssueKey("owner/repo", 11)})

        self.assertEqual(
            context_keys,
            {
                IssueKey("owner/repo", 10),
                IssueKey("owner/repo", 11),
                IssueKey("owner/repo", 12),
            },
        )

    def test_done_leaf_descendant_hidden_when_hide_done_selected(self):
        root = _item(10, "[Scott T] Engineering")
        project = _item(11, "Week project", labels=["when:this-week"],
                        parent=(10, "[Scott T] Engineering"), parent_repo="owner/repo")
        done_child = _item(12, "Completed child", status="Done",
                           parent=(11, "Week project"), parent_repo="owner/repo")
        index, children = build_issue_tree([root, project, done_child])
        gui = _make_gui(index, children, when_filters=["when:this-week"], hide_done=True)

        context_keys = gui._context_keys_for({IssueKey("owner/repo", 11)})

        self.assertIn(IssueKey("owner/repo", 10), context_keys)
        self.assertIn(IssueKey("owner/repo", 11), context_keys)
        self.assertNotIn(IssueKey("owner/repo", 12), context_keys)

    def test_done_leaf_descendant_visible_when_hide_done_cleared(self):
        root = _item(10, "[Scott T] Engineering")
        project = _item(11, "Week project", labels=["when:this-week"],
                        parent=(10, "[Scott T] Engineering"), parent_repo="owner/repo")
        done_child = _item(12, "Completed child", status="Done",
                           parent=(11, "Week project"), parent_repo="owner/repo")
        index, children = build_issue_tree([root, project, done_child])
        gui = _make_gui(index, children, when_filters=["when:this-week"], hide_done=False)

        context_keys = gui._context_keys_for({IssueKey("owner/repo", 11)})

        self.assertIn(IssueKey("owner/repo", 12), context_keys)


class PhaseFilterVisibilityTests(unittest.TestCase):
    def test_waiting_filter_shows_only_waiting_items(self):
        items = [
            _item(1, "Waiting task", labels=["gtd:waiting-for"]),
            _item(2, "Week task",    labels=["when:this-week"]),
        ]
        index, children = build_issue_tree(items)
        gui = _make_gui(index, children, phase_filters=["waiting"])
        self.assertTrue(gui._is_visible_grouped(IssueKey("owner/repo", 1), index[IssueKey("owner/repo", 1)]))
        self.assertFalse(gui._is_visible_grouped(IssueKey("owner/repo", 2), index[IssueKey("owner/repo", 2)]))

    def test_someday_filter(self):
        items = [
            _item(1, "Someday task", labels=["gtd:someday-maybe"]),
            _item(2, "Normal task"),
        ]
        index, children = build_issue_tree(items)
        gui = _make_gui(index, children, phase_filters=["someday"])
        self.assertTrue(gui._is_visible_grouped(IssueKey("owner/repo", 1), index[IssueKey("owner/repo", 1)]))
        self.assertFalse(gui._is_visible_grouped(IssueKey("owner/repo", 2), index[IssueKey("owner/repo", 2)]))

    def test_no_phase_filter_shows_all(self):
        items = [
            _item(1, "Waiting", labels=["gtd:waiting-for"]),
            _item(2, "Normal"),
        ]
        index, children = build_issue_tree(items)
        gui = _make_gui(index, children, phase_filters=[])
        for n in [1, 2]:
            key = IssueKey("owner/repo", n)
            self.assertTrue(gui._is_visible_grouped(key, index[key]))


class AreaFilterVisibilityTests(unittest.TestCase):
    def setUp(self):
        self.eng_root  = _item(10, "[Scott T] Engineering")
        self.eng_child = _item(11, "Eng task", parent=(10, "[Scott T] Engineering"), parent_repo="owner/repo")
        self.ops_root  = _item(20, "[Scott T] Operations")
        self.ops_child = _item(21, "Ops task", parent=(20, "[Scott T] Operations"), parent_repo="owner/repo")
        self.index, self.children = build_issue_tree(
            [self.eng_root, self.eng_child, self.ops_root, self.ops_child]
        )

    def test_area_filter_isolates_engineering(self):
        gui = _make_gui(self.index, self.children, area="[Scott T] Engineering")
        self.assertTrue(gui._is_visible_grouped(IssueKey("owner/repo", 11), self.index[IssueKey("owner/repo", 11)]))
        self.assertFalse(gui._is_visible_grouped(IssueKey("owner/repo", 21), self.index[IssueKey("owner/repo", 21)]))

    def test_area_all_shows_everything(self):
        gui = _make_gui(self.index, self.children, area="All")
        for n in [10, 11, 20, 21]:
            key = IssueKey("owner/repo", n)
            self.assertTrue(gui._is_visible_grouped(key, self.index[key]))

    def test_area_filter_applies_in_hierarchy_mode_with_bubble_up(self):
        gui = _make_gui(self.index, self.children, area="[Scott T] Engineering", group_by="Hierarchy")
        # eng root is visible; ops root is NOT (no children pass)
        self.assertTrue(gui._is_visible(IssueKey("owner/repo", 10)))
        self.assertFalse(gui._is_visible(IssueKey("owner/repo", 20)))


class GroupByWhenBucketTests(unittest.TestCase):
    def test_items_grouped_into_correct_horizons(self):
        items = [
            _item(1, "Today task",   labels=["when:today"]),
            _item(2, "Week task A",  labels=["when:this-week"]),
            _item(3, "Week task B",  labels=["when:this-week"]),
            _item(4, "Month task",   labels=["when:this-month"]),
            _item(5, "No horizon"),  # excluded from any horizon bucket
        ]
        index, children = build_issue_tree(items)
        gui = _make_gui(index, children, when_filters=[])  # no ceiling filter

        today_bucket  = [k for k, itm in index.items() if _item_when(itm) == "when:today"   and gui._is_visible_grouped(k, itm)]
        week_bucket   = [k for k, itm in index.items() if _item_when(itm) == "when:this-week" and gui._is_visible_grouped(k, itm)]
        month_bucket  = [k for k, itm in index.items() if _item_when(itm) == "when:this-month" and gui._is_visible_grouped(k, itm)]

        self.assertEqual(len(today_bucket),  1)
        self.assertEqual(len(week_bucket),   2)
        self.assertEqual(len(month_bucket),  1)
        # item 5 (no horizon) doesn't appear in any bucket
        no_horizon_key = IssueKey("owner/repo", 5)
        self.assertNotIn(no_horizon_key, today_bucket + week_bucket + month_bucket)

    def test_when_ceiling_prunes_buckets(self):
        items = [
            _item(1, "Today task",   labels=["when:today"]),
            _item(2, "Week task",    labels=["when:this-week"]),
            _item(3, "Month task",   labels=["when:this-month"]),
        ]
        index, children = build_issue_tree(items)
        gui = _make_gui(index, children, when_filters=["when:this-week"])  # ceiling = week

        week_visible  = gui._is_visible_grouped(IssueKey("owner/repo", 2), index[IssueKey("owner/repo", 2)])
        month_visible = gui._is_visible_grouped(IssueKey("owner/repo", 3), index[IssueKey("owner/repo", 3)])
        self.assertTrue(week_visible)
        self.assertFalse(month_visible)

    def test_when_group_renders_context_as_tree(self):
        root = _item(10, "[Scott T] Engineering")
        project = _item(11, "Week project", labels=["when:this-week"],
                        parent=(10, "[Scott T] Engineering"), parent_repo="owner/repo")
        child = _item(12, "Project child",
                      parent=(11, "Week project"), parent_repo="owner/repo")
        index, children = build_issue_tree([root, project, child])
        gui = _make_gui(index, children, when_filters=["when:this-week"])
        tree = _attach_fake_tree(gui)

        gui._populate_tree_by_when()

        header_id = tree.children[""][0]
        root_id = next(item_id for item_id, node in tree.nodes.items() if node["text"] == "#10  [Scott T] Engineering")
        project_id = next(item_id for item_id, node in tree.nodes.items() if node["text"] == "#11  Week project")
        child_id = next(item_id for item_id, node in tree.nodes.items() if node["text"] == "#12  Project child")
        self.assertEqual(tree.nodes[header_id]["text"], "  This Week  (3)")
        self.assertEqual(tree.nodes[root_id]["parent"], header_id)
        self.assertEqual(tree.nodes[project_id]["parent"], root_id)
        self.assertEqual(tree.nodes[child_id]["parent"], project_id)

    def test_when_group_does_not_render_done_leaf_when_hide_done_selected(self):
        root = _item(10, "[Scott T] Engineering")
        project = _item(11, "Week project", labels=["when:this-week"],
                        parent=(10, "[Scott T] Engineering"), parent_repo="owner/repo")
        done_child = _item(12, "Completed child", status="Done",
                           parent=(11, "Week project"), parent_repo="owner/repo")
        index, children = build_issue_tree([root, project, done_child])
        gui = _make_gui(index, children, when_filters=["when:this-week"], hide_done=True)
        tree = _attach_fake_tree(gui)

        gui._populate_tree_by_when()

        rendered_text = {node["text"] for node in tree.nodes.values()}
        self.assertIn("#10  [Scott T] Engineering", rendered_text)
        self.assertIn("#11  Week project", rendered_text)
        self.assertNotIn("#12  Completed child", rendered_text)


class GroupByAreaBucketTests(unittest.TestCase):
    def test_items_grouped_by_root_title(self):
        eng_root  = _item(10, "[Scott T] Engineering")
        eng_child = _item(11, "Eng task", parent=(10, "[Scott T] Engineering"), parent_repo="owner/repo")
        ops_root  = _item(20, "[Scott T] Operations")
        ops_child = _item(21, "Ops task", parent=(20, "[Scott T] Operations"), parent_repo="owner/repo")
        items = [eng_root, eng_child, ops_root, ops_child]
        index, children = build_issue_tree(items)
        gui = _make_gui(index, children)

        eng_bucket = [
            k for k, itm in index.items()
            if _root_title_for(k, index, children) == "[Scott T] Engineering"
            and gui._is_visible_grouped(k, itm)
        ]
        ops_bucket = [
            k for k, itm in index.items()
            if _root_title_for(k, index, children) == "[Scott T] Operations"
            and gui._is_visible_grouped(k, itm)
        ]
        self.assertEqual(len(eng_bucket), 2)
        self.assertEqual(len(ops_bucket), 2)


class RepoMatchesTests(unittest.TestCase):
    def test_empty_query_matches_anything(self):
        self.assertTrue(_repo_matches("swtandy/personal-management", ""))

    def test_full_form_matches_exact(self):
        self.assertTrue(_repo_matches("swtandy/personal-management", "swtandy/personal-management"))

    def test_short_name_matches_full_owner_repo(self):
        # Cowork fix: querying by "personal-management" should find "swtandy/personal-management"
        self.assertTrue(_repo_matches("swtandy/personal-management", "personal-management"))

    def test_short_name_does_not_match_different_repo(self):
        self.assertFalse(_repo_matches("swtandy/other-repo", "personal-management"))

    def test_different_repo_names_do_not_match(self):
        self.assertFalse(_repo_matches("swtandy/repo-a", "repo-b"))

    def test_no_owner_item_matched_by_short_name(self):
        self.assertTrue(_repo_matches("repo", "repo"))


class GroupByWhenEmptyStateTests(unittest.TestCase):
    """Regression: 'Group by When' appeared empty when no issues had when: labels.

    The fix was to default group_by to 'Area', which shows all issues regardless
    of when: label presence. These tests document both the broken behaviour (When
    mode is empty without labels) and the correct behaviour (Area mode is not).
    """

    def _items_without_when_labels(self):
        root = _item(1, "[Scott T] Home And Property")
        child = _item(2, "Fix deck", parent=(1, "[Scott T] Home And Property"), parent_repo="owner/repo")
        task = _item(3, "Buy lumber", parent=(2, "Fix deck"), parent_repo="owner/repo")
        return [root, child, task]

    def test_when_group_renders_nothing_when_no_items_have_when_labels(self):
        """The bug: all 69 issues appeared missing because none were triaged with when: labels."""
        index, children = build_issue_tree(self._items_without_when_labels())
        gui = _make_gui(index, children, when_filters=[], group_by="When")
        tree = _attach_fake_tree(gui)

        gui._populate_tree_by_when()

        # Only the "No items match" message row is inserted — no issue rows
        rendered = [node["text"] for node in tree.nodes.values()]
        self.assertNotIn("#1  [Scott T] Home And Property", rendered)
        self.assertNotIn("#2  Fix deck", rendered)
        self.assertIn("No items match the current filters.", rendered[0])

    def test_area_group_shows_all_items_without_when_labels(self):
        """The fix: Area grouping displays issues regardless of when: label."""
        index, children = build_issue_tree(self._items_without_when_labels())
        gui = _make_gui(index, children, when_filters=[], group_by="Area")
        tree = _attach_fake_tree(gui)

        gui._populate_tree_by_area()

        rendered = {node["text"] for node in tree.nodes.values()}
        self.assertIn("#1  [Scott T] Home And Property", rendered)
        self.assertIn("#2  Fix deck", rendered)
        self.assertIn("#3  Buy lumber", rendered)


class ApplyChangeAttachmentOpsTests(unittest.TestCase):
    """Wiring tests: _command_apply_change routes attachment ops to attachments.py correctly."""

    def _gui_with_issue(self, fake_client):
        gui = ProjectIssueGui.__new__(ProjectIssueGui)
        gui._items = [{
            "repo": "owner/repo", "number": 9, "title": "Deck layout", "url": "https://github.com/owner/repo/issues/9",
            "state": "OPEN", "status": "Backlog", "priority": "", "labels": [], "assignees": [],
            "parent": None, "parent_repo": "", "fields": {}, "item_id": "item-id",
        }]
        return gui

    @patch("agents.project_gui.GitHubClient")
    def test_attach_file_to_issue_op_uploads_and_returns_result(self, mock_client_cls):
        from tests.test_attachments import FakeGitHubClient, PNG_HEADER, _write_temp_file

        fake_client = FakeGitHubClient()
        mock_client_cls.return_value = fake_client
        gui = self._gui_with_issue(fake_client)
        path = _write_temp_file(".png", PNG_HEADER + b"0" * 32)
        try:
            result = gui._command_apply_change({
                "op": "attach_file_to_issue",
                "issue_number": 9,
                "repo": "owner/repo",
                "params": {"file_path": path, "caption": "Deck plan"},
            })
        finally:
            import os
            os.unlink(path)

        self.assertTrue(result["ok"])
        self.assertIn("raw_url", result)
        self.assertEqual(len(fake_client.comments), 1)

    @patch("agents.project_gui.GitHubClient")
    def test_delete_issue_file_op_marks_deleted(self, mock_client_cls):
        from tests.test_attachments import FakeGitHubClient, PNG_HEADER, _write_temp_file
        import attachments as attachments_module

        fake_client = FakeGitHubClient()
        mock_client_cls.return_value = fake_client
        gui = self._gui_with_issue(fake_client)
        path = _write_temp_file(".png", PNG_HEADER + b"0" * 32)
        try:
            attached = attachments_module.attach_file(fake_client, "owner/repo", 9, path)
            result = gui._command_apply_change({
                "op": "delete_issue_file",
                "issue_number": 9,
                "repo": "owner/repo",
                "params": {"path": attached["path"]},
            })
        finally:
            import os
            os.unlink(path)

        self.assertTrue(result["ok"])
        self.assertTrue(result["deleted"])

    @patch("agents.project_gui.GitHubClient")
    def test_list_files_command_returns_manifest(self, mock_client_cls):
        from tests.test_attachments import FakeGitHubClient

        fake_client = FakeGitHubClient()
        mock_client_cls.return_value = fake_client
        gui = self._gui_with_issue(fake_client)

        result = gui._command_list_files({"issue_number": 9, "repo": "owner/repo"})

        self.assertTrue(result["ok"])
        self.assertEqual(result["attachments"], [])

    @patch("agents.project_gui.GitHubClient")
    def test_get_file_command_returns_verified_attachment(self, mock_client_cls):
        import attachments as attachments_module
        from tests.test_attachments import FakeGitHubClient, PNG_HEADER, _write_temp_file

        fake_client = FakeGitHubClient()
        mock_client_cls.return_value = fake_client
        gui = self._gui_with_issue(fake_client)
        path = _write_temp_file(".png", PNG_HEADER + b"retrieve")
        try:
            attached = attachments_module.attach_file(fake_client, "owner/repo", 9, path, mode="none")
            result = gui._command_get_file({
                "issue_number": 9, "repo": "owner/repo", "path": attached["path"],
            })
        finally:
            import os
            os.unlink(path)

        self.assertTrue(result["ok"])
        self.assertTrue(result["verified_sha256"])

    @patch("agents.project_gui.GitHubClient")
    def test_get_files_command_writes_batch(self, mock_client_cls):
        import attachments as attachments_module
        import tempfile
        from pathlib import Path
        from tests.test_attachments import FakeGitHubClient, PNG_HEADER, _write_temp_file

        fake_client = FakeGitHubClient()
        mock_client_cls.return_value = fake_client
        gui = self._gui_with_issue(fake_client)
        path = _write_temp_file(".png", PNG_HEADER + b"batch")
        try:
            attachments_module.attach_file(fake_client, "owner/repo", 9, path, mode="none")
            with tempfile.TemporaryDirectory() as directory:
                result = gui._command_get_files({
                    "issue_number": 9, "repo": "owner/repo", "dest_dir": directory,
                })
                written = Path(directory, Path(path).name).read_bytes()
        finally:
            import os
            os.unlink(path)

        self.assertTrue(result["ok"])
        self.assertEqual(written, PNG_HEADER + b"batch")

    @patch("agents.project_gui.GitHubClient")
    def test_get_files_command_rejects_invalid_batch_limit(self, mock_client_cls):
        from tests.test_attachments import FakeGitHubClient

        fake_client = FakeGitHubClient()
        mock_client_cls.return_value = fake_client
        gui = self._gui_with_issue(fake_client)
        result = gui._command_get_files({
            "issue_number": 9, "repo": "owner/repo", "dest_dir": "/tmp/output",
            "max_total_bytes": "not-an-integer",
        })
        self.assertEqual(result["error"]["code"], "invalid_batch_limit")

    @patch("agents.project_gui.GitHubClient")
    def test_create_issue_with_attachments_appends_section_to_body(self, mock_client_cls):
        from tests.test_attachments import FakeGitHubClient, PNG_HEADER, _write_temp_file

        fake_client = FakeGitHubClient()
        mock_client_cls.return_value = fake_client
        gui = ProjectIssueGui.__new__(ProjectIssueGui)
        path = _write_temp_file(".png", PNG_HEADER + b"0" * 32)
        try:
            result = gui._apply_create_issue(
                fake_client,
                {},
                {
                    "repo": "owner/repo",
                    "title": "New issue",
                    "body": "Original body",
                    "attachments": [{"file_path": path, "caption": "Plan"}],
                },
            )
        finally:
            import os
            os.unlink(path)

        self.assertIn("attachments", result["issue"])
        self.assertTrue(result["issue"]["attachments"][0]["ok"])
        self.assertIn("## Attachments", fake_client.issue_body)


if __name__ == "__main__":
    unittest.main()
