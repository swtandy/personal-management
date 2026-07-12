# CLAUDE.md — SWT Personal Management

This file is read automatically by Claude Code at session start.

---

## Project Purpose

A personal GTD operating system for Scott Tandy (swtandy) built on GitHub Issues + MCP tooling. All interaction is agent-managed via MCP — no CLI scripts. The goal is to consolidate personal life tracking into a single GitHub repo (`swtandy/personal-management`) with structured work logs, GTD labels, Project V2 fields, and cross-session handoffs.

---

## GitHub Repos Involved

| Repo | Role |
|---|---|
| `swtandy/personal-management` | Primary — consolidated personal OS |
| `swtandy/openclawstuff` | Legacy source — 22 issues migrated, kept for reference |

GitHub username: `swtandy`  
Token: stored in `.env` (gitignored — never committed)

GitHub Project: **Personal Management** — Project #2  
URL: `https://github.com/users/swtandy/projects/2`  
Project ID: `PVT_kwHOAdx20s4BbJkA`  
Fields: Status (Backlog/In Progress/Blocked/Done), Priority (P1–P4), When (Today/This Week/This Month/This Quarter/Someday/Maybe)

---

## Local Setup

Requires Python 3.13 (Homebrew). Use the project venv:

```bash
cd ~/Documents/Claude/Projects/SWT\ Personal\ Management
python3.13 -m venv .venv          # first time only
.venv/bin/pip install -r requirements.txt
```

The MCP server (`agents/gtd_mgmt_mcp_server.py`) is the only entry point — there are no CLI scripts.

---

## Architecture

```
config.py              ← centralised tunables (GITHUB_USER, GITHUB_PROJECT_NUMBER, etc.)
github_client.py       ← GraphQL + REST API client, work-log parser
attachments.py         ← file-attachment validation, manifest, and upload/delete logic (gtd-assets branch)
agents/
  gtd_mgmt_mcp_server.py  ← 28-tool FastMCP server (mediates through GUI)
  project_gui.py           ← Tkinter read-only GUI (auto-launched, optional)
utils/                 ← helpers (currently empty)
```

The GUI (`project_gui.py`) acts as a local data cache for the MCP server. It launches on demand via `launch_gui` and is not required for pure agent operation — most tools will auto-launch it if needed. All edits go through MCP tools, never through the GUI directly.

---

## MCP Server Tools (`agents/gtd_mgmt_mcp_server.py`)

| Tool | What it does |
|---|---|
| `gui_status()` | Check GUI and MCP server state |
| `launch_gui()` | Start the Tkinter GUI process |
| `load_default_project()` | Fetch and display configured GitHub Project |
| `refresh()` | Reload project state |
| `search_project_items(query)` | Full-text search across all project items |
| `find_issue(issue_number, repo)` | Locate exact issue by number |
| `get_issue_context(issue_number, repo)` | Full issue + comments + project state |
| `resume_from_issue(repo, issue_number)` | Full resume context with work logs, blockers, next action |
| `get_latest_work_log(repo, issue_number)` | Parse latest structured work-log comment |
| `resume_project(query)` | Resume by text query (returns candidates) |
| `create_resume_handoff(repo, issue_number)` | Generate workdown file + post as GitHub comment |
| `append_work_log(repo, issue_number, ..., attachments)` | Add structured work-log comment with all GTD fields; optional file attachments |
| `add_comment(repo, issue_number, body, attachments)` | Post a plain comment; optional file attachments |
| `update_issue_body(repo, issue_number, body)` | Rewrite issue description |
| `create_issue(repo, title, body, labels, status, priority, attachments)` | Create issue, add to Project, set fields |
| `capture_issue(repo, title, ..., attachments)` | Capture inbox item with source context |
| `add_labels(issue_number, repo, labels)` | Ensure and apply labels |
| `set_project_field(issue_number, repo, field_name, option_name)` | Set Status/Priority/When via GraphQL |
| `set_issue_parent(child_issue_number, child_repo, parent_issue_number, parent_repo)` | Set sub-issue hierarchy |
| `organize_issue(issue_number, repo, ...)` | Combined label/field/parent update in one call |
| `bulk_organize_issues(items, ..., dry_run)` | Batch updates — always dry_run=True first |
| `close_issue(repo, issue_number)` | Mark issue closed |
| `attach_file_to_issue(issue_number, file_path, repo, caption, mode)` | Upload a file to the `gtd-assets` branch and embed/link it on an issue |
| `list_issue_files(issue_number, repo)` | List an issue's attachment manifest (incl. superseded/deleted) |
| `update_issue_file(issue_number, path, file_path, repo, caption, mode)` | Replace an attachment, preserving history |
| `delete_issue_file(issue_number, path, repo, handle_references)` | Delete an attachment; optionally annotate referencing comments |
| `gui_command(command)` | Direct HTTP API to GUI (debugging) |
| `stop_gui()` | Terminate GUI process |

---

## Skills

Two skills — each exists for Claude Code and the Codex app:

| Skill | Claude Code | Codex app |
|---|---|---|
| **gtd-mgmt** | `.claude/commands/gtd-mgmt.md` | `.agents/skills/gtd_mgmt/SKILL.md` |
| **gtd-workflow** | `.claude/commands/gtd-workflow.md` | `.agents/skills/gtd_workflow/SKILL.md` |

Deploy skills to both runtimes:
```bash
bash scripts/sync_skills.sh
```

---

## MCP Server Setup

### Claude Code (project-scoped, auto-loaded)

`.mcp.json` at the repo root registers the server automatically when Claude Code opens this directory.

### Claude for Desktop

1. **Settings → Developer → Edit Config** (or open `~/Library/Application Support/Claude/claude_desktop_config.json`)
2. Add:
```json
{
  "mcpServers": {
    "gtd_mgmt": {
      "command": "/Users/scotttandy/Documents/Claude/Projects/SWT Personal Management/.venv/bin/python3.13",
      "args": ["/Users/scotttandy/Documents/Claude/Projects/SWT Personal Management/agents/gtd_mgmt_mcp_server.py"],
      "cwd": "/Users/scotttandy/Documents/Claude/Projects/SWT Personal Management"
    }
  }
}
```
3. Fully quit and relaunch Claude for Desktop.

Or just run `bash scripts/sync_skills.sh` — it updates the desktop config automatically.

---

## Current Status (updated 2026-06-19)

### Done
- [x] Git repo initialized, pushed to `https://github.com/swtandy/personal-management`
- [x] 65 issues migrated and linked to GitHub Project V2
- [x] Python venv at `.venv/` (Python 3.13)
- [x] Ported gtd-agents architecture: `config.py`, `github_client.py`, 24-tool MCP server, GUI, dual-platform skills, sync script
- [x] GitHub Project V2 "Personal Management" (#2) with Status, Priority, When fields
- [x] Skill files: `.claude/commands/` and `.codex/skills/` for both gtd-mgmt and gtd-workflow
- [x] `plugins/gtd/` plugin structure and `.mcp.json` project-scoped auto-registration
- [x] `[Scott T] Inbox` created as issue #70; wired up in MCP server + all skill files
- [x] Areas of Focus defined (#71–#76); existing EPICs re-parented; skill files updated
- [x] File attachments (`attachments.py`, orphan `gtd-assets` branch, 4 new MCP tools + attachments param on add_comment/append_work_log/create_issue/capture_issue) — 2026-07-12

### Areas Of Focus

| Issue | Area | Covers |
|---|---|---|
| #71 | Home And Property | Deck at 85 Joaquin Road, home maintenance, repairs, garden |
| #72 | Workshop And Making | Woodworking, tools, fabrication projects |
| #73 | Health And Wellbeing | Medical, eye care, fitness, diet, mental health |
| #74 | Travel And Leisure | Vacations, timeshares (Westin Maui), trips, events |
| #75 | Career And Finance | Work, skills, learning, budgeting, investments, taxes |
| #76 | Relationships And Social | Family, friends, community, social commitments |

### Not yet done
- [ ] Run `bash scripts/sync_skills.sh` to deploy skills to Claude Code and Codex runtimes
- [ ] Install dependencies: `.venv/bin/pip install -r requirements.txt` (adds `customtkinter`)
- [ ] Triage open issues — assign Status/Priority/When in the Project
- [ ] Decide what to do with `swtandy/openclawstuff` — archive or leave as-is
- [x] EPIC: Personal (#34) dissolved — #54 → #73, #60 → #74, #34 closed

---

## Work Log Format

Structured session notes use a marker so future sessions can find them:

```md
<!-- gtd_mgmt:work-log:v1 -->
```

Always use `append_work_log` — not ad hoc comments — so resume prompts reliably locate the latest session state.
