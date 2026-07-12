# Work Computer Prompt — Implement Complete gtd_mgmt File Attachments

Copy this entire document into Codex on the work computer while the work version of the `gtd_mgmt` repository is open.

---

## Prompt for Codex

I have an older work-specific version of this `gtd_mgmt` codebase. It predates the file-attachment features described below. Treat this as a **new implementation adapted to this repository**, not as a request to blindly cherry-pick personal-repository commits or assume identical paths.

First inspect the repository, its local instructions, current MCP/GUI architecture, GitHub client, tests, skills, plugin packaging, and sync/deployment documentation. Identify the closest integration points and compare them with this specification. Then propose a concise implementation plan and call out any conflicts or environment-specific decisions. Unless a material security or architecture decision requires my input, proceed to implement the proven baseline, add tests, run the complete test suite, update the relevant skill/plugin documentation, and stop for my review before committing. Do not push, deploy, or commit until I explicitly approve those actions.

### Objective

Add a robust file-attachment subsystem to `gtd_mgmt` that supports:

- Adding validated files to GitHub issues.
- Adding files inline while creating issues, capturing source material, adding comments, or appending structured work logs.
- Listing attachment metadata and lifecycle state.
- Replacing attachments while retaining version history.
- Soft-deleting attachments and reporting or annotating references.
- Retrieving one verified attachment as base64 or by writing it locally.
- Retrieving a filtered batch of verified attachments into a directory.
- Working with private repositories without requiring the MCP caller to hold a GitHub token or directly reach GitHub content hosts.

The MCP server remains the trusted authenticated boundary. The caller supplies local input/output paths, but GitHub authentication stays inside the server.

## 1. Inspect and adapt before editing

Determine:

1. Where MCP tools are registered.
2. Whether tool calls go directly to GitHub or are mediated through a local GUI/HTTP command server.
3. How repositories and duplicate issue numbers are resolved.
4. How GitHub REST calls, retries, and errors are implemented.
5. Where `add_comment`, `append_work_log`, `create_issue`, and `capture_issue` are implemented.
6. Which skill copies and plugin manifests are authoritative in this work repository.
7. How plugin versions and runtime caches are synchronized.
8. Whether work security policy permits storing issue attachments on a dedicated Git branch. If it does not, stop and propose an approved storage backend with equivalent manifest and integrity semantics.

Preserve unrelated behavior and existing tests. Do not rewrite the surrounding architecture merely to match this document.

## 2. Storage design

Use an orphan branch named `gtd-assets` in the same repository as the issue.

```text
gtd-assets branch
  README.md
  issues/<issue_number>/manifest.json
  issues/<issue_number>/<slug>-<sha256-prefix>.<ext>
```

The per-issue `manifest.json` is the source of truth. Do not infer the attachment inventory from issue comments.

The proven baseline manifest is a JSON array of entries. Each new entry contains:

```json
{
  "path": "issues/123/design-draft-a1b2c3d4.pdf",
  "original_name": "Design Draft.pdf",
  "caption": "Approved design draft",
  "content_sha256": "full lowercase SHA-256 hex digest",
  "size_bytes": 123456,
  "mime": "application/pdf",
  "added_at": "2026-07-12T18:00:00Z",
  "added_by": "gtd_mgmt",
  "git_sha": "Git blob SHA"
}
```

Lifecycle fields are added when applicable:

```json
{
  "superseded_by": "issues/123/design-draft-newhash.pdf",
  "deleted": true
}
```

Use content-addressed filenames with a sanitized slug, the first eight characters of SHA-256, and the validated extension. Limit the slug to 60 characters.

### Manifest concurrency

Use the GitHub Contents API SHA when updating `manifest.json`. On a `409` stale-SHA conflict:

1. Refetch the manifest.
2. Reapply the mutation.
3. Retry once.
4. Raise a clear conflict if it still fails.

Create a dedicated `ManifestConflict` exception rather than treating all HTTP failures as concurrency conflicts.

## 3. GitHub client additions

Adapt these capabilities to the repository's existing client and retry conventions:

- `get_branch_sha(repo, branch) -> str | None`
- `get_repo_visibility(repo) -> bool` or equivalent private/public result
- `ensure_orphan_branch(repo, branch, readme_text) -> commit_sha`
- `get_file_contents(repo, path, ref) -> {sha, content: bytes} | None`
- `put_file_contents(repo, path, content: bytes, message, branch, sha=None) -> {sha, commit_sha}`
- `delete_file_contents(repo, path, message, branch, sha)`
- `get_git_blob(repo, sha) -> bytes | None`

Use authenticated `api.github.com` requests inside the MCP server. Decode GitHub base64 responses to bytes. A `404` should return `None` for read helpers. Preserve the existing HTTP retry strategy.

Retrieval should first request the current path from `gtd-assets`. If it is missing or its SHA-256 does not verify, retrieve the immutable Git blob using the manifest's `git_sha`. This fallback is necessary for deleted files and stale branch copies.

Do not make the MCP caller fetch `raw.githubusercontent.com`. Sandboxes may block that host, and private raw URLs require authentication.

## 4. Upload validation

Create a focused attachment module rather than embedding all behavior in the MCP or GUI files.

### General validation

- Reject symlink inputs.
- Require an existing regular, non-empty file.
- Reject unknown extensions.
- Reject executable/script extensions at minimum: `exe`, `dll`, `sh`, `bat`, `ps1`, `app`, `dmg`, `msi`, `jar`.
- Reject executable signatures even when renamed:
  - Windows PE (`MZ`)
  - ELF
  - Mach-O/fat Mach-O
  - Shebang scripts
- Read bytes once, then compute SHA-256 and validate the signature.
- Apply a 50 MiB absolute hard ceiling.
- Apply a 200 MiB active attachment budget per issue.

### Supported types and per-file limits

| Extensions | MIME/category | Limit | Validation |
|---|---|---:|---|
| png | image/png | 10 MiB | PNG signature |
| jpg, jpeg | image/jpeg | 10 MiB | JPEG signature |
| gif | image/gif | 10 MiB | GIF87a/GIF89a |
| webp | image/webp | 10 MiB | RIFF/WEBP |
| svg | image/svg+xml | 5 MiB | SVG/XML sniff |
| pdf | application/pdf | 25 MiB | `%PDF-` |
| md | text/markdown | 25 MiB | valid UTF-8 |
| txt | text/plain | 25 MiB | valid UTF-8 |
| csv | text/csv | 25 MiB | valid UTF-8 |
| docx | Office document | 25 MiB | ZIP signature |
| xlsx | Office spreadsheet | 25 MiB | ZIP signature |
| pptx | Office presentation | 25 MiB | ZIP signature |
| zip | application/zip | 50 MiB | ZIP signature |
| skp, dxf, dwg, layout | CAD/application-specific | 50 MiB | allowlisted; no proven signature check |

For `md`, `txt`, and `csv`, reject content matching at least:

- AWS access key IDs.
- Private key blocks.
- GitHub token formats.
- Slack token formats.

Keep the patterns centralized and return the matched pattern name without echoing secret content.

### Rendering behavior

- Public-repository images may be emitted as Markdown images.
- Other types are Markdown links.
- For private repositories, always use links rather than claiming inline rendering; GitHub's image proxy cannot fetch private raw content reliably.
- Build raw links using a commit-pinned `gtd-assets` branch commit SHA, not an unpinned branch name.

## 5. Core attachment operations

Implement cohesive internal functions corresponding to the following behavior.

### Attach

`attach_file(client, repo, issue_number, file_path, caption="", name="", mode="comment", comment_text="")`

- Validate the file.
- Ensure the orphan branch exists.
- Deduplicate by `content_sha256` among non-deleted entries.
- Enforce the per-issue byte budget before upload.
- Upload bytes, then append the manifest entry with conflict retry.
- Return path, original name, raw URL, rendering state, and whether it was deduplicated.
- `mode="comment"`: post a comment containing optional text plus embed/link.
- `mode="body_append"`: append embed/link to the issue body.
- `mode="none"`: upload only.
- If upload succeeds but comment/body embedding fails, report the partial failure clearly; never pretend the upload did not occur.

### List

`list_files(client, repo, issue_number)`

- Return every manifest entry, including superseded and deleted entries.
- Add computed boolean `superseded` and `deleted` fields.
- Add a commit-pinned raw URL when available.
- Do not change existing list behavior later when retrieval tools are added.

### Update

`update_file(client, repo, issue_number, old_manifest_path, new_file_path, caption="", mode="comment")`

- Validate and upload the replacement.
- Mark the old entry with `superseded_by=<new_path>`.
- Append a new manifest entry rather than overwriting history.
- Optionally post an update comment with the new link.

### Delete

`delete_file(client, repo, issue_number, path, handle_references="warn")`

- Treat repeated deletion as idempotent.
- Delete the current branch file using its Git SHA.
- Mark the manifest entry `deleted=true`; retain metadata and Git SHA so historical retrieval remains possible.
- Search issue comments for the attachment path.
- Return affected comment IDs/URLs.
- With `handle_references="annotate"`, append a dated deletion notice to those comments.

### Multiple attachments on existing workflows

Add optional:

```python
attachments: list[dict] | None
```

to:

- `add_comment`
- `append_work_log`
- `create_issue`
- `capture_issue`

Each item is:

```json
{"file_path": "/absolute/local/path", "caption": "optional caption"}
```

Implement one shared helper that uploads each item with `mode="none"` and builds a Markdown block. Individual attachment failures should be returned per file rather than crashing the whole helper.

For comments and work logs, append a single `## Attachments` section. For issue creation/capture, create the issue first, upload against the new issue number, then append the section to the issue body. Required issue creation failures stop the operation; optional Project-field/parent failures remain warnings according to existing behavior.

Increase relevant request timeouts to account for file uploads.

## 6. Single-file retrieval

Expose:

```python
get_issue_file(
    issue_number: int,
    original_name: str = "",
    path: str = "",
    content_sha256: str = "",
    git_sha: str = "",
    output: str = "base64",
    dest_path: str = "",
    overwrite: bool = False,
    include_superseded: bool = False,
    include_deleted: bool = False,
    repo: str = "",
    launch_if_needed: bool = True,
)
```

### Selector rules

- Require exactly one of `original_name`, `path`, `content_sha256`, or `git_sha`.
- Exclude superseded and deleted entries by default.
- `include_superseded` and `include_deleted` are independent controls.
- If no visible entry matches, return `attachment_not_found` or `attachment_deleted` with available name/path candidates.
- If a selector matches multiple visible entries, return `ambiguous_attachment`; do not silently select one. Tell the caller to use path or a hash.

### Manifest validation before retrieval

Reject malformed entries before reading bytes:

- `path` must start with `issues/<issue_number>/` and contain no `..` path component.
- `original_name` must be a basename, not a path.
- `content_sha256` must be 64 lowercase hexadecimal characters.
- `git_sha` must be a plausible non-empty Git object ID.
- `size_bytes` must be a non-negative integer, excluding booleans.
- `mime` must be non-empty.

Use stable structured errors:

```json
{
  "ok": false,
  "error": {
    "code": "invalid_manifest",
    "message": "...",
    "details": {}
  }
}
```

### Byte resolution and verification

1. Read `path` from `gtd-assets` using the authenticated GitHub client.
2. Compute SHA-256.
3. If missing or stale, request `git_sha` through the Git blob API.
4. Verify final SHA-256 against `content_sha256`.
5. Verify byte length against `size_bytes`.
6. Return a hard error on mismatch; never return unverified bytes.
7. If a stale current copy was replaced by a valid Git blob, return a `working_copy_stale` warning.

Expected retrieval errors include:

- `invalid_selector`
- `attachment_not_found`
- `attachment_deleted`
- `ambiguous_attachment`
- `invalid_manifest`
- `invalid_manifest_path`
- `blob_unavailable`
- `hash_mismatch`
- `size_mismatch`
- `invalid_output`
- `invalid_destination`
- `destination_exists`
- `inline_size_exceeded`

### Output modes

`base64`:

- Default mode.
- Return `content_base64` only after verification.
- Enforce a 5 MiB pre-encoding limit and direct larger callers to `write`.

`write`:

- Require an absolute `dest_path`.
- Reject a destination symlink.
- Refuse existing files unless `overwrite=true`.
- Create parent directories.
- Reject an immediate symlink parent at minimum; apply stronger ancestor/root policy if required by work security standards.
- Write a temporary file in the destination directory, flush and `fsync`, then atomically replace the destination.
- Return the final `dest_path` and `verified_sha256=true`.

Do not implement `local_path` unless this server actually maintains a shared local checkout of `gtd-assets`. The proven implementation uses the authenticated Contents/Git Blob APIs because API uploads do not populate the server repository's local Git object store.

## 7. Batch retrieval

Expose:

```python
get_issue_files(
    issue_number: int,
    dest_dir: str,
    mime_prefix: str = "",
    include_superseded: bool = False,
    include_deleted: bool = False,
    overwrite: bool = False,
    fail_fast: bool = False,
    max_total_bytes: int = 209715200,
    repo: str = "",
    launch_if_needed: bool = True,
)
```

Behavior:

- Require an absolute, non-symlink destination directory.
- Select current, non-deleted entries by default.
- Optionally filter with MIME prefix such as `image/`.
- Use `original_name` for destination filenames.
- Detect duplicate selected `original_name` values before writing anything; return `destination_name_collision` with paths.
- Sum declared sizes and reject the batch before writing if it exceeds `max_total_bytes`.
- Reuse the single-file retrieval path so verification behavior cannot drift.
- Refuse existing destinations unless `overwrite=true`.
- Continue after per-file failures by default and return all results.
- With `fail_fast=true`, stop after the first error.
- Return selected, processed, succeeded, and failed counts plus per-file results.

## 8. MCP and GUI/transport integration

Expose six MCP tools:

1. `attach_file_to_issue`
2. `list_issue_files`
3. `get_issue_file`
4. `get_issue_files`
5. `update_issue_file`
6. `delete_issue_file`

If this codebase uses a local GUI HTTP command server:

- Add GET routes for list and retrieval operations.
- URL-encode all query arguments.
- Parse booleans explicitly from `1`, `true`, `yes`, or `on`.
- Validate integer batch limits at the transport boundary.
- Add apply-change dispatch branches for attach/update/delete.
- Continue resolving issues through the existing repository-aware `_resolve_issue` path.
- Keep the GUI read-only; file mutations occur through the MCP/apply-change command path, not GUI widgets.

Suggested timeouts:

- List: 30 seconds.
- Single retrieval: 60 seconds.
- Batch retrieval: 120 seconds.
- Upload-bearing comment/work-log/update operations: at least 60 seconds.

## 9. Required tests

Build an in-memory fake GitHub client with:

- Branch SHA state.
- Path-to-bytes storage.
- Immutable blob-SHA-to-bytes storage retained after branch deletion.
- Manifest conflict injection.
- Comment/body recording.
- Realistic 40-character Git SHAs.

### Validation tests

- Slug normalization and length.
- Every allowed format and signature.
- Extension/signature mismatch.
- Unknown and blocked extensions.
- Renamed executable signatures.
- Empty, missing, symlink, oversized files.
- Text secret-pattern detection.

### Add/list/update/delete tests

- Orphan branch creation.
- Manifest creation and stable metadata.
- Content deduplication.
- Per-issue budget enforcement.
- Manifest conflict refetch/retry.
- Public image embedding versus private link behavior.
- Comment and body modes.
- Update supersession history.
- Delete idempotency.
- Reference warning and annotation.
- Multi-attachment helper partial failures.
- Attachments integrated into comments, work logs, create, and capture.

### Single retrieval tests

- All four selectors return identical verified bytes.
- Exactly-one-selector validation.
- Missing selector candidates.
- Ambiguity handling.
- Deleted visibility and Git blob recovery.
- Superseded visibility.
- Stale current path falls back to blob with warning.
- Missing current path and blob returns `blob_unavailable`.
- Hash mismatch hard failure.
- Size mismatch hard failure.
- Invalid manifest metadata and path.
- Base64 size guard.
- Atomic write.
- Existing destination refusal.
- Successful explicit overwrite.

### Batch tests

- Retrieve all current files.
- MIME filtering.
- Duplicate original-name collision before any write.
- Batch byte limit before any write.
- Existing destination behavior.
- Partial failure continues by default.
- `fail_fast` stops processing.
- Per-file verification results and aggregate counts.

### Client and transport tests

- GitHub Contents and Git Blob base64 decoding.
- `404` read behavior.
- Manifest-conflict exception on `409`.
- Orphan branch already exists and creation flows.
- GUI command handlers for single and batch retrieval.
- MCP wrapper forwards selectors, booleans, paths, filtering, and byte limit correctly.
- Existing list behavior remains unchanged.
- Run the entire existing test suite, not only new tests.

## 10. Skill and documentation updates

Update every skill/documentation source actually used in this work repository. Possible locations include:

- `.agents/skills/gtd_mgmt/SKILL.md` for the Codex app.
- `.claude/commands/gtd-mgmt.md` for Claude Code.
- `plugins/gtd/skills/gtd-mgmt/SKILL.md` for the Cowork plugin.
- Any repository-specific skill mirror that is genuinely active.
- Architecture/tool tables such as `CLAUDE.md` or `README.md`.

Document:

- All six attachment tools.
- Optional `attachments` on comment, work-log, create, and capture operations.
- Exactly-one-selector retrieval semantics.
- Base64 and write limits.
- Batch collision and overwrite behavior.
- Private repository rendering limitation.
- Structured warnings and partial failures.

Do not create redundant skill copies that the work clients do not read. Determine authoritative locations from this repository's sync documentation.

If plugin content changes, bump the plugin version according to this repository's SemVer policy. A plugin update with an unchanged version may be treated as a no-op even when files changed.

## 11. Deployment and verification

Before running any sync/deployment script:

1. Read it completely.
2. Check current machine paths and repository identity.
3. Verify the project virtual environment and dependencies.
4. Confirm token presence without printing it.
5. Confirm plugin name and marketplace name match.
6. Confirm embedded MCP paths point to this work checkout.
7. Confirm the plugin version was bumped.
8. Run tests and obtain review before commit/push/deploy.

Known deployment lessons:

- Codex, Claude Code, and Cowork may use different skill and MCP locations.
- Cowork's plugin CLI cache may differ from its active runtime cache.
- A marketplace clone must see the pushed plugin-version commit before an update succeeds.
- A fresh Cowork install may require launching Cowork and running sync a second time to create/populate its runtime directory.
- Under `set -euo pipefail`, expected no-match discovery commands must be guarded (for example, `... || true`) or the sync script can abort incorrectly.
- Ensure required shell variables such as the Codex home directory are defined before use.
- After sync, check for stale MCP entries pointing to scripts that no longer exist.
- Restart each affected client after updating skills or MCP configurations.

Do not push or deploy without my explicit approval.

## 12. Acceptance criteria

The implementation is complete when:

1. A supported local file can be attached to an existing or newly created issue and appears in its manifest.
2. Invalid, executable, mismatched, secret-bearing, empty, symlink, and oversized inputs are rejected.
3. Reattaching identical content deduplicates rather than uploading another blob.
4. Replacement retains the old manifest entry and links it to the new path.
5. Deletion preserves enough metadata to retrieve the historical Git blob when explicitly allowed.
6. Listing reports all current, superseded, and deleted entries without regression.
7. Single retrieval works by every selector and never returns unverified bytes.
8. Base64 and atomic-write output modes enforce their guards.
9. Batch retrieval filters, detects collisions, enforces a total limit, and reports partial failures accurately.
10. Private-repository behavior does not depend on the caller fetching an authenticated raw URL.
11. Comment, work-log, create, and capture attachment integration works.
12. Focused tests and the full existing suite pass.
13. Skill/plugin documentation accurately exposes the new tools.
14. The worktree contains only intentional changes and is presented for review before commit.

## 13. Proven baseline versus future enhancements

Implement the sections above first. Do not silently expand scope into these future items:

- Versioned manifest schema and monotonic revisions.
- Stable logical attachment IDs and explicit version numbers.
- Idempotency keys for mutations.
- Stronger optimistic concurrency exposed to callers.
- Restore and permanent purge tools.
- Audit and repair tools for orphaned or inconsistent data.
- Configurable writable-root allowlists and all-ancestor symlink rejection.
- Content-addressed local caching.
- Short-lived localhost download tickets or streaming.
- Cross-issue attachment search.
- Attachment summaries automatically included in resume context.

If the work environment needs any of these for security or compliance, propose them separately and obtain approval before broadening the baseline implementation.

## 14. Implementation learnings to preserve

- The manifest, not comments, must be authoritative.
- Store both SHA-256 and Git blob SHA; they solve different problems.
- Verify both content hash and recorded byte length on every retrieval.
- Preserve Git blob identity when soft-deleting so deleted files remain recoverable.
- Retrieval through the authenticated server is more reliable than asking sandboxed callers to fetch raw URLs.
- Do not silently resolve ambiguous original filenames.
- Batch collision detection must happen before the first write.
- Reuse the single-file retrieval path in batch operations to avoid verification drift.
- Write retrieved files atomically and refuse overwrite by default.
- Model upload-plus-comment as a potentially partial operation and report that state honestly.
- Use realistic Git SHAs in test fakes; stricter validation will expose unrealistic fixtures.
- Test transport wiring as well as core helpers; correct internal logic is insufficient if MCP parameters are dropped or misparsed.
- Plugin versioning and runtime synchronization are part of feature delivery, not optional documentation chores.

At the end, report:

- Files changed.
- Tool contracts added or modified.
- Security and architecture decisions.
- Tests added and complete test results.
- Any divergence from this specification and why.
- Remaining deployment/restart steps.
- A concise diff-review checklist for me.

Then stop and ask me to review. Do not commit until I approve.

---

## Reference history from the personal implementation

These references are informational only; the work implementation should be adapted locally:

- `997aa30` — introduced the add/list/update/delete lifecycle, validation, GitHub client support, workflow integrations, skills, and tests.
- `d48f009` — bumped the plugin version because skill content changed.
- `8d76c65` — fixed sync-script failures involving an undefined Codex home variable and an expected `find | grep` no-match under `pipefail`.
- `e6d9905` — added verified single and batch retrieval, transport wiring, tests, documentation, and the longer-term roadmap.
