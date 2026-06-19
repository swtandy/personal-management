---
name: gtd_mgmt
description: Use when the user wants Codex to resume, inspect, summarize, create, organize, or update GTD project work tracked in the configured GitHub Project, including finding where work left off, reading latest issue comments and gtd_mgmt work logs, creating GitHub issues, applying GTD/domain labels, setting Project fields, parenting deliverables/tasks, appending structured work-log comments, and refreshing the local read-only project GUI.
---

# gtd_mgmt

Use this skill for GTD project memory and GitHub Project issue management.

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
   - Use `create_resume_handoff(repo, issue_number)` for exact issue references when Scott needs to switch to another Codex project/workspace.
   - The tool writes a Markdown workdown file and resolves the recommended local Codex project path when possible.
   - Report the handoff file path, the recommended Codex project path, and any path-resolution warnings.
   - Creating a handoff automatically adds `when:this-week` to the issue (promote-only — skipped if already `when:today`). No additional issue updates during handoff creation unless Scott explicitly asks.
6. For end-of-session updates:
   - Use `append_work_log`, not ad hoc comments, unless the user explicitly asks for a plain comment.
   - Include enough detail for future Codex runs to resume quickly: work completed, current state, next steps, blockers, and useful context.
   - Include `codex_project` with the absolute local Codex project/workspace path where the work happened. This is separate from GitHub `repo` and should be captured even when the repository name is obvious.
7. After writes, confirm the issue URL/comment URL and refresh status.

## Organization Operations

Use these tools when `gtd_workflow` has decided what should exist and `gtd_mgmt` needs to land it in GitHub:

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


Use `create_resume_handoff(repo, issue_number)` when Scott wants to resume a
specific issue in its target Codex project. The generated Markdown file is a
self-contained workdown packet for the new target-project thread.

The file includes:

- A top orientation-only section with text Scott can paste into any Codex chat
  to decide which Codex application project to open. This prompt must say to use
  `gtd_workflow` and `gtd_mgmt` only to choose the Codex app project, and must
  prohibit implementation, repo inspection, tests, edits, handoff creation, and
  GitHub updates.
- The source issue, URL, Project status, priority, parent, and children.
- A single `Recommended Codex Project` section containing the resolved
  Codex application project name/container, `codex_project_path`, confidence,
  reason, and existence check whenever the project can be resolved. This section
  is the canonical source for orientation-only "which Codex project should I
  open?" answers.
- Separate `Related Local Workspaces` and `Related GitHub Repositories` sections.
  These are useful context, but they are not the Codex app project and must not
  be substituted for it.
- A separate execution-after-switch prompt Scott can use in the target project
  thread after opening the recommended Codex app project. This prompt should
  orient the agent to all listed workspaces and repos, allow only lightweight
  repository-state inspection during orientation, and require the agent to stop
  and align with Scott on a plan before implementation, edits, broad tests,
  commits, handoff creation, or GitHub/GTD updates.
- The "where I left off" summary and next action.
- Blockers/open questions and latest structured work-log fields.
- Resume warnings before target-thread instructions, so path-resolution or
  metadata problems are visible before work begins.
- End-of-session instructions naming the exact issue to prepare an update for
  and the `append_work_log` fields to return, including `codex_project` for the
  Codex app project name and `codex_project_path` for the Codex app project path
  used by the work session.

The generated handoff should explicitly say that it is already the handoff. If
the source issue's latest next action says to create a handoff, the target
thread should not create another handoff unless Scott explicitly asks. After
orientation it should summarize the likely implementation workspaces/repos,
current repo state, possible next actions, and a recommended plan, then ask Scott
to confirm the plan before doing implementation work.

Target project threads should not update the GTD issue directly unless Scott
explicitly asks. They should return `append_work_log` field values so Scott or
the originating GTD thread can apply the update.

When returning end-of-session fields, include `codex_project` as the Codex app
project name/container and `codex_project_path` as the Codex app project path.
Do not rely on GitHub repos or local source checkout paths alone; those belong
in `related_github_repos` and `related_local_workspaces`.

If the target Codex project path is unresolved or ambiguous, report that warning
and ask Scott to choose the correct workspace before beginning implementation
work.

If Scott asks only where to work, which Codex project to use, or for a
recommendation based on a handoff/workdown, treat the request as orientation-only:
read the issue or handoff context and use the `Recommended Codex Project`
section when present. Return exactly the Codex app project name, Codex app
project path, confidence, and reason from that section, then stop. Do not
inspect repos or local workspaces, run tests, edit files, create another handoff,
or update GitHub.

## GUI Contract

The GUI is read-only. It displays the configured GitHub Project issue hierarchy, search/filter state, and lazily loaded latest comments. It should not be used for edits.

Double-click issue or comment rows to open GitHub. Use MCP tools for all issue reads and writes.

## Comment Format

Structured session notes use:

```md
<!-- gtd_mgmt:work-log:v1 -->
```

Prefer `append_work_log` so future "where did I leave off" requests can reliably find the latest work log.
