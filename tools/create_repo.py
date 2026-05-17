"""
create_repo.py
Create the personal-management GitHub repo (run once).
Run: python tools/create_repo.py
"""

import sys
from github_client import post, get

REPO_NAME = "personal-management"
DESCRIPTION = "Personal management operating system — issues, tasks, research"

# Check if it already exists
try:
    existing = get(f"/repos/swtandy/{REPO_NAME}")
    print(f"Repo already exists: {existing['html_url']}")
    sys.exit(0)
except SystemExit as e:
    if e.code == 1:
        pass  # 404 → doesn't exist yet, continue

result = post("/user/repos", {
    "name": REPO_NAME,
    "description": DESCRIPTION,
    "private": False,
    "auto_init": True,
    "has_issues": True,
    "has_projects": True,
})

print(f"Created repo: {result['html_url']}")
