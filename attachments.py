"""
File attachments for gtd_mgmt issues.

Files live on an orphan `gtd-assets` branch in the same repo as the issue:
  issues/<issue_number>/manifest.json         index of attachments for the issue
  issues/<issue_number>/<slug>-<sha8>.<ext>   the file content

See gtd_mgmt_file_attachments_spec.md for the full design.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from github_client import GitHubClient, ManifestConflict, split_repo

GTD_ASSETS_BRANCH = "gtd-assets"
README_TEXT = (
    "# gtd-assets\n\n"
    "This orphan branch stores file attachments for gtd_mgmt issues.\n"
    "Do not merge it into `main`. Each issue's files and manifest live under "
    "`issues/<issue_number>/`. The manifest.json in each issue directory is the "
    "source of truth for that issue's attachments — never inferred from comments.\n"
)

_MB = 1024 * 1024
HARD_CEILING_BYTES = 50 * _MB
DEFAULT_MAX_TOTAL_PER_ISSUE_BYTES = 200 * _MB
MAX_INLINE_RETRIEVAL_BYTES = 5 * _MB
DEFAULT_MAX_BATCH_RETRIEVAL_BYTES = 200 * _MB

BLOCKED_EXTENSIONS = {"exe", "dll", "sh", "bat", "ps1", "app", "dmg", "msi", "jar"}
TEXT_SCAN_EXTENSIONS = {"md", "txt", "csv"}

SECRET_PATTERNS = [
    ("aws_access_key_id", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("private_key_block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |)PRIVATE KEY-----")),
    ("github_token", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")),
    ("slack_token", re.compile(r"xox[baprs]-[0-9A-Za-z-]{10,}")),
]


def secret_scan(text: str) -> str | None:
    """Return the name of the first matched secret pattern, or None."""
    for name, pattern in SECRET_PATTERNS:
        if pattern.search(text):
            return name
    return None


def _sniff_png(data: bytes) -> bool:
    return data.startswith(b"\x89PNG\r\n\x1a\n")


def _sniff_jpeg(data: bytes) -> bool:
    return data.startswith(b"\xff\xd8\xff")


def _sniff_gif(data: bytes) -> bool:
    return data.startswith((b"GIF87a", b"GIF89a"))


def _sniff_webp(data: bytes) -> bool:
    return data[:4] == b"RIFF" and data[8:12] == b"WEBP"


def _sniff_pdf(data: bytes) -> bool:
    return data.startswith(b"%PDF-")


def _sniff_zip(data: bytes) -> bool:
    return data[:4] in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")


def _sniff_svg(data: bytes) -> bool:
    head = data[:512].decode("utf-8", errors="ignore").lower()
    return "<svg" in head or ("<?xml" in head and "svg" in head)


def _sniff_text(data: bytes) -> bool:
    try:
        data.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


BLOCKED_SIGNATURES: list[tuple[str, Any]] = [
    ("windows_pe", lambda d: d.startswith(b"MZ")),
    ("elf_binary", lambda d: d.startswith(b"\x7fELF")),
    ("macho_binary", lambda d: d[:4] in (
        b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf", b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe",
    )),
    ("shebang_script", lambda d: d.startswith(b"#!")),
]

EXTENSION_TABLE: dict[str, dict[str, Any]] = {
    "png":  {"category": "image", "mime": "image/png", "inline": True, "cap": 10 * _MB, "sniff": _sniff_png},
    "jpg":  {"category": "image", "mime": "image/jpeg", "inline": True, "cap": 10 * _MB, "sniff": _sniff_jpeg},
    "jpeg": {"category": "image", "mime": "image/jpeg", "inline": True, "cap": 10 * _MB, "sniff": _sniff_jpeg},
    "gif":  {"category": "image", "mime": "image/gif", "inline": True, "cap": 10 * _MB, "sniff": _sniff_gif},
    "webp": {"category": "image", "mime": "image/webp", "inline": True, "cap": 10 * _MB, "sniff": _sniff_webp},
    "svg":  {"category": "vector", "mime": "image/svg+xml", "inline": True, "cap": 5 * _MB, "sniff": _sniff_svg},
    "pdf":  {"category": "doc", "mime": "application/pdf", "inline": False, "cap": 25 * _MB, "sniff": _sniff_pdf},
    "md":   {"category": "doc", "mime": "text/markdown", "inline": False, "cap": 25 * _MB, "sniff": _sniff_text},
    "txt":  {"category": "doc", "mime": "text/plain", "inline": False, "cap": 25 * _MB, "sniff": _sniff_text},
    "csv":  {"category": "doc", "mime": "text/csv", "inline": False, "cap": 25 * _MB, "sniff": _sniff_text},
    "docx": {"category": "office", "mime": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "inline": False, "cap": 25 * _MB, "sniff": _sniff_zip},
    "xlsx": {"category": "office", "mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "inline": False, "cap": 25 * _MB, "sniff": _sniff_zip},
    "pptx": {"category": "office", "mime": "application/vnd.openxmlformats-officedocument.presentationml.presentation", "inline": False, "cap": 25 * _MB, "sniff": _sniff_zip},
    "skp":    {"category": "cad", "mime": "application/octet-stream", "inline": False, "cap": 50 * _MB, "sniff": None},
    "dxf":    {"category": "cad", "mime": "application/dxf", "inline": False, "cap": 50 * _MB, "sniff": None},
    "dwg":    {"category": "cad", "mime": "application/acad", "inline": False, "cap": 50 * _MB, "sniff": None},
    "layout": {"category": "cad", "mime": "application/octet-stream", "inline": False, "cap": 50 * _MB, "sniff": None},
    "zip":  {"category": "archive", "mime": "application/zip", "inline": False, "cap": 50 * _MB, "sniff": _sniff_zip},
}


def slugify(name: str) -> str:
    lowered = (name or "").strip().lower()
    slug = re.sub(r"[^a-z0-9-]+", "-", lowered)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return (slug or "file")[:60]


def validate_attachment(file_path: str, name_override: str = "") -> dict[str, Any]:
    """Validate a local file against the attachment allowlist and return its metadata + bytes.

    Raises ValueError with a caller-facing message on any validation failure.
    """
    path = Path(file_path).expanduser()
    if path.is_symlink():
        raise ValueError("symlinks are not allowed as attachments")
    if not path.is_file():
        raise ValueError(f"file not found: {file_path}")

    size_bytes = path.stat().st_size
    if size_bytes == 0:
        raise ValueError("empty files are not allowed as attachments")

    ext = path.suffix.lower().lstrip(".")
    if ext in BLOCKED_EXTENSIONS:
        raise ValueError(f"file type .{ext} is blocked (executables/scripts are never allowed)")
    spec = EXTENSION_TABLE.get(ext)
    if not spec:
        raise ValueError(f"file type .{ext} is not in the attachment allowlist")

    if size_bytes > spec["cap"]:
        raise ValueError(
            f".{ext} files are capped at {spec['cap'] // _MB} MB (got {size_bytes / _MB:.1f} MB)"
        )
    if size_bytes > HARD_CEILING_BYTES:
        raise ValueError(
            f"file exceeds the {HARD_CEILING_BYTES // _MB} MB hard ceiling; compress it or link externally"
        )

    data = path.read_bytes()

    for sig_name, check in BLOCKED_SIGNATURES:
        if check(data):
            raise ValueError(f"file content matches a blocked signature ({sig_name}); refusing upload")

    sniff = spec["sniff"]
    if sniff and not sniff(data):
        raise ValueError(f"file content does not match the expected format for .{ext} (extension/content mismatch)")

    if ext in TEXT_SCAN_EXTENSIONS:
        match = secret_scan(data.decode("utf-8", errors="ignore"))
        if match:
            raise ValueError(f"refusing to upload: content matched secret pattern '{match}'")

    return {
        "slug": slugify(name_override or path.stem),
        "ext": ext,
        "category": spec["category"],
        "mime": spec["mime"],
        "inline": spec["inline"],
        "size_bytes": size_bytes,
        "content": data,
        "sha256": hashlib.sha256(data).hexdigest(),
        "original_name": path.name,
    }


def build_embed_markdown(caption: str, url: str, inline: bool) -> str:
    text = caption or "attachment"
    return f"![{text}]({url})" if inline else f"[{text}]({url})"


def _manifest_path(issue_number: int) -> str:
    return f"issues/{issue_number}/manifest.json"


def get_manifest(client: GitHubClient, repo: str, issue_number: int) -> dict[str, Any]:
    result = client.get_file_contents(repo, _manifest_path(issue_number), GTD_ASSETS_BRANCH)
    if result is None:
        return {"entries": [], "sha": None}
    return {"entries": json.loads(result["content"].decode("utf-8")), "sha": result["sha"]}


def put_manifest(client: GitHubClient, repo: str, issue_number: int, entries: list[dict], sha: str | None) -> None:
    content = json.dumps(entries, indent=2).encode("utf-8")
    client.put_file_contents(
        repo, _manifest_path(issue_number), content,
        "Update attachment manifest", GTD_ASSETS_BRANCH, sha=sha,
    )


def _mutate_manifest_with_retry(
    client: GitHubClient, repo: str, issue_number: int, mutate_fn, max_attempts: int = 2,
) -> list[dict]:
    """Fetch, mutate, and write the manifest, retrying once on a concurrent-write conflict."""
    last_exc: Exception | None = None
    for _ in range(max_attempts):
        manifest = get_manifest(client, repo, issue_number)
        entries = manifest["entries"]
        mutate_fn(entries)
        try:
            put_manifest(client, repo, issue_number, entries, manifest["sha"])
            return entries
        except ManifestConflict as exc:
            last_exc = exc
            continue
    raise last_exc


def _raw_url(repo: str, commit_sha: str, path: str) -> str:
    owner, name = split_repo(repo)
    return f"https://raw.githubusercontent.com/{owner}/{name}/{commit_sha}/{path}"


def _total_active_bytes(entries: list[dict]) -> int:
    return sum(int(e.get("size_bytes") or 0) for e in entries if not e.get("deleted"))


def attach_file(
    client: GitHubClient,
    repo: str,
    issue_number: int,
    file_path: str,
    *,
    caption: str = "",
    name: str = "",
    mode: str = "comment",
    comment_text: str = "",
    max_total_per_issue_bytes: int = DEFAULT_MAX_TOTAL_PER_ISSUE_BYTES,
) -> dict[str, Any]:
    """Attach a local file to an issue. mode: comment | body_append | none."""
    validated = validate_attachment(file_path, name)
    client.ensure_orphan_branch(repo, GTD_ASSETS_BRANCH, README_TEXT)

    manifest = get_manifest(client, repo, issue_number)
    entries = manifest["entries"]
    existing = next(
        (e for e in entries if e.get("content_sha256") == validated["sha256"] and not e.get("deleted")),
        None,
    )
    deduplicated = existing is not None

    if existing:
        entry = existing
    else:
        total_after = _total_active_bytes(entries) + validated["size_bytes"]
        if total_after > max_total_per_issue_bytes:
            raise ValueError(
                f"attaching this file would exceed the {max_total_per_issue_bytes // _MB} MB "
                f"per-issue attachment budget; prune old attachments with delete_issue_file first"
            )
        filename = f"{validated['slug']}-{validated['sha256'][:8]}.{validated['ext']}"
        path = f"issues/{issue_number}/{filename}"
        put_result = client.put_file_contents(
            repo, path, validated["content"], f"Attach {filename} to issue #{issue_number}", GTD_ASSETS_BRANCH,
        )
        entry = {
            "path": path,
            "original_name": validated["original_name"],
            "caption": caption,
            "content_sha256": validated["sha256"],
            "size_bytes": validated["size_bytes"],
            "mime": validated["mime"],
            "added_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "added_by": "gtd_mgmt",
            "git_sha": put_result["sha"],
        }
        _mutate_manifest_with_retry(client, repo, issue_number, lambda e: e.append(entry))

    commit_sha = client.get_branch_sha(repo, GTD_ASSETS_BRANCH) or ""
    raw_url = _raw_url(repo, commit_sha, entry["path"])
    is_private = client.get_repo_visibility(repo)
    rendered = bool(validated["inline"]) and not is_private

    result: dict[str, Any] = {
        "ok": True,
        "path": entry["path"],
        "original_name": entry["original_name"],
        "raw_url": raw_url,
        "rendered": rendered,
        "deduplicated": deduplicated,
    }
    if validated["inline"] and is_private:
        result["reason"] = "private repo — raw URLs require auth"

    if mode != "none":
        markdown = build_embed_markdown(caption or entry["original_name"], raw_url, rendered)
        body = "\n\n".join(part for part in (comment_text, markdown) if part)
        try:
            if mode == "body_append":
                issue = client.get_issue(repo, issue_number)
                new_body = (issue.get("body") or "") + "\n\n" + body
                client.update_issue_body(repo, issue_number, new_body)
            else:
                comment = client.add_issue_comment(repo, issue_number, body)
                result["comment_url"] = comment["url"]
                result["comment_id"] = comment["id"]
        except Exception as exc:
            result["ok"] = False
            result["comment_error"] = str(exc)

    return result


def list_files(client: GitHubClient, repo: str, issue_number: int) -> dict[str, Any]:
    manifest = get_manifest(client, repo, issue_number)
    head_sha = client.get_branch_sha(repo, GTD_ASSETS_BRANCH) or ""
    attachments = []
    for entry in manifest["entries"]:
        item = dict(entry)
        item["raw_url"] = _raw_url(repo, head_sha, entry["path"]) if head_sha else ""
        item["superseded"] = bool(entry.get("superseded_by"))
        item["deleted"] = bool(entry.get("deleted"))
        attachments.append(item)
    return {"ok": True, "repo": repo, "issue_number": issue_number, "count": len(attachments), "attachments": attachments}


def _retrieval_error(code: str, message: str, **details: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": False, "error": {"code": code, "message": message}}
    if details:
        result["error"]["details"] = details
    return result


def _select_file(
    entries: list[dict[str, Any]],
    selectors: dict[str, str],
    *,
    include_superseded: bool,
    include_deleted: bool,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    supplied = {key: value for key, value in selectors.items() if value}
    if len(supplied) != 1:
        return None, _retrieval_error(
            "invalid_selector",
            "exactly one of original_name, path, content_sha256, or git_sha is required",
        )

    key, value = next(iter(supplied.items()))
    matches = [entry for entry in entries if str(entry.get(key) or "") == value]
    visible = [
        entry for entry in matches
        if (include_superseded or not entry.get("superseded_by"))
        and (include_deleted or not entry.get("deleted"))
    ]
    candidates = [
        {"original_name": entry.get("original_name"), "path": entry.get("path")}
        for entry in entries
    ]
    if not visible:
        code = "attachment_deleted" if matches and any(e.get("deleted") for e in matches) else "attachment_not_found"
        return None, _retrieval_error(code, f"no retrievable attachment matched {key}={value!r}", candidates=candidates)
    if len(visible) > 1:
        return None, _retrieval_error(
            "ambiguous_attachment",
            f"multiple attachments matched {key}={value!r}; select by path, content_sha256, or git_sha",
            candidates=[{"original_name": e.get("original_name"), "path": e.get("path")} for e in visible],
        )
    return visible[0], None


def _validate_retrieval_entry(entry: dict[str, Any], issue_number: int) -> dict[str, Any] | None:
    """Return a structured error when required retrieval metadata is malformed."""
    path = entry.get("path")
    original_name = entry.get("original_name")
    content_sha256 = entry.get("content_sha256")
    git_sha = entry.get("git_sha")
    size_bytes = entry.get("size_bytes")
    mime = entry.get("mime")
    if not isinstance(path, str) or not path:
        return _retrieval_error("invalid_manifest", "attachment manifest path is missing or invalid")
    expected_prefix = f"issues/{issue_number}/"
    if not path.startswith(expected_prefix) or ".." in Path(path).parts:
        return _retrieval_error("invalid_manifest_path", "attachment path is outside the issue attachment directory")
    if not isinstance(original_name, str) or not original_name or Path(original_name).name != original_name:
        return _retrieval_error("invalid_manifest", "attachment original_name is missing or unsafe", path=path)
    if not isinstance(content_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", content_sha256):
        return _retrieval_error("invalid_manifest", "attachment content_sha256 is missing or invalid", path=path)
    if not isinstance(git_sha, str) or not re.fullmatch(r"[0-9A-Za-z-]{4,64}", git_sha):
        return _retrieval_error("invalid_manifest", "attachment git_sha is missing or invalid", path=path)
    if not isinstance(size_bytes, int) or isinstance(size_bytes, bool) or size_bytes < 0:
        return _retrieval_error("invalid_manifest", "attachment size_bytes is missing or invalid", path=path)
    if not isinstance(mime, str) or not mime:
        return _retrieval_error("invalid_manifest", "attachment mime is missing or invalid", path=path)
    return None


def get_file(
    client: GitHubClient,
    repo: str,
    issue_number: int,
    *,
    original_name: str = "",
    path: str = "",
    content_sha256: str = "",
    git_sha: str = "",
    output: str = "base64",
    dest_path: str = "",
    overwrite: bool = False,
    include_superseded: bool = False,
    include_deleted: bool = False,
    max_inline_bytes: int = MAX_INLINE_RETRIEVAL_BYTES,
) -> dict[str, Any]:
    """Retrieve and verify one attachment from the authenticated gtd-assets store."""
    if output not in {"base64", "write"}:
        return _retrieval_error("invalid_output", "output must be 'base64' or 'write'")
    if output == "write" and not dest_path:
        return _retrieval_error("invalid_destination", "dest_path is required when output is 'write'")

    manifest = get_manifest(client, repo, issue_number)
    entry, error = _select_file(
        manifest["entries"],
        {
            "original_name": original_name.strip(),
            "path": path.strip(),
            "content_sha256": content_sha256.strip(),
            "git_sha": git_sha.strip(),
        },
        include_superseded=include_superseded,
        include_deleted=include_deleted,
    )
    if error:
        return error
    assert entry is not None

    validation_error = _validate_retrieval_entry(entry, issue_number)
    if validation_error:
        return validation_error
    manifest_path = str(entry.get("path") or "")
    expected_sha256 = str(entry.get("content_sha256") or "")
    stored = client.get_file_contents(repo, manifest_path, GTD_ASSETS_BRANCH)
    data = stored["content"] if stored is not None else None
    warnings: list[dict[str, str]] = []
    if data is None or hashlib.sha256(data).hexdigest() != expected_sha256:
        blob_sha = str(entry.get("git_sha") or "")
        blob = client.get_git_blob(repo, blob_sha) if blob_sha else None
        if blob is not None:
            if data is not None:
                warnings.append({"code": "working_copy_stale", "message": "used the stored Git blob because the branch copy did not verify"})
            data = blob
    if data is None:
        return _retrieval_error("blob_unavailable", "attachment bytes are unavailable from the gtd-assets store")
    actual_sha256 = hashlib.sha256(data).hexdigest()
    if not expected_sha256 or actual_sha256 != expected_sha256:
        return _retrieval_error(
            "hash_mismatch", "retrieved attachment did not match its manifest SHA-256",
            expected_sha256=expected_sha256, actual_sha256=actual_sha256,
        )
    expected_size = int(entry["size_bytes"])
    if len(data) != expected_size:
        return _retrieval_error(
            "size_mismatch", "retrieved attachment did not match its manifest size",
            expected_size_bytes=expected_size, actual_size_bytes=len(data),
        )

    attachment = dict(entry)
    attachment["superseded"] = bool(entry.get("superseded_by"))
    attachment["deleted"] = bool(entry.get("deleted"))
    result: dict[str, Any] = {
        "ok": True, "issue_number": issue_number, "repo": repo,
        "attachment": attachment, "output": output, "verified_sha256": True, "warnings": warnings,
    }
    if output == "base64":
        if len(data) > max_inline_bytes:
            return _retrieval_error(
                "inline_size_exceeded",
                f"attachment exceeds the {max_inline_bytes} byte inline limit; use output='write'",
                size_bytes=len(data), max_inline_bytes=max_inline_bytes,
            )
        result["content_base64"] = base64.b64encode(data).decode("ascii")
        return result

    destination = Path(dest_path).expanduser()
    if not destination.is_absolute():
        return _retrieval_error("invalid_destination", "dest_path must be absolute")
    if destination.is_symlink():
        return _retrieval_error("invalid_destination", "dest_path may not be a symlink")
    if destination.exists() and not overwrite:
        return _retrieval_error("destination_exists", "dest_path already exists; pass overwrite=true to replace it")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.parent.is_symlink():
        return _retrieval_error("invalid_destination", "dest_path parent may not be a symlink")
    fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    result["dest_path"] = str(destination)
    return result


def get_files(
    client: GitHubClient,
    repo: str,
    issue_number: int,
    dest_dir: str,
    *,
    mime_prefix: str = "",
    include_superseded: bool = False,
    include_deleted: bool = False,
    overwrite: bool = False,
    fail_fast: bool = False,
    max_total_bytes: int = DEFAULT_MAX_BATCH_RETRIEVAL_BYTES,
) -> dict[str, Any]:
    """Retrieve eligible issue attachments into a directory with per-file results."""
    destination = Path(dest_dir).expanduser()
    if not destination.is_absolute():
        return _retrieval_error("invalid_destination", "dest_dir must be absolute")
    if destination.is_symlink():
        return _retrieval_error("invalid_destination", "dest_dir may not be a symlink")
    if not isinstance(max_total_bytes, int) or isinstance(max_total_bytes, bool) or max_total_bytes <= 0:
        return _retrieval_error("invalid_batch_limit", "max_total_bytes must be a positive integer")

    manifest = get_manifest(client, repo, issue_number)
    eligible = [
        entry for entry in manifest["entries"]
        if (include_superseded or not entry.get("superseded_by"))
        and (include_deleted or not entry.get("deleted"))
        and (not mime_prefix or str(entry.get("mime") or "").startswith(mime_prefix))
    ]
    names: dict[str, list[str]] = {}
    for entry in eligible:
        name = str(entry.get("original_name") or "")
        names.setdefault(name, []).append(str(entry.get("path") or ""))
    collisions = {name: paths for name, paths in names.items() if name and len(paths) > 1}
    if collisions:
        return _retrieval_error(
            "destination_name_collision",
            "multiple selected attachments have the same original_name",
            collisions=collisions,
        )

    declared_total = sum(
        entry.get("size_bytes") if isinstance(entry.get("size_bytes"), int) else 0
        for entry in eligible
    )
    if declared_total > max_total_bytes:
        return _retrieval_error(
            "batch_size_exceeded", "selected attachments exceed the batch byte limit",
            declared_total_bytes=declared_total, max_total_bytes=max_total_bytes,
        )

    destination.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    succeeded = 0
    for entry in eligible:
        entry_error = _validate_retrieval_entry(entry, issue_number)
        if entry_error:
            result = {"original_name": entry.get("original_name"), "path": entry.get("path"), **entry_error}
        else:
            result = get_file(
                client, repo, issue_number,
                path=str(entry["path"]), output="write",
                dest_path=str(destination / str(entry["original_name"])), overwrite=overwrite,
                include_superseded=include_superseded, include_deleted=include_deleted,
            )
        results.append(result)
        if result.get("ok"):
            succeeded += 1
        elif fail_fast:
            break

    return {
        "ok": succeeded == len(eligible),
        "repo": repo,
        "issue_number": issue_number,
        "dest_dir": str(destination),
        "selected_count": len(eligible),
        "processed_count": len(results),
        "succeeded_count": succeeded,
        "failed_count": len(results) - succeeded,
        "files": results,
        "warnings": [],
    }


def update_file(
    client: GitHubClient,
    repo: str,
    issue_number: int,
    path: str,
    file_path: str,
    *,
    caption: str = "",
    mode: str = "comment",
) -> dict[str, Any]:
    validated = validate_attachment(file_path)
    client.ensure_orphan_branch(repo, GTD_ASSETS_BRANCH, README_TEXT)

    manifest = get_manifest(client, repo, issue_number)
    old_entry = next((e for e in manifest["entries"] if e.get("path") == path), None)
    if old_entry is None:
        raise ValueError(f"no manifest entry found for path {path!r} on issue #{issue_number}")

    filename = f"{validated['slug']}-{validated['sha256'][:8]}.{validated['ext']}"
    new_path = f"issues/{issue_number}/{filename}"
    put_result = client.put_file_contents(
        repo, new_path, validated["content"], f"Update attachment for issue #{issue_number}", GTD_ASSETS_BRANCH,
    )
    new_entry = {
        "path": new_path,
        "original_name": validated["original_name"],
        "caption": caption,
        "content_sha256": validated["sha256"],
        "size_bytes": validated["size_bytes"],
        "mime": validated["mime"],
        "added_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "added_by": "gtd_mgmt",
        "git_sha": put_result["sha"],
    }

    def _mutate(entries: list[dict]) -> None:
        for e in entries:
            if e.get("path") == path:
                e["superseded_by"] = new_path
        entries.append(new_entry)

    _mutate_manifest_with_retry(client, repo, issue_number, _mutate)

    commit_sha = client.get_branch_sha(repo, GTD_ASSETS_BRANCH) or ""
    raw_url = _raw_url(repo, commit_sha, new_path)
    is_private = client.get_repo_visibility(repo)
    rendered = bool(validated["inline"]) and not is_private

    result: dict[str, Any] = {
        "ok": True,
        "old_path": path,
        "new_path": new_path,
        "raw_url": raw_url,
        "rendered": rendered,
    }

    if mode != "none":
        markdown = build_embed_markdown(caption or new_entry["original_name"], raw_url, rendered)
        body = f"Updated attachment: {old_entry.get('original_name', path)} -> {new_entry['original_name']}\n\n{markdown}"
        try:
            comment = client.add_issue_comment(repo, issue_number, body)
            result["comment_url"] = comment["url"]
            result["comment_id"] = comment["id"]
        except Exception as exc:
            result["ok"] = False
            result["comment_error"] = str(exc)

    return result


def delete_file(
    client: GitHubClient,
    repo: str,
    issue_number: int,
    path: str,
    *,
    handle_references: str = "warn",
) -> dict[str, Any]:
    manifest = get_manifest(client, repo, issue_number)
    entry = next((e for e in manifest["entries"] if e.get("path") == path), None)
    if entry is None:
        raise ValueError(f"no manifest entry found for path {path!r} on issue #{issue_number}")
    if entry.get("deleted"):
        return {"ok": True, "path": path, "already_deleted": True, "references": []}

    client.delete_file_contents(
        repo, path, f"Delete attachment {path}", GTD_ASSETS_BRANCH, entry.get("git_sha", ""),
    )

    def _mutate(entries: list[dict]) -> None:
        for e in entries:
            if e.get("path") == path:
                e["deleted"] = True

    _mutate_manifest_with_retry(client, repo, issue_number, _mutate)

    comments = client.get_issue_comments(repo, issue_number, limit=200)
    references = [
        {"id": c["id"], "url": c["url"]} for c in comments if path in (c.get("body") or "")
    ]
    annotated = False
    if handle_references == "annotate" and references:
        marker = f"\n\n> ⚠️ attachment deleted {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
        for ref in references:
            comment_id = ref["id"]
            original = next((c for c in comments if c["id"] == comment_id), None)
            if original is None:
                continue
            client.update_issue_comment(repo, comment_id, (original.get("body") or "") + marker)
        annotated = True

    return {"ok": True, "path": path, "deleted": True, "references": references, "annotated": annotated}


def attach_many_and_build_section(
    client: GitHubClient,
    repo: str,
    issue_number: int,
    attachments: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Upload each {file_path, caption?} with mode=none and build a shared '## Attachments' body.

    Returns {"markdown": str, "results": [...]}. markdown is "" if nothing succeeded.
    """
    results = []
    embeds = []
    for att in attachments or []:
        file_path = str((att or {}).get("file_path") or "").strip()
        caption = str((att or {}).get("caption") or "").strip()
        if not file_path:
            results.append({"ok": False, "error": "attachments[].file_path is required"})
            continue
        try:
            result = attach_file(client, repo, issue_number, file_path, caption=caption, mode="none")
        except Exception as exc:
            results.append({"ok": False, "file_path": file_path, "error": str(exc)})
            continue
        results.append(result)
        if result.get("ok"):
            embeds.append(build_embed_markdown(caption or result.get("original_name", ""), result["raw_url"], result["rendered"]))

    markdown = "\n\n".join(embeds)
    return {"markdown": markdown, "results": results}
