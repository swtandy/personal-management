# How Skill + MCP Sync Works

Syncing skills and an MCP server to Claude Code CLI, Cowork, and Codex CLI
requires touching five separate configuration locations across three clients.
None of the clients share configuration — updating one does not update the
others. Every sync problem we have hit came from either an assumption about
prior state or a missing step in this pipeline.

This document covers the general process and then calls out every specific
failure we have encountered. It applies to this project
(`swtandy/personal-management`) and is written to be reusable when setting
up a new project.

---

## Step 0 — Establish Your Coordinates Before Touching Anything

Do not assume any prior state. On a new machine, after a reinstall, or when
applying this to a different project, answer every question below before
running the sync script.

### 1. What machine and paths am I on?

```bash
echo $HOME                          # your home directory
whoami                              # your username
```

Every path in every config file is machine-specific. Paths that worked on
another machine will silently fail on this one.

### 2. What is the repo's GitHub identity?

```bash
cd <repo-root>
git remote get-url origin           # e.g. https://github.com/swtandy/personal-management.git
```

The GitHub owner (`swtandy`) and repo name (`personal-management`) are used:
- As the marketplace identifier: `swtandy/personal-management`
- As the plugin install command: `claude plugin install gtd@personal-management`

**Do not assume these match a previous project.** A different owner, a
different repo name, or a different plugin name means every command changes.

### 3. What is the repo's local path?

```bash
pwd                                 # confirm you are at the repo root
```

The MCP config files (`~/.claude.json`, `~/.codex/config.toml`,
`claude_desktop_config.json`, and `plugins/gtd/.mcp.json`) all embed the
**absolute local path** to the MCP server script and the venv Python binary.
If the repo lives at a different path than expected, those configs are wrong.

### 4. Does the venv exist and are dependencies installed?

```bash
ls .venv/bin/python3.13             # or whichever Python version this project uses
.venv/bin/pip list | grep -E "fastmcp|customtkinter|python-dotenv"
```

The sync script uses the project venv to run Python snippets that update
config files. If the venv is missing or incomplete, the sync will fail
partway through. Create it first:

```bash
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 5. Is the GitHub token present?

```bash
grep GITHUB_TOKEN .env 2>/dev/null && echo "found" || echo "MISSING"
```

The MCP server reads the token from `.env` at startup. If `.env` is missing
or the token is stale, the server will start but fail every GitHub API call.

### 6. What is the plugin name?

```bash
cat plugins/gtd/.claude-plugin/plugin.json   # "name" field
cat .claude-plugin/marketplace.json          # "name" and "plugins[].name"
```

The plugin name in `plugin.json` must match what `marketplace.json` declares.
The install command is `claude plugin install <plugin-name>@<marketplace-name>`.
For this project: `claude plugin install gtd@personal-management`.

### 7. Do the MCP paths in plugins/gtd/.mcp.json match this machine?

```bash
cat plugins/gtd/.mcp.json
```

This file embeds the absolute path to the venv Python binary and the MCP
server script. It is machine-specific. If it references a different user's
home directory or a different repo checkout path, update it before running
the sync. The sync script copies this file into the Cowork runtime directory,
so an outdated `.mcp.json` means the Cowork MCP will fail even when everything
else succeeds.

---

## Required Repo Structure

The following files must exist before the sync script can work. Check each
one when applying this to a new project.

```
<repo-root>/
  .claude-plugin/
    marketplace.json          ← required for `claude plugin marketplace add`
  plugins/
    gtd/
      .claude-plugin/
        plugin.json           ← plugin manifest with name + version
      .mcp.json               ← machine-specific MCP server paths (update per machine)
      skills/
        gtd-mgmt/
          SKILL.md            ← skill text for Cowork plugin
        gtd-workflow/
          SKILL.md
  .agents/
    skills/
      gtd_mgmt/
        SKILL.md              ← Codex app skill (read directly from repo — no sync)
        agents/
          openai.yaml         ← UI metadata + MCP dependency declaration
      gtd_workflow/
        SKILL.md
        agents/
          openai.yaml
  .claude/
    commands/
      gtd-mgmt.md             ← source for Claude Code CLI skill
      gtd-workflow.md
  .codex/
    config.toml               ← Codex MCP server registration (synced to ~/.codex/config.toml)
  agents/
    gtd_mgmt_mcp_server.py    ← the MCP server entry point
  scripts/
    sync_skills.sh            ← the sync script
  .env                        ← GITHUB_TOKEN (gitignored, never committed)
```

`marketplace.json` format:
```json
{
  "name": "<repo-name>",
  "owner": { "name": "<github-owner>" },
  "plugins": [
    { "name": "gtd", "source": "./plugins/gtd", "description": "..." }
  ]
}
```

`plugin.json` format:
```json
{
  "name": "gtd",
  "description": "...",
  "version": "1.2.0",
  "author": { "name": "<github-owner>" }
}
```

---

## What Gets Synced Where

| Source (this repo) | Destination | Client |
|---|---|---|
| `.claude/commands/gtd-mgmt.md` | `~/.claude/skills/gtd-mgmt/SKILL.md` | Claude Code CLI |
| `.claude/commands/gtd-workflow.md` | `~/.claude/skills/gtd-workflow/SKILL.md` | Claude Code CLI |
| `.agents/skills/gtd_mgmt/` | (read from repo — no sync needed) | Codex app |
| `.agents/skills/gtd_workflow/` | (read from repo — no sync needed) | Codex app |
| `plugins/gtd/` | `~/.claude/plugins/cache/personal-management/gtd/<version>/` | Cowork CLI cache (intermediate) |
| `plugins/gtd/skills/` + `plugins/gtd/.claude-plugin/` | `~/Library/Application Support/Claude/local-agent-mode-sessions/.../rpm/plugin_<id>/` | Cowork runtime (what Cowork actually reads) |
| MCP server path | `~/.claude.json` | Claude Code MCP |
| `.codex/config.toml` (in repo, MCP block) | `~/.codex/config.toml` | Codex MCP |
| MCP server path | `~/Library/Application Support/Claude/claude_desktop_config.json` | Cowork MCP |

The Cowork runtime rpm path contains opaque UUIDs and changes on reinstall.
**Never hardcode it.** The sync script finds it dynamically.

---

## The Standard Edit → Deploy Loop

```
1. Edit skill or plugin files in this repo
2. Bump version in plugins/gtd/.claude-plugin/plugin.json
3. git add, commit, push
4. bash scripts/sync_skills.sh
5. Restart Cowork; restart Codex or Claude Code if skill files changed
```

Every step matters. Skipping step 2 means `claude plugin update` reports
"already at latest" and does nothing. Skipping step 3 means the marketplace
clone is stale. Skipping step 5 means running sessions use the old skill text.

---

## First-Time Setup on a New Machine

Cowork's runtime directory does not exist until Cowork has launched with the
plugin installed. This requires a two-pass sync.

```bash
# 1. Clone the repo
git clone https://github.com/swtandy/personal-management.git
cd personal-management

# 2. Create the venv and install dependencies (check Python version first)
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 3. Copy .env with GitHub token (never committed — get it from your secure store)
#    echo 'GITHUB_TOKEN=ghp_...' > .env

# 4. Update plugins/gtd/.mcp.json with this machine's absolute paths
#    (command, args, cwd must all point to THIS checkout)

# 5. First sync pass — installs skills and MCP configs; installs Cowork plugin
#    into CLI cache; reports "Cowork rpm directory not found" (expected)
bash scripts/sync_skills.sh

# 6. Launch Cowork — first launch installs the plugin into the rpm directory

# 7. Second sync pass — now finds the rpm directory and syncs the runtime cache
bash scripts/sync_skills.sh

# 8. Restart Codex and Claude Code to pick up MCP config
```

The "Cowork rpm directory not found" message in step 5 is not a failure.
The rpm directory is created by Cowork on first launch. Step 7 completes it.

---

## What the Sync Script Does (Step by Step)

For **Claude Code CLI**:
- Copies `.claude/commands/*.md` to `~/.claude/skills/<name>/SKILL.md`
- Writes MCP server entry into `~/.claude.json` (project-scoped)

For **Codex app**:
- Validates `.agents/skills/*/SKILL.md` exist (no copy needed — Codex reads from the repo)
- Writes MCP server entry into `~/.codex/config.toml`

For **Cowork** (desktop app):
- Writes MCP server entry into `~/Library/Application Support/Claude/claude_desktop_config.json`

For **Cowork**:
1. Registers the marketplace if not already present:
   `claude plugin marketplace add swtandy/personal-management`
   Clones the repo to `~/.claude/plugins/marketplaces/swtandy-personal-management/`

2. **Pulls the marketplace clone** so the CLI sees the version in the latest
   push. Without this pull, `claude plugin update` compares against a stale
   local copy and reports "already at latest" even after bumping the version.

3. Runs `claude plugin update gtd@personal-management` (or `install` on first
   run). This updates `~/.claude/plugins/cache/` only — it does **not** update
   the Cowork runtime.

4. Finds the Cowork rpm directory dynamically and copies both `skills/` and
   `.claude-plugin/` from `plugins/gtd/` into it.

The sync script never removes stale MCP entries from config files — see the
troubleshooting section below.

---

## CRITICAL: Seven Things That Will Waste Your Day

### 1. The three clients use three completely separate locations

| Client | Skills location | MCP config |
|---|---|---|
| Claude Code CLI | `~/.claude/skills/` | `~/.claude.json` |
| Cowork | `~/Library/Application Support/Claude/local-agent-mode-sessions/.../rpm/plugin_<id>/skills/` | `claude_desktop_config.json` |
| Codex CLI | `~/.codex/skills/` | `~/.codex/config.toml` |

Updating one does not update the others. Running only `claude plugin update`
updates the CLI cache but not the Cowork runtime.

### 2. Cowork rpm needs both subdirectories copied — not just skills/

```
rpm/plugin_<id>/
  skills/           ← skill text
  .claude-plugin/   ← version manifest (plugin.json)
```

If `.claude-plugin/plugin.json` still says the old version, Cowork reports
the plugin as unchanged even if every skill file was replaced.

### 3. Version must be bumped on every content change

`claude plugin update` compares version strings. Unchanged version = no-op,
even if every file inside changed. **Bump on every commit that touches
`plugins/gtd/`.** Use semver: patch for text changes, minor for new skills.

### 4. marketplace.json must exist at the repo root

`claude plugin marketplace add` looks for `.claude-plugin/marketplace.json`
at the **repo root** — not inside `plugins/gtd/`. Without it:

```
Marketplace file not found at ~/.claude/plugins/marketplaces/<name>/.claude-plugin/marketplace.json
```

This file exists at `.claude-plugin/marketplace.json` in this repo. If adding
a new project, create it there first, commit, push, then register.

### 5. plugins/gtd/.mcp.json contains machine-specific absolute paths

The `.mcp.json` embedded in the plugin directory is copied verbatim into the
Cowork runtime. It must contain the absolute path to the venv Python binary
and the MCP server script for **the current machine**. If you clone the repo
on a new machine or a different path, update `.mcp.json` before syncing.
Do not commit a `.mcp.json` that hardcodes another machine's paths.

### 6. The sync script adds MCP entries but never removes stale ones

`claude_desktop_config.json` and `~/.claude.json` are append-only from the
sync script's perspective. If a previous project or setup left an entry
pointing to a non-existent script (e.g. `tools/mcp_server.py` from an old
layout), the desktop app will try to start it, fail, and show
"Server disconnected" — even though the current `gtd_mgmt` entry is correct.

After any sync, check `claude_desktop_config.json` for stale `mcpServers`
entries and remove them manually:

```bash
cat "$HOME/Library/Application Support/Claude/claude_desktop_config.json" | \
  python3 -c "import json,sys; d=json.load(sys.stdin); print(list(d.get('mcpServers',{}).keys()))"
```

Remove any entry whose `args` path no longer exists.

### 7. First Cowork install requires two sync passes

### 8. Codex app skills live in `.agents/skills/`, not `.codex/skills/`

The Codex app scans `.agents/skills/` from the repo directory at runtime.
Files in `.codex/skills/` are silently ignored — no error, no warning, skills
just don't appear. Each skill needs a `SKILL.md` with `name` and `description`
frontmatter, and optionally `agents/openai.yaml` for UI metadata and MCP
dependency declarations. The `openai.yaml` must use the nested `interface:`
format — flat keys at the root level are not read.

**Codex app skills do not need syncing.** The sync script only validates they
exist and writes the MCP entry to `~/.codex/config.toml`. Do not add a copy
step for `.agents/skills/` — it would be both wrong and unnecessary.

The rpm plugin runtime directory does not exist until Cowork has launched with
the plugin installed. The sync script will report "rpm directory not found" on
the first run — that is not a failure. Launch Cowork, let it fully start, then
re-run the sync script.

---

## The `claude` Binary Is Not on PATH

The `claude` CLI ships inside the desktop app bundle:

```
~/Library/Application Support/Claude/claude-code/<version>/claude.app/Contents/MacOS/claude
```

The sync script finds it by globbing for the latest version. To run it
manually:

```bash
alias claude="$HOME/Library/Application Support/Claude/claude-code/$(ls "$HOME/Library/Application Support/Claude/claude-code" | sort -V | tail -1)/claude.app/Contents/MacOS/claude"
```

---

## Troubleshooting

### Skills appear as "unknown skill" in Cowork

The Cowork rpm runtime directory is not populated. Cause: either the plugin
was never installed, or Cowork hasn't been launched since install.

```bash
# Check if the rpm skills directory exists
find "$HOME/Library/Application Support/Claude/local-agent-mode-sessions" \
  -type d -name "gtd-workflow" | grep "/rpm/"
```

If nothing is returned: install the plugin (`claude plugin install gtd@personal-management`),
launch Cowork, then re-run the sync script.

### Skills appear in Claude Code but not Cowork (or vice versa)

They use different directories. Claude Code CLI reads from `~/.claude/skills/`;
Cowork reads from the rpm directory. Re-run the sync script — it handles both.

### Cowork shows old skill text after restart

The rpm runtime was not updated. Re-run the sync script — it finds the rpm
path dynamically and copies fresh skill files in:

```bash
bash scripts/sync_skills.sh
```

If the rpm directory isn't found, Cowork hasn't loaded the plugin yet.
Launch Cowork, let it fully start, then re-run.

### Plugin update says "already at latest version" after a change

Version string in `plugins/gtd/.claude-plugin/plugin.json` was not bumped.
Bump it, commit, push, then re-run the sync.

### `claude plugin marketplace add` fails with "Marketplace file not found"

The repo root is missing `.claude-plugin/marketplace.json`. Create it,
commit, push, then retry.

### "Server disconnected" in Claude desktop / Cowork

A stale `mcpServers` entry in `claude_desktop_config.json` is pointing to a
path that no longer exists. The sync script does not clean up old entries.

```bash
cat "$HOME/Library/Application Support/Claude/claude_desktop_config.json"
```

Find and remove any `mcpServers` entry whose `args` script path doesn't exist,
then restart the app.

### MCP tools available in Claude Code but not Cowork (or vice versa)

Each client has its own MCP config file. Confirm the entry exists in the right
file for each client:

- Claude Code: `~/.claude.json` → `mcpServers.gtd_mgmt`
- Cowork: `~/Library/Application Support/Claude/claude_desktop_config.json` → `mcpServers.gtd_mgmt`
- Codex: `~/.codex/config.toml` → `[mcp_servers.gtd_mgmt]`

Re-run the sync script to write all three, then restart the affected client.

### MCP server starts but returns no GitHub data

The GitHub token is missing or expired. Check:

```bash
cd <repo-root>
.venv/bin/python3.13 -c "
from dotenv import load_dotenv; import os; load_dotenv()
t = os.getenv('GITHUB_TOKEN','')
print('Token present:', bool(t)); print('Prefix:', t[:8]+'...' if t else 'NONE')
"
```

If missing, add `GITHUB_TOKEN=ghp_...` to `.env` at the repo root.

### Skills load correctly but MCP tools fail on a freshly cloned repo

The venv does not exist or dependencies are not installed. The MCP server
imports packages from the project venv — a system Python or a different venv
will not have them:

```bash
cd <repo-root>
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Then re-run the sync so MCP configs point to `.venv/bin/python3.13` in the
new checkout location.

### Sync says `claude not found`

The app bundle path changed (new Claude version installed). The script globs
for the latest version — if it still fails, find the binary manually:

```bash
find "$HOME/Library/Application Support/Claude/claude-code" -name claude -type f
```
