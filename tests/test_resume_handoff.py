import unittest
from pathlib import Path
from unittest.mock import patch

from agents.gtd_mgmt_mcp_server import (
    REPO_ROOT,
    _codex_app_project_from_work_log,
    _default_codex_app_project,
    build_resume_handoff_markdown,
    resolve_codex_project_for_context,
    resolve_codex_project_path,
)


class ResumeHandoffTests(unittest.TestCase):
    def test_resolve_codex_project_uses_explicit_full_repo_mapping(self):
        result = resolve_codex_project_path(
            "owner/repo",
            project_path_map={"owner/repo": "/tmp/repo"},
            trusted_paths=[],
        )

        self.assertEqual(result["path"], "/tmp/repo")
        self.assertEqual(result["confidence"], "explicit")
        self.assertEqual(result["source"], "CODEX_PROJECT_PATHS[owner/repo]")

    def test_resolve_codex_project_uses_trusted_project_basename(self):
        result = resolve_codex_project_path(
            "owner/personal-management",
            project_path_map={},
            trusted_paths=[Path("/Users/scotttandy/Documents/repos/personal-management")],
        )

        self.assertEqual(result["path"], "/Users/scotttandy/Documents/repos/personal-management")
        self.assertEqual(result["confidence"], "high")
        self.assertEqual(result["source"], "Codex trusted projects")

    def test_resolve_codex_project_reports_ambiguous_trusted_matches(self):
        result = resolve_codex_project_path(
            "owner/repo",
            project_path_map={},
            trusted_paths=[Path("/a/repo"), Path("/b/repo")],
        )

        self.assertEqual(result["confidence"], "ambiguous")
        self.assertEqual(result["candidates"], ["/a/repo", "/b/repo"])
        self.assertIn("Multiple trusted Codex projects", result["warning"])

    def test_resolve_codex_project_uses_repo_root_for_current_repo(self):
        result = resolve_codex_project_path(
            "swtandy/SWT Personal Management",
            project_path_map={},
            trusted_paths=[],
        )

        self.assertEqual(result["path"], str(REPO_ROOT))
        self.assertEqual(result["confidence"], "high")

    def test_resolve_codex_project_for_context_prefers_codex_project_label(self):
        result = resolve_codex_project_for_context(
            {"labels": ["codex-project:SWT Personal Management"]},
            "swtandy/personal-management",
        )

        self.assertEqual(result["path"], str(REPO_ROOT))
        self.assertEqual(result["confidence"], "high")
        self.assertIn("codex-project:SWT Personal Management label", result["source"])

    def test_resolve_codex_project_for_context_uses_explicit_target_path(self):
        # _existing_path_from_text splits on whitespace so paths with spaces
        # (like REPO_ROOT = "SWT Personal Management") can't be found via body text.
        # Use /tmp which is guaranteed to exist and have no spaces.
        with patch.dict("os.environ", {"CODEX_PROJECT_PATHS": ""}):
            result = resolve_codex_project_for_context(
                {"body": "## Target Codex Project\n`/tmp`"},
                "swtandy/personal-management",
            )

        self.assertEqual(result["path"], "/tmp")
        self.assertEqual(result["confidence"], "high")
        self.assertEqual(result["source"], "explicit target path in issue/work-log context")

    def test_build_resume_handoff_markdown_includes_target_prompt_and_update_issue(self):
        context = {
            "ok": True,
            "repo": "swtandy/personal-management",
            "issue_number": 1,
            "url": "https://github.com/swtandy/personal-management/issues/1",
            "title": "Fix the thing",
            "state": "OPEN",
            "project": {
                "title": "Personal Management",
                "number": 2,
                "status": "This Week",
                "priority": "P2-High",
                "parent": {"repo": "swtandy/personal-management", "number": 100, "title": "Parent project"},
                "children": [{"repo": "swtandy/personal-management", "number": 2, "title": "Follow-up"}],
            },
            "resume_summary": {
                "where_we_left_off": "Investigated failing test.",
                "next_action": "Patch the parser.",
                "blockers": ["Need product decision."],
            },
            "latest_work_log": {
                "parsed": {
                    "work_completed": ["Reviewed the issue."],
                    "current_state": ["Parser fails on empty input."],
                    "next_steps": ["Patch the parser."],
                    "blockers_open_questions": ["Need product decision."],
                    "useful_context": ["Run pytest tests/."],
                }
            },
            "warnings": ["no structured gtd_mgmt work-log found"],
        }
        codex_project = {
            "path": "/Users/scotttandy/Documents/Claude/Projects/SWT Personal Management",
            "source": "Codex trusted projects",
            "confidence": "high",
        }

        with patch.dict(
            "os.environ",
            {
                "CODEX_APP_PROJECT_NAME": "SWT Personal Management",
                "CODEX_APP_PROJECT_PATH": "/Users/scotttandy/Documents/Claude/Projects/SWT Personal Management",
            },
        ):
            markdown = build_resume_handoff_markdown(context, codex_project)

        self.assertIn("# Workdown: swtandy/personal-management#1 - Fix the thing", markdown)
        self.assertIn("## Paste This To Choose Where To Work", markdown)
        self.assertIn("Use gtd_workflow and gtd_mgmt only to decide where Scott should work on swtandy/personal-management#1", markdown)
        self.assertIn("Do not start implementation, inspect or edit repositories", markdown)
        self.assertIn("Codex project means the project name/container in the Codex application", markdown)
        self.assertIn("Use only the 'Recommended Codex Project' section", markdown)
        self.assertIn("Recommended Codex project: SWT Personal Management", markdown)
        self.assertIn("Codex project path: /Users/scotttandy/Documents/Claude/Projects/SWT Personal Management", markdown)
        self.assertIn("## Recommended Codex Project", markdown)
        self.assertIn("Codex project is the project name/container in the Codex application", markdown)
        self.assertIn("`codex_project`: SWT Personal Management", markdown)
        self.assertIn("`codex_project_path`: /Users/scotttandy/Documents/Claude/Projects/SWT Personal Management", markdown)
        self.assertIn("## Related Local Workspaces", markdown)
        self.assertIn("`implementation_workspace`: `/Users/scotttandy/Documents/Claude/Projects/SWT Personal Management`", markdown)
        self.assertIn("## Related GitHub Repositories", markdown)
        self.assertIn("- swtandy/personal-management", markdown)
        self.assertIn("## Paste This After Switching To The Recommended Project", markdown)
        self.assertIn("Use this handoff/workdown context to orient yourself to swtandy/personal-management#1", markdown)
        self.assertIn("the actual implementation work may live in one or more related local workspaces", markdown)
        self.assertIn("inspect only enough local repository state to understand the current working context", markdown)
        self.assertIn("Do not edit files, run broad tests, create commits", markdown)
        self.assertIn("After orientation, stop and summarize", markdown)
        self.assertIn("Your first step after orientation is to align with Scott on the plan", markdown)
        self.assertIn("Ask for confirmation before doing implementation work", markdown)
        self.assertIn("Do not create another handoff unless Scott explicitly asks", markdown)
        self.assertIn("Patch the parser.", markdown)
        self.assertIn("Issue: `swtandy/personal-management#1`", markdown)
        self.assertIn("### Previous Work Session Codex Project", markdown)
        self.assertIn("/Users/scotttandy/Documents/Claude/Projects/SWT Personal Management", markdown)
        self.assertIn("gtd_mgmt.append_work_log", markdown)
        self.assertIn("Return these `gtd_mgmt.append_work_log` fields", markdown)
        self.assertIn("codex_project", markdown)
        self.assertIn("work_completed", markdown)
        self.assertIn("no structured gtd_mgmt work-log found", markdown)
        self.assertLess(markdown.index("## Resume Warnings"), markdown.index("## Context For The Target Project Thread"))


class ResolveExplicitPathTests(unittest.TestCase):
    def test_explicit_path_exists_returns_high_confidence(self):
        result = resolve_codex_project_path(
            "swtandy/personal-management",
            explicit_path=str(REPO_ROOT),
        )
        self.assertEqual(result["path"], str(REPO_ROOT))
        self.assertEqual(result["confidence"], "high")
        self.assertEqual(result["source"], "explicit codex_project_path from work log")
        self.assertTrue(result["exists"])
        self.assertNotIn("warning", result)

    def test_explicit_path_nonexistent_returns_low_confidence_with_warning(self):
        result = resolve_codex_project_path(
            "swtandy/personal-management",
            explicit_path="/nonexistent/path/that/does/not/exist",
        )
        self.assertEqual(result["path"], "/nonexistent/path/that/does/not/exist")
        self.assertEqual(result["confidence"], "low")
        self.assertFalse(result["exists"])
        self.assertIn("warning", result)
        self.assertNotEqual(result["path"], "/")


class WorkLogCodexAppProjectTests(unittest.TestCase):
    """Tests for _codex_app_project_from_work_log and the build_resume_handoff_markdown integration."""

    def _make_context(self, extra_parsed=None):
        """Minimal context with no codex_project in the work log."""
        parsed = {
            "work_completed": ["Did some work."],
            "current_state": ["In progress."],
            "next_steps": ["Fix the bug."],
            "blockers_open_questions": [],
            "useful_context": [],
        }
        if extra_parsed:
            parsed.update(extra_parsed)
        return {
            "ok": True,
            "repo": "swtandy/personal-management",
            "issue_number": 10,
            "url": "https://github.com/swtandy/personal-management/issues/10",
            "title": "Do the thing",
            "state": "OPEN",
            "project": {"title": "Personal Management", "number": 2, "status": "This Week", "priority": "P2-High"},
            "resume_summary": {"where_we_left_off": "Debugging.", "next_action": "Fix it.", "blockers": []},
            "latest_work_log": {"parsed": parsed},
            "warnings": [],
        }

    def _workspace(self, path=None):
        return {
            "path": path or str(REPO_ROOT),
            "source": "test",
            "confidence": "high",
        }

    def test_work_log_codex_project_and_path_used_for_recommended_section(self):
        wl_path = str(Path.home())
        ctx = self._make_context({
            "codex_project": ["OxCore Low Level"],
            "codex_project_path": [wl_path],
        })
        markdown = build_resume_handoff_markdown(ctx, self._workspace())

        self.assertIn("`codex_project`: OxCore Low Level", markdown)
        self.assertIn(f"`codex_project_path`: {wl_path}", markdown)
        rec_section = markdown.split("## Recommended Codex Project")[1].split("## Related")[0]
        self.assertNotIn("Fallback", rec_section)
        self.assertIn("Recommended Codex project: OxCore Low Level", markdown)
        self.assertIn("high", rec_section)

    def test_codex_app_project_from_work_log_helper_extracts_name_and_path(self):
        result = _codex_app_project_from_work_log({
            "codex_project": ["MyProject"],
            "codex_project_path": [str(Path.home())],
        })
        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "MyProject")
        self.assertEqual(result["path"], str(Path.home()))
        self.assertEqual(result["confidence"], "high")
        self.assertTrue(result["exists"])

    def test_unresolvable_work_log_path_never_yields_slash_for_workspace(self):
        ctx = self._make_context({
            "codex_project": ["OxCore Low Level / mobile"],
        })
        markdown = build_resume_handoff_markdown(ctx, {"path": "", "source": "unresolved", "confidence": "unknown"})

        impl_section = markdown.split("## Related Local Workspaces")[1].split("##")[0]
        self.assertNotIn("`implementation_workspace`: `/`", impl_section)
        self.assertNotIn("`implementation_workspace`: ``", impl_section)
        self.assertIn("Unresolved", impl_section)
        self.assertIn("implementation_workspace could not be resolved", markdown)

    def test_codex_app_project_from_work_log_returns_none_when_absent(self):
        self.assertIsNone(_codex_app_project_from_work_log({}))
        self.assertIsNone(_codex_app_project_from_work_log({"work_completed": ["stuff"]}))

    def test_no_work_log_codex_project_falls_back_with_low_confidence(self):
        ctx = self._make_context()
        with patch.dict(
            "os.environ",
            {
                "CODEX_APP_PROJECT_NAME": "SWT Personal Management",
                "CODEX_APP_PROJECT_PATH": "/Users/scotttandy/Documents/Claude/Projects/SWT Personal Management",
            },
        ):
            markdown = build_resume_handoff_markdown(ctx, self._workspace())

        rec_section = markdown.split("## Recommended Codex Project")[1].split("##")[0]
        self.assertIn("SWT Personal Management", rec_section)
        self.assertIn("low", rec_section)
        self.assertIn("Fallback", rec_section)


class PathsWithSpacesTests(unittest.TestCase):
    """Paths containing spaces must not be truncated at the first space token."""

    def _ctx(self, extra_parsed):
        parsed = {"work_completed": ["Did work."], "current_state": ["In progress."]}
        parsed.update(extra_parsed)
        return {
            "ok": True,
            "repo": "swtandy/personal-management",
            "issue_number": 11,
            "url": "https://github.com/swtandy/personal-management/issues/11",
            "title": "FGPA work",
            "state": "OPEN",
            "project": {},
            "resume_summary": {},
            "latest_work_log": {"parsed": parsed},
            "warnings": [],
        }

    def test_codex_project_path_with_spaces_preserved_in_recommended_section(self):
        ctx = self._ctx({
            "codex_project": ["FGPA Planning"],
            "codex_project_path": ["/Users/scotttandy/Documents/FGPA Planning"],
        })
        workspace = resolve_codex_project_for_context(ctx, "swtandy/personal-management")
        markdown = build_resume_handoff_markdown(ctx, workspace)

        rec = markdown.split("## Recommended Codex Project")[1].split("##")[0]
        self.assertIn("`codex_project`: FGPA Planning", rec)
        self.assertIn("`codex_project_path`: /Users/scotttandy/Documents/FGPA Planning", rec)
        self.assertNotIn("`codex_project_path`: /Users/scotttandy/Documents/FGPA\n", rec)

    def test_semicolon_separated_related_workspaces_with_spaces(self):
        ctx = self._ctx({
            "related_local_workspaces": [
                "/Users/scotttandy/Documents/FGPA Planning; "
                "/Users/scotttandy/Documents/repos/oxpython; "
                "/Users/scotttandy/Documents/Claude/Projects/SWT Personal Management"
            ],
        })
        result = resolve_codex_project_for_context(ctx, "swtandy/personal-management")

        self.assertEqual(result["path"], "/Users/scotttandy/Documents/FGPA Planning")
        self.assertNotEqual(result["path"], "/Users/scotttandy/Documents/FGPA")
        self.assertNotEqual(result["path"], "/")

    def test_single_workspace_with_spaces_not_truncated(self):
        ctx = self._ctx({
            "related_local_workspaces": ["/Users/scotttandy/Documents/FGPA Planning"],
        })
        result = resolve_codex_project_for_context(ctx, "swtandy/personal-management")

        self.assertEqual(result["path"], "/Users/scotttandy/Documents/FGPA Planning")
        self.assertNotEqual(result["path"], "/Users/scotttandy/Documents/FGPA")

    def test_implementation_workspace_in_markdown_uses_full_path_with_spaces(self):
        wl_path = "/Users/scotttandy/Documents/FGPA Planning"
        ctx = self._ctx({
            "codex_project": ["FGPA Planning"],
            "codex_project_path": [wl_path],
            "related_local_workspaces": [wl_path],
        })
        workspace = resolve_codex_project_for_context(ctx, "swtandy/personal-management")
        markdown = build_resume_handoff_markdown(ctx, workspace)

        impl_section = markdown.split("## Related Local Workspaces")[1].split("##")[0]
        self.assertIn(f"`implementation_workspace`: `{wl_path}`", impl_section)
        self.assertNotIn("`implementation_workspace`: `/Users/scotttandy/Documents/FGPA`", impl_section)
        self.assertNotIn("`implementation_workspace`: `Unresolved", impl_section)


class DefaultCodexAppProjectTests(unittest.TestCase):
    def test_uses_repo_root_when_no_env_vars_set(self):
        with patch.dict("os.environ", {}, clear=False) as env:
            env.pop("CODEX_APP_PROJECT_PATH", None)
            env.pop("CODEX_APP_PROJECT_NAME", None)
            result = _default_codex_app_project()
        self.assertEqual(result["path"], str(REPO_ROOT))
        self.assertEqual(result["name"], REPO_ROOT.name)
        self.assertTrue(result["exists"])

    def test_env_var_override_still_works(self):
        with patch.dict(
            "os.environ",
            {
                "CODEX_APP_PROJECT_NAME": "My GTD Workspace",
                "CODEX_APP_PROJECT_PATH": "/tmp/my-gtd",
            },
        ):
            result = _default_codex_app_project()
        self.assertEqual(result["path"], "/tmp/my-gtd")
        self.assertEqual(result["name"], "My GTD Workspace")


if __name__ == "__main__":
    unittest.main()
