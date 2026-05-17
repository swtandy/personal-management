"""
list_repos.py
List all repos on the authenticated account.
Run: python tools/list_repos.py
"""

from github_client import get_all, GITHUB_USERNAME

repos = get_all(f"/user/repos", params={"type": "all", "sort": "updated"})

print(f"\n{'Repo':<45} {'Open Issues':>11}  {'Description'}")
print("-" * 90)
for r in repos:
    name = r["full_name"]
    issues = r["open_issues_count"]
    desc = (r.get("description") or "")[:50]
    print(f"{name:<45} {issues:>11}  {desc}")

print(f"\nTotal: {len(repos)} repos")
