#!/usr/bin/env python3
"""MCP server for launching and controlling the GTD project GUI."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any
try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 fallback
    tomllib = None

from mcp.server.fastmcp import FastMCP

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import GITHUB_PROJECT_NUMBER, GITHUB_USER


GUI_SCRIPT = REPO_ROOT / "agents" / "project_gui.py"
PORTS = (8775, 8776, 8777)
PID_PATH = Path("/tmp") / "gtd_mgmt_gui.pid"
LOG_PATH = Path("/tmp") / "gtd_mgmt_gui.log"
DEFAULT_HANDOFF_DIR = REPO_ROOT / "handoffs"
DEFAULT_CODEX_APP_PROJECT_NAME = "SWT Personal Management"
DEFAULT_CODEX_APP_PROJECT_PATH = Path("/Users/scotttandy/Documents/Claude/Projects/SWT Personal Management")

_gui_process: subprocess.Popen | None = None

mcp = FastMCP("gtd_mgmt")


def _json(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, sort_keys=True)


def _request_json(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    port: int | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    if not path.startswith("/"):
        path = "/" + path
    base_port = port or _find_server_port()
    if base_port is None:
        raise RuntimeError("gtd_mgmt GUI command server not found")
    url = f"http://127.0.0.1:{base_port}{path}"
    data = None
    headers = {"Accept": "application/json"}
    if method.upper() == "POST":
        data = json.dumps(payload or {}).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _probe_port(port: int) -> dict[str, Any] | None:
    try:
        data = _request_json("GET", "/status", port=port, timeout=0.5)
        data["base_url"] = f"http://127.0.0.1:{port}"
        return data
    except Exception:
        return None


def _find_server_port() -> int | None:
    for port in PORTS:
        if _probe_port(port):
            return port
    return None


def _find_server() -> dict[str, Any] | None:
    for port in PORTS:
        data = _probe_port(port)
        if data:
            return data
    return None


def _read_pid() -> int | None:
    try:
        return int(PID_PATH.read_text().strip())
    except Exception:
        return None


def _pid_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _wait_for_server(timeout_seconds: float = 15.0) -> dict[str, Any] | None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        server = _find_server()
        if server:
            return server
        time.sleep(0.25)
    return None


def _ensure_gui(launch_if_needed: bool = True) -> dict[str, Any]:
    server = _find_server()
    if server:
        return server
    if not launch_if_needed:
        raise RuntimeError("gtd_mgmt GUI is not running")
    launched = json.loads(launch_gui(dry_run=False))
    server = launched.get("server")
    if not server:
        raise RuntimeError(f"gtd_mgmt GUI did not start: {launched}")
    return server


def _ensure_project_loaded(launch_if_needed: bool = True, timeout_seconds: float = 60.0) -> dict[str, Any]:
    status = _ensure_gui(launch_if_needed)
    if status.get("loading"):
        status = _wait_until_loaded(timeout_seconds)
    if not status.get("project_title") and not status.get("issue_count"):
        _request_json("POST", "/load-project", {})
        status = _wait_until_loaded(timeout_seconds)
    return status


def _wait_until_loaded(timeout_seconds: float = 60.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_status: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last_status = _request_json("GET", "/status")
        if not last_status.get("loading"):
            return last_status
        time.sleep(0.5)
    return last_status


def _post_apply_change(payload: dict[str, Any], *, timeout: float = 60.0, wait: bool = True) -> str:
    result = _request_json("POST", "/apply-change", payload, timeout=timeout)
    if wait and result.get("ok"):
        result["status"] = _wait_until_loaded(timeout)
    return _json(result)


def _get_issue_context_data(
    repo: str,
    issue_number: int,
    comments: int = 8,
    launch_if_needed: bool = True,
) -> dict[str, Any]:
    try:
        status = _ensure_project_loaded(launch_if_needed)
        if status.get("error"):
            return {
                "ok": False,
                "repo": repo,
                "issue_number": issue_number,
                "error": "default GitHub Project failed to load",
                "details": status.get("error"),
                "status": status,
            }
        params = urllib.parse.urlencode({"n": issue_number, "repo": repo, "comments": comments})
        return _request_json("GET", f"/context?{params}", timeout=30.0)
    except Exception as exc:
        return {
            "ok": False,
            "repo": repo,
            "issue_number": issue_number,
            "error": str(exc),
            "hint": "Confirm the gtd_mgmt GUI can load the configured GitHub Project and that the issue is in that project.",
        }


def _repo_name(repo: str) -> str:
    return repo.rsplit("/", 1)[-1] if "/" in repo else repo


def _is_current_repo_name(name: str) -> bool:
    return name == "SWT Personal Management" and REPO_ROOT.name == "SWT Personal Management"


def _parse_project_path_map(raw: str) -> dict[str, str]:
    raw = (raw or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return {str(key): str(value) for key, value in data.items()}
    except json.JSONDecodeError:
        pass

    mapping = {}
    for entry in raw.replace("\n", ";").split(";"):
        if "=" not in entry:
            continue
        key, value = entry.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key and value:
            mapping[key] = value
    return mapping


def _trusted_codex_project_paths(config_path: Path | None = None) -> list[Path]:
    config = config_path or Path.home() / ".codex" / "config.toml"
    if tomllib is None or not config.exists():
        return []
    try:
        data = tomllib.loads(config.read_text())
    except Exception:
        return []
    projects = data.get("projects")
    if not isinstance(projects, dict):
        return []
    return [Path(path).expanduser() for path in projects.keys()]


def resolve_codex_project_path(
    repo: str,
    *,
    explicit_path: str | None = None,
    project_path_map: dict[str, str] | None = None,
    trusted_paths: list[Path] | None = None,
) -> dict[str, Any]:
    """Resolve a GitHub repo name to the local Codex project path Scott should switch to."""
    repo = str(repo or "").strip()
    if explicit_path and explicit_path.strip():
        p = Path(explicit_path.strip()).expanduser()
        result: dict[str, Any] = {
            "repo": repo,
            "path": str(p),
            "source": "explicit codex_project_path from work log",
            "exists": p.exists(),
            "confidence": "high" if p.exists() else "low",
        }
        if not p.exists():
            result["warning"] = f"Work log codex_project_path does not exist on disk: {p}"
        return result
    name = _repo_name(repo)
    mapping = project_path_map if project_path_map is not None else _parse_project_path_map(os.getenv("CODEX_PROJECT_PATHS", ""))
    trusted = trusted_paths if trusted_paths is not None else _trusted_codex_project_paths()

    for key in (repo, name):
        if key in mapping:
            path = Path(mapping[key]).expanduser()
            return {
                "repo": repo,
                "path": str(path),
                "source": f"CODEX_PROJECT_PATHS[{key}]",
                "exists": path.exists(),
                "confidence": "explicit",
            }

    if name == REPO_ROOT.name or _is_current_repo_name(name):
        return {
            "repo": repo,
            "path": str(REPO_ROOT),
            "source": "SWT Personal Management repo root",
            "exists": True,
            "confidence": "high",
        }

    trusted_matches = [path for path in trusted if path.name == name]
    if len(trusted_matches) == 1:
        path = trusted_matches[0]
        return {
            "repo": repo,
            "path": str(path),
            "source": "Codex trusted projects",
            "exists": path.exists(),
            "confidence": "high",
        }
    if len(trusted_matches) > 1:
        return {
            "repo": repo,
            "path": "",
            "source": "Codex trusted projects",
            "exists": False,
            "confidence": "ambiguous",
            "candidates": [str(path) for path in trusted_matches],
            "warning": "Multiple trusted Codex projects match this repo name; choose the correct project manually.",
        }

    inferred = Path.home() / "source" / "repos" / name
    if inferred.exists():
        return {
            "repo": repo,
            "path": str(inferred),
            "source": "~/source/repos/<repo>",
            "exists": True,
            "confidence": "inferred",
        }

    return {
        "repo": repo,
        "path": "",
        "source": "unresolved",
        "exists": False,
        "confidence": "unknown",
        "warning": "Could not resolve the local Codex project path automatically.",
    }


def _context_labels(context: dict[str, Any]) -> list[str]:
    labels = context.get("labels") or (context.get("issue") or {}).get("labels") or []
    return [str(label).strip() for label in labels if str(label).strip()]


def _context_text_fields(context: dict[str, Any]) -> list[str]:
    parsed = ((context.get("latest_work_log") or {}).get("parsed") or {})
    values = [
        context.get("body") or "",
        (context.get("issue") or {}).get("body") or "",
    ]
    for key in ("current_state", "next_steps", "codex_project", "useful_context"):
        values.extend(parsed.get(key) or [])
    return [str(value) for value in values if str(value).strip()]


def _existing_path_from_text(text: str) -> Path | None:
    for raw in text.replace("`", " ").split():
        candidate = raw.rstrip(".,;:)")
        if not candidate.startswith("/") or len(candidate) <= 1:
            continue
        path = Path(candidate).expanduser()
        if path.exists() and path.is_dir():
            return path
    return None


def resolve_codex_project_for_context(context: dict[str, Any], fallback_repo: str) -> dict[str, Any]:
    """Resolve the target Codex project from handoff-specific issue context."""
    parsed = _parsed_work_log(context)

    # Prefer related_local_workspaces from the work log as the implementation workspace.
    # Split on ; and , only — never on whitespace — so paths with spaces are preserved.
    for item in (parsed.get("related_local_workspaces") or []):
        for part in str(item).replace(";", ",").split(","):
            candidate = part.strip().rstrip(".:")
            if not candidate.startswith("/") or len(candidate) <= 1:
                continue
            return resolve_codex_project_path(fallback_repo, explicit_path=candidate)

    for label in _context_labels(context):
        if not label.startswith("codex-project:"):
            continue
        project_name = label.split(":", 1)[1].strip()
        if not project_name:
            continue
        resolved = resolve_codex_project_path(project_name)
        if resolved.get("path"):
            resolved["source"] = f"{label} label -> {resolved.get('source')}"
            return resolved

    for text in _context_text_fields(context):
        path = _existing_path_from_text(text)
        if path:
            return {
                "repo": fallback_repo,
                "path": str(path),
                "source": "explicit target path in issue/work-log context",
                "exists": True,
                "confidence": "high",
            }

    return resolve_codex_project_path(fallback_repo)


def _markdown_list(values: list[Any] | None, *, empty: str = "None documented.") -> str:
    cleaned = [str(value).strip() for value in values or [] if str(value).strip()]
    if not cleaned:
        return empty
    return "\n".join(f"- {value}" for value in cleaned)


def _markdown_value(value: Any, *, empty: str = "None documented.") -> str:
    text = str(value or "").strip()
    return text if text else empty


def _parsed_work_log(context: dict[str, Any]) -> dict[str, list[str]]:
    return ((context.get("latest_work_log") or {}).get("parsed") or {})


def _default_codex_app_project() -> dict[str, Any]:
    """Return the Codex app project, distinct from related repos/workspaces."""
    raw_path = os.getenv("CODEX_APP_PROJECT_PATH", "").strip()
    # Fall back to REPO_ROOT (where this MCP server lives = the current Claude Code workspace)
    # rather than a hardcoded path that only applies to one machine configuration.
    path = Path(raw_path).expanduser() if raw_path else REPO_ROOT
    name = os.getenv("CODEX_APP_PROJECT_NAME", "").strip() or path.name or DEFAULT_CODEX_APP_PROJECT_NAME
    return {
        "name": name,
        "path": str(path),
        "confidence": "high" if path.exists() else "unknown",
        "reason": "This is the Claude Code workspace for Scott's GTD issue-management work.",
        "exists": path.exists(),
    }


def _codex_app_project_from_work_log(parsed: dict[str, list[str]]) -> dict[str, Any] | None:
    """Extract Codex app project from work-log fields; return None when both fields are absent."""
    names = [v.strip() for v in (parsed.get("codex_project") or []) if v.strip()]
    paths = [v.strip() for v in (parsed.get("codex_project_path") or []) if v.strip()]
    if not names and not paths:
        return None
    name = names[0] if names else ""
    path_str = paths[0] if paths else ""
    if path_str:
        p = Path(path_str).expanduser()
        exists = p.exists()
        path_out = str(p)
    else:
        exists = False
        path_out = ""
    if not name and path_str:
        name = Path(path_str).name
    return {
        "name": name,
        "path": path_out,
        "confidence": "high",
        "reason": "Derived from latest work log (codex_project / codex_project_path).",
        "exists": exists,
    }


def _related_github_repos(context: dict[str, Any], workspace: dict[str, Any]) -> list[str]:
    repos = [str(context.get("repo") or "").strip()]
    workspace_repo = _repo_name(str(workspace.get("repo") or "")).strip()
    if workspace_repo and "/" not in workspace_repo:
        owner = (str(context.get("repo") or "").split("/", 1)[0] or "").strip()
        if owner:
            repos.append(f"{owner}/{workspace_repo}")
    elif workspace.get("repo"):
        repos.append(str(workspace["repo"]).strip())
    return list(dict.fromkeys(repo for repo in repos if repo))


def _build_project_routing_prompt(issue_ref: str, codex_app_project: dict[str, Any]) -> str:
    name = _markdown_value(codex_app_project.get("name"), empty="Unresolved")
    path = _markdown_value(codex_app_project.get("path"), empty="Unresolved")
    confidence = _markdown_value(codex_app_project.get("confidence"), empty="unknown")
    reason = _markdown_value(codex_app_project.get("reason"), empty="No reason documented.")
    return (
        f"Use gtd_workflow and gtd_mgmt only to decide where Scott should work on {issue_ref}. "
        "Do not start implementation, inspect or edit repositories, run tests, create another handoff, or update GitHub. "
        "Codex project means the project name/container in the Codex application, not a GitHub repo and not merely a source checkout. "
        "Use only the 'Recommended Codex Project' section below for the Codex project answer. "
        "Use 'Related Local Workspaces' and 'Related GitHub Repositories' only as supporting context. "
        "Return exactly these five lines:\n"
        f"Recommended Codex project: {name}\n"
        f"Codex project path: {path}\n"
        f"Confidence: {confidence}\n"
        f"Reason: {reason}\n"
        "Related context: see handoff sections for local workspaces and GitHub repositories."
    )


def _build_execution_resume_prompt(issue_ref: str) -> str:
    return (
        f"Use this handoff/workdown context to orient yourself to {issue_ref}. "
        "You are now in the recommended Codex application project, but the actual implementation work may live in "
        "one or more related local workspaces or GitHub repositories listed later in this handoff.\n\n"
        "First, read the handoff sections in this order: Recommended Codex Project, Related Local Workspaces, "
        "Related GitHub Repositories, Source Issue, Where We Left Off, Next Action, Blockers / Open Questions, "
        "Latest Structured Work Log, and End-Of-Session GTD Update.\n\n"
        "Then inspect only enough local repository state to understand the current working context: current directories, "
        "git status, branch, remotes, and relevant files in the listed related local workspaces. Do not edit files, run "
        "broad tests, create commits, create another handoff, or update GitHub during orientation.\n\n"
        "After orientation, stop and summarize: 1. Which Codex app project is coordinating the work. "
        "2. Which local workspace(s) and GitHub repo(s) appear to contain the implementation work. "
        "3. What the current repo state is, including uncommitted changes that may belong to Scott or another session. "
        "4. What you believe the next useful actions are, with 2-4 concrete options if there is more than one reasonable path. "
        "5. Your recommended plan.\n\n"
        "Your first step after orientation is to align with Scott on the plan. Ask for confirmation before doing implementation work, "
        "making edits, running expensive or broad validation, creating commits, pushing, opening PRs, creating another handoff, "
        "or updating the GTD issue. Do not create another handoff unless Scott explicitly asks. "
        "Before finishing any later implementation session, summarize what changed and return the "
        "GTD work-log fields from the End-Of-Session section."
    )


def build_resume_handoff_markdown(context: dict[str, Any], codex_project: dict[str, Any]) -> str:
    """Build the Markdown workdown packet for a target project Codex thread."""
    repo = str(context.get("repo") or "")
    issue_number = context.get("issue_number") or ""
    title = str(context.get("title") or "")
    project = context.get("project") or {}
    resume = context.get("resume_summary") or {}
    parsed = _parsed_work_log(context)
    parent = project.get("parent")
    children = project.get("children") or []
    warnings = list(context.get("warnings") or [])
    if codex_project.get("warning"):
        warnings.append(str(codex_project["warning"]))

    child_lines = [
        f"{child.get('repo') or repo}#{child.get('number')}: {child.get('title') or ''}".strip()
        for child in children
    ]
    parent_text = "None"
    if parent:
        parent_text = f"{parent.get('repo') or repo}#{parent.get('number')}: {parent.get('title') or ''}".strip()

    codex_app_project = _codex_app_project_from_work_log(parsed)
    if codex_app_project is None:
        codex_app_project = _default_codex_app_project()
        codex_app_project["confidence"] = "low"
        codex_app_project["reason"] = (
            "Fallback: work log has no codex_project / codex_project_path. "
            "Verify before resuming."
        )
    workspace_path = codex_project.get("path") or ""
    if not workspace_path or workspace_path == "/":
        workspace_path = "Unresolved — ask Scott which workspace to open."
        warnings.append(
            "implementation_workspace could not be resolved from the work log. "
            "Open this handoff from the correct workspace manually."
        )
    workspace_name = Path(workspace_path).name if str(workspace_path).startswith("/") else "Unresolved"
    related_repos = _related_github_repos(context, codex_project)
    children_section = "- Children: None documented."
    if child_lines:
        children_section = "- Children:\n" + "\n".join(f"  - {line}" for line in child_lines)
    issue_ref = f"{repo}#{issue_number}"
    project_routing_prompt = _build_project_routing_prompt(issue_ref, codex_app_project)
    execution_resume_prompt = _build_execution_resume_prompt(issue_ref)

    return f"""# Workdown: {repo}#{issue_number} - {title}

## Paste This To Choose Where To Work

```text
{project_routing_prompt}
```

## Recommended Codex Project

Use this section as the canonical answer for orientation-only "which Codex project should I open?" prompts. A Codex project is the project name/container in the Codex application.

- `codex_project`: {_markdown_value(codex_app_project.get("name"), empty="Unresolved")}
- `codex_project_path`: {_markdown_value(codex_app_project.get("path"), empty="Unresolved")}
- `confidence`: {_markdown_value(codex_app_project.get("confidence"), empty="unknown")}
- `reason`: {_markdown_value(codex_app_project.get("reason"), empty="unresolved")}
- `exists`: {_markdown_value(codex_app_project.get("exists"), empty="unknown")}

## Related Local Workspaces

These are source checkouts or filesystem workspaces involved in the task. They are not the Codex app project unless explicitly listed above.

- `implementation_workspace`: `{workspace_path}`
- `implementation_workspace_name`: {workspace_name}
- `workspace_resolution_source`: {_markdown_value(codex_project.get("source"), empty="unresolved")}
- `workspace_confidence`: {_markdown_value(codex_project.get("confidence"), empty="unknown")}

## Related GitHub Repositories

These are GitHub repositories involved in the task. They are not the Codex app project.

{_markdown_list(related_repos)}

## Paste This After Switching To The Recommended Project

```text
{execution_resume_prompt}
```

## Source Issue

- Issue: `{repo}#{issue_number}`
- URL: {_markdown_value(context.get("url"))}
- Title: {_markdown_value(title)}
- State: {_markdown_value(context.get("state"))}
- Project: {_markdown_value(project.get("title"))} #{_markdown_value(project.get("number"), empty="")}
- Status: {_markdown_value(project.get("status"))}
- Priority: {_markdown_value(project.get("priority"))}
- Parent: {parent_text}
{children_section}

## Where We Left Off

{_markdown_value(resume.get("where_we_left_off"))}

## Next Action

{_markdown_value(resume.get("next_action"))}

## Blockers / Open Questions

{_markdown_list(resume.get("blockers"))}

## Latest Structured Work Log

### Work Completed

{_markdown_list(parsed.get("work_completed"))}

### Current State

{_markdown_list(parsed.get("current_state"))}

### Next Steps

{_markdown_list(parsed.get("next_steps"))}

### Blockers / Open Questions

{_markdown_list(parsed.get("blockers_open_questions"))}

### Previous Work Session Codex Project

{_markdown_list(parsed.get("codex_project"), empty="None documented in the latest structured work log. Use the Recommended Codex Project section above for the known Codex app project.")}

### Useful Context

{_markdown_list(parsed.get("useful_context"))}

## Resume Warnings

{_markdown_list(warnings)}

## Context For The Target Project Thread

You are now working inside the recommended Codex application project. Use this file as the handoff context for orienting to the source issue, related local workspaces, and related GitHub repositories before planning any implementation work.

Do not edit files, run broad tests, create commits, create another handoff, or update GitHub during orientation. After orientation, stop and align with Scott on the plan before implementation. Do not update the GTD issue directly from the target project thread unless Scott explicitly asks. Instead, return the end-of-session GTD update fields below so Scott or the originating GTD thread can apply them with `gtd_mgmt.append_work_log`.

## End-Of-Session GTD Update

When the project work session is done, prepare a structured work-log update for this issue:

- Issue: `{repo}#{issue_number}`
- URL: {_markdown_value(context.get("url"))}

Return these `gtd_mgmt.append_work_log` fields, or apply them only if Scott explicitly asks you to update the issue:

- `work_completed`: what changed in the project workspace, including files, tests, commits, or decisions.
- `current_state`: where the work stands now.
- `next_steps`: the next concrete action for a future session.
- `blockers`: open questions, dependencies, or reasons work could not continue.
- `codex_project`: the Codex application project name/container where the work was coordinated. If work was performed in the recommended project for this handoff, use `{_markdown_value(codex_app_project.get("name"), empty="Unresolved")}`.
- `codex_project_path`: the Codex application project path. If work was performed in the recommended project for this handoff, use `{_markdown_value(codex_app_project.get("path"), empty="Unresolved")}`.
- `related_local_workspaces`: local source checkouts or filesystem workspaces used, such as `{workspace_path}`.
- `related_github_repos`: GitHub repositories used, such as `{", ".join(related_repos)}`.
- `useful_context`: commands run, validation results, branch/PR links, important caveats, and anything future Codex needs to resume quickly.
"""


def _handoff_filename(repo: str, issue_number: int) -> str:
    safe_repo = "".join(ch if ch.isalnum() else "-" for ch in repo.strip()).strip("-").lower()
    return f"{safe_repo}-{issue_number}-workdown.md"


@mcp.tool()
def gui_status() -> str:
    """Return GUI process and loaded project status."""
    global _gui_process

    process_state: dict[str, Any] = {"tracked": False}
    if _gui_process is not None:
        returncode = _gui_process.poll()
        process_state = {
            "tracked": True,
            "pid": _gui_process.pid,
            "running": returncode is None,
            "returncode": returncode,
        }
        if returncode is not None:
            _gui_process = None

    pid = _read_pid()
    pid_state = None
    if pid is not None:
        pid_state = {"pid": pid, "running": _pid_running(pid), "pid_path": str(PID_PATH)}

    return _json({"ok": True, "process": process_state, "pidfile": pid_state, "server": _find_server()})


@mcp.tool()
def launch_gui(dry_run: bool = False, python_executable: str | None = None) -> str:
    """Launch the GTD project GUI, which auto-loads the configured project."""
    global _gui_process

    server = _find_server()
    if server:
        return _json({"ok": True, "already_running": True, "server": server})

    py = python_executable or sys.executable
    cmd = [py, str(GUI_SCRIPT)]
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(REPO_ROOT), env.get("PYTHONPATH", "")])

    if dry_run:
        return _json({"ok": True, "dry_run": True, "command": cmd, "cwd": str(REPO_ROOT)})

    log_file = LOG_PATH.open("a")
    _gui_process = subprocess.Popen(
        cmd,
        cwd=str(REPO_ROOT),
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    PID_PATH.write_text(f"{_gui_process.pid}\n")
    server = _wait_for_server()
    return _json({
        "ok": True,
        "launched": True,
        "pid": _gui_process.pid,
        "server": server,
        "log_path": str(LOG_PATH),
        "pid_path": str(PID_PATH),
    })


@mcp.tool()
def load_default_project(launch_if_needed: bool = True, wait: bool = True, timeout_seconds: float = 60.0) -> str:
    """Load or refresh the configured GTD GitHub Project."""
    _ensure_gui(launch_if_needed)
    queued = _request_json("POST", "/load-project", {})
    status = _wait_until_loaded(timeout_seconds) if wait else _request_json("GET", "/status")
    return _json({"ok": True, "queued": queued, "status": status})


@mcp.tool()
def refresh(wait: bool = True, timeout_seconds: float = 60.0) -> str:
    """Refresh the GUI from GitHub."""
    _ensure_gui(True)
    queued = _request_json("POST", "/refresh", {})
    status = _wait_until_loaded(timeout_seconds) if wait else _request_json("GET", "/status")
    return _json({"ok": True, "queued": queued, "status": status})


@mcp.tool()
def search_project_items(query: str, limit: int = 10, launch_if_needed: bool = True) -> str:
    """Search loaded GTD project items by title, number, repo, labels, or assignees."""
    _ensure_gui(launch_if_needed)
    params = urllib.parse.urlencode({"q": query, "limit": limit})
    return _json(_request_json("GET", f"/search?{params}"))


@mcp.tool()
def find_issue(issue_number: int, repo: str = "", launch_if_needed: bool = True) -> str:
    """Find one issue by number in the loaded project. Pass repo to disambiguate duplicate numbers."""
    _ensure_gui(launch_if_needed)
    params = urllib.parse.urlencode({"n": issue_number, "repo": repo})
    return _json(_request_json("GET", f"/find-issue?{params}"))


@mcp.tool()
def get_issue_context(issue_number: int, repo: str = "", comments: int = 5, launch_if_needed: bool = True) -> str:
    """Return issue fields, parent/children, recent comments, and latest gtd_mgmt work log."""
    return _json(_get_issue_context_data(repo, issue_number, comments, launch_if_needed))


@mcp.tool()
def resume_from_issue(repo: str, issue_number: int, comments: int = 8, launch_if_needed: bool = True) -> str:
    """Resume GTD work from an exact owner/repo issue reference such as swtandy/personal-management#1."""
    return _json(_get_issue_context_data(repo, issue_number, comments, launch_if_needed))


@mcp.tool()
def get_latest_work_log(issue_number: int, repo: str = "", launch_if_needed: bool = True) -> str:
    """Return the latest structured gtd_mgmt work-log comment for an issue."""
    _ensure_gui(launch_if_needed)
    params = urllib.parse.urlencode({"n": issue_number, "repo": repo})
    return _json(_request_json("GET", f"/latest-work-log?{params}", timeout=30.0))


@mcp.tool()
def resume_project(query: str, launch_if_needed: bool = True) -> str:
    """Search for a project by text and return full context if there is a single match."""
    _ensure_project_loaded(launch_if_needed)
    params = urllib.parse.urlencode({"q": query, "limit": 5})
    search = _request_json("GET", f"/search?{params}")
    matches = search.get("matches") or []
    if len(matches) != 1:
        return _json({"ok": True, "query": query, "status": "needs_selection", "matches": matches})
    match = matches[0]
    context = _get_issue_context_data(match["repo"], int(match["number"]), comments=8, launch_if_needed=launch_if_needed)
    return _json({"ok": True, "query": query, "status": "resolved", "context": context})


@mcp.tool()
def create_resume_handoff(
    repo: str,
    issue_number: int,
    output_dir: str = "",
    comments: int = 8,
    launch_if_needed: bool = True,
    overwrite: bool = True,
) -> str:
    """Create a Markdown workdown file and post it as a GitHub comment for resuming a GTD issue in the target workspace."""
    context = _get_issue_context_data(repo, issue_number, comments=comments, launch_if_needed=launch_if_needed)
    if not context.get("ok"):
        return _json({"ok": False, "repo": repo, "issue_number": issue_number, "context": context})

    codex_project = resolve_codex_project_for_context(context, str(context.get("repo") or repo))
    _parsed = _parsed_work_log(context)
    codex_app_project = _codex_app_project_from_work_log(_parsed)
    if codex_app_project is None:
        codex_app_project = _default_codex_app_project()
        codex_app_project["confidence"] = "low"
        codex_app_project["reason"] = (
            "Fallback: work log has no codex_project / codex_project_path. "
            "Verify before resuming."
        )
    related_repos = _related_github_repos(context, codex_project)
    body = build_resume_handoff_markdown(context, codex_project)
    issue_ref = f"{context.get('repo') or repo}#{context.get('issue_number') or issue_number}"
    directory = Path(output_dir).expanduser() if output_dir else DEFAULT_HANDOFF_DIR
    path = directory / _handoff_filename(str(context.get("repo") or repo), int(context.get("issue_number") or issue_number))
    if path.exists() and not overwrite:
        return _json({
            "ok": False,
            "error": "handoff file already exists",
            "path": str(path),
            "hint": "Pass overwrite=True or choose a different output_dir.",
        })
    directory.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")

    resolved_repo = context.get("repo") or repo
    resolved_issue_number = int(context.get("issue_number") or issue_number)
    comment_payload = {
        "op": "add_comment",
        "issue_number": resolved_issue_number,
        "repo": resolved_repo,
        "params": {"body": body},
    }
    comment_result_raw = _post_apply_change(comment_payload, timeout=30.0, wait=True)
    try:
        comment_result = json.loads(comment_result_raw)
    except Exception:
        comment_result = {"raw": comment_result_raw}

    # Promote-only: add when:this-week unless the issue already has when:today.
    current_labels = context.get("labels") or []
    when_label_result = None
    if "when:today" not in current_labels:
        label_payload = {
            "op": "add_labels",
            "issue_number": resolved_issue_number,
            "repo": resolved_repo,
            "params": {"labels": ["when:this-week"]},
        }
        label_raw = _post_apply_change(label_payload, timeout=30.0, wait=True)
        try:
            when_label_result = json.loads(label_raw)
        except Exception:
            when_label_result = {"raw": label_raw}

    return _json({
        "ok": True,
        "path": str(path),
        "repo": resolved_repo,
        "issue_number": resolved_issue_number,
        "title": context.get("title") or "",
        "codex_project": codex_app_project,
        "related_workspace": codex_project,
        "related_github_repos": related_repos,
        "comment_posted": comment_result,
        "when_label": when_label_result,
        "pasteable_routing_prompt": _build_project_routing_prompt(issue_ref, codex_app_project),
        "pasteable_resume_prompt": _build_execution_resume_prompt(issue_ref),
        "recommended_next_action": context.get("recommended_next_action") or "",
        "warnings": context.get("warnings") or [],
    })


@mcp.tool()
def append_work_log(
    issue_number: int,
    repo: str = "",
    work_completed: str = "",
    current_state: str = "",
    next_steps: str = "",
    blockers: str = "",
    codex_project: str = "",
    codex_project_path: str = "",
    related_local_workspaces: str = "",
    related_github_repos: str = "",
    useful_context: str = "",
    attachments: list[dict] | None = None,
    launch_if_needed: bool = True,
    wait: bool = True,
) -> str:
    """Append a structured gtd_mgmt work-log comment to an issue and refresh the GUI.

    attachments: optional list of {"file_path": "/abs/path", "caption": "optional"} to
    upload and embed under a new '## Attachments' section in the same work-log comment.
    """
    _ensure_gui(launch_if_needed)
    payload = {
        "op": "append_work_log",
        "issue_number": issue_number,
        "repo": repo,
        "params": {
            "work_completed": work_completed,
            "current_state": current_state,
            "next_steps": next_steps,
            "blockers": blockers,
            "codex_project": codex_project,
            "codex_project_path": codex_project_path,
            "related_local_workspaces": related_local_workspaces,
            "related_github_repos": related_github_repos,
            "useful_context": useful_context,
            "attachments": attachments or [],
        },
    }
    return _post_apply_change(payload, timeout=60.0, wait=wait)


@mcp.tool()
def add_comment(
    issue_number: int,
    body: str,
    repo: str = "",
    attachments: list[dict] | None = None,
    launch_if_needed: bool = True,
    wait: bool = True,
) -> str:
    """Append a plain comment to an issue and refresh the GUI.

    attachments: optional list of {"file_path": "/abs/path", "caption": "optional"} to
    upload and embed under a new '## Attachments' section in the same comment.
    """
    _ensure_gui(launch_if_needed)
    payload = {
        "op": "add_comment",
        "issue_number": issue_number,
        "repo": repo,
        "params": {"body": body, "attachments": attachments or []},
    }
    return _post_apply_change(payload, timeout=60.0, wait=wait)


@mcp.tool()
def attach_file_to_issue(
    issue_number: int,
    file_path: str,
    repo: str = "",
    caption: str = "",
    mode: str = "comment",
    comment_text: str = "",
    name: str = "",
    launch_if_needed: bool = True,
    wait: bool = True,
) -> str:
    """Upload a local file to an issue on the gtd-assets branch and embed/link it.

    mode: "comment" (default, posts a new comment embedding the file), "body_append"
    (appends to the issue body instead), or "none" (upload only, return the URL).
    """
    _ensure_gui(launch_if_needed)
    payload = {
        "op": "attach_file_to_issue",
        "issue_number": issue_number,
        "repo": repo,
        "params": {
            "file_path": file_path,
            "caption": caption,
            "mode": mode,
            "comment_text": comment_text,
            "name": name,
        },
    }
    return _post_apply_change(payload, timeout=60.0, wait=wait)


@mcp.tool()
def list_issue_files(issue_number: int, repo: str = "", launch_if_needed: bool = True) -> str:
    """List all attachments recorded in an issue's manifest, including superseded/deleted entries."""
    _ensure_gui(launch_if_needed)
    params = urllib.parse.urlencode({"n": issue_number, "repo": repo})
    return _json(_request_json("GET", f"/list-files?{params}", timeout=30.0))


@mcp.tool()
def get_issue_file(
    issue_number: int,
    original_name: str = "",
    path: str = "",
    content_sha256: str = "",
    git_sha: str = "",
    output: str = "base64",
    dest_path: str = "",
    overwrite: bool = False,
    include_superseded: bool = False,
    include_deleted: bool = False,
    repo: str = "",
    launch_if_needed: bool = True,
) -> str:
    """Retrieve one verified issue attachment by exactly one selector.

    output is "base64" or "write". write requires an absolute dest_path and
    refuses replacement unless overwrite is true.
    """
    _ensure_gui(launch_if_needed)
    params = urllib.parse.urlencode({
        "n": issue_number, "repo": repo, "original_name": original_name, "path": path,
        "content_sha256": content_sha256, "git_sha": git_sha, "output": output,
        "dest_path": dest_path, "overwrite": str(overwrite).lower(),
        "include_superseded": str(include_superseded).lower(),
        "include_deleted": str(include_deleted).lower(),
    })
    return _json(_request_json("GET", f"/get-file?{params}", timeout=60.0))


@mcp.tool()
def get_issue_files(
    issue_number: int,
    dest_dir: str,
    mime_prefix: str = "",
    include_superseded: bool = False,
    include_deleted: bool = False,
    overwrite: bool = False,
    fail_fast: bool = False,
    max_total_bytes: int = 209715200,
    repo: str = "",
    launch_if_needed: bool = True,
) -> str:
    """Retrieve eligible issue attachments into dest_dir with per-file results."""
    _ensure_gui(launch_if_needed)
    params = urllib.parse.urlencode({
        "n": issue_number, "repo": repo, "dest_dir": dest_dir, "mime_prefix": mime_prefix,
        "include_superseded": str(include_superseded).lower(),
        "include_deleted": str(include_deleted).lower(), "overwrite": str(overwrite).lower(),
        "fail_fast": str(fail_fast).lower(), "max_total_bytes": max_total_bytes,
    })
    return _json(_request_json("GET", f"/get-files?{params}", timeout=120.0))


@mcp.tool()
def update_issue_file(
    issue_number: int,
    path: str,
    file_path: str,
    repo: str = "",
    caption: str = "",
    mode: str = "comment",
    launch_if_needed: bool = True,
    wait: bool = True,
) -> str:
    """Replace an issue attachment with a new file, preserving history (old path -> new path)."""
    _ensure_gui(launch_if_needed)
    payload = {
        "op": "update_issue_file",
        "issue_number": issue_number,
        "repo": repo,
        "params": {"path": path, "file_path": file_path, "caption": caption, "mode": mode},
    }
    return _post_apply_change(payload, timeout=60.0, wait=wait)


@mcp.tool()
def delete_issue_file(
    issue_number: int,
    path: str,
    repo: str = "",
    handle_references: str = "warn",
    launch_if_needed: bool = True,
    wait: bool = True,
) -> str:
    """Delete an issue attachment. handle_references: "warn" (default, lists affected comments)
    or "annotate" (also appends a dead-link notice to those comments)."""
    _ensure_gui(launch_if_needed)
    payload = {
        "op": "delete_issue_file",
        "issue_number": issue_number,
        "repo": repo,
        "params": {"path": path, "handle_references": handle_references},
    }
    return _post_apply_change(payload, timeout=30.0, wait=wait)


@mcp.tool()
def update_issue_body(issue_number: int, body: str, repo: str = "", launch_if_needed: bool = True, wait: bool = True) -> str:
    """Replace the body of an issue with new Markdown content."""
    _ensure_gui(launch_if_needed)
    payload = {"op": "update_issue_body", "issue_number": issue_number, "repo": repo, "params": {"body": body}}
    return _post_apply_change(payload, timeout=30.0, wait=wait)


@mcp.tool()
def create_issue(
    repo: str,
    title: str,
    body: str = "",
    labels: list[str] | None = None,
    status: str = "Backlog",
    priority: str = "",
    attachments: list[dict] | None = None,
    launch_if_needed: bool = True,
    wait: bool = True,
) -> str:
    """Create an issue and add it to the Project. Invalid optional fields return warnings.

    attachments: optional list of {"file_path": "/abs/path", "caption": "optional"} uploaded
    to the new issue and appended as a '## Attachments' section on its body.
    """
    _ensure_gui(launch_if_needed)
    payload = {
        "op": "create_issue",
        "params": {
            "repo": repo,
            "title": title,
            "body": body,
            "labels": labels or [],
            "status": status,
            "priority": priority,
            "attachments": attachments or [],
        },
    }
    return _post_apply_change(payload, timeout=60.0, wait=wait)


@mcp.tool()
def capture_issue(
    repo: str,
    title: str,
    body: str = "",
    labels: list[str] | None = None,
    status: str = "Backlog",
    priority: str = "",
    parent_issue_number: int | None = 70,
    parent_repo: str = "",
    source_text: str = "",
    source_label: str = "",
    next_action: str = "",
    waiting_for: str = "",
    attachments: list[dict] | None = None,
    launch_if_needed: bool = True,
    wait: bool = True,
) -> str:
    """Capture source context as an organized GitHub issue. Optional field failures return warnings.

    attachments: optional list of {"file_path": "/abs/path", "caption": "optional"} uploaded
    to the new issue and appended as a '## Attachments' section on its body.
    """
    _ensure_gui(launch_if_needed)
    payload = {
        "op": "capture_issue",
        "params": {
            "repo": repo,
            "title": title,
            "body": body,
            "labels": labels or [],
            "status": status,
            "priority": priority,
            "parent_issue_number": parent_issue_number,
            "parent_repo": parent_repo,
            "source_text": source_text,
            "source_label": source_label,
            "next_action": next_action,
            "waiting_for": waiting_for,
            "attachments": attachments or [],
        },
    }
    return _post_apply_change(payload, timeout=60.0, wait=wait)


@mcp.tool()
def add_labels(
    issue_number: int,
    labels: list[str],
    repo: str = "",
    launch_if_needed: bool = True,
    wait: bool = True,
) -> str:
    """Ensure and add labels to an issue, then refresh the GUI."""
    _ensure_gui(launch_if_needed)
    payload = {"op": "add_labels", "issue_number": issue_number, "repo": repo, "params": {"labels": labels}}
    return _post_apply_change(payload, timeout=30.0, wait=wait)


@mcp.tool()
def set_project_field(
    issue_number: int,
    field_name: str,
    option_name: str,
    repo: str = "",
    launch_if_needed: bool = True,
    wait: bool = True,
) -> str:
    """Set a loaded issue's Project V2 single-select field by option name."""
    _ensure_gui(launch_if_needed)
    payload = {
        "op": "set_project_field",
        "issue_number": issue_number,
        "repo": repo,
        "params": {"field_name": field_name, "option_name": option_name},
    }
    return _post_apply_change(payload, timeout=30.0, wait=wait)


@mcp.tool()
def set_issue_parent(
    child_issue_number: int,
    parent_issue_number: int,
    child_repo: str = "",
    parent_repo: str = "",
    launch_if_needed: bool = True,
    wait: bool = True,
) -> str:
    """Set a GitHub sub-issue parent relationship, then refresh the GUI."""
    _ensure_gui(launch_if_needed)
    payload = {
        "op": "set_issue_parent",
        "issue_number": child_issue_number,
        "repo": child_repo,
        "params": {"parent_issue_number": parent_issue_number, "parent_repo": parent_repo},
    }
    return _post_apply_change(payload, timeout=30.0, wait=wait)


@mcp.tool()
def organize_issue(
    issue_number: int,
    repo: str = "",
    labels: list[str] | None = None,
    status: str = "",
    priority: str = "",
    parent_issue_number: int | None = None,
    parent_repo: str = "",
    launch_if_needed: bool = True,
    wait: bool = True,
) -> str:
    """Apply labels, Status/Priority, and optional parent relationship to an issue."""
    _ensure_gui(launch_if_needed)
    payload = {
        "op": "organize_issue",
        "issue_number": issue_number,
        "repo": repo,
        "params": {
            "labels": labels or [],
            "status": status,
            "priority": priority,
            "parent_issue_number": parent_issue_number,
            "parent_repo": parent_repo,
        },
    }
    return _post_apply_change(payload, timeout=60.0, wait=wait)


@mcp.tool()
def bulk_organize_issues(
    items: list[dict],
    labels: list[str] | None = None,
    status: str = "",
    priority: str = "",
    parent_issue_number: int | None = None,
    parent_repo: str = "",
    dry_run: bool = True,
    launch_if_needed: bool = True,
    wait: bool = True,
) -> str:
    """
    Apply common organization updates across many issues.

    Use dry_run=True first for bulk changes. Each item should be
    {"repo": "owner/repo", "issue_number": 123}.
    """
    _ensure_gui(launch_if_needed)
    payload = {
        "op": "bulk_organize_issues",
        "params": {
            "items": items,
            "labels": labels or [],
            "status": status,
            "priority": priority,
            "parent_issue_number": parent_issue_number,
            "parent_repo": parent_repo,
            "dry_run": dry_run,
        },
    }
    return _post_apply_change(payload, timeout=120.0, wait=wait and not dry_run)


@mcp.tool()
def close_issue(
    issue_number: int,
    repo: str = "",
    reason: str = "completed",
    launch_if_needed: bool = True,
    wait: bool = True,
) -> str:
    """Close a GitHub issue. reason: completed (default) or not_planned."""
    _ensure_gui(launch_if_needed)
    payload = {"op": "close_issue", "issue_number": issue_number, "repo": repo, "params": {"reason": reason}}
    return _post_apply_change(payload, timeout=30.0, wait=wait)


@mcp.tool()
def gui_command(method: str, path: str, payload: dict[str, Any] | None = None) -> str:
    """Send a raw JSON command to the GTD GUI command server."""
    try:
        return _json(_request_json(method, path, payload))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return _json({"ok": False, "status": exc.code, "body": body})
    except Exception as exc:
        return _json({"ok": False, "error": str(exc)})


@mcp.tool()
def stop_gui() -> str:
    """Stop the GTD GUI if it was launched by this MCP server."""
    global _gui_process

    pid = _gui_process.pid if _gui_process and _gui_process.poll() is None else _read_pid()
    if pid is None or not _pid_running(pid):
        return _json({"ok": True, "stopped": False, "reason": "no running GUI process found"})
    os.killpg(pid, signal.SIGTERM)
    return _json({"ok": True, "stopped": True, "pid": pid})


if __name__ == "__main__":
    mcp.run()
