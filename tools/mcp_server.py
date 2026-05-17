#!/usr/bin/env python3
"""
MCP server exposing GitHub management tools to Claude co-work.

Setup: see CLAUDE.md → MCP Server section.
Run directly to test: python3 tools/mcp_server.py (prints nothing — awaits stdio)
"""

import sys
import time
from pathlib import Path

# Ensure tools/ is on the path so github_client is importable
sys.path.insert(0, str(Path(__file__).parent))

from mcp.server.fastmcp import FastMCP
from github_client import get_all, get, post, patch, delete

mcp = FastMCP("GitHub Personal Management")


# ---------------------------------------------------------------------------
# Repos
# ---------------------------------------------------------------------------

@mcp.tool()
def list_repos() -> str:
    """List all GitHub repos owned by swtandy with open issue counts."""
    repos = get_all("/user/repos", params={"sort": "updated", "affiliation": "owner"})
    if not repos:
        return "No repos found."
    lines = [
        f"{r['full_name']}  ({r['open_issues_count']} open issues)"
        + (f"  — {r['description']}" if r.get("description") else "")
        for r in repos
    ]
    return f"{len(repos)} repos:\n\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
# Issues
# ---------------------------------------------------------------------------

@mcp.tool()
def list_issues(repo: str, state: str = "open") -> str:
    """
    List issues in a repo.

    Args:
        repo: owner/repo, e.g. swtandy/personal-management
        state: open | closed | all  (default: open)
    """
    issues = get_all(
        f"/repos/{repo}/issues",
        params={"state": state, "sort": "created", "direction": "asc"},
    )
    issues = [i for i in issues if "pull_request" not in i]
    if not issues:
        return f"No {state} issues in {repo}."
    lines = []
    for i in issues:
        labels = ", ".join(l["name"] for l in i.get("labels", []))
        label_str = f"  [{labels}]" if labels else ""
        lines.append(f"#{i['number']} [{i['state']}] {i['title']}{label_str}")
    return f"{len(issues)} issues in {repo} (state={state}):\n\n" + "\n".join(lines)


@mcp.tool()
def get_issue(repo: str, issue_number: int) -> str:
    """
    Get full details of a single issue including body and comments.

    Args:
        repo: owner/repo
        issue_number: issue number
    """
    issue = get(f"/repos/{repo}/issues/{issue_number}")
    labels = ", ".join(l["name"] for l in issue.get("labels", []))
    comments_raw = get_all(f"/repos/{repo}/issues/{issue_number}/comments")

    out = [
        f"#{issue['number']} [{issue['state']}] {issue['title']}",
        f"Labels: {labels or 'none'}",
        f"URL: {issue['html_url']}",
        f"Created: {issue['created_at'][:10]}",
        "",
        issue.get("body") or "(no body)",
    ]

    if comments_raw:
        out += ["", f"--- {len(comments_raw)} comment(s) ---"]
        for c in comments_raw:
            out += ["", f"@{c['user']['login']} ({c['created_at'][:10]}):", c["body"]]

    return "\n".join(out)


@mcp.tool()
def create_issue(repo: str, title: str, body: str = "", labels: list[str] = []) -> str:
    """
    Create a new issue.

    Args:
        repo: owner/repo
        title: issue title
        body: issue body (markdown)
        labels: list of label names (must already exist in repo)
    """
    payload = {"title": title, "body": body, "labels": labels}
    created = post(f"/repos/{repo}/issues", payload)
    return f"Created #{created['number']}: {created['title']}\n{created['html_url']}"


@mcp.tool()
def update_issue(
    repo: str,
    issue_number: int,
    title: str = None,
    body: str = None,
    state: str = None,
    labels: list[str] = None,
) -> str:
    """
    Update an existing issue. Only fields you provide are changed.

    Args:
        repo: owner/repo
        issue_number: issue number
        title: new title (optional)
        body: new body (optional)
        state: open | closed (optional)
        labels: replace label list (optional — replaces all existing labels)
    """
    payload = {}
    if title is not None:
        payload["title"] = title
    if body is not None:
        payload["body"] = body
    if state is not None:
        payload["state"] = state
    if labels is not None:
        payload["labels"] = labels
    if not payload:
        return "Nothing to update — no fields provided."
    updated = patch(f"/repos/{repo}/issues/{issue_number}", payload)
    return f"Updated #{updated['number']}: {updated['title']} [{updated['state']}]\n{updated['html_url']}"


@mcp.tool()
def add_comment(repo: str, issue_number: int, body: str) -> str:
    """
    Add a comment to an issue.

    Args:
        repo: owner/repo
        issue_number: issue number
        body: comment text (markdown)
    """
    comment = post(f"/repos/{repo}/issues/{issue_number}/comments", {"body": body})
    return f"Comment added: {comment['html_url']}"


@mcp.tool()
def close_issue(repo: str, issue_number: int, comment: str = None) -> str:
    """
    Close an issue, optionally leaving a closing comment.

    Args:
        repo: owner/repo
        issue_number: issue number
        comment: optional comment to add before closing
    """
    if comment:
        post(f"/repos/{repo}/issues/{issue_number}/comments", {"body": comment})
    patch(f"/repos/{repo}/issues/{issue_number}", {"state": "closed"})
    return f"Closed #{issue_number} in {repo}."


# ---------------------------------------------------------------------------
# Sub-issues (parent/child relationships)
# ---------------------------------------------------------------------------

@mcp.tool()
def list_sub_issues(repo: str, issue_number: int) -> str:
    """
    List all sub-issues (children) of an issue.

    Args:
        repo: owner/repo
        issue_number: parent issue number
    """
    subs = get_all(f"/repos/{repo}/issues/{issue_number}/sub_issues")
    if not subs:
        return f"#{issue_number} has no sub-issues."
    lines = []
    for s in subs:
        labels = ", ".join(l["name"] for l in s.get("labels", []))
        label_str = f"  [{labels}]" if labels else ""
        lines.append(f"  #{s['number']} [{s['state']}] {s['title']}{label_str}")
    return f"#{issue_number} has {len(subs)} sub-issue(s):\n" + "\n".join(lines)


@mcp.tool()
def get_parent_issue(repo: str, issue_number: int) -> str:
    """
    Get the parent issue of a sub-issue, if any.

    Args:
        repo: owner/repo
        issue_number: child issue number
    """
    parent = get(f"/repos/{repo}/issues/{issue_number}/parent")
    if not parent:
        return f"#{issue_number} has no parent issue."
    labels = ", ".join(l["name"] for l in parent.get("labels", []))
    return f"Parent of #{issue_number}: #{parent['number']} [{parent['state']}] {parent['title']}  [{labels}]\n{parent['html_url']}"


@mcp.tool()
def add_sub_issue(repo: str, parent_issue_number: int, sub_issue_number: int) -> str:
    """
    Make an issue a sub-issue (child) of another issue.

    Args:
        repo: owner/repo
        parent_issue_number: the parent issue number
        sub_issue_number: the child issue number
    """
    # API requires the internal issue ID, not the number — look it up
    child = get(f"/repos/{repo}/issues/{sub_issue_number}")
    result = post(
        f"/repos/{repo}/issues/{parent_issue_number}/sub_issues",
        {"sub_issue_id": child["id"]},
    )
    return f"#{sub_issue_number} is now a sub-issue of #{parent_issue_number}.\n{result.get('html_url', '')}"


@mcp.tool()
def remove_sub_issue(repo: str, parent_issue_number: int, sub_issue_number: int) -> str:
    """
    Remove a sub-issue relationship (does not delete the issue).

    Args:
        repo: owner/repo
        parent_issue_number: the parent issue number
        sub_issue_number: the child issue number to detach
    """
    child = get(f"/repos/{repo}/issues/{sub_issue_number}")
    delete(
        f"/repos/{repo}/issues/{parent_issue_number}/sub_issue",
        {"sub_issue_id": child["id"]},
    )
    return f"#{sub_issue_number} removed from sub-issues of #{parent_issue_number}."


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------

@mcp.tool()
def list_labels(repo: str) -> str:
    """
    List all labels in a repo.

    Args:
        repo: owner/repo
    """
    labels = get_all(f"/repos/{repo}/labels")
    if not labels:
        return f"No labels in {repo}."
    lines = [f"{l['name']}  #{l['color']}  {l.get('description', '')}" for l in labels]
    return f"{len(labels)} labels in {repo}:\n\n" + "\n".join(lines)


@mcp.tool()
def create_label(repo: str, name: str, color: str = "ededed", description: str = "") -> str:
    """
    Create a label in a repo.

    Args:
        repo: owner/repo
        name: label name
        color: hex color without # (default: ededed)
        description: optional description
    """
    post(f"/repos/{repo}/labels", {"name": name, "color": color, "description": description})
    return f"Created label '{name}' in {repo}."


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

@mcp.tool()
def migrate_issues(source_repo: str, dest_repo: str, dry_run: bool = True, state: str = "open") -> str:
    """
    Copy issues from one repo to another. Always dry_run=True first.

    Args:
        source_repo: owner/repo to copy FROM
        dest_repo: owner/repo to copy TO
        dry_run: if True, preview only — nothing is written (default: True)
        state: open | closed | all (default: open)
    """
    issues = get_all(
        f"/repos/{source_repo}/issues",
        params={"state": state, "sort": "created", "direction": "asc"},
    )
    issues = [i for i in issues if "pull_request" not in i]

    if not issues:
        return f"No {state} issues in {source_repo}."

    if dry_run:
        lines = [f"DRY RUN — {len(issues)} issues would be migrated:\n"]
        for i in issues:
            labels = [l["name"] for l in i.get("labels", [])]
            lines.append(f"  [{i['state']}] #{i['number']} {i['title']}  labels={labels}")
        lines.append("\nSet dry_run=false to execute.")
        return "\n".join(lines)

    # Sync labels
    dest_labels = {l["name"] for l in get_all(f"/repos/{dest_repo}/labels")}
    source_labels = get_all(f"/repos/{source_repo}/labels")
    created_labels = []
    for lbl in source_labels:
        if lbl["name"] not in dest_labels:
            post(f"/repos/{dest_repo}/labels", {
                "name": lbl["name"],
                "color": lbl.get("color", "ededed"),
                "description": lbl.get("description", ""),
            })
            created_labels.append(lbl["name"])

    migrated = []
    for issue in issues:
        original_url = issue["html_url"]
        labels = [l["name"] for l in issue.get("labels", [])]
        body = (issue.get("body") or "") + \
            f"\n\n---\n_Migrated from [{source_repo}#{issue['number']}]({original_url})_"
        created = post(f"/repos/{dest_repo}/issues", {
            "title": issue["title"], "body": body, "labels": labels,
        })
        if issue["state"] == "closed":
            patch(f"/repos/{dest_repo}/issues/{created['number']}", {"state": "closed"})
        migrated.append(f"  #{created['number']} ← {source_repo}#{issue['number']}: {issue['title'][:60]}")
        time.sleep(0.5)

    lines = [f"Migrated {len(migrated)} issues to {dest_repo}:"]
    if created_labels:
        lines.append(f"Labels created: {', '.join(created_labels)}")
    lines += migrated
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run()
