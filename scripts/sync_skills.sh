#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="${PYTHON:-.venv/bin/python3.13}"
# Resolve relative python_bin against repo_root
if [[ "$python_bin" != /* ]]; then
    python_bin="$repo_root/$python_bin"
fi

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

# ---------------------------------------------------------------------------
# Codex MCP config  →  ~/.codex/config.toml
# ---------------------------------------------------------------------------
codex_config="$codex_home/config.toml"
mkdir -p "$codex_home"
CODEX_CONFIG="$codex_config" REPO_ROOT="$repo_root" "$python_bin" <<'PY'
from pathlib import Path
import os
import re

config_path = Path(os.environ["CODEX_CONFIG"]).expanduser()
repo_root = Path(os.environ["REPO_ROOT"]).resolve()
config_path.parent.mkdir(parents=True, exist_ok=True)

desired = {
    "command": f'"{repo_root / ".venv/bin/python3.13"}"',
    "args": f'["{repo_root / "agents/gtd_mgmt_mcp_server.py"}"]',
    "cwd": f'"{repo_root}"',
}
defaults = {
    "startup_timeout_sec": "15",
    "tool_timeout_sec": "120",
}

lines = config_path.read_text().splitlines() if config_path.exists() else []
section_header = "[mcp_servers.gtd_mgmt]"

try:
    start = lines.index(section_header)
except ValueError:
    if lines and lines[-1].strip():
        lines.append("")
    lines.append(section_header)
    for key, value in desired.items():
        lines.append(f"{key} = {value}")
    for key, value in defaults.items():
        lines.append(f"{key} = {value}")
else:
    end = start + 1
    while end < len(lines) and not lines[end].startswith("["):
        end += 1

    present = set()
    for index in range(start + 1, end):
        stripped = lines[index].strip()
        for key, value in desired.items():
            if re.match(rf"^{re.escape(key)}\s*=", stripped):
                lines[index] = f"{key} = {value}"
                present.add(key)
    insert_at = start + 1
    for key, value in reversed(list(desired.items())):
        if key not in present:
            lines.insert(insert_at, f"{key} = {value}")
    section_lines = "\n".join(lines[start:end])
    for key, value in defaults.items():
        if not re.search(rf"(?m)^{re.escape(key)}\s*=", section_lines):
            lines.insert(start + 1 + len(desired), f"{key} = {value}")

config_path.write_text("\n".join(lines) + "\n")
PY
echo "Updated Codex MCP config: $codex_config"
echo ""

# ---------------------------------------------------------------------------
# Claude Code skills and commands  →  ~/.claude/
# ---------------------------------------------------------------------------
claude_home="${CLAUDE_HOME:-$HOME/.claude}"
claude_skills_dir="$claude_home/skills"
claude_commands_dir="$claude_home/commands"
mkdir -p "$claude_skills_dir"
mkdir -p "$claude_commands_dir"

for skill in gtd-mgmt gtd-workflow; do
    source_file="$repo_root/.claude/commands/$skill.md"
    target_skill_dir="$claude_skills_dir/$skill"

    if [[ ! -f "$source_file" ]]; then
        echo "Missing Claude Code skill source: $source_file" >&2
        exit 1
    fi

    mkdir -p "$target_skill_dir"
    cp "$source_file" "$target_skill_dir/SKILL.md"
    echo "Synced Claude Code skill: $skill -> $target_skill_dir/SKILL.md"

    # Remove stale global command file if present
    stale_cmd="$claude_commands_dir/$skill.md"
    if [[ -f "$stale_cmd" ]]; then
        rm "$stale_cmd"
        echo "Removed stale global command: $stale_cmd"
    fi
done

# ---------------------------------------------------------------------------
# Clean up stale MCP config from ~/.claude/settings.json
# ---------------------------------------------------------------------------
claude_settings="$claude_home/settings.json"
if [[ -f "$claude_settings" ]]; then
    CLAUDE_SETTINGS="$claude_settings" "$python_bin" <<'PY'
from pathlib import Path
import json, os

p = Path(os.environ["CLAUDE_SETTINGS"])
if not p.exists() or not p.stat().st_size:
    exit(0)
settings = json.loads(p.read_text())
if "mcpServers" in settings:
    del settings["mcpServers"]
    p.write_text(json.dumps(settings, indent=2) + "\n")
    print(f"Removed stale mcpServers from {p}")
PY
fi

# ---------------------------------------------------------------------------
# Claude Code MCP config  →  ~/.claude.json
# ---------------------------------------------------------------------------
claude_config="${CLAUDE_CONFIG:-$HOME/.claude.json}"
CLAUDE_CONFIG="$claude_config" REPO_ROOT="$repo_root" "$python_bin" <<'PY'
from pathlib import Path
import json
import os

config_path = Path(os.environ["CLAUDE_CONFIG"]).expanduser()
repo_root = Path(os.environ["REPO_ROOT"]).resolve()
config_path.parent.mkdir(parents=True, exist_ok=True)

if config_path.exists() and config_path.stat().st_size:
    settings = json.loads(config_path.read_text())
else:
    settings = {}

server_config = {
    "type": "stdio",
    "command": str(repo_root / ".venv/bin/python3.13"),
    "args": [str(repo_root / "agents/gtd_mgmt_mcp_server.py")],
    "cwd": str(repo_root),
    "timeout": 120000,
}

settings.setdefault("mcpServers", {})
settings["mcpServers"]["gtd_mgmt"] = server_config

projects = settings.setdefault("projects", {})
project_settings = projects.setdefault(str(repo_root), {})
project_settings.setdefault("mcpServers", {})
project_settings["mcpServers"]["gtd_mgmt"] = server_config

config_path.write_text(json.dumps(settings, indent=2) + "\n")
PY
echo "Updated Claude Code MCP config: $claude_config"
echo "Restart Claude Code or start a new session to pick up MCP config changes."
echo ""

# ---------------------------------------------------------------------------
# Claude desktop app MCP config  →  ~/Library/Application Support/Claude/claude_desktop_config.json
# ---------------------------------------------------------------------------
desktop_config="$HOME/Library/Application Support/Claude/claude_desktop_config.json"
if [[ -f "$desktop_config" ]]; then
    DESKTOP_CONFIG="$desktop_config" REPO_ROOT="$repo_root" "$python_bin" <<'PY'
from pathlib import Path
import json, os

config_path = Path(os.environ["DESKTOP_CONFIG"])
repo_root = Path(os.environ["REPO_ROOT"]).resolve()

settings = json.loads(config_path.read_text()) if config_path.exists() and config_path.stat().st_size else {}

server_config = {
    "type": "stdio",
    "command": str(repo_root / ".venv/bin/python3.13"),
    "args": [str(repo_root / "agents/gtd_mgmt_mcp_server.py")],
    "cwd": str(repo_root),
}

settings.setdefault("mcpServers", {})
settings["mcpServers"]["gtd_mgmt"] = server_config
config_path.write_text(json.dumps(settings, indent=2) + "\n")
print(f"Updated desktop app MCP config: {config_path}")
PY
else
    echo "Claude desktop app config not found, skipping: $desktop_config"
fi
echo "Restart the Claude desktop app to pick up MCP config changes."
echo ""

echo "Sync complete."
