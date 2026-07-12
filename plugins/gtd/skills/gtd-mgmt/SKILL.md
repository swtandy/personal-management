---
description: Resume, inspect, create, organize, or update GTD project work tracked in the configured GitHub Project, including work logs, labels, Project fields, hierarchies, and the read-only GUI.
---

# gtd-mgmt

Use this skill for GTD project memory and GitHub Project issue management.

## Terminology Bridge

The `gtd_mgmt` MCP tools were originally built for Codex CLI and use Codex-specific language in their output. When you see these terms, interpret them as follows:

- **"Codex application project"** / **"Codex project"** → the workspace directory to start Claude Code from
- **`codex_project`** (in work-log fields or MCP responses) → the workspace name (e.g. `gtd-agents`)
- **`codex_project_path`** (in work-log fields or MCP responses) → the absolute path of that workspace
- **"Recommended Codex Project" section in handoff files** → the recommended workspace directory for Claude Code

When reporting resume results or handoff recommendations to the user, translate this terminology: say "workspace" instead of "Codex project" and "start Claude Code from `<path>`" instead of "switch to Codex project".

When writing `append_work_log` fields, use the Claude Code workspace path for `codex_project_path` and a short workspace name for `codex_project`.

## Workflow

1. Check GUI/MCP state with `gui_status`.
2. Launch the GUI with `launch_gui` if it is not running.
3. Load or refresh the configured project with `load_default_project`.
4. For "where did I leave off" requests:
   - For exact issue references such as `owner/repo#123`, call `resume_from_issue(repo, issue_number)` first.
   - `get_issue_context(issue_number, repo)` is also available for exact issues and returns the same structured resume context.
   - For text-only project requests, use `resume_project(query)`.
   - If multiple candidates are returned, ask the user to choose or use `search_project_items`.
   - Treat `latest_work_log.parsed` as the primary source for where work left off.
   - Use `resume_summary.next_action` as the recommended next step unless the user asks for deeper analysis.
5. For cross-project resume handoffs:
   - Use `create_resume_handoff(repo, issue_number)` for exact issue references when Scott needs to switch to another workspace.
   - The tool writes a Markdown workdown file and resolves the recommended local workspace path when possible.
   - Report the handoff file path, the recommended workspace path, and any path-resolution warnings.
   - Translate "Codex project" language from the generated file when summarizing for the user.
   - Creating a handoff automatically adds `when:this-week` to the issue (promote-only — skipped if already `when:today`).
6. For end-of-session updates:
   - Use `append_work_log`, not ad hoc comments, unless the user explicitly asks for a plain comment.
   - Include enough detail for future sessions to resume quickly: work completed, current state, next steps, blockers, and useful context.
   - Include `codex_project` with the short workspace name and `codex_project_path` with the absolute path of the Claude Code workspace where the work happened.
   - Include `useful_context` with commands run, branch/PR links, and anything needed to resume quickly.
7. After writes, confirm the issue URL/comment URL and refresh status.

## Organization Operations

Use these tools when `/gtd-workflow` has decided what should exist and `/gtd-mgmt` needs to land it in GitHub:

- `create_issue(repo, title, body, labels, status, priority)` creates a GitHub issue, adds it to the configured Project, and sets Status/Priority.
- `capture_issue(repo, title, body, labels, status, priority, parent_issue_number, parent_repo, source_text, source_label, next_action, waiting_for)` captures pasted emails, meeting notes, Teams/Slack follow-ups, or quick GTD next actions as organized GitHub issues with source context.
- `add_labels(issue_number, repo, labels)` ensures and applies labels.
- `set_project_field(issue_number, repo, field_name, option_name)` sets a Project V2 single-select field such as Status or Priority.
- `set_issue_parent(child_issue_number, child_repo, parent_issue_number, parent_repo)` sets GitHub sub-issue hierarchy.
- `organize_issue(issue_number, repo, labels, status, priority, parent_issue_number, parent_repo)` applies common organization updates in one call.
- `bulk_organize_issues(items, labels, status, priority, parent_issue_number, parent_repo, dry_run)` applies common organization updates across many issues.

Prefer these tools over ad hoc GitHub REST/GraphQL. Refresh or check status after bulk operations.

For bulk changes, use `dry_run=True` first unless the user explicitly asks to apply immediately.

Use `capture_issue` for new actionable source material. It defaults the parent to `[Scott T] Inbox` (#70) — triage later by re-parenting to the correct Area root.

## Attachments

Real files (screenshots, floor plans, PDFs, spreadsheets) can be landed directly on an issue instead of just describing them:

- `attach_file_to_issue(issue_number, file_path, repo, caption, mode)` uploads a local file to the issue's `gtd-assets` manifest and embeds/links it (`mode="comment"` posts a comment, `"body_append"` appends to the issue body, `"none"` uploads only and returns the URL).
- `list_issue_files(issue_number, repo)` lists everything attached to an issue, including superseded/deleted entries.
- `update_issue_file(issue_number, path, file_path, repo, caption, mode)` replaces an attachment while preserving history.
- `delete_issue_file(issue_number, path, repo, handle_references)` removes an attachment; `handle_references="annotate"` also flags comments that referenced it.
- `add_comment`, `append_work_log`, `create_issue`, and `capture_issue` all accept an optional `attachments` list of `{"file_path": "...", "caption": "..."}` to upload and embed inline in the same call, instead of attaching separately.

Images render inline; other file types are linked. Private repos always render as links (GitHub's image proxy can't fetch private raw content).

For issue creation/capture, required setup failures should stop the operation, but optional organization failures such as invalid Status, invalid Priority, or parent assignment failure may return `warnings`. Report warnings to the user and continue from the created issue instead of retrying blindly. If Priority is unavailable, leave Priority blank and preserve the requested value in the warning.

## Resume Context

For exact issue resume requests, prefer:

```text
resume_from_issue(repo="owner/repo", issue_number=123)
```

The response includes:

- Issue identity and body: `repo`, `issue_number`, `url`, `title`, `state`, `body`, `labels`, `assignees`.
- GitHub Project state: `project.title`, `project.number`, `project.status`, `project.priority`, `project.parent`, `project.children`.
- Work-log memory: `latest_work_log`, `latest_work_log.parsed`, and `all_work_logs`.
- Human-ready resume fields: `resume_summary.where_we_left_off`, `resume_summary.next_action`, `resume_summary.blockers`, and top-level `recommended_next_action`.
- `warnings` when comments, work logs, or project context are incomplete.

If no structured work-log exists, use the returned warnings and fall back to issue body, recent comments, and Project fields. Do not manually search GitHub or invoke `gh issue view` unless the tool returns an actionable failure that cannot be resolved through `load_default_project` or `refresh`.

## Resume Handoff Files

Use `create_resume_handoff(repo, issue_number)` when Scott wants to resume a specific issue in a different workspace.

The generated Markdown file will use "Codex project" language throughout (see Terminology Bridge above). When presenting the file or summarizing its contents to the user, translate:
- "Recommended Codex Project" → the recommended workspace to start Claude Code from
- `codex_project_path` → workspace path

The file includes:

- A top orientation-only section with text Scott can paste into any Claude Code session to decide which workspace to open. Read the prompt text and substitute "workspace" for "Codex project" when describing it.
- The source issue, URL, Project status, priority, parent, and children.
- A `Recommended Codex Project` section (workspace recommendation) with path, confidence, and reason.
- Separate `Related Local Workspaces` and `Related GitHub Repositories` sections.
- A separate execution-after-switch prompt Scott can use after opening the recommended workspace.
- The "where I left off" summary and next action.
- Blockers/open questions and latest structured work-log fields.
- End-of-session instructions.

The generated handoff is already the handoff. If the source issue's latest next action says to create a handoff, the target session should not create another handoff unless Scott explicitly asks.

Target sessions should not update the GTD issue directly unless Scott explicitly asks. They should return `append_work_log` field values so Scott or the originating GTD session can apply the update.

If the target workspace path is unresolved or ambiguous, report that warning and ask Scott to choose the correct workspace before beginning implementation work.

If Scott asks only where to work or which workspace to use, treat the request as orientation-only: read the issue or handoff context and use the `Recommended Codex Project` section. Return the workspace name, path, confidence, and reason, then stop.

## GUI Contract

The GUI is read-only. It displays the configured GitHub Project issue hierarchy, search/filter state, and lazily loaded latest comments. It should not be used for edits.

Double-click issue or comment rows to open GitHub. Use MCP tools for all issue reads and writes.

## Comment Format

Structured session notes use:

```md
<!-- gtd_mgmt:work-log:v1 -->
```

Prefer `append_work_log` so future "where did I leave off" requests can reliably find the latest work log.
