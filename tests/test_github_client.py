import base64
import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("GITHUB_TOKEN", "test-token")

from github_client import (
    GitHubClient,
    ManifestConflict,
    WORK_LOG_MARKER,
    build_field_map,
    format_work_log_comment,
    parse_work_log_body,
)


class GitHubClientTests(unittest.TestCase):
    def test_set_issue_parent_sends_parent_as_issue_and_child_as_sub_issue(self):
        client = GitHubClient(token="test-token")
        client.graphql = Mock(return_value={})

        client.set_issue_parent("child-node-id", "parent-node-id")

        mutation, variables = client.graphql.call_args.args
        self.assertIn("issueId: $parentId", mutation)
        self.assertIn("subIssueId: $childId", mutation)
        self.assertEqual(
            variables,
            {"parentId": "parent-node-id", "childId": "child-node-id"},
        )

    def test_parse_item_includes_parent_repo_for_cross_repo_trees(self):
        client = GitHubClient(token="test-token")
        parsed = client.parse_item({
            "id": "project-item-id",
            "fieldValues": {"nodes": []},
            "content": {
                "id": "issue-id",
                "number": 2,
                "title": "Child",
                "repository": {"nameWithOwner": "owner/child-repo"},
                "labels": {"nodes": []},
                "assignees": {"nodes": []},
                "parent": {
                    "number": 1,
                    "title": "Parent",
                    "repository": {"nameWithOwner": "owner/parent-repo"},
                },
                "trackedIssues": {"nodes": []},
            },
        })

        self.assertEqual(parsed["parent"], (1, "Parent"))
        self.assertEqual(parsed["parent_repo"], "owner/parent-repo")

    def test_format_work_log_comment_includes_resume_sections_and_marker(self):
        body = format_work_log_comment(
            work_completed="- Built MVP",
            current_state="- Tests pass",
            next_steps="- Try it on real issue",
            codex_project="- SWT Personal Management",
            codex_project_path="- /Users/scotttandy/Documents/Claude/Projects/SWT Personal Management",
            related_local_workspaces="- /Users/scotttandy/Documents/Claude/Projects/SWT Personal Management",
            related_github_repos="- swtandy/personal-management",
        )

        self.assertIn(WORK_LOG_MARKER, body)
        self.assertIn("## Work Completed", body)
        self.assertIn("## Current State", body)
        self.assertIn("## Next Steps", body)
        self.assertIn("## Codex Project", body)
        self.assertIn("## Codex Project Path", body)
        self.assertIn("## Related Local Workspaces", body)
        self.assertIn("## Related GitHub Repositories", body)
        self.assertIn("- Built MVP", body)

    def test_parse_work_log_body_returns_resume_sections(self):
        body = "\n".join([
            WORK_LOG_MARKER,
            "",
            "## Work Completed",
            "- Built MVP",
            "",
            "## Current State",
            "- System stood up",
            "",
            "## Next Steps",
            "- Review cleanup labels",
            "",
            "## Blockers / Open Questions",
            "- Decide output stream",
            "",
            "## Codex Project",
            "- SWT Personal Management",
            "",
            "## Codex Project Path",
            "- /Users/scotttandy/Documents/Claude/Projects/SWT Personal Management",
            "",
            "## Related Local Workspaces",
            "- /Users/scotttandy/Documents/Claude/Projects/SWT Personal Management",
            "",
            "## Related GitHub Repositories",
            "- swtandy/personal-management",
            "",
            "## Useful Context",
            "- Priority may be unavailable",
        ])

        parsed = parse_work_log_body(body)

        self.assertEqual(parsed["work_completed"], ["Built MVP"])
        self.assertEqual(parsed["current_state"], ["System stood up"])
        self.assertEqual(parsed["next_steps"], ["Review cleanup labels"])
        self.assertEqual(parsed["blockers_open_questions"], ["Decide output stream"])
        self.assertEqual(parsed["codex_project"], ["SWT Personal Management"])
        self.assertEqual(parsed["codex_project_path"], ["/Users/scotttandy/Documents/Claude/Projects/SWT Personal Management"])
        self.assertEqual(parsed["related_local_workspaces"], ["/Users/scotttandy/Documents/Claude/Projects/SWT Personal Management"])
        self.assertEqual(parsed["related_github_repos"], ["swtandy/personal-management"])
        self.assertEqual(parsed["useful_context"], ["Priority may be unavailable"])

    def test_get_work_logs_returns_parsed_logs_sorted_by_updated_time(self):
        client = GitHubClient(token="test-token")
        client.get_issue_comments = Mock(return_value=[
            {
                "body": "regular comment",
                "updated_at": "2026-06-03T20:00:00Z",
            },
            {
                "body": f"{WORK_LOG_MARKER}\n\n## Current State\n- Older",
                "updated_at": "2026-06-03T21:00:00Z",
            },
            {
                "body": f"{WORK_LOG_MARKER}\n\n## Current State\n- Newer",
                "updated_at": "2026-06-03T22:30:57Z",
            },
        ])

        logs = client.get_work_logs("swtandy/personal-management", 1)

        self.assertEqual(len(logs), 2)
        self.assertEqual(logs[-1]["updated_at"], "2026-06-03T22:30:57Z")
        self.assertEqual(logs[-1]["parsed"]["current_state"], ["Newer"])

    def test_build_field_map_collects_single_select_options(self):
        project = {
            "fields": {
                "nodes": [
                    {"id": "status-id", "name": "Status", "options": [{"name": "Backlog", "id": "opt-backlog"}]},
                    None,
                ]
            }
        }

        self.assertEqual(build_field_map(project), {"Status": {"id": "status-id", "options": {"Backlog": "opt-backlog"}}})

    def test_add_issue_to_project_returns_item_id(self):
        client = GitHubClient(token="test-token")
        client.graphql = Mock(return_value={"addProjectV2ItemById": {"item": {"id": "item-id"}}})

        item_id = client.add_issue_to_project("project-id", "issue-node-id")

        self.assertEqual(item_id, "item-id")
        _, variables = client.graphql.call_args.args
        self.assertEqual(variables, {"projectId": "project-id", "contentId": "issue-node-id"})

    def test_update_project_field_by_name_uses_option_id(self):
        client = GitHubClient(token="test-token")
        client.update_item_field_single_select = Mock()
        project = {
            "fields": {
                "nodes": [
                    {"id": "priority-id", "name": "Priority", "options": [{"name": "P2-High", "id": "p2-id"}]},
                ]
            }
        }

        client.update_project_field_by_name("project-id", "item-id", project, "Priority", "P2-High")

        client.update_item_field_single_select.assert_called_once_with("project-id", "item-id", "priority-id", "p2-id")

    @patch("github_client.requests.post")
    def test_create_issue_posts_to_repo_with_labels(self, mock_post):
        response = Mock()
        response.json.return_value = {"number": 7, "node_id": "issue-node-id"}
        mock_post.return_value = response
        client = GitHubClient(token="test-token")
        client.ensure_label_exists = Mock()

        issue = client.create_issue("owner/repo", "Title", body="Body", labels=["gtd:project"])

        self.assertEqual(issue["node_id"], "issue-node-id")
        client.ensure_label_exists.assert_called_once_with("owner", "repo", "gtd:project")
        mock_post.assert_called_once_with(
            "https://api.github.com/repos/owner/repo/issues",
            json={"title": "Title", "body": "Body", "labels": ["gtd:project"]},
            headers=client.headers,
        )
        response.raise_for_status.assert_called_once()

    def test_set_issue_parent_by_number_removes_old_parent_then_adds_new_parent(self):
        client = GitHubClient(token="test-token")
        client.get_issue_node = Mock(side_effect=[
            {"id": "child-id", "parent": {"id": "old-parent-id"}},
            {"id": "new-parent-id"},
        ])
        client.remove_issue_parent = Mock()
        client.set_issue_parent = Mock()

        client.set_issue_parent_by_number("owner/repo", 2, "owner/repo", 1)

        client.remove_issue_parent.assert_called_once_with("child-id", "old-parent-id")
        client.set_issue_parent.assert_called_once_with("child-id", "new-parent-id")

    def test_format_work_log_comment_omits_attachments_section_when_empty(self):
        body = format_work_log_comment(work_completed="- Did stuff")
        self.assertNotIn("## Attachments", body)

    def test_format_work_log_comment_includes_attachments_section_when_provided(self):
        body = format_work_log_comment(work_completed="- Did stuff", attachments_markdown="![floor plan](https://example.com/a.png)")
        self.assertIn("## Attachments", body)
        self.assertIn("![floor plan](https://example.com/a.png)", body)

    @patch("github_client.requests.get")
    def test_get_file_contents_returns_none_on_404(self, mock_get):
        response = Mock(status_code=404)
        mock_get.return_value = response
        client = GitHubClient(token="test-token")

        result = client.get_file_contents("owner/repo", "issues/1/manifest.json", "gtd-assets")

        self.assertIsNone(result)

    @patch("github_client.requests.get")
    def test_get_file_contents_decodes_base64_content(self, mock_get):
        response = Mock(status_code=200)
        response.json.return_value = {
            "sha": "blob-sha",
            "encoding": "base64",
            "content": base64.b64encode(b"[]").decode("ascii"),
        }
        mock_get.return_value = response
        client = GitHubClient(token="test-token")

        result = client.get_file_contents("owner/repo", "issues/1/manifest.json", "gtd-assets")

        self.assertEqual(result, {"sha": "blob-sha", "content": b"[]"})

    @patch("github_client.requests.get")
    def test_get_git_blob_decodes_base64_content(self, mock_get):
        response = Mock(status_code=200)
        response.json.return_value = {
            "sha": "blob-sha",
            "encoding": "base64",
            "content": base64.b64encode(b"binary-data").decode("ascii"),
        }
        mock_get.return_value = response
        client = GitHubClient(token="test-token")

        result = client.get_git_blob("owner/repo", "blob-sha")

        self.assertEqual(result, b"binary-data")

    @patch("github_client.requests.get")
    def test_get_git_blob_returns_none_on_404(self, mock_get):
        mock_get.return_value = Mock(status_code=404)
        client = GitHubClient(token="test-token")

        self.assertIsNone(client.get_git_blob("owner/repo", "missing-sha"))

    @patch("github_client.requests.put")
    def test_put_file_contents_raises_manifest_conflict_on_409(self, mock_put):
        mock_put.return_value = Mock(status_code=409)
        client = GitHubClient(token="test-token")

        with self.assertRaises(ManifestConflict):
            client.put_file_contents("owner/repo", "issues/1/manifest.json", b"[]", "msg", "gtd-assets", sha="stale-sha")

    @patch("github_client.requests.put")
    def test_put_file_contents_returns_blob_and_commit_sha(self, mock_put):
        response = Mock(status_code=201)
        response.json.return_value = {"content": {"sha": "new-blob-sha"}, "commit": {"sha": "commit-sha"}}
        mock_put.return_value = response
        client = GitHubClient(token="test-token")

        result = client.put_file_contents("owner/repo", "issues/1/file.png", b"data", "msg", "gtd-assets")

        self.assertEqual(result, {"sha": "new-blob-sha", "commit_sha": "commit-sha"})

    @patch("github_client.requests.get")
    def test_ensure_orphan_branch_returns_existing_sha_without_creating(self, mock_get):
        response = Mock(status_code=200)
        response.json.return_value = {"object": {"sha": "existing-sha"}}
        mock_get.return_value = response
        client = GitHubClient(token="test-token")

        sha = client.ensure_orphan_branch("owner/repo", "gtd-assets", "readme text")

        self.assertEqual(sha, "existing-sha")

    @patch("github_client.requests.post")
    @patch("github_client.requests.get")
    def test_ensure_orphan_branch_creates_branch_when_missing(self, mock_get, mock_post):
        mock_get.return_value = Mock(status_code=404)

        blob_resp = Mock(status_code=201); blob_resp.json.return_value = {"sha": "blob-sha"}
        tree_resp = Mock(status_code=201); tree_resp.json.return_value = {"sha": "tree-sha"}
        commit_resp = Mock(status_code=201); commit_resp.json.return_value = {"sha": "commit-sha"}
        ref_resp = Mock(status_code=201)
        mock_post.side_effect = [blob_resp, tree_resp, commit_resp, ref_resp]

        client = GitHubClient(token="test-token")
        sha = client.ensure_orphan_branch("owner/repo", "gtd-assets", "readme text")

        self.assertEqual(sha, "commit-sha")
        self.assertEqual(mock_post.call_count, 4)

    @patch("github_client.requests.post")
    @patch("github_client.requests.get")
    def test_ensure_orphan_branch_handles_concurrent_ref_creation_race(self, mock_get, mock_post):
        mock_get.side_effect = [
            Mock(status_code=404),  # initial check: branch missing
            Mock(status_code=200, json=Mock(return_value={"object": {"sha": "raced-in-sha"}})),  # refetch after 422
        ]
        blob_resp = Mock(status_code=201); blob_resp.json.return_value = {"sha": "blob-sha"}
        tree_resp = Mock(status_code=201); tree_resp.json.return_value = {"sha": "tree-sha"}
        commit_resp = Mock(status_code=201); commit_resp.json.return_value = {"sha": "commit-sha"}
        ref_resp = Mock(status_code=422)
        mock_post.side_effect = [blob_resp, tree_resp, commit_resp, ref_resp]

        client = GitHubClient(token="test-token")
        sha = client.ensure_orphan_branch("owner/repo", "gtd-assets", "readme text")

        self.assertEqual(sha, "raced-in-sha")


if __name__ == "__main__":
    unittest.main()
