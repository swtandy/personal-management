"""
issue_tree.py
Build a full parent/child issue tree for a repo in one function call.

Usage:
    from issue_tree import build_issue_tree
    tree = build_issue_tree("swtandy/personal-management")

Returns a dict with three keys:
    issues  — flat dict keyed by issue number, each entry has:
                number, id, title, state, labels, url, parent, children
    roots   — sorted list of issue numbers with no parent
    tree    — nested list of nodes (same fields, children embedded recursively)

API calls: 1 (list issues) + N (sub_issues per issue) = N+1 total.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from github_client import get_all


def build_issue_tree(repo: str, state: str = "all") -> dict:
    raw = get_all(
        f"/repos/{repo}/issues",
        params={"state": state, "sort": "created", "direction": "asc"},
    )
    raw = [i for i in raw if "pull_request" not in i]

    # Build flat lookup — children and parent filled in below
    issues = {
        i["number"]: {
            "number": i["number"],
            "id": i["id"],
            "title": i["title"],
            "state": i["state"],
            "labels": [l["name"] for l in i.get("labels", [])],
            "url": i["html_url"],
            "parent": None,
            "children": [],
        }
        for i in raw
    }

    # Discover relationships: for each issue fetch its sub-issues
    for number in list(issues.keys()):
        subs = get_all(f"/repos/{repo}/issues/{number}/sub_issues")
        for sub in subs:
            child_num = sub["number"]
            if child_num in issues:
                issues[number]["children"].append(child_num)
                issues[child_num]["parent"] = number
            # sub-issue exists but wasn't in our fetch (e.g. different state filter)
            # — add it as a stub so the tree is complete
            else:
                issues[child_num] = {
                    "number": sub["number"],
                    "id": sub["id"],
                    "title": sub["title"],
                    "state": sub["state"],
                    "labels": [l["name"] for l in sub.get("labels", [])],
                    "url": sub["html_url"],
                    "parent": number,
                    "children": [],
                    "stub": True,
                }
                issues[number]["children"].append(child_num)

    # Sort children lists in the flat dict so callers don't have to
    for issue in issues.values():
        issue["children"].sort()

    roots = sorted(n for n, i in issues.items() if i["parent"] is None)

    def _node(number):
        n = dict(issues[number])
        n["children"] = [_node(c) for c in sorted(n["children"])]
        return n

    return {
        "repo": repo,
        "total": len(issues),
        "roots": roots,
        "issues": issues,
        "tree": [_node(r) for r in roots],
    }


def format_tree(tree_dict: dict, indent: int = 0) -> str:
    """Return a compact ASCII tree string for human/model reading."""
    lines = []
    prefix = "  " * indent
    for node in tree_dict if isinstance(tree_dict, list) else tree_dict["tree"]:
        labels = f"  [{', '.join(node['labels'])}]" if node["labels"] else ""
        state_tag = "" if node["state"] == "open" else " [closed]"
        lines.append(f"{prefix}#{node['number']} {node['title']}{state_tag}{labels}")
        if node["children"]:
            lines.append(format_tree(node["children"], indent + 1))
    return "\n".join(lines)
