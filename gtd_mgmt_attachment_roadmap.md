# gtd_mgmt Attachment Roadmap

**Status:** Active roadmap

**Started:** 2026-07-12

**Scope:** Adding, updating, retrieving, governing, and repairing files attached to GitHub issues through `gtd_mgmt`

## Desired outcome

Build an attachment subsystem that is safe to retry, detects concurrent changes, preserves recoverable history, verifies every retrieved file, and can diagnose or repair partial failures without requiring callers to access GitHub content hosts directly.

## Guiding principles

- Never return unverified bytes.
- Prefer recoverable operations over destructive ones.
- Make retries idempotent and concurrent changes explicit.
- Keep the manifest as the source of truth, with a versioned schema.
- Return stable machine-readable error codes and useful recovery details.
- Keep large binary payloads out of MCP responses when practical.
- Preserve compatibility with existing attachment manifests and tools.

## Current baseline

- [x] Validate attachment types, sizes, signatures, and selected secret patterns.
- [x] Upload files to the `gtd-assets` branch.
- [x] Record attachment metadata in an issue manifest.
- [x] List current, superseded, and deleted manifest entries.
- [x] Replace attachments while preserving supersession history.
- [x] Soft-delete attachments and optionally annotate references.
- [x] Retrieve a file by original name, path, content SHA-256, or Git SHA.
- [x] Verify SHA-256 before returning or writing retrieved bytes.
- [x] Return small files as base64 with a 5 MiB guard.
- [x] Atomically write retrieved files to an absolute destination.
- [x] Retrieve deleted or missing branch files through their stored Git blob SHA.
- [x] Cover the retrieval core with automated tests.

## Milestone 1 — Retrieval completeness and integrity

**Priority:** Now

**Goal:** Make the new retrieval path complete, predictable, and convenient before changing the manifest schema.

- [x] Add `get_issue_files` for batch retrieval of current attachments.
- [x] Support optional `mime_prefix` filtering.
- [x] Define deterministic destination naming and collision handling.
- [x] Support `fail_fast=false` with per-file success/error results.
- [x] Enforce a maximum total byte count per batch.
- [x] Verify manifest `size_bytes` as well as `content_sha256`.
- [ ] Verify that a retrieved Git blob reports the expected `git_sha` where the GitHub response supplies it.
- [x] Reject malformed manifest entries with stable `invalid_manifest` errors.
- [x] Add tests for branch-copy fallback warnings, blob absence, invalid manifest paths, overwrite behavior, and batch partial failure.
- [x] Add focused GUI/MCP wiring tests for `get_issue_file` and `get_issue_files`.
- [ ] Perform a real-world retrieval of the four deck-layout PNGs and verify their hashes/signatures.

### Milestone 1 acceptance criteria

- One call can retrieve all eligible files for an issue into a directory.
- No file is reported successful unless its content hash and recorded size verify.
- Filename collisions never silently overwrite a file.
- A failure for one attachment is reported without losing successful results unless `fail_fast=true`.
- Existing `list_issue_files` and single-file behavior remain backward compatible.

## Milestone 2 — Concurrency and retry safety

**Priority:** Next

**Goal:** Make mutations safe when multiple agents or retries act on the same issue.

- [ ] Add a manifest `schema_version` and monotonic `revision`.
- [ ] Preserve compatibility with the existing top-level manifest array during migration.
- [ ] Add optimistic concurrency using an expected manifest revision or Git SHA.
- [ ] Return a stable `manifest_conflict` error with current revision details.
- [ ] Add optional idempotency keys to attach, update, and delete operations.
- [ ] Store enough operation metadata to recognize safe retries.
- [ ] Ensure retries do not duplicate issue comments.
- [ ] Add concurrent-update and timeout/retry tests.

## Milestone 3 — Stable identity and version lifecycle

**Priority:** Planned

**Goal:** Separate a logical attachment from its filenames, paths, and individual versions.

- [ ] Assign each logical attachment a stable `attachment_id`.
- [ ] Record explicit version numbers and replacement relationships.
- [ ] Add `list_issue_file_versions`.
- [ ] Add `restore_issue_file` for soft-deleted files.
- [ ] Add `restore_issue_file_version` for superseded versions.
- [ ] Add metadata-only caption, display-name, tag, and ordering updates.
- [ ] Define a separately authorized permanent `purge_issue_file` operation.
- [ ] Add retention-policy configuration for deleted content.

## Milestone 4 — Audit and repair

**Priority:** Planned

**Goal:** Detect and recover from partial upload, manifest, comment, or deletion failures.

- [ ] Add `audit_issue_files` with no-write default behavior.
- [ ] Detect missing blobs, orphaned blobs, invalid hashes, broken supersession links, and malformed entries.
- [ ] Detect manifest entries whose referenced issue comments no longer exist.
- [ ] Add `repair_issue_files` with mandatory `dry_run=true` by default.
- [ ] Make each repair action explicit and independently reportable.
- [ ] Record a structured attachment-operation audit log.
- [ ] Add fault-injection tests for failures after each mutation step.

## Milestone 5 — Secure and efficient transfer

**Priority:** Later

**Goal:** Support larger files and repeated access without oversized MCP responses or unnecessary downloads.

- [ ] Add configurable writable-root restrictions for `output="write"`.
- [ ] Reject traversal through any symlinked destination ancestor.
- [ ] Set explicit conservative permissions on written files.
- [ ] Add a content-addressed local cache keyed by SHA-256.
- [ ] Define cache size, age, and eviction rules.
- [ ] Add short-lived localhost download tickets for large files.
- [ ] Consider byte-range or chunked retrieval for large content.
- [ ] Add ZIP inspection, decompression limits, and optional malware scanning.

## Milestone 6 — Discovery and workflow integration

**Priority:** Later

**Goal:** Make attachments easy for agents to discover and use during normal GTD work.

- [ ] Include concise current-attachment summaries in issue context and resume results.
- [ ] Add cross-issue attachment search by name, caption, MIME type, hash, tag, issue, and date.
- [ ] Add optional batch ZIP export.
- [ ] Add asynchronous progress and cancellation for large batch operations.
- [ ] Document common add, replace, retrieve, restore, audit, and repair workflows.

## Today’s selected work — Milestone 1A

This is the recommended subset to start today. It builds directly on the new retrieval helper, has limited migration risk, and gives immediate value to the deck-layout workflow.

- [x] Strengthen single-file integrity checks:
  - [x] Verify `size_bytes` in addition to SHA-256.
  - [x] Return `invalid_manifest` for missing or malformed required metadata.
  - [x] Add explicit tests for stale branch fallback, unavailable blobs, invalid paths, and successful overwrite.
- [x] Implement `get_issue_files` batch retrieval:
  - [x] Retrieve current, non-deleted attachments by default.
  - [x] Accept `dest_dir`, optional `mime_prefix`, `include_superseded`, and `include_deleted`.
  - [x] Refuse filename collisions and existing destinations by default.
  - [x] Return per-file results and continue after individual failures.
  - [x] Enforce a configurable batch byte ceiling.
- [x] Wire the batch tool through the GUI command server and MCP server.
- [x] Add unit and GUI/MCP wiring tests.
- [x] Run the complete automated test suite (`190 passed, 10 subtests passed`).
- [ ] After deployment, retrieve and verify the four real deck-layout PNGs.

### Explicitly deferred from today

- Manifest schema migration and stable attachment IDs.
- Idempotency and optimistic concurrency.
- Restore and permanent purge operations.
- Audit/repair mutations.
- Local caching, download tickets, and streaming.
- Cross-issue search and resume-context integration.

## Definition of done for today

- `get_issue_file` validates required manifest metadata, content size, and SHA-256.
- `get_issue_files` retrieves multiple eligible files safely with per-file results.
- Batch retrieval cannot silently overwrite or collapse filename collisions.
- Single-file and batch retrieval have focused unit and transport-wiring coverage.
- The full existing test suite passes.
- Remaining work and any design decisions discovered during implementation are recorded in this roadmap.
