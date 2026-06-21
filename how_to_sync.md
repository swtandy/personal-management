# How Skill Sync Works

This document explains the full sync pipeline so changes to skills and the
Cowork plugin actually reach every client.

---

## CRITICAL: Four Things That Will Waste Your Day If You Forget Them

These have each caused real debugging sessions. Read before touching anything.

---

### 1. The CLI and Cowork load plugins from completely different directories

The `claude plugin` CLI and the Cowork desktop app are **not the same thing**
and do **not share a plugin directory**. Updating one does not update the other.

| What | Where it stores plugins | Who reads it |
|---|---|---|
| `claude plugin` CLI | `~/.claude/plugins/cache/personal-management/gtd/<version>/` | Claude Code CLI only |
| Cowork desktop app | `~/Library/Application Support/Claude/local-agent-mode-sessions/.../rpm/plugin_<id>/` | Cowork only |

**Both must be updated.** The sync script handles both automatically. Running
only `claude plugin update` is not enough.

The rpm path contains opaque UUIDs and can change after a Cowork reinstall.
The sync script finds it dynamically — do not hardcode it anywhere.

---

### 2. The Cowork rpm directory contains two subdirectories — both must be copied

The Cowork runtime plugin directory has this structure:

```
rpm/plugin_<id>/
  skills/           ← skill text (SKILL.md files)
  .claude-plugin/   ← plugin manifest including version number (plugin.json)
```

**Copying only `skills/` is not enough.** If `.claude-plugin/plugin.json` still
says the old version, Cowork reports the plugin as unchanged even though the
skill text is different. The sync script copies both. Do not write a shortcut
that only copies `skills/`.

---

### 3. You must bump the version in plugin.json on every content change

The `claude plugin update` command compares version strings. If the version in
`plugins/gtd/.claude-plugin/plugin.json` hasn't changed, it does nothing and
reports "already at latest version" — even if every file inside changed.

**Bump the version on every commit that touches `plugins/gtd/`.** The sync
script will not fix this for you.

---

### 4. The repo root needs marketplace.json before the marketplace can be registered

`claude plugin marketplace add swtandy/personal-management` requires a file at
`.claude-plugin/marketplace.json` in the repo root (not inside `plugins/gtd/`).
Without it the command fails with:

```
Marketplace file not found at ~/.claude/plugins/marketplaces/swtandy-personal-management/.claude-plugin/marketplace.json
```

This file already exists in the repo (`/.claude-plugin/marketplace.json`). If
you ever see that error it means the file was deleted or the wrong repo URL was
used.

---

## What Gets Synced Where

| Source (this repo) | Destination | Client |
|---|---|---|
| `.codex/skills/gtd_mgmt/` | `~/.codex/skills/gtd_mgmt/` | Codex CLI |
| `.codex/skills/gtd_workflow/` | `~/.codex/skills/gtd_workflow/` | Codex CLI |
| `.claude/commands/gtd-mgmt.md` | `~/.claude/skills/gtd-mgmt/SKILL.md` | Claude Code CLI |
| `.claude/commands/gtd-workflow.md` | `~/.claude/skills/gtd-workflow/SKILL.md` | Claude Code CLI |
| `plugins/gtd/` | `~/.claude/plugins/cache/personal-management/gtd/<version>/` | CLI cache (not what Cowork loads) |
| `plugins/gtd/` | `~/Library/Application Support/Claude/local-agent-mode-sessions/.../rpm/plugin_<id>/` | Cowork runtime (what Cowork actually loads) |
| MCP server path | `~/.claude.json` | Claude Code MCP |
| MCP server path | `~/.codex/config.toml` | Codex MCP |
| MCP server path | `~/Library/Application Support/Claude/claude_desktop_config.json` | Claude desktop app / Cowork MCP |

---

## The Standard Edit → Deploy Loop

```
1. Edit skill or plugin files in this repo
2. Bump plugin version in plugins/gtd/.claude-plugin/plugin.json
3. git add, commit, push
4. bash scripts/sync_skills.sh
5. Restart Cowork (and Codex / Claude Code if those skill files changed)
```

Every step matters. Skipping any one of them means the change does not reach
the client.

---

## What the Sync Script Does (Step by Step)

The script (`scripts/sync_skills.sh`) does the following for Cowork:

1. Registers the marketplace if not already present:
   `claude plugin marketplace add swtandy/personal-management`
   The marketplace is stored as a git clone at
   `~/.claude/plugins/marketplaces/swtandy-personal-management/`.

2. **Pulls the marketplace clone** (`git pull`) so the CLI can see the version
   declared in the just-pushed commit. Without this pull, `claude plugin update`
   compares against a stale local copy and reports "already at latest" even
   after a version bump.

3. Runs `claude plugin update gtd@personal-management` (or `install` on first
   run) to update the CLI cache at `~/.claude/plugins/cache/`. This does **not**
   update the Cowork runtime.

4. **Finds the Cowork rpm directory dynamically** and copies both `skills/` and
   `.claude-plugin/` from `plugins/gtd/` into it. Both subdirectories must be
   copied — `skills/` alone leaves the old version number in `plugin.json` and
   Cowork considers the plugin unchanged.

Use semver for version bumps. Content-only changes (skill text): bump patch.
New skills or tools: bump minor. Breaking changes: bump major.

---

## The `claude` Binary Is Not on PATH

The `claude` CLI ships inside the desktop app bundle, not at a standard PATH
location:

```
~/Library/Application Support/Claude/claude-code/<version>/claude.app/Contents/MacOS/claude
```

The sync script finds it automatically by globbing that path. If you run the
`claude` command manually, use the full path or set up a shell alias:

```bash
alias claude="$HOME/Library/Application Support/Claude/claude-code/$(ls "$HOME/Library/Application Support/Claude/claude-code" | sort -V | tail -1)/claude.app/Contents/MacOS/claude"
```

---

## First-Time Setup on a New Machine

```bash
# 1. Clone the repo
git clone https://github.com/swtandy/personal-management.git
cd personal-management

# 2. Create the venv and install dependencies
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 3. Run the sync — installs Codex/Claude Code skills, MCP configs, and the Cowork plugin
bash scripts/sync_skills.sh

# 4. Launch Cowork (first launch creates the rpm plugin directory)

# 5. Re-run the sync — now it can find the rpm directory and sync the runtime cache
bash scripts/sync_skills.sh

# 6. Restart Codex and Claude Code to pick up skills and MCP config
```

Note: step 3 will report "Cowork rpm gtd plugin directory not found" on first
run — that is expected. The rpm directory is created when Cowork first loads the
plugin after step 4. Re-running in step 5 completes the runtime sync.

---

## Troubleshooting

### Cowork shows old skill text after restart

First confirm what path Cowork is actually loading from:

```bash
find "$HOME/Library/Application Support/Claude/local-agent-mode-sessions" \
  -type d -name "gtd-workflow" | grep "/rpm/"
```

Then re-run the sync — it finds and updates that path automatically:

```bash
bash scripts/sync_skills.sh
```

If the rpm directory isn't found at all, Cowork hasn't loaded the plugin yet.
Launch Cowork, let it fully start, then re-run the sync.

### Sync reports success but Cowork still shows old version number

The sync copied `skills/` but the old `plugin.json` was left in
`.claude-plugin/`. This should not happen with the current sync script, but if
it does, manually verify both were copied:

```bash
rpm_gtd=$(find "$HOME/Library/Application Support/Claude/local-agent-mode-sessions" \
  -type d -name "gtd-workflow" | grep "/rpm/" | sed 's|/skills/gtd-workflow||' | head -1)
cat "$rpm_gtd/.claude-plugin/plugin.json"   # should show current version
```

### Plugin update says "already at latest version" after a content change

You forgot to bump `plugins/gtd/.claude-plugin/plugin.json`. Bump the version,
commit, push, then re-run the sync.

### Sync says `claude not found`

The app bundle path changed (new app version installed). The script globs for
the latest version directory — if it still fails, find the binary manually:

```bash
find "$HOME/Library/Application Support/Claude/claude-code" -name claude -type f
```

### `claude plugin marketplace add` fails with "Marketplace file not found"

The repo root is missing `.claude-plugin/marketplace.json`. This file must exist
at the repo root (not inside `plugins/gtd/`) for the marketplace to register.
Check it exists, commit, push, then re-run the sync.

### Skills changed but Codex/Claude Code still uses old text

Restart the app or start a new thread/session. Skill files are loaded at
session start — a running session does not reload them mid-conversation.

### MCP server not connecting

Re-run the sync (updates `~/.claude.json` and `~/.codex/config.toml` with the
current repo path), then restart the client. The sync always writes the
absolute path of the current checkout, so it self-corrects if the repo moves.

### Claude desktop app reports "Server disconnected" after sync

The sync script adds the `gtd_mgmt` entry to `claude_desktop_config.json` but
does **not** remove old entries. If the config has a stale entry from a previous
setup (e.g. `github-personal-management` pointing to `tools/mcp_server.py`
which no longer exists), the desktop app will fail to start that server and show
"Server disconnected" — even though `gtd_mgmt` is correctly configured.

Fix: open `~/Library/Application Support/Claude/claude_desktop_config.json`,
find any `mcpServers` entries that don't point to
`agents/gtd_mgmt_mcp_server.py`, and remove them. Then restart the desktop app.
