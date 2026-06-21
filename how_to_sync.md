# How Skill Sync Works

This document explains the full sync pipeline so changes to skills and the
Cowork plugin actually reach every client.

---

## CRITICAL: Three Things That Will Waste Your Day If You Forget Them

These have each caused repeated debugging sessions. Read before touching anything.

---

### 1. The CLI and Cowork load plugins from completely different directories

The `claude plugin` CLI and the Cowork desktop app are **not the same thing**
and do **not share a plugin directory**. Updating one does not update the other.

| What | Where it stores plugins | Who reads it |
|---|---|---|
| `claude plugin` CLI | `~/.claude/plugins/cache/gtd-agents/gtd/<version>/` | Claude Code CLI only |
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

## What Gets Synced Where

| Source (this repo) | Destination | Client |
|---|---|---|
| `.codex/skills/gtd_mgmt/` | `~/.codex/skills/gtd_mgmt/` | Codex CLI |
| `.codex/skills/gtd_workflow/` | `~/.codex/skills/gtd_workflow/` | Codex CLI |
| `.claude/commands/gtd-mgmt.md` | `~/.claude/skills/gtd-mgmt/SKILL.md` | Claude Code / Cowork (skills dir) |
| `.claude/commands/gtd-workflow.md` | `~/.claude/skills/gtd-workflow/SKILL.md` | Claude Code / Cowork (skills dir) |
| `plugins/gtd/` | `~/.claude/plugins/cache/gtd-agents/gtd/<version>/` | CLI cache (not what Cowork loads) |
| `plugins/gtd/` | `~/Library/Application Support/Claude/local-agent-mode-sessions/.../rpm/plugin_<id>/` | Cowork runtime (what Cowork actually loads) |
| MCP server path | `~/.claude.json` | Claude Code MCP |
| MCP server path | `~/.codex/config.toml` | Codex MCP |
| MCP server path | `~/Library/Application Support/Claude/claude_desktop_config.json` | Claude desktop app MCP |

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
   `claude plugin marketplace add swtoxmiq/gtd-agents`
   The marketplace is stored as a git clone at
   `~/.claude/plugins/marketplaces/gtd-agents/`.

2. **Pulls the marketplace clone** (`git pull`) so the CLI can see the version
   declared in the just-pushed commit. Without this pull, `claude plugin update`
   compares against a stale local copy and reports "already at latest" even
   after a version bump.

3. Runs `claude plugin update gtd@gtd-agents` (or `install` on first run) to
   update the CLI cache at `~/.claude/plugins/cache/`. This does **not** update
   the Cowork runtime.

4. **Finds the Cowork rpm directory dynamically** and copies both `skills/` and
   `.claude-plugin/` into it. Both subdirectories must be copied — `skills/`
   alone leaves the old version number in `plugin.json` and Cowork considers
   the plugin unchanged.

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
git clone https://github.com/swtoxmiq/gtd-agents.git
cd gtd-agents

# 2. Create the venv and install dependencies (see README)
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 3. Run the sync — installs everything including the Cowork plugin
bash scripts/sync_skills.sh

# 4. Restart Codex, Claude Code, and Cowork
```

Note: on first run the Cowork runtime sync step will report "not found" because
Cowork hasn't launched yet and the rpm directory doesn't exist. Launch Cowork
once, then re-run `bash scripts/sync_skills.sh`.

**If the marketplace sync fails** ("Marketplace sync failed. Check the repository URL
and try again."): this is usually a GitHub App access problem — see the
troubleshooting section below. As a bypass, use the `create-cowork-plugin` skill
in Cowork to install the plugin directly without the marketplace, then re-run
`sync_skills.sh` so the script finds the rpm directory and handles future updates.

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

### Cowork shows "Marketplace sync failed. Check the repository URL and try again."

This is a GitHub App access problem, not a URL problem. Cowork uses a GitHub App
(not OAuth) to clone repos. For org repos the App must be explicitly installed on
the org — being in the org's Authorized Apps list is not the same thing.

For personal repos (`swtoxmiq/gtd-agents`) this is uncommon but can appear after
a Cowork reinstall or token expiry. Try re-authorizing the Cowork GitHub App in
your GitHub account settings. If the problem persists, use the `create-cowork-plugin`
skill in Cowork to install the plugin directly, then re-run `sync_skills.sh`.

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
