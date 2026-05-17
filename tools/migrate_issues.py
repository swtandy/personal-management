"""
migrate_issues.py
Copy issues from a source repo into the destination repo.
Preserves: title, body, labels (creates them if missing), state.
Adds a footer note citing the original issue URL.

Run (dry-run first!):
  python tools/migrate_issues.py --source swtandy/openclaw --dest swtandy/personal-management --dry-run
  python tools/migrate_issues.py --source swtandy/openclaw --dest swtandy/personal-management
"""

import sys
import time
import argparse
from github_client import get_all, get, post, patch, rate_limit_pause

parser = argparse.ArgumentParser(description="Migrate GitHub issues between repos")
parser.add_argument("--source", required=True, help="owner/repo to copy FROM")
parser.add_argument("--dest", required=True, help="owner/repo to copy TO")
parser.add_argument("--state", default="all", choices=["open", "closed", "all"])
parser.add_argument("--label-filter", default=None, help="Only migrate issues with this label")
parser.add_argument("--dry-run", action="store_true", help="Print what would happen, don't write")
args = parser.parse_args()

# --- Fetch source issues ---
print(f"Fetching issues from {args.source} (state={args.state}) …")
issues = get_all(
    f"/repos/{args.source}/issues",
    params={"state": args.state, "sort": "created", "direction": "asc"},
)
issues = [i for i in issues if "pull_request" not in i]

if args.label_filter:
    issues = [i for i in issues if any(l["name"] == args.label_filter for l in i.get("labels", []))]

print(f"Found {len(issues)} issues to migrate.\n")

if args.dry_run:
    for i in issues:
        labels = [l["name"] for l in i.get("labels", [])]
        print(f"  [{i['state']}] #{i['number']} {i['title']}  labels={labels}")
    print("\n(Dry run — nothing written)")
    sys.exit(0)

# --- Ensure labels exist in dest ---
print(f"Syncing labels to {args.dest} …")
dest_labels = {l["name"] for l in get_all(f"/repos/{args.dest}/labels")}
source_labels = get_all(f"/repos/{args.source}/labels")

for lbl in source_labels:
    if lbl["name"] not in dest_labels:
        post(f"/repos/{args.dest}/labels", {
            "name": lbl["name"],
            "color": lbl.get("color", "ededed"),
            "description": lbl.get("description", ""),
        })
        print(f"  Created label: {lbl['name']}")

# --- Migrate issues ---
print(f"\nMigrating {len(issues)} issues …\n")
migrated = 0

for idx, issue in enumerate(issues):
    rate_limit_pause(min_remaining=50)

    original_url = issue["html_url"]
    labels = [l["name"] for l in issue.get("labels", [])]
    body = issue.get("body") or ""
    body_with_credit = (
        body
        + f"\n\n---\n_Migrated from [{args.source}#{issue['number']}]({original_url})_"
    )

    payload = {
        "title": issue["title"],
        "body": body_with_credit,
        "labels": labels,
    }

    created = post(f"/repos/{args.dest}/issues", payload)
    migrated += 1

    # If the original was closed, close the new one too
    if issue["state"] == "closed":
        patch(f"/repos/{args.dest}/issues/{created['number']}", {"state": "closed"})

    print(f"  [{idx+1}/{len(issues)}] #{created['number']} ← {args.source}#{issue['number']}: {issue['title'][:60]}")
    time.sleep(0.5)  # be polite to the API

print(f"\nDone. {migrated} issues migrated to {args.dest}.")
