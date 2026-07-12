"""
GitHub GraphQL API client for Projects V2.
All interactions with GitHub go through this module.
"""
import base64
from datetime import datetime, timezone

import requests
from config import GITHUB_TOKEN, GH_GRAPHQL_URL

WORK_LOG_MARKER = "<!-- gtd_mgmt:work-log:v1 -->"


class ManifestConflict(RuntimeError):
    """Raised when a Contents API write hits a stale-sha conflict (HTTP 409)."""


class GitHubClient:
    def __init__(self, token: str | None = None):
        token = token if token is not None else GITHUB_TOKEN
        if not token:
            raise RuntimeError(
                "No GitHub token found. Set GITHUB_TOKEN in "
                "/Users/scotttandy/Documents/Claude/Projects/SWT Personal Management/.env "
                "or the environment."
            )
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def graphql(self, query: str, variables: dict = None) -> dict:
        """Execute a GraphQL query and return parsed data, raising on errors."""
        payload = {"query": query}
        if variables:
            payload["variables"] = variables
        resp = requests.post(GH_GRAPHQL_URL, json=payload, headers=self.headers)
        resp.raise_for_status()
        data = resp.json()
        if "errors" in data:
            raise RuntimeError(f"GraphQL errors: {data['errors']}")
        return data["data"]

    # ------------------------------------------------------------------ #
    #  Project queries                                                     #
    # ------------------------------------------------------------------ #

    def get_project(self, user: str, project_number: int) -> dict:
        """Fetch project metadata including all field definitions."""
        query = """
        query($user: String!, $number: Int!) {
          user(login: $user) {
            projectV2(number: $number) {
              id
              title
              fields(first: 30) {
                nodes {
                  ... on ProjectV2Field {
                    id name dataType
                  }
                  ... on ProjectV2SingleSelectField {
                    id name
                    options { id name color }
                  }
                  ... on ProjectV2IterationField {
                    id name
                  }
                }
              }
            }
          }
        }
        """
        data = self.graphql(query, {"user": user, "number": project_number})
        return data["user"]["projectV2"]

    def get_project_items(self, project_id: str, after: str = None) -> dict:
        """Fetch all project items (paginated). Returns raw nodes + pageInfo."""
        query = """
        query($projectId: ID!, $after: String) {
          node(id: $projectId) {
            ... on ProjectV2 {
              items(first: 50, after: $after) {
                pageInfo { hasNextPage endCursor }
                nodes {
                  id
                  fieldValues(first: 20) {
                    nodes {
                      ... on ProjectV2ItemFieldSingleSelectValue {
                        name
                        field { ... on ProjectV2SingleSelectField { name } }
                      }
                      ... on ProjectV2ItemFieldTextValue {
                        text
                        field { ... on ProjectV2Field { name } }
                      }
                      ... on ProjectV2ItemFieldNumberValue {
                        number
                        field { ... on ProjectV2Field { name } }
                      }
                      ... on ProjectV2ItemFieldIterationValue {
                        title
                        field { ... on ProjectV2IterationField { name } }
                      }
                    }
                  }
                  content {
                    ... on Issue {
                      id number title body url state
                      repository { nameWithOwner }
                      labels(first: 10) { nodes { name color } }
                      assignees(first: 5) { nodes { login } }
                      parent { id number title repository { nameWithOwner } }
                      trackedIssues(first: 20) { nodes { number title repository { nameWithOwner } } }
                    }
                  }
                }
              }
            }
          }
        }
        """
        return self.graphql(query, {"projectId": project_id, "after": after})

    def get_all_items(self, project_id: str) -> list:
        """Fetch ALL project items across pages and return a flat list."""
        items = []
        after = None
        while True:
            data = self.get_project_items(project_id, after)
            page = data["node"]["items"]
            items.extend(page["nodes"])
            if not page["pageInfo"]["hasNextPage"]:
                break
            after = page["pageInfo"]["endCursor"]
        return items

    # ------------------------------------------------------------------ #
    #  Mutations                                                           #
    # ------------------------------------------------------------------ #

    def update_item_field_single_select(
        self, project_id: str, item_id: str, field_id: str, option_id: str
    ) -> None:
        """Set a single-select field (e.g. Status, Priority) on a project item."""
        mutation = """
        mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $optionId: String!) {
          updateProjectV2ItemFieldValue(input: {
            projectId: $projectId
            itemId: $itemId
            fieldId: $fieldId
            value: { singleSelectOptionId: $optionId }
          }) {
            projectV2Item { id }
          }
        }
        """
        self.graphql(mutation, {
            "projectId": project_id,
            "itemId": item_id,
            "fieldId": field_id,
            "optionId": option_id,
        })

    def add_issue_to_project(self, project_id: str, issue_node_id: str) -> str:
        """Add an issue node to a Project V2 and return the project item id."""
        mutation = """
        mutation($projectId: ID!, $contentId: ID!) {
          addProjectV2ItemById(input: { projectId: $projectId, contentId: $contentId }) {
            item { id }
          }
        }
        """
        result = self.graphql(mutation, {"projectId": project_id, "contentId": issue_node_id})
        return result["addProjectV2ItemById"]["item"]["id"]

    def update_project_field_by_name(
        self,
        project_id: str,
        item_id: str,
        project: dict,
        field_name: str,
        option_name: str,
    ) -> None:
        """Set a Project V2 single-select field by field and option display names."""
        field_map = build_field_map(project)
        field = field_map.get(field_name)
        if not field:
            raise ValueError(f"project field not found: {field_name}")
        option_id = field["options"].get(option_name)
        if not option_id:
            raise ValueError(f"option {option_name!r} not found for field {field_name!r}")
        self.update_item_field_single_select(project_id, item_id, field["id"], option_id)

    def add_label_to_issue(self, repo_owner: str, repo_name: str, issue_number: int, label_name: str) -> None:
        """Ensure a label exists on a repo and add it to an issue."""
        url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/issues/{issue_number}/labels"
        resp = requests.post(url, json={"labels": [label_name]}, headers=self.headers)
        resp.raise_for_status()

    def add_labels_to_issue(self, repo: str, issue_number: int, labels: list[str], color: str = "ededed") -> None:
        """Ensure labels exist on a repo and add them to an issue."""
        owner, repo_name = split_repo(repo)
        clean_labels = [label.strip() for label in labels if label and label.strip()]
        for label in clean_labels:
            self.ensure_label_exists(owner, repo_name, label, color)
        if clean_labels:
            url = f"https://api.github.com/repos/{repo}/issues/{issue_number}/labels"
            resp = requests.post(url, json={"labels": clean_labels}, headers=self.headers)
            resp.raise_for_status()

    def ensure_label_exists(self, repo_owner: str, repo_name: str, label_name: str, color: str = "ededed") -> None:
        """Create label if it doesn't already exist."""
        url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/labels"
        existing = requests.get(url + f"/{label_name}", headers=self.headers)
        if existing.status_code == 404:
            resp = requests.post(url, json={"name": label_name, "color": color}, headers=self.headers)
            resp.raise_for_status()

    def set_issue_parent(self, child_issue_id: str, parent_issue_id: str) -> None:
        """Set a parent issue relationship (sub-issue tracking)."""
        mutation = """
        mutation($parentId: ID!, $childId: ID!) {
          addSubIssue(input: { issueId: $parentId, subIssueId: $childId }) {
            issue { id number }
          }
        }
        """
        self.graphql(mutation, {"parentId": parent_issue_id, "childId": child_issue_id})

    def remove_issue_parent(self, child_issue_id: str, parent_issue_id: str) -> None:
        """Remove a parent issue relationship."""
        mutation = """
        mutation($parentId: ID!, $childId: ID!) {
          removeSubIssue(input: { issueId: $parentId, subIssueId: $childId }) {
            issue { id number }
          }
        }
        """
        self.graphql(mutation, {"parentId": parent_issue_id, "childId": child_issue_id})

    def get_issue_node(self, repo: str, issue_number: int) -> dict:
        """Fetch issue node data needed for mutations."""
        owner, repo_name = split_repo(repo)
        query = """
        query($owner: String!, $repo: String!, $number: Int!) {
          repository(owner: $owner, name: $repo) {
            issue(number: $number) {
              id
              number
              title
              url
              parent { id number title repository { nameWithOwner } }
            }
          }
        }
        """
        data = self.graphql(query, {"owner": owner, "repo": repo_name, "number": issue_number})
        issue = ((data.get("repository") or {}).get("issue") or None)
        if not issue:
            raise ValueError(f"issue #{issue_number} not found in {repo}")
        return issue

    def set_issue_parent_by_number(
        self,
        child_repo: str,
        child_issue_number: int,
        parent_repo: str,
        parent_issue_number: int,
    ) -> None:
        """Move an issue under a parent issue using repo and issue numbers."""
        child = self.get_issue_node(child_repo, child_issue_number)
        parent = self.get_issue_node(parent_repo, parent_issue_number)
        old_parent = child.get("parent") or {}
        if old_parent.get("id") == parent["id"]:
            return
        if old_parent.get("id"):
            self.remove_issue_parent(child["id"], old_parent["id"])
        self.set_issue_parent(child["id"], parent["id"])

    def create_repo(self, name: str, description: str = "", private: bool = True) -> dict:
        """Create a new GitHub repository."""
        url = "https://api.github.com/user/repos"
        resp = requests.post(url, json={
            "name": name,
            "description": description,
            "private": private,
            "auto_init": True,
        }, headers=self.headers)
        resp.raise_for_status()
        return resp.json()

    def create_issue(self, repo: str, title: str, body: str = "", labels: list[str] | None = None) -> dict:
        """Create a GitHub issue via REST API and return the issue JSON."""
        if "/" not in repo:
            raise ValueError("repo must be owner/repo")
        payload = {"title": title, "body": body}
        clean_labels = [label.strip() for label in (labels or []) if label and label.strip()]
        if clean_labels:
            owner, repo_name = split_repo(repo)
            for label in clean_labels:
                self.ensure_label_exists(owner, repo_name, label)
            payload["labels"] = clean_labels
        url = f"https://api.github.com/repos/{repo}/issues"
        resp = requests.post(url, json=payload, headers=self.headers)
        resp.raise_for_status()
        return resp.json()

    def get_issue_comments(self, repo: str, issue_number: int, limit: int = 20) -> list[dict]:
        """Return recent issue comments in chronological order, capped by limit."""
        if "/" not in repo:
            raise ValueError("repo must be owner/repo")
        url = f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments"
        resp = requests.get(url, params={"per_page": 100, "page": 1}, headers=self.headers)
        resp.raise_for_status()
        comments = resp.json()
        return [self.parse_comment(comment) for comment in comments[-limit:]]

    def get_latest_work_log(self, repo: str, issue_number: int, limit: int = 50) -> dict | None:
        """Return the latest gtd_mgmt work-log comment for an issue, if present."""
        work_logs = self.get_work_logs(repo, issue_number, limit=limit)
        return work_logs[-1] if work_logs else None

    def get_work_logs(self, repo: str, issue_number: int, limit: int = 100) -> list[dict]:
        """Return structured gtd_mgmt work-log comments sorted oldest to newest."""
        comments = self.get_issue_comments(repo, issue_number, limit=limit)
        work_logs = []
        for comment in comments:
            if WORK_LOG_MARKER not in (comment.get("body") or ""):
                continue
            parsed = dict(comment)
            parsed["parsed"] = parse_work_log_body(parsed.get("body") or "")
            work_logs.append(parsed)
        return sorted(work_logs, key=_comment_sort_timestamp)

    def add_issue_comment(self, repo: str, issue_number: int, body: str) -> dict:
        """Append a comment to a GitHub issue."""
        if "/" not in repo:
            raise ValueError("repo must be owner/repo")
        url = f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments"
        resp = requests.post(url, json={"body": body}, headers=self.headers)
        resp.raise_for_status()
        return self.parse_comment(resp.json())

    def update_issue_comment(self, repo: str, comment_id: int | str, body: str) -> dict:
        """Replace the body of an existing issue comment."""
        if "/" not in repo:
            raise ValueError("repo must be owner/repo")
        url = f"https://api.github.com/repos/{repo}/issues/comments/{comment_id}"
        resp = requests.patch(url, json={"body": body}, headers=self.headers)
        resp.raise_for_status()
        return self.parse_comment(resp.json())

    def get_issue(self, repo: str, issue_number: int) -> dict:
        """Fetch a raw issue (including body) via REST."""
        if "/" not in repo:
            raise ValueError("repo must be owner/repo")
        url = f"https://api.github.com/repos/{repo}/issues/{issue_number}"
        resp = requests.get(url, headers=self.headers)
        resp.raise_for_status()
        return resp.json()

    def get_repo_visibility(self, repo: str) -> bool:
        """Return True if the repo is private."""
        owner, repo_name = split_repo(repo)
        url = f"https://api.github.com/repos/{owner}/{repo_name}"
        resp = requests.get(url, headers=self.headers)
        resp.raise_for_status()
        return bool(resp.json().get("private"))

    def get_branch_sha(self, repo: str, branch: str) -> str | None:
        """Return the head commit sha for a branch, or None if it doesn't exist."""
        owner, repo_name = split_repo(repo)
        url = f"https://api.github.com/repos/{owner}/{repo_name}/git/ref/heads/{branch}"
        resp = requests.get(url, headers=self.headers)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()["object"]["sha"]

    def ensure_orphan_branch(self, repo: str, branch: str, readme_text: str) -> str:
        """Create an orphan branch with an initial README commit if it doesn't exist yet.

        Race-safe: if another process creates the branch concurrently, the 422 from
        the ref-create call is treated as success and the existing branch is used.
        """
        existing = self.get_branch_sha(repo, branch)
        if existing:
            return existing

        owner, repo_name = split_repo(repo)
        base = f"https://api.github.com/repos/{owner}/{repo_name}/git"

        blob_resp = requests.post(f"{base}/blobs", json={"content": readme_text, "encoding": "utf-8"}, headers=self.headers)
        blob_resp.raise_for_status()
        blob_sha = blob_resp.json()["sha"]

        tree_resp = requests.post(
            f"{base}/trees",
            json={"tree": [{"path": "README.md", "mode": "100644", "type": "blob", "sha": blob_sha}]},
            headers=self.headers,
        )
        tree_resp.raise_for_status()
        tree_sha = tree_resp.json()["sha"]

        commit_resp = requests.post(
            f"{base}/commits",
            json={"message": f"Initialize {branch} branch", "tree": tree_sha, "parents": []},
            headers=self.headers,
        )
        commit_resp.raise_for_status()
        commit_sha = commit_resp.json()["sha"]

        ref_resp = requests.post(
            f"{base}/refs",
            json={"ref": f"refs/heads/{branch}", "sha": commit_sha},
            headers=self.headers,
        )
        if ref_resp.status_code == 422:
            existing = self.get_branch_sha(repo, branch)
            if existing:
                return existing
        ref_resp.raise_for_status()
        return commit_sha

    def get_file_contents(self, repo: str, path: str, ref: str) -> dict | None:
        """Return {"sha": blob_sha, "content": bytes} for a file, or None if missing."""
        owner, repo_name = split_repo(repo)
        url = f"https://api.github.com/repos/{owner}/{repo_name}/contents/{path}"
        resp = requests.get(url, params={"ref": ref}, headers=self.headers)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        if data.get("encoding") == "base64":
            content = base64.b64decode(data["content"])
        else:
            content = str(data.get("content") or "").encode("utf-8")
        return {"sha": data["sha"], "content": content}

    def put_file_contents(
        self, repo: str, path: str, content: bytes, message: str, branch: str, sha: str | None = None,
    ) -> dict:
        """Create or update a file via the Contents API. Returns {"sha", "commit_sha"}.

        Raises ManifestConflict on a 409 (stale sha) so callers can refetch and retry.
        """
        owner, repo_name = split_repo(repo)
        url = f"https://api.github.com/repos/{owner}/{repo_name}/contents/{path}"
        payload = {
            "message": message,
            "content": base64.b64encode(content).decode("ascii"),
            "branch": branch,
        }
        if sha:
            payload["sha"] = sha
        resp = requests.put(url, json=payload, headers=self.headers)
        if resp.status_code == 409:
            raise ManifestConflict(f"conflict writing {path} (stale sha)")
        resp.raise_for_status()
        data = resp.json()
        return {"sha": data["content"]["sha"], "commit_sha": data["commit"]["sha"]}

    def delete_file_contents(self, repo: str, path: str, message: str, branch: str, sha: str) -> dict:
        """Delete a file via the Contents API."""
        owner, repo_name = split_repo(repo)
        url = f"https://api.github.com/repos/{owner}/{repo_name}/contents/{path}"
        resp = requests.delete(
            url, json={"message": message, "sha": sha, "branch": branch}, headers=self.headers,
        )
        resp.raise_for_status()
        return resp.json()

    def update_issue_body(self, repo: str, issue_number: int, body: str) -> dict:
        """Replace the body of a GitHub issue via PATCH."""
        if "/" not in repo:
            raise ValueError("repo must be owner/repo")
        url = f"https://api.github.com/repos/{repo}/issues/{issue_number}"
        resp = requests.patch(url, json={"body": body}, headers=self.headers)
        resp.raise_for_status()
        return resp.json()

    def close_issue(self, repo: str, issue_number: int, reason: str = "completed") -> dict:
        """Close a GitHub issue via PATCH. reason: completed, not_planned."""
        if "/" not in repo:
            raise ValueError("repo must be owner/repo")
        url = f"https://api.github.com/repos/{repo}/issues/{issue_number}"
        resp = requests.patch(url, json={"state": "closed", "state_reason": reason}, headers=self.headers)
        resp.raise_for_status()
        return resp.json()

    def append_work_log(
        self,
        repo: str,
        issue_number: int,
        *,
        work_completed: str = "",
        current_state: str = "",
        next_steps: str = "",
        blockers: str = "",
        codex_project: str = "",
        codex_project_path: str = "",
        related_local_workspaces: str = "",
        related_github_repos: str = "",
        useful_context: str = "",
        attachments_markdown: str = "",
    ) -> dict:
        """Append a structured GTD work-log comment and return the created comment."""
        body = format_work_log_comment(
            work_completed=work_completed,
            current_state=current_state,
            next_steps=next_steps,
            blockers=blockers,
            codex_project=codex_project,
            codex_project_path=codex_project_path,
            related_local_workspaces=related_local_workspaces,
            related_github_repos=related_github_repos,
            useful_context=useful_context,
            attachments_markdown=attachments_markdown,
        )
        return self.add_issue_comment(repo, issue_number, body)

    # ------------------------------------------------------------------ #
    #  Helpers                                                            #
    # ------------------------------------------------------------------ #

    def parse_item(self, node: dict) -> dict:
        """
        Flatten a raw project item node into a clean dict:
          { id, number, title, body, url, state, repo, labels,
            assignees, status, priority, parent, children }
        """
        content = node.get("content") or {}
        if not content:
            return None  # draft item, skip

        field_values = {}
        for fv in (node.get("fieldValues") or {}).get("nodes", []):
            field = fv.get("field", {})
            fname = field.get("name", "")
            if "name" in fv:
                field_values[fname] = fv["name"]
            elif "text" in fv:
                field_values[fname] = fv["text"]
            elif "number" in fv:
                field_values[fname] = fv["number"]
            elif "title" in fv:
                field_values[fname] = fv["title"]

        repo = content.get("repository", {}).get("nameWithOwner", "")
        labels = [l["name"] for l in (content.get("labels") or {}).get("nodes", [])]
        assignees = [a["login"] for a in (content.get("assignees") or {}).get("nodes", [])]
        parent = content.get("parent")
        parent_repo = (parent.get("repository") or {}).get("nameWithOwner", "") if parent else ""
        children = [(c["number"], c["title"]) for c in
                    (content.get("trackedIssues") or {}).get("nodes", [])]

        return {
            "item_id": node["id"],
            "issue_id": content.get("id"),
            "number": content.get("number"),
            "title": content.get("title", ""),
            "body": content.get("body", ""),
            "url": content.get("url", ""),
            "state": content.get("state", ""),
            "repo": repo,
            "labels": labels,
            "assignees": assignees,
            "status": field_values.get("Status", ""),
            "priority": field_values.get("Priority", ""),
            "parent": (parent.get("number"), parent.get("title")) if parent else None,
            "parent_repo": parent_repo,
            "children": children,
            "fields": field_values,
        }

    @staticmethod
    def parse_comment(comment: dict) -> dict:
        user = comment.get("user") or {}
        return {
            "id": comment.get("id"),
            "body": comment.get("body") or "",
            "url": comment.get("html_url") or "",
            "created_at": comment.get("created_at") or "",
            "updated_at": comment.get("updated_at") or "",
            "author": user.get("login") or "",
        }


def format_work_log_comment(
    *,
    work_completed: str = "",
    current_state: str = "",
    next_steps: str = "",
    blockers: str = "",
    codex_project: str = "",
    codex_project_path: str = "",
    related_local_workspaces: str = "",
    related_github_repos: str = "",
    useful_context: str = "",
    attachments_markdown: str = "",
) -> str:
    """Build a structured comment optimized for future resume prompts."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        WORK_LOG_MARKER,
        "",
        f"_Logged by `gtd_mgmt` at {timestamp}_",
        "",
        "## Work Completed",
        _clean_section(work_completed),
        "",
        "## Current State",
        _clean_section(current_state),
        "",
        "## Next Steps",
        _clean_section(next_steps),
        "",
        "## Blockers / Open Questions",
        _clean_section(blockers),
        "",
        "## Codex Project",
        _clean_section(codex_project),
        "",
        "## Codex Project Path",
        _clean_section(codex_project_path),
        "",
        "## Related Local Workspaces",
        _clean_section(related_local_workspaces),
        "",
        "## Related GitHub Repositories",
        _clean_section(related_github_repos),
        "",
        "## Useful Context",
        _clean_section(useful_context),
    ]
    if attachments_markdown.strip():
        lines += ["", "## Attachments", attachments_markdown.strip()]
    return "\n".join(lines)


def parse_work_log_body(body: str) -> dict[str, list[str]]:
    """Parse a structured gtd_mgmt work-log body into resume sections."""
    parsed = {
        "work_completed": [],
        "current_state": [],
        "next_steps": [],
        "blockers_open_questions": [],
        "codex_project": [],
        "codex_project_path": [],
        "related_local_workspaces": [],
        "related_github_repos": [],
        "useful_context": [],
    }
    section = None
    section_names = {
        "work completed": "work_completed",
        "current state": "current_state",
        "next steps": "next_steps",
        "blockers / open questions": "blockers_open_questions",
        "blockers/open questions": "blockers_open_questions",
        "blockers": "blockers_open_questions",
        "open questions": "blockers_open_questions",
        "codex project": "codex_project",
        "codex workspace": "codex_project",
        "codex project/workspace": "codex_project",
        "codex project path": "codex_project_path",
        "related local workspaces": "related_local_workspaces",
        "related local workspace": "related_local_workspaces",
        "related github repositories": "related_github_repos",
        "related github repos": "related_github_repos",
        "useful context": "useful_context",
    }

    for raw_line in (body or "").splitlines():
        line = raw_line.strip()
        if not line or line == WORK_LOG_MARKER or line.startswith("_Logged by `gtd_mgmt`"):
            continue
        if line.startswith("## "):
            section = section_names.get(line[3:].strip().lower())
            continue
        if section is None:
            continue
        cleaned = _clean_work_log_line(line)
        if cleaned:
            parsed[section].append(cleaned)
    return parsed


def _clean_work_log_line(line: str) -> str:
    cleaned = line.strip()
    while cleaned.startswith(("-", "*")):
        cleaned = cleaned[1:].strip()
    if cleaned.lower() in ("none documented.", "none documented", "none", "n/a"):
        return ""
    return cleaned


def _comment_sort_timestamp(comment: dict) -> str:
    return comment.get("updated_at") or comment.get("created_at") or ""


def _clean_section(value: str) -> str:
    value = (value or "").strip()
    return value if value else "- None documented."


def split_repo(repo: str) -> tuple[str, str]:
    """Split an owner/repo string."""
    if "/" not in repo:
        raise ValueError("repo must be owner/repo")
    owner, repo_name = repo.split("/", 1)
    if not owner or not repo_name:
        raise ValueError("repo must be owner/repo")
    return owner, repo_name


def build_field_map(project: dict) -> dict:
    """Build {field_name: {id, options}} from a Project V2 metadata response."""
    field_map = {}
    for field in (project.get("fields") or {}).get("nodes", []):
        if not field:
            continue
        name = field.get("name", "")
        entry = {"id": field.get("id", ""), "options": {}}
        for option in field.get("options", []):
            entry["options"][option["name"]] = option["id"]
        field_map[name] = entry
    return field_map
