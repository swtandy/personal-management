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

```bash
cd ~/Documents/Claude/Projects/SWT\ Personal\ Management
pip3 install -r requirements.txt
```

Python 3.9 / macOS. Use `pip3`, not `pip` (pip not on PATH).

---

## Tools Reference (`/tools`)

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
- [x] Git repo initialized, initial commit `92abb4b` on `main`
- [x] `swtandy/personal-management` created on GitHub
- [x] All 22 issues migrated from `swtandy/openclawstuff` → `swtandy/personal-management` (labels synced, source attribution in each issue footer)
- [x] Python deps installed locally

### Not yet done
- [ ] Push local repo to `https://github.com/swtandy/personal-management.git`
  - Run: `git remote add origin https://github.com/swtandy/personal-management.git && git push -u origin main`
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
