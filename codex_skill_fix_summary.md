# Codex App Skill Fix — Context for Claude Code

## What Was Wrong

The Codex app skills were stored in `.codex/skills/` — a directory Codex never
scans. According to the official Codex docs, project skills must live in
`.agents/skills/` (scanned from CWD up to repo root). `.codex/` is only for
`config.toml`.

Additionally, the `agents/openai.yaml` metadata files used a flat format that
doesn't match the documented nested `interface:` structure, and were missing
`dependencies` declarations for the MCP server.

## What Was Fixed (already done, don't redo)

1. Created `.agents/skills/gtd_mgmt/SKILL.md` and
   `.agents/skills/gtd_workflow/SKILL.md` — copied from the existing
   `.codex/skills/` versions (content is correct).

2. Created `.agents/skills/gtd_mgmt/agents/openai.yaml` and
   `.agents/skills/gtd_workflow/agents/openai.yaml` with the correct nested
   `interface:` format and `dependencies.tools` MCP declarations.

3. Updated `CLAUDE.md` skill table to reference `.agents/skills/` paths.

The `.codex/skills/` directory still exists but is no longer the canonical
location. The `.codex/config.toml` MCP server registration is correct and
should not change.

## Key Insight About Codex App Skills

**Codex app skills don't need syncing.** Codex reads `.agents/skills/`
directly from the repo at runtime — no copy to a user directory required.
The old `sync_skills.sh` Codex step (copying `.codex/skills/` →
`~/.codex/skills/`) was both wrong (wrong source directory) and unnecessary
(Codex reads from the repo, not `~/.codex/skills/`).

Only the `~/.codex/config.toml` MCP entry still needs syncing (so Codex
finds the MCP server). That part of the script is correct.

---

## Task 1 — Update `how_to_sync.md`

File: `how_to_sync.md`

### Required Repo Structure section

Replace `.codex/skills/` tree with `.agents/skills/`:

```
# OLD (remove these lines):
  .codex/
    skills/
      gtd_mgmt/
        SKILL.md              ← source for Codex CLI skill
      gtd_workflow/
        SKILL.md

# NEW (add these lines):
  .agents/
    skills/
      gtd_mgmt/
        SKILL.md              ← Codex app skill (read directly from repo)
        agents/
          openai.yaml         ← UI metadata + MCP dependency declaration
      gtd_workflow/
        SKILL.md
        agents/
          openai.yaml
```

### What Gets Synced Where table

Replace the two `.codex/skills/` rows with a single note row:

```
# OLD (remove):
| `.codex/skills/gtd_mgmt/`      | `~/.codex/skills/gtd_mgmt/`      | Codex CLI |
| `.codex/skills/gtd_workflow/`   | `~/.codex/skills/gtd_workflow/`   | Codex CLI |

# NEW (replace with):
| `.agents/skills/gtd_mgmt/`     | (read from repo — no sync needed) | Codex app |
| `.agents/skills/gtd_workflow/`  | (read from repo — no sync needed) | Codex app |
| `.codex/config.toml`            | `~/.codex/config.toml`            | Codex MCP |
```

### What the Sync Script Does section

Remove the bullet that says it copies `.codex/skills/` to `~/.codex/skills/`.

Add a note:
> Codex app skills in `.agents/skills/` are read directly from the repo — no
> copy to `~/.codex/skills/` is needed. The sync script only writes the MCP
> server entry to `~/.codex/config.toml`.

### CRITICAL section — add new item

Add as item 8 (or renumber):

> **8. Codex app skills live in `.agents/skills/`, not `.codex/skills/`**
>
> The Codex app scans `.agents/skills/` in the repo directory. Files in
> `.codex/skills/` are silently ignored. Each skill needs a `SKILL.md` with
> `name` and `description` frontmatter, and optionally `agents/openai.yaml`
> for UI metadata and MCP dependency declarations. The `openai.yaml` must use
> the nested `interface:` format — flat keys at the root level are not read.

---

## Task 2 — Update `scripts/sync_skills.sh`

### Remove the Codex CLI skills copy block

Delete or comment out this entire section (lines ~14-31):

```bash
# ---------------------------------------------------------------------------
# Codex CLI skills  →  ~/.codex/skills/
# ---------------------------------------------------------------------------
codex_home="${CODEX_HOME:-$HOME/.codex}"
codex_skills_dir="$codex_home/skills"
mkdir -p "$codex_skills_dir"

for skill in gtd_mgmt gtd_workflow; do
    source_dir="$repo_root/.codex/skills/$skill"
    target_dir="$codex_skills_dir/$skill"

    if [[ ! -d "$source_dir" ]]; then
        echo "Missing Codex skill: $source_dir" >&2
        exit 1
    fi

    mkdir -p "$target_dir"
    cp -R "$source_dir/." "$target_dir/"
    echo "Synced Codex skill: $skill -> $target_dir"
done

echo "Restart Codex or start a new thread to pick up Codex skill changes."
echo ""
```

### Replace with a validation block

```bash
# ---------------------------------------------------------------------------
# Codex app skills  →  .agents/skills/ (read from repo — no sync needed)
# ---------------------------------------------------------------------------
# The Codex app reads skills directly from .agents/skills/ in the repo.
# No copy to ~/.codex/skills/ is required. Validate the files exist.
for skill in gtd_mgmt gtd_workflow; do
    skill_file="$repo_root/.agents/skills/$skill/SKILL.md"
    if [[ ! -f "$skill_file" ]]; then
        echo "WARNING: Missing Codex app skill: $skill_file" >&2
        echo "  Skills will not appear in the Codex app until this file exists." >&2
    else
        echo "Codex app skill present: .agents/skills/$skill/SKILL.md"
    fi
done
echo "Restart Codex to pick up skill changes (no sync needed — reads from repo)."
echo ""
```

The `~/.codex/config.toml` MCP config block that follows is correct — keep it.

---

## Task 3 — Add Tests

File: `tests/test_sync_skills.py`

Add the following test cases:

1. **`test_agents_skills_directory_exists`** — assert `.agents/skills/` exists
   at repo root.

2. **`test_gtd_mgmt_skill_md_exists`** — assert
   `.agents/skills/gtd_mgmt/SKILL.md` exists and is non-empty.

3. **`test_gtd_workflow_skill_md_exists`** — assert
   `.agents/skills/gtd_workflow/SKILL.md` exists and is non-empty.

4. **`test_skill_md_has_required_frontmatter`** — for each SKILL.md, parse
   YAML frontmatter (content between `---` delimiters) and assert both `name`
   and `description` keys are present and non-empty.

5. **`test_openai_yaml_uses_interface_key`** — for each
   `.agents/skills/*/agents/openai.yaml`, load YAML and assert the top-level
   key is `interface` (not flat `display_name`).

6. **`test_openai_yaml_declares_mcp_dependency`** — for each `openai.yaml`,
   assert `dependencies.tools` contains at least one entry with
   `type == "mcp"` and `value == "gtd_mgmt"`.

7. **`test_sync_script_does_not_copy_to_codex_skills`** — read
   `scripts/sync_skills.sh` as text and assert it does NOT contain
   `~/.codex/skills/` as a copy destination (to prevent regression).

8. **`test_codex_config_toml_mcp_entry_exists`** — read
   `.codex/config.toml` and assert `[mcp_servers.gtd_mgmt]` section is
   present with `command`, `args`, and `cwd` keys.

Use `pathlib.Path` and `yaml` (already a transitive dep via `fastmcp`).
Mirror the style of `tests/test_mcp_startup.py` — `unittest.TestCase`,
`REPO_ROOT = Path(__file__).resolve().parent.parent`.
