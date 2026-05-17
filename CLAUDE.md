# CLAUDE.md — SWT Personal Management

This file is read automatically by Claude Code at session start. Paste it into Claude co-work to sync context between the two environments.

---

## Project Purpose

A personal management operating system for Scott Tandy (swtandy) built on GitHub Issues + Python tooling. The goal is to consolidate life/project tracking into a single GitHub repo (`swtandy/personal-management`) rather than scattered repos.

---

## GitHub Repos Involved

| Repo | Role |
|---|---|
| `swtandy/personal-management` | **Destination** — the consolidated personal OS |
| `swtandy/openclawstuff` | **Source** — original issue tracker, 22 issues (deck project at 85 Joaquin Road) |

GitHub username: `swtandy`  
Token: stored in `.env` (gitignored — never committed)

---

## Local Setup

Requires Python 3.10+. Use the project venv (Python 3.13 via Homebrew):

```bash
cd ~/Documents/Claude/Projects/SWT\ Personal\ Management
python3.13 -m venv .venv          # first time only
.venv/bin/pip install -r requirements.txt
```

Scripts can also be run with system `pip3`/`python3` for the CLI tools (Python 3.9), but the MCP server requires the `.venv`.

---

## MCP Server — Claude co-work integration

`tools/mcp_server.py` exposes GitHub tools directly to Claude co-work via MCP. Co-work can call these without any copy-paste:

| Tool | What it does |
|---|---|
| `list_repos()` | All repos with open issue counts |
| `list_issues(repo, state)` | Issues in a repo (open/closed/all) |
| `get_issue(repo, number)` | Full issue detail + comments |
| `create_issue(repo, title, body, labels)` | Create a new issue |
| `update_issue(repo, number, ...)` | Update title, body, state, or labels |
| `add_comment(repo, number, body)` | Add a comment |
| `close_issue(repo, number, comment)` | Close, with optional comment |
| `list_labels(repo)` | All labels in a repo |
| `create_label(repo, name, color, description)` | Create a label |
| `migrate_issues(source, dest, dry_run, state)` | Migrate issues — always dry_run=true first |

### Adding to Claude for Desktop

Local stdio MCP servers require **Claude for Desktop** (the Mac app) — the claude.ai web interface only supports remotely-hosted MCP servers.

1. In Claude for Desktop: **Settings → Developer → Edit Config**  
   (or open `~/Library/Application Support/Claude/claude_desktop_config.json` directly)

2. Add:
```json
{
  "mcpServers": {
    "github-personal-management": {
      "command": "/Users/scotttandy/Documents/Claude/Projects/SWT Personal Management/.venv/bin/python3.13",
      "args": [
        "/Users/scotttandy/Documents/Claude/Projects/SWT Personal Management/tools/mcp_server.py"
      ]
    }
  }
}
```

3. Fully quit and relaunch Claude for Desktop. The GitHub tools will appear in chat.

---

## CLI Tools Reference (`/tools`)

All scripts load `.env` from the project root automatically via `github_client.py`.

| Script | Usage |
|---|---|
| `list_repos.py` | `python3 tools/list_repos.py` |
| `list_issues.py` | `python3 tools/list_issues.py swtandy/openclawstuff [--state open\|closed\|all] [--json]` |
| `create_repo.py` | `python3 tools/create_repo.py` — safe to re-run, checks first |
| `migrate_issues.py` | `python3 tools/migrate_issues.py --source <repo> --dest <repo> [--dry-run] [--state all] [--label-filter <label>]` |

**Always `--dry-run` before a real migration.**

---

## Current Status (updated 2026-05-17)

### Done
- [x] Git repo initialized, pushed to `https://github.com/swtandy/personal-management`
- [x] `swtandy/personal-management` created on GitHub
- [x] All 22 issues migrated from `swtandy/openclawstuff` → `swtandy/personal-management` (labels synced, source attribution in each issue footer)
- [x] Python venv at `.venv/` (Python 3.13) with all deps including `mcp`
- [x] MCP server `tools/mcp_server.py` — 10 tools ready for co-work integration
- [x] CLI toolkit: `github_client.py`, `list_repos.py`, `list_issues.py`, `create_repo.py`, `migrate_issues.py`

### Not yet done
- [ ] Add MCP server to claude.ai co-work (see MCP Server section above)
- [ ] Decide what to do with `swtandy/openclawstuff` — close issues, archive repo, or leave as-is
- [ ] Define what other life areas go into `personal-management` beyond the deck project

### Open decisions
- Should the deck issues (#1–22) be reorganized (milestones, projects board) now that they're in the new repo?
- Are there other source repos to consolidate?

---

## Keeping Claude Code + Claude co-work in sync

- Claude Code reads this file automatically each session
- For co-work: paste the **Current Status** section (or the whole file) at the start of the session
- When either Claude makes progress, update the **Current Status** section above
