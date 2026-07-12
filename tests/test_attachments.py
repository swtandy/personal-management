import base64
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("GITHUB_TOKEN", "test-token")

import attachments
from github_client import ManifestConflict

PNG_HEADER = b"\x89PNG\r\n\x1a\n"
ZIP_HEADER = b"PK\x03\x04"
PDF_HEADER = b"%PDF-1.4\n"
MZ_HEADER = b"MZ\x90\x00\x03"


def _write_temp_file(suffix: str, content: bytes) -> str:
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as f:
        f.write(content)
    return path


class FakeGitHubClient:
    """In-memory stand-in for GitHubClient's Contents API surface used by attachments.py."""

    def __init__(self):
        self.files: dict[str, dict] = {}
        self.blobs: dict[str, bytes] = {}
        self.branch_sha: str | None = None
        self.private = False
        self.comments: list[dict] = []
        self._next_comment_id = 1
        self.put_calls: list[str] = []
        self.conflict_once_for: str | None = None
        self.issue_body = ""

    def ensure_orphan_branch(self, repo, branch, readme_text):
        if self.branch_sha is None:
            self.branch_sha = "root-commit-sha"
        return self.branch_sha

    def get_branch_sha(self, repo, branch):
        return self.branch_sha

    def get_repo_visibility(self, repo):
        return self.private

    def get_file_contents(self, repo, path, ref):
        entry = self.files.get(path)
        if entry is None:
            return None
        return {"sha": entry["sha"], "content": entry["content"]}

    def put_file_contents(self, repo, path, content, message, branch, sha=None):
        self.put_calls.append(path)
        if self.conflict_once_for == path:
            self.conflict_once_for = None
            raise ManifestConflict("conflict")
        existing = self.files.get(path)
        if sha is not None and (existing is None or existing["sha"] != sha):
            raise ManifestConflict("stale sha")
        new_sha = hashlib.sha1(content).hexdigest()
        self.files[path] = {"sha": new_sha, "content": content}
        self.blobs[new_sha] = content
        self.branch_sha = f"commit-{len(self.put_calls)}"
        return {"sha": new_sha, "commit_sha": self.branch_sha}

    def get_git_blob(self, repo, sha):
        return self.blobs.get(sha)

    def delete_file_contents(self, repo, path, message, branch, sha):
        self.files.pop(path, None)
        return {}

    def add_issue_comment(self, repo, issue_number, body):
        comment = {
            "id": self._next_comment_id,
            "body": body,
            "url": f"https://github.com/{repo}/issues/{issue_number}#comment-{self._next_comment_id}",
        }
        self._next_comment_id += 1
        self.comments.append(comment)
        return comment

    def update_issue_comment(self, repo, comment_id, body):
        for c in self.comments:
            if c["id"] == comment_id:
                c["body"] = body
                return c
        raise ValueError("comment not found")

    def get_issue_comments(self, repo, issue_number, limit=20):
        return list(self.comments[-limit:])

    def get_issue(self, repo, issue_number):
        return {"body": self.issue_body}

    def update_issue_body(self, repo, issue_number, body):
        self.issue_body = body
        return {"body": body}

    # -- Minimal stubs so this fake can also stand in for _apply_create_issue /
    #    _apply_capture_issue wiring tests in test_project_gui.py. --
    def create_issue(self, repo, title, body="", labels=None):
        self.issue_body = body
        return {"number": 123, "title": title, "html_url": f"https://github.com/{repo}/issues/123", "node_id": "node-id"}

    def get_project(self, user, number):
        return {"id": "project-id", "fields": {"nodes": []}}

    def add_issue_to_project(self, project_id, issue_node_id):
        return "item-id"

    def update_project_field_by_name(self, project_id, item_id, project, field_name, option_name):
        return None

    def set_issue_parent_by_number(self, repo, issue_number, parent_repo, parent_issue_number):
        return None


class SlugifyTests(unittest.TestCase):
    def test_lowercases_and_strips_special_characters(self):
        self.assertEqual(attachments.slugify("Deck Layout v2 (final).png"), "deck-layout-v2-final-png")

    def test_falls_back_to_file_when_empty(self):
        self.assertEqual(attachments.slugify("***"), "file")

    def test_truncates_to_60_chars(self):
        self.assertEqual(len(attachments.slugify("a" * 100)), 60)


class SecretScanTests(unittest.TestCase):
    def test_detects_aws_access_key(self):
        self.assertEqual(attachments.secret_scan("key=AKIAABCDEFGHIJKLMNOP"), "aws_access_key_id")

    def test_detects_private_key_block(self):
        self.assertEqual(
            attachments.secret_scan("-----BEGIN RSA PRIVATE KEY-----\nMIIB...\n-----END RSA PRIVATE KEY-----"),
            "private_key_block",
        )

    def test_returns_none_for_clean_text(self):
        self.assertIsNone(attachments.secret_scan("just some notes about the deck layout"))


class ValidateAttachmentTests(unittest.TestCase):
    def setUp(self):
        self._paths: list[str] = []

    def tearDown(self):
        for path in self._paths:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass

    def _temp(self, suffix: str, content: bytes) -> str:
        path = _write_temp_file(suffix, content)
        self._paths.append(path)
        return path

    def test_valid_png_passes_validation(self):
        content = PNG_HEADER + b"0" * 32
        path = self._temp(".png", content)

        result = attachments.validate_attachment(path)

        self.assertEqual(result["ext"], "png")
        self.assertEqual(result["category"], "image")
        self.assertTrue(result["inline"])
        self.assertEqual(result["sha256"], hashlib.sha256(content).hexdigest())

    def test_blocked_extension_rejected(self):
        path = self._temp(".exe", MZ_HEADER + b"0" * 32)
        with self.assertRaisesRegex(ValueError, "blocked"):
            attachments.validate_attachment(path)

    def test_extension_not_in_allowlist_rejected(self):
        path = self._temp(".xyz", b"some content")
        with self.assertRaisesRegex(ValueError, "not in the attachment allowlist"):
            attachments.validate_attachment(path)

    def test_empty_file_rejected(self):
        path = self._temp(".png", b"")
        with self.assertRaisesRegex(ValueError, "empty"):
            attachments.validate_attachment(path)

    def test_symlink_rejected(self):
        real_path = self._temp(".png", PNG_HEADER + b"0" * 32)
        link_path = real_path + ".link.png"
        os.symlink(real_path, link_path)
        self._paths.append(link_path)
        with self.assertRaisesRegex(ValueError, "symlinks"):
            attachments.validate_attachment(link_path)

    def test_extension_content_mismatch_rejected(self):
        path = self._temp(".png", b"this is not actually a png file at all")
        with self.assertRaisesRegex(ValueError, "does not match the expected format"):
            attachments.validate_attachment(path)

    def test_executable_renamed_to_allowed_extension_rejected(self):
        path = self._temp(".png", MZ_HEADER + b"0" * 32)
        with self.assertRaisesRegex(ValueError, "blocked signature"):
            attachments.validate_attachment(path)

    def test_secret_in_text_file_rejected(self):
        path = self._temp(".txt", b"aws_key = AKIAABCDEFGHIJKLMNOP")
        with self.assertRaisesRegex(ValueError, "secret pattern"):
            attachments.validate_attachment(path)

    def test_over_category_cap_rejected(self):
        path = self._temp(".txt", b"hello world, this is more than five bytes")
        with patch.dict(attachments.EXTENSION_TABLE, {"txt": {**attachments.EXTENSION_TABLE["txt"], "cap": 5}}):
            with self.assertRaisesRegex(ValueError, "capped at"):
                attachments.validate_attachment(path)

    def test_over_hard_ceiling_rejected(self):
        path = self._temp(".txt", b"hello world, this is more than five bytes")
        with patch.object(attachments, "HARD_CEILING_BYTES", 5):
            with self.assertRaisesRegex(ValueError, "hard ceiling"):
                attachments.validate_attachment(path)

    def test_name_override_controls_slug(self):
        path = self._temp(".png", PNG_HEADER + b"0" * 32)
        result = attachments.validate_attachment(path, name_override="Deck Plan Final")
        self.assertEqual(result["slug"], "deck-plan-final")


class ManifestHelperTests(unittest.TestCase):
    def test_get_manifest_returns_empty_when_missing(self):
        client = FakeGitHubClient()
        manifest = attachments.get_manifest(client, "owner/repo", 1)
        self.assertEqual(manifest, {"entries": [], "sha": None})

    def test_mutate_manifest_with_retry_recovers_from_conflict(self):
        client = FakeGitHubClient()
        client.files["issues/1/manifest.json"] = {"sha": "sha0", "content": b"[]"}
        client.conflict_once_for = "issues/1/manifest.json"

        entries = attachments._mutate_manifest_with_retry(
            client, "owner/repo", 1, lambda e: e.append({"path": "x"}),
        )

        self.assertEqual(entries, [{"path": "x"}])
        stored = json.loads(client.files["issues/1/manifest.json"]["content"])
        self.assertEqual(stored, [{"path": "x"}])


class AttachFileTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeGitHubClient()
        self._paths: list[str] = []

    def tearDown(self):
        for path in self._paths:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass

    def _png(self) -> str:
        path = _write_temp_file(".png", PNG_HEADER + b"0" * 32)
        self._paths.append(path)
        return path

    def test_uploads_and_posts_comment_with_embed(self):
        result = attachments.attach_file(self.client, "owner/repo", 42, self._png(), caption="Floor plan")

        self.assertTrue(result["ok"])
        self.assertTrue(result["rendered"])
        self.assertFalse(result["deduplicated"])
        self.assertTrue(result["raw_url"].startswith("https://raw.githubusercontent.com/owner/repo/"))
        self.assertEqual(len(self.client.comments), 1)
        self.assertIn("![Floor plan]", self.client.comments[0]["body"])

        manifest = json.loads(self.client.files["issues/42/manifest.json"]["content"])
        self.assertEqual(len(manifest), 1)
        self.assertEqual(manifest[0]["caption"], "Floor plan")

    def test_reattaching_identical_content_deduplicates_blob_but_posts_new_comment(self):
        png_path = self._png()
        first = attachments.attach_file(self.client, "owner/repo", 42, png_path)
        second = attachments.attach_file(self.client, "owner/repo", 42, png_path)

        self.assertFalse(first["deduplicated"])
        self.assertTrue(second["deduplicated"])
        self.assertEqual(first["path"], second["path"])
        self.assertEqual(len(self.client.comments), 2)
        manifest = json.loads(self.client.files["issues/42/manifest.json"]["content"])
        self.assertEqual(len(manifest), 1)

    def test_mode_none_uploads_without_posting_comment(self):
        result = attachments.attach_file(self.client, "owner/repo", 42, self._png(), mode="none")
        self.assertTrue(result["ok"])
        self.assertEqual(self.client.comments, [])

    def test_private_repo_reports_not_rendered_and_links_instead_of_embeds(self):
        self.client.private = True
        result = attachments.attach_file(self.client, "owner/repo", 42, self._png())

        self.assertFalse(result["rendered"])
        self.assertIn("reason", result)
        self.assertTrue(self.client.comments[0]["body"].startswith("["))

    def test_body_append_mode_appends_to_issue_body_without_commenting(self):
        self.client.issue_body = "Original body"
        result = attachments.attach_file(self.client, "owner/repo", 42, self._png(), mode="body_append")

        self.assertTrue(result["ok"])
        self.assertTrue(self.client.issue_body.startswith("Original body"))
        self.assertIn(result["raw_url"], self.client.issue_body)
        self.assertEqual(self.client.comments, [])

    def test_exceeding_per_issue_budget_raises(self):
        self.client.files["issues/42/manifest.json"] = {
            "sha": "sha0",
            "content": json.dumps([{"path": "issues/42/big.png", "size_bytes": 1000, "content_sha256": "x"}]).encode(),
        }
        with self.assertRaisesRegex(ValueError, "attachment budget"):
            attachments.attach_file(self.client, "owner/repo", 42, self._png(), max_total_per_issue_bytes=10)


class UpdateFileTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeGitHubClient()
        self._paths: list[str] = []

    def tearDown(self):
        for path in self._paths:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass

    def _png(self, filler: bytes = b"0" * 32) -> str:
        path = _write_temp_file(".png", PNG_HEADER + filler)
        self._paths.append(path)
        return path

    def test_update_supersedes_old_entry_and_posts_new_comment(self):
        original = attachments.attach_file(self.client, "owner/repo", 7, self._png())
        result = attachments.update_file(self.client, "owner/repo", 7, original["path"], self._png(b"1" * 40))

        self.assertTrue(result["ok"])
        self.assertEqual(result["old_path"], original["path"])
        self.assertNotEqual(result["new_path"], original["path"])

        manifest = json.loads(self.client.files["issues/7/manifest.json"]["content"])
        old_entry = next(e for e in manifest if e["path"] == original["path"])
        self.assertEqual(old_entry["superseded_by"], result["new_path"])
        self.assertEqual(len(self.client.comments), 2)  # original attach comment + update comment

    def test_update_missing_path_raises(self):
        with self.assertRaisesRegex(ValueError, "no manifest entry"):
            attachments.update_file(self.client, "owner/repo", 7, "issues/7/missing.png", self._png())


class DeleteFileTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeGitHubClient()
        self._paths: list[str] = []

    def tearDown(self):
        for path in self._paths:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass

    def _png(self) -> str:
        path = _write_temp_file(".png", PNG_HEADER + b"0" * 32)
        self._paths.append(path)
        return path

    def test_delete_marks_deleted_and_warns_about_references(self):
        attached = attachments.attach_file(self.client, "owner/repo", 3, self._png())
        result = attachments.delete_file(self.client, "owner/repo", 3, attached["path"], handle_references="warn")

        self.assertTrue(result["deleted"])
        self.assertEqual(len(result["references"]), 1)
        self.assertNotIn(attached["path"], self.client.files)
        manifest = json.loads(self.client.files["issues/3/manifest.json"]["content"])
        self.assertTrue(manifest[0]["deleted"])
        # comment body untouched in warn mode
        self.assertNotIn("deleted", self.client.comments[0]["body"])

    def test_delete_with_annotate_appends_notice_to_referencing_comments(self):
        attached = attachments.attach_file(self.client, "owner/repo", 3, self._png())
        attachments.delete_file(self.client, "owner/repo", 3, attached["path"], handle_references="annotate")

        self.assertIn("attachment deleted", self.client.comments[0]["body"])

    def test_delete_missing_path_raises(self):
        with self.assertRaisesRegex(ValueError, "no manifest entry"):
            attachments.delete_file(self.client, "owner/repo", 3, "issues/3/missing.png")


class ListFilesTests(unittest.TestCase):
    def test_empty_manifest_returns_empty_list_not_error(self):
        client = FakeGitHubClient()
        result = attachments.list_files(client, "owner/repo", 99)
        self.assertTrue(result["ok"])
        self.assertEqual(result["attachments"], [])

    def test_flags_superseded_and_deleted_entries(self):
        client = FakeGitHubClient()
        path = _write_temp_file(".png", PNG_HEADER + b"0" * 32)
        try:
            attached = attachments.attach_file(client, "owner/repo", 5, path)
            attachments.delete_file(client, "owner/repo", 5, attached["path"])
            result = attachments.list_files(client, "owner/repo", 5)
            self.assertEqual(result["count"], 1)
            self.assertTrue(result["attachments"][0]["deleted"])
        finally:
            os.unlink(path)


class GetFileTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeGitHubClient()
        self.source = _write_temp_file(".png", PNG_HEADER + b"retrievable-image")
        self.attached = attachments.attach_file(
            self.client, "owner/repo", 12, self.source, mode="none",
        )

    def tearDown(self):
        os.unlink(self.source)

    def test_retrieves_base64_by_each_unique_selector(self):
        manifest_entry = json.loads(self.client.files["issues/12/manifest.json"]["content"])[0]
        expected = Path(self.source).read_bytes()
        for selector in ("original_name", "path", "content_sha256", "git_sha"):
            with self.subTest(selector=selector):
                result = attachments.get_file(
                    self.client, "owner/repo", 12, **{selector: manifest_entry[selector]},
                )
                self.assertTrue(result["ok"])
                self.assertTrue(result["verified_sha256"])
                self.assertEqual(base64.b64decode(result["content_base64"]), expected)

    def test_write_is_atomic_and_refuses_overwrite_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "nested" / "retrieved.png"
            result = attachments.get_file(
                self.client, "owner/repo", 12,
                path=self.attached["path"], output="write", dest_path=str(destination),
            )
            self.assertTrue(result["ok"])
            self.assertEqual(destination.read_bytes(), Path(self.source).read_bytes())
            duplicate = attachments.get_file(
                self.client, "owner/repo", 12,
                path=self.attached["path"], output="write", dest_path=str(destination),
            )
            self.assertEqual(duplicate["error"]["code"], "destination_exists")

    def test_requires_exactly_one_selector(self):
        result = attachments.get_file(self.client, "owner/repo", 12)
        self.assertEqual(result["error"]["code"], "invalid_selector")
        result = attachments.get_file(
            self.client, "owner/repo", 12,
            original_name=Path(self.source).name, path=self.attached["path"],
        )
        self.assertEqual(result["error"]["code"], "invalid_selector")

    def test_missing_selector_lists_candidates(self):
        result = attachments.get_file(self.client, "owner/repo", 12, path="issues/12/missing.png")
        self.assertEqual(result["error"]["code"], "attachment_not_found")
        self.assertEqual(result["error"]["details"]["candidates"][0]["path"], self.attached["path"])

    def test_hash_mismatch_is_a_hard_error(self):
        self.client.files[self.attached["path"]]["content"] = b"tampered"
        manifest_entry = json.loads(self.client.files["issues/12/manifest.json"]["content"])[0]
        self.client.blobs[manifest_entry["git_sha"]] = b"also-tampered"
        result = attachments.get_file(self.client, "owner/repo", 12, path=self.attached["path"])
        self.assertEqual(result["error"]["code"], "hash_mismatch")

    def test_deleted_attachment_can_be_retrieved_from_git_blob_when_requested(self):
        expected = Path(self.source).read_bytes()
        attachments.delete_file(self.client, "owner/repo", 12, self.attached["path"])
        hidden = attachments.get_file(self.client, "owner/repo", 12, path=self.attached["path"])
        self.assertEqual(hidden["error"]["code"], "attachment_deleted")
        result = attachments.get_file(
            self.client, "owner/repo", 12, path=self.attached["path"], include_deleted=True,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(base64.b64decode(result["content_base64"]), expected)

    def test_inline_size_guard(self):
        result = attachments.get_file(
            self.client, "owner/repo", 12, path=self.attached["path"], max_inline_bytes=1,
        )
        self.assertEqual(result["error"]["code"], "inline_size_exceeded")

    def test_size_mismatch_is_a_hard_error(self):
        manifest = json.loads(self.client.files["issues/12/manifest.json"]["content"])
        manifest[0]["size_bytes"] += 1
        self.client.files["issues/12/manifest.json"]["content"] = json.dumps(manifest).encode()
        result = attachments.get_file(self.client, "owner/repo", 12, path=self.attached["path"])
        self.assertEqual(result["error"]["code"], "size_mismatch")

    def test_invalid_manifest_metadata_is_rejected(self):
        manifest = json.loads(self.client.files["issues/12/manifest.json"]["content"])
        manifest[0]["content_sha256"] = "not-a-hash"
        self.client.files["issues/12/manifest.json"]["content"] = json.dumps(manifest).encode()
        result = attachments.get_file(self.client, "owner/repo", 12, path=self.attached["path"])
        self.assertEqual(result["error"]["code"], "invalid_manifest")

    def test_invalid_manifest_path_is_rejected(self):
        manifest = json.loads(self.client.files["issues/12/manifest.json"]["content"])
        manifest[0]["path"] = "issues/12/../../secret.png"
        self.client.files["issues/12/manifest.json"]["content"] = json.dumps(manifest).encode()
        result = attachments.get_file(
            self.client, "owner/repo", 12, path="issues/12/../../secret.png",
        )
        self.assertEqual(result["error"]["code"], "invalid_manifest_path")

    def test_stale_branch_copy_falls_back_to_verified_blob_with_warning(self):
        self.client.files[self.attached["path"]]["content"] = b"stale"
        result = attachments.get_file(self.client, "owner/repo", 12, path=self.attached["path"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["warnings"][0]["code"], "working_copy_stale")

    def test_unavailable_branch_copy_and_blob_returns_error(self):
        manifest = json.loads(self.client.files["issues/12/manifest.json"]["content"])[0]
        self.client.files.pop(self.attached["path"])
        self.client.blobs.pop(manifest["git_sha"])
        result = attachments.get_file(self.client, "owner/repo", 12, path=self.attached["path"])
        self.assertEqual(result["error"]["code"], "blob_unavailable")

    def test_overwrite_true_replaces_existing_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "retrieved.png"
            destination.write_bytes(b"old")
            result = attachments.get_file(
                self.client, "owner/repo", 12, path=self.attached["path"],
                output="write", dest_path=str(destination), overwrite=True,
            )
            self.assertTrue(result["ok"])
            self.assertEqual(destination.read_bytes(), Path(self.source).read_bytes())


class GetFilesTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeGitHubClient()
        self.first = _write_temp_file("-first.png", PNG_HEADER + b"first")
        self.second = _write_temp_file("-second.png", PNG_HEADER + b"second")
        self.first_attached = attachments.attach_file(self.client, "owner/repo", 20, self.first, mode="none")
        self.second_attached = attachments.attach_file(self.client, "owner/repo", 20, self.second, mode="none")

    def tearDown(self):
        os.unlink(self.first)
        os.unlink(self.second)

    def test_retrieves_all_current_files(self):
        with tempfile.TemporaryDirectory() as directory:
            result = attachments.get_files(self.client, "owner/repo", 20, directory)
            self.assertTrue(result["ok"])
            self.assertEqual(result["succeeded_count"], 2)
            self.assertEqual((Path(directory) / Path(self.first).name).read_bytes(), Path(self.first).read_bytes())
            self.assertEqual((Path(directory) / Path(self.second).name).read_bytes(), Path(self.second).read_bytes())

    def test_mime_prefix_filters_selection(self):
        manifest = json.loads(self.client.files["issues/20/manifest.json"]["content"])
        manifest[1]["mime"] = "application/octet-stream"
        self.client.files["issues/20/manifest.json"]["content"] = json.dumps(manifest).encode()
        with tempfile.TemporaryDirectory() as directory:
            result = attachments.get_files(self.client, "owner/repo", 20, directory, mime_prefix="image/")
            self.assertTrue(result["ok"])
            self.assertEqual(result["selected_count"], 1)

    def test_duplicate_original_names_are_rejected_before_writes(self):
        manifest = json.loads(self.client.files["issues/20/manifest.json"]["content"])
        manifest[1]["original_name"] = manifest[0]["original_name"]
        self.client.files["issues/20/manifest.json"]["content"] = json.dumps(manifest).encode()
        with tempfile.TemporaryDirectory() as directory:
            result = attachments.get_files(self.client, "owner/repo", 20, directory)
            self.assertEqual(result["error"]["code"], "destination_name_collision")
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_batch_size_limit_is_enforced_before_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            result = attachments.get_files(self.client, "owner/repo", 20, directory, max_total_bytes=1)
            self.assertEqual(result["error"]["code"], "batch_size_exceeded")
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_partial_failure_continues_by_default(self):
        self.client.files[self.first_attached["path"]]["content"] = b"bad"
        manifest = json.loads(self.client.files["issues/20/manifest.json"]["content"])
        first_entry = next(entry for entry in manifest if entry["path"] == self.first_attached["path"])
        self.client.blobs[first_entry["git_sha"]] = b"also-bad"
        with tempfile.TemporaryDirectory() as directory:
            result = attachments.get_files(self.client, "owner/repo", 20, directory)
            self.assertFalse(result["ok"])
            self.assertEqual(result["processed_count"], 2)
            self.assertEqual(result["succeeded_count"], 1)
            self.assertEqual(result["failed_count"], 1)

    def test_fail_fast_stops_after_first_failure(self):
        self.client.files[self.first_attached["path"]]["content"] = b"bad"
        manifest = json.loads(self.client.files["issues/20/manifest.json"]["content"])
        first_entry = next(entry for entry in manifest if entry["path"] == self.first_attached["path"])
        self.client.blobs[first_entry["git_sha"]] = b"also-bad"
        with tempfile.TemporaryDirectory() as directory:
            result = attachments.get_files(self.client, "owner/repo", 20, directory, fail_fast=True)
            self.assertFalse(result["ok"])
            self.assertEqual(result["processed_count"], 1)


class AttachManyAndBuildSectionTests(unittest.TestCase):
    def test_builds_combined_markdown_and_skips_failures(self):
        client = FakeGitHubClient()
        png_path = _write_temp_file(".png", PNG_HEADER + b"0" * 32)
        try:
            section = attachments.attach_many_and_build_section(
                client, "owner/repo", 11,
                [
                    {"file_path": png_path, "caption": "Plan A"},
                    {"file_path": "/nonexistent/missing.png", "caption": "Plan B"},
                ],
            )
            self.assertIn("![Plan A]", section["markdown"])
            self.assertEqual(len(section["results"]), 2)
            self.assertTrue(section["results"][0]["ok"])
            self.assertFalse(section["results"][1]["ok"])
        finally:
            os.unlink(png_path)

    def test_empty_attachments_returns_empty_section(self):
        client = FakeGitHubClient()
        section = attachments.attach_many_and_build_section(client, "owner/repo", 11, [])
        self.assertEqual(section, {"markdown": "", "results": []})


if __name__ == "__main__":
    unittest.main()
