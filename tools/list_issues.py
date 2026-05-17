"""
list_issues.py
List all issues (open + closed) in a repo, with labels and body preview.
Run: python tools/list_issues.py swtandy/openclaw
     python tools/list_issues.py swtandy/openclaw --state open
     python tools/list_issues.py swtandy/openclaw --json   (full JSON dump)
"""

import sys
import json
import argparse
from github_client import get_all

parser = argparse.ArgumentParser(description="List GitHub issues for a repo")
parser.add_argument("repo", help="owner/repo  e.g. swtandy/openclaw")
parser.add_argument("--state", default="all", choices=["open", "closed", "all"])
parser.add_argument("--json", action="store_true", dest="as_json", help="Dump raw JSON")
args = parser.parse_args()

issues = get_all(
    f"/repos/{args.repo}/issues",
    params={"state": args.state, "sort": "created", "direction": "asc"},
)

# Filter out pull requests (GitHub API returns PRs as issues too)
issues = [i for i in issues if "pull_request" not in i]

if args.as_json:
    print(json.dumps(issues, indent=2))
    sys.exit(0)

print(f"\n{len(issues)} issues in {args.repo} (state={args.state})\n")
print(f"{'#':<6} {'State':<8} {'Title':<55} {'Labels'}")
print("-" * 100)
for i in issues:
    num = f"#{i['number']}"
    state = i["state"]
    title = i["title"][:54]
    labels = ", ".join(l["name"] for l in i.get("labels", []))
    print(f"{num:<6} {state:<8} {title:<55} {labels}")
