#!/usr/bin/env python3
"""Tk GUI for browsing the configured GitHub Project issue hierarchy."""
from __future__ import annotations

import os
os.environ.setdefault("TK_SILENCE_DEPRECATION", "1")

import argparse
import http.server
import json
import sys
import queue
import threading
import tkinter as tk
import webbrowser
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse

import customtkinter as ctk
from tkinter import ttk

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from config import GITHUB_PROJECT_NUMBER, GITHUB_USER
from github_client import GitHubClient

CMD_PORTS = (8775, 8776, 8777)

COLORS = {
    "base": "#1e1e2e",
    "mantle": "#181825",
    "surface0": "#313244",
    "overlay0": "#6c7086",
    "text": "#cdd6f4",
    "blue": "#89b4fa",
    "sky": "#89dceb",
    "mauve": "#cba6f7",
    "yellow": "#f9e2af",
    "green": "#a6e3a1",
    "red": "#f38ba8",
    "peach": "#fab387",
    "teal": "#94e2d5",
}

PRIORITY_ORDER = {"P1-Critical": 0, "P2-High": 1, "P3-Medium": 2, "P4-Low": 3, "": 9}
STATUS_ORDER = {"This Week": 0, "Ready": 1, "Backlog": 2, "Done": 9, "": 8}
WHEN_ORDER = {"when:today": 0, "when:this-week": 1, "when:this-month": 2, "when:this-quarter": 3, "": 9}
INBOX_ROOT_TITLE = "[Scott T] Inbox"


@dataclass(frozen=True)
class IssueKey:
    repo: str
    number: int


def issue_key(item: dict[str, Any]) -> IssueKey:
    return IssueKey(str(item.get("repo") or ""), int(item.get("number") or 0))


def parent_key(item: dict[str, Any]) -> IssueKey | None:
    parent = item.get("parent")
    if not parent:
        return None
    parent_number = parent[0]
    if not parent_number:
        return None
    repo = str(item.get("parent_repo") or item.get("repo") or "")
    return IssueKey(repo, int(parent_number))


def build_issue_tree(items: list[dict[str, Any]]) -> tuple[dict[IssueKey, dict[str, Any]], dict[IssueKey | None, list[IssueKey]]]:
    """Build a parent -> child issue map from parsed GitHub project items."""
    index = {issue_key(item): item for item in items if item.get("number")}
    children: dict[IssueKey | None, list[IssueKey]] = {None: []}

    for key, item in index.items():
        pkey = parent_key(item)
        if pkey not in index:
            pkey = None
        children.setdefault(pkey, []).append(key)
        children.setdefault(key, [])

    for child_keys in children.values():
        child_keys.sort(key=lambda key: _sort_key(index[key]))

    return index, children


def _item_when(item: dict[str, Any]) -> str:
    """Return the first when:* label on an item, or empty string."""
    for label in item.get("labels") or []:
        if label.startswith("when:"):
            return label
    return ""


def _is_done_item(item: dict[str, Any]) -> bool:
    return (
        str(item.get("status") or "").lower() == "done"
        or str(item.get("state") or "").upper() == "CLOSED"
    )


def _root_key_for(key: IssueKey, index: dict, children_map: dict) -> IssueKey:
    """Walk parent links to the tree root. Cycle-safe."""
    visited: set[IssueKey] = set()
    cur = key
    while cur not in visited:
        visited.add(cur)
        item = index.get(cur)
        if not item:
            break
        pkey = parent_key(item)
        if pkey is None or pkey not in index:
            return cur
        cur = pkey
    return key


def _root_title_for(key: IssueKey, index: dict, children_map: dict) -> str:
    """Return the title of the root ancestor (= the domain/Area name)."""
    root = _root_key_for(key, index, children_map)
    item = index.get(root)
    return str(item.get("title") or "") if item else ""


def _item_phase(key: IssueKey, item: dict[str, Any], index: dict, children_map: dict) -> str:
    """Derive GTD phase: done/waiting/someday/inbox/project/next-action."""
    if str(item.get("state") or "").upper() == "CLOSED":
        return "done"
    labels = set(item.get("labels") or [])
    if "gtd:waiting-for" in labels:
        return "waiting"
    if "gtd:someday-maybe" in labels:
        return "someday"
    if _root_title_for(key, index, children_map) == INBOX_ROOT_TITLE:
        return "inbox"
    if children_map.get(key):
        return "project"
    if _item_when(item):
        return "next-action"
    return "inbox"


def _sort_key(item: dict[str, Any]) -> tuple[int, int, str]:
    return (
        WHEN_ORDER.get(_item_when(item), 9),
        PRIORITY_ORDER.get(str(item.get("priority") or ""), 9),
        str(item.get("title") or "").lower(),
    )


class CommandHandler(http.server.BaseHTTPRequestHandler):
    """Forward local HTTP commands to the Tk main thread."""

    def __init__(self, cmd_queue: queue.Queue, *args, **kwargs) -> None:
        self._cmd_queue = cmd_queue
        super().__init__(*args, **kwargs)

    def log_message(self, *_) -> None:
        pass

    def _send_json(self, data: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _dispatch(self, cmd: dict[str, Any]) -> dict[str, Any]:
        event = threading.Event()
        result: list[dict[str, Any] | None] = [None]
        cmd["_event"] = event
        cmd["_result"] = result
        self._cmd_queue.put(cmd)
        event.wait(timeout=30.0)
        return result[0] or {"ok": False, "error": "command timed out"}

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)
        if path in ("/status", "/issues", "/refresh"):
            self._send_json(self._dispatch({"cmd": path.lstrip("/")}))
            return
        if path == "/find-issue":
            self._send_json(self._dispatch({
                "cmd": "find-issue",
                "data": {"issue_number": query.get("n", [None])[0], "repo": query.get("repo", [""])[0]},
            }))
            return
        if path == "/search":
            self._send_json(self._dispatch({
                "cmd": "search",
                "data": {"query": query.get("q", [""])[0], "limit": query.get("limit", [10])[0]},
            }))
            return
        if path == "/context":
            self._send_json(self._dispatch({
                "cmd": "context",
                "data": {
                    "issue_number": query.get("n", [None])[0],
                    "repo": query.get("repo", [""])[0],
                    "comments": query.get("comments", ["5"])[0],
                },
            }))
            return
        if path == "/comments":
            self._send_json(self._dispatch({
                "cmd": "comments",
                "data": {
                    "issue_number": query.get("n", [None])[0],
                    "repo": query.get("repo", [""])[0],
                    "limit": query.get("limit", ["5"])[0],
                },
            }))
            return
        if path == "/latest-work-log":
            self._send_json(self._dispatch({
                "cmd": "latest-work-log",
                "data": {"issue_number": query.get("n", [None])[0], "repo": query.get("repo", [""])[0]},
            }))
            return
        self._send_json({"ok": False, "error": f"unknown endpoint: {path}"}, 404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path.rstrip("/") or "/"
        length = int(self.headers.get("Content-Length", "0"))
        try:
            data = json.loads(self.rfile.read(length)) if length else {}
        except json.JSONDecodeError:
            self._send_json({"ok": False, "error": "invalid JSON body"}, 400)
            return
        if path in ("/apply-change", "/refresh", "/load-project", "/set-filters"):
            self._send_json(self._dispatch({"cmd": path.lstrip("/"), "data": data}))
            return
        self._send_json({"ok": False, "error": f"unknown endpoint: {path}"}, 404)


class ProjectIssueGui(ctk.CTk):
    def __init__(self) -> None:
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        super().__init__()

        self.title("GTD Project Issues")
        self.geometry("1280x780")
        self.minsize(920, 560)
        self.configure(fg_color=COLORS["base"])

        self._items: list[dict[str, Any]] = []
        self._index: dict[IssueKey, dict[str, Any]] = {}
        self._children: dict[IssueKey | None, list[IssueKey]] = {None: []}
        self._load_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._cmd_queue: queue.Queue = queue.Queue()
        self._cmd_port: int | None = None
        self._item_urls: dict[str, str] = {}
        self._item_keys: dict[str, IssueKey] = {}
        self._comment_group_keys: dict[str, IssueKey] = {}
        self._loaded_comment_groups: set[str] = set()
        self._project_title = ""
        self._load_error = ""
        self._loading = False

        self._hide_done = ctk.BooleanVar(value=True)
        self._search_var = ctk.StringVar(value="")
        self._when_filter_vars: dict[str, ctk.BooleanVar] = {
            "when:today":        ctk.BooleanVar(value=False),
            "when:this-week":    ctk.BooleanVar(value=False),
            "when:this-month":   ctk.BooleanVar(value=False),
            "when:this-quarter": ctk.BooleanVar(value=False),
        }
        self._phase_filter_vars: dict[str, ctk.BooleanVar] = {
            "waiting": ctk.BooleanVar(value=False),
            "someday": ctk.BooleanVar(value=False),
            "inbox":   ctk.BooleanVar(value=False),
        }
        self._area_var = ctk.StringVar(value="All")
        self._group_by_var = ctk.StringVar(value="Area")

        self._build_ui()
        self._apply_tree_style()
        self._start_command_server()
        self._poll_commands()
        self.after(100, self._poll_load_queue)
        self._load_project()

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # Row 0: main toolbar
        toolbar = ctk.CTkFrame(self, height=54, corner_radius=0)
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.grid_columnconfigure(5, weight=1)

        ctk.CTkLabel(toolbar, text="Project").grid(row=0, column=0, padx=(14, 8), pady=10)
        self._project_label = ctk.CTkLabel(
            toolbar,
            text=f"{GITHUB_USER} / Project #{GITHUB_PROJECT_NUMBER}",
            anchor="w",
        )
        self._project_label.grid(row=0, column=1, padx=(0, 16), pady=10, sticky="w")

        self._load_btn = ctk.CTkButton(toolbar, text="Refresh", width=100, command=self._load_project)
        self._load_btn.grid(row=0, column=2, padx=(0, 10), pady=10)

        ctk.CTkCheckBox(
            toolbar,
            text="Hide Done",
            variable=self._hide_done,
            command=self._populate_tree,
            height=30,
        ).grid(row=0, column=3, padx=8, pady=10)

        ctk.CTkLabel(toolbar, text="Search").grid(row=0, column=4, padx=(16, 8), pady=10)
        self._search_entry = ctk.CTkEntry(toolbar, textvariable=self._search_var, width=260)
        self._search_entry.grid(row=0, column=5, sticky="w", pady=10)
        self._search_entry.bind("<KeyRelease>", lambda _: self._populate_tree())

        # Row 1: filter bar
        filter_bar = ctk.CTkFrame(self, height=40, corner_radius=0, fg_color=COLORS["mantle"])
        filter_bar.grid(row=1, column=0, sticky="ew")
        _fb_font = ("Helvetica Neue", 11)
        col = 0

        ctk.CTkLabel(filter_bar, text="When:", text_color=COLORS["overlay0"], font=_fb_font).grid(
            row=0, column=col, padx=(14, 6), pady=7,
        )
        col += 1
        for when_key, when_label in [
            ("when:today",        "Today"),
            ("when:this-week",    "This Week ↓"),
            ("when:this-month",   "This Month ↓"),
            ("when:this-quarter", "This Quarter ↓"),
        ]:
            ctk.CTkCheckBox(
                filter_bar, text=when_label,
                variable=self._when_filter_vars[when_key],
                command=self._populate_tree, height=26, font=_fb_font,
            ).grid(row=0, column=col, padx=6, pady=7)
            col += 1

        ctk.CTkLabel(filter_bar, text="│", text_color=COLORS["surface0"]).grid(row=0, column=col, padx=4)
        col += 1

        ctk.CTkLabel(filter_bar, text="Phase:", text_color=COLORS["overlay0"], font=_fb_font).grid(
            row=0, column=col, padx=(6, 6), pady=7,
        )
        col += 1
        for phase_key, phase_label in [
            ("waiting", "Waiting For"),
            ("someday", "Someday"),
            ("inbox",   "Inbox"),
        ]:
            ctk.CTkCheckBox(
                filter_bar, text=phase_label,
                variable=self._phase_filter_vars[phase_key],
                command=self._populate_tree, height=26, font=_fb_font,
            ).grid(row=0, column=col, padx=6, pady=7)
            col += 1

        ctk.CTkLabel(filter_bar, text="│", text_color=COLORS["surface0"]).grid(row=0, column=col, padx=4)
        col += 1

        ctk.CTkLabel(filter_bar, text="Area:", text_color=COLORS["overlay0"], font=_fb_font).grid(
            row=0, column=col, padx=(6, 4), pady=7,
        )
        col += 1
        self._area_menu = ctk.CTkOptionMenu(
            filter_bar, variable=self._area_var, values=["All"],
            command=lambda _: self._populate_tree(), width=160, font=_fb_font,
        )
        self._area_menu.grid(row=0, column=col, padx=(0, 6), pady=7)
        col += 1

        filter_bar.grid_columnconfigure(col, weight=1)  # spacer
        col += 1

        ctk.CTkLabel(filter_bar, text="Group by:", text_color=COLORS["overlay0"], font=_fb_font).grid(
            row=0, column=col, padx=(6, 4), pady=7,
        )
        col += 1
        self._group_by_btn = ctk.CTkSegmentedButton(
            filter_bar, values=["When", "Area", "Hierarchy"],
            variable=self._group_by_var, command=lambda _: self._populate_tree(),
            font=_fb_font,
        )
        self._group_by_btn.grid(row=0, column=col, padx=(0, 14), pady=7)

        # Row 2: main panel (tree)
        panel = ctk.CTkFrame(self, corner_radius=0)
        panel.grid(row=2, column=0, sticky="nsew")
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(0, weight=1)

        self._tree = ttk.Treeview(
            panel,
            style="GTD.Treeview",
            columns=("status", "priority", "repo", "assignees", "labels"),
            show="tree headings",
            selectmode="browse",
        )
        self._tree.heading("#0", text="  Issue", anchor="w")
        self._tree.heading("status", text="Status", anchor="center")
        self._tree.heading("priority", text="Priority", anchor="center")
        self._tree.heading("repo", text="Repo", anchor="w")
        self._tree.heading("assignees", text="Assignees", anchor="w")
        self._tree.heading("labels", text="Labels", anchor="w")

        self._tree.column("#0", width=520, minwidth=280, stretch=True)
        self._tree.column("status", width=120, anchor="center", stretch=False)
        self._tree.column("priority", width=120, anchor="center", stretch=False)
        self._tree.column("repo", width=150, anchor="w", stretch=False)
        self._tree.column("assignees", width=150, anchor="w", stretch=False)
        self._tree.column("labels", width=320, anchor="w", stretch=True)

        yscroll = ttk.Scrollbar(panel, orient="vertical", command=self._tree.yview)
        xscroll = ttk.Scrollbar(panel, orient="horizontal", command=self._tree.xview)
        self._tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)

        self._tree.grid(row=0, column=0, sticky="nsew", padx=(10, 0), pady=(10, 0))
        yscroll.grid(row=0, column=1, sticky="ns", padx=(0, 10), pady=(10, 0))
        xscroll.grid(row=1, column=0, sticky="ew", padx=(10, 0), pady=(0, 10))

        self._tree.bind("<Double-1>", lambda e: self._open_issue_url(self._tree.identify_row(e.y)))
        self._tree.bind("<Return>", lambda _: self._open_issue_url(self._tree.focus()))
        self._tree.bind("<<TreeviewOpen>>", self._on_tree_open)

        status_bar = ctk.CTkFrame(self, height=32, corner_radius=0)
        status_bar.grid(row=3, column=0, sticky="ew")
        status_bar.grid_propagate(False)
        self._status = ctk.CTkLabel(status_bar, text="", anchor="w")
        self._status.pack(side="left", padx=12, fill="y")

    def _apply_tree_style(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "GTD.Treeview",
            background=COLORS["base"],
            foreground=COLORS["text"],
            rowheight=27,
            fieldbackground=COLORS["base"],
            bordercolor=COLORS["surface0"],
            relief="flat",
            font=("Menlo", 11),
        )
        style.configure(
            "GTD.Treeview.Heading",
            background=COLORS["mantle"],
            foreground=COLORS["blue"],
            font=("Helvetica Neue", 11, "bold"),
            relief="flat",
            borderwidth=0,
        )
        style.map(
            "GTD.Treeview",
            background=[("selected", COLORS["surface0"])],
            foreground=[("selected", COLORS["text"])],
        )
        self._tree.tag_configure("root", foreground=COLORS["teal"], font=("Helvetica Neue", 11, "bold"))
        self._tree.tag_configure("critical", foreground=COLORS["red"])
        self._tree.tag_configure("high", foreground=COLORS["peach"])
        self._tree.tag_configure("medium", foreground=COLORS["yellow"])
        self._tree.tag_configure("done", foreground=COLORS["overlay0"])
        self._tree.tag_configure("normal", foreground=COLORS["text"])
        self._tree.tag_configure("week_focus", foreground=COLORS["sky"], font=("Menlo", 11, "bold"))
        self._tree.tag_configure("group_header", foreground=COLORS["blue"], font=("Helvetica Neue", 12, "bold"))
        self._tree.tag_configure("message", foreground=COLORS["overlay0"], font=("Helvetica Neue", 11, "italic"))
        self._tree.tag_configure("error", foreground=COLORS["red"], font=("Helvetica Neue", 11, "bold"))
        self._tree.tag_configure("comment_group", foreground=COLORS["blue"], font=("Helvetica Neue", 11, "italic"))
        self._tree.tag_configure("comment", foreground=COLORS["overlay0"])

    def _start_command_server(self) -> None:
        cmd_queue = self._cmd_queue

        def handler(*args, **kwargs):
            return CommandHandler(cmd_queue, *args, **kwargs)

        for port in CMD_PORTS:
            try:
                server = http.server.HTTPServer(("127.0.0.1", port), handler)
                threading.Thread(target=server.serve_forever, daemon=True).start()
                self._cmd_port = port
                print(f"[project_gui] listening on http://127.0.0.1:{port}", flush=True)
                return
            except OSError:
                continue
        print("[project_gui] warning: no command server port available", flush=True)

    def _poll_commands(self) -> None:
        try:
            while True:
                cmd = self._cmd_queue.get_nowait()
                result = self._execute_command(cmd)
                cmd["_result"][0] = result
                cmd["_event"].set()
        except queue.Empty:
            pass
        self.after(100, self._poll_commands)

    def _execute_command(self, cmd: dict[str, Any]) -> dict[str, Any]:
        name = cmd.get("cmd")
        data = cmd.get("data") or {}
        try:
            if name == "status":
                return self._command_status()
            if name == "issues":
                return {"ok": True, **self._command_status(), "issues": [self._issue_summary(item) for item in self._items]}
            if name == "refresh":
                self._load_project()
                return {"ok": True, "action": "refreshing"}
            if name == "load-project":
                self._load_project()
                return {"ok": True, "action": "loading", "account": GITHUB_USER, "project_number": GITHUB_PROJECT_NUMBER}
            if name == "set-filters":
                return self._command_set_filters(data)
            if name == "find-issue":
                return self._command_find_issue(data)
            if name == "search":
                return self._command_search(data)
            if name == "context":
                return self._command_context(data)
            if name == "comments":
                return self._command_comments(data)
            if name == "latest-work-log":
                return self._command_latest_work_log(data)
            if name == "apply-change":
                return self._command_apply_change(data)
            return {"ok": False, "error": f"unknown command: {name}"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def _command_status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "source_type": "project",
            "account": GITHUB_USER,
            "project_number": GITHUB_PROJECT_NUMBER,
            "project_title": self._project_title,
            "loading": self._loading,
            "error": self._load_error,
            "issue_count": len(self._items),
            "root_count": len(self._children.get(None, [])),
            "port": self._cmd_port,
            "filters": self._current_filters(),
        }

    def _current_filters(self) -> dict[str, Any]:
        return {
            "hide_done": self._hide_done.get(),
            "search": self._search_var.get(),
            "when": [k for k, v in self._when_filter_vars.items() if v.get()],
            "phase": [k for k, v in self._phase_filter_vars.items() if v.get()],
            "area": self._area_var.get(),
            "group_by": self._group_by_var.get(),
        }

    def _command_set_filters(self, data: dict[str, Any]) -> dict[str, Any]:
        if "hide_done" in data:
            self._hide_done.set(bool(data["hide_done"]))
        if "search" in data:
            self._search_var.set(str(data["search"]))
        if "when" in data:
            active = set(data["when"] or [])
            for k, v in self._when_filter_vars.items():
                v.set(k in active)
        if "phase" in data:
            active = set(data["phase"] or [])
            for k, v in self._phase_filter_vars.items():
                v.set(k in active)
        if "area" in data:
            self._area_var.set(str(data["area"] or "All"))
        if "group_by" in data:
            val = str(data["group_by"] or "When").strip().capitalize()
            if val in ("When", "Area", "Hierarchy"):
                self._group_by_var.set(val)
        self._populate_tree()
        return {"ok": True, "filters": self._current_filters()}

    def _command_find_issue(self, data: dict[str, Any]) -> dict[str, Any]:
        issue_number = _coerce_issue_number(data.get("issue_number"))
        repo = str(data.get("repo", "") or "").strip()
        matches = self._issues_by_number(issue_number, repo=repo)
        return {"ok": True, "count": len(matches), "matches": matches}

    def _command_search(self, data: dict[str, Any]) -> dict[str, Any]:
        query_text = str(data.get("query") or "").strip().lower()
        limit = int(data.get("limit") or 10)
        if not query_text:
            return {"ok": False, "error": "query is required"}
        matches = []
        for item in self._items:
            haystack = " ".join([
                str(item.get("number") or ""),
                str(item.get("title") or ""),
                str(item.get("repo") or ""),
                " ".join(item.get("labels") or []),
                " ".join(item.get("assignees") or []),
            ]).lower()
            if query_text in haystack:
                matches.append(self._issue_summary(item))
            if len(matches) >= limit:
                break
        return {"ok": True, "query": query_text, "count": len(matches), "matches": matches}

    def _command_context(self, data: dict[str, Any]) -> dict[str, Any]:
        item = self._resolve_issue(data)
        repo = item["repo"]
        issue_number = int(item["number"])
        comment_limit = int(data.get("comments") or 5)
        client = GitHubClient()
        warnings = []
        comments = []
        all_work_logs = []
        try:
            comments = client.get_issue_comments(repo, issue_number, limit=comment_limit)
            all_work_logs = client.get_work_logs(repo, issue_number)
        except Exception as exc:
            warnings.append(f"comments unavailable: {exc}")
        latest_work_log = all_work_logs[-1] if all_work_logs else None
        if latest_work_log is None:
            warnings.append("no structured gtd_mgmt work-log found")

        issue = self._issue_summary(item, include_body=True)
        parent = self._parent_summary(item)
        children = [self._issue_summary(self._index[key]) for key in self._children.get(issue_key(item), []) if key in self._index]
        project = build_project_context(self._project_title, GITHUB_PROJECT_NUMBER, item, parent, children)
        resume_summary = build_resume_summary(issue, latest_work_log, comments, warnings)

        return {
            "ok": True,
            "repo": repo,
            "issue_number": issue_number,
            "url": issue.get("url", ""),
            "title": issue.get("title", ""),
            "state": issue.get("state", ""),
            "body": issue.get("body", ""),
            "labels": issue.get("labels", []),
            "assignees": issue.get("assignees", []),
            "project": project,
            "issue": issue,
            "parent": parent,
            "children": children,
            "recent_comments": comments,
            "latest_work_log": latest_work_log,
            "all_work_logs": all_work_logs,
            "recommended_next_action": resume_summary["next_action"],
            "resume_summary": resume_summary,
            "warnings": warnings,
        }

    def _command_comments(self, data: dict[str, Any]) -> dict[str, Any]:
        item = self._resolve_issue(data)
        limit = int(data.get("limit") or 5)
        comments = GitHubClient().get_issue_comments(item["repo"], int(item["number"]), limit=limit)
        return {"ok": True, "issue": self._issue_summary(item), "comments": comments}

    def _command_latest_work_log(self, data: dict[str, Any]) -> dict[str, Any]:
        item = self._resolve_issue(data)
        comment = GitHubClient().get_latest_work_log(item["repo"], int(item["number"]))
        return {"ok": True, "issue": self._issue_summary(item), "latest_work_log": comment}

    def _command_apply_change(self, data: dict[str, Any]) -> dict[str, Any]:
        op = str(data.get("op") or "").strip()
        params = data.get("params") or {}
        client = GitHubClient()

        if op == "create_issue":
            result = self._apply_create_issue(client, data, params)
            self._load_project()
            return {"ok": True, "op": op, **result, "refresh": "queued"}
        if op == "capture_issue":
            result = self._apply_capture_issue(client, data, params)
            self._load_project()
            return {"ok": True, "op": op, **result, "refresh": "queued"}
        if op == "bulk_organize_issues":
            result = apply_bulk_organize_issues(client, self._items, params)
            if not result["dry_run"]:
                self._load_project()
            refresh = "skipped" if result["dry_run"] else "queued"
            return {"ok": True, "op": op, **result, "refresh": refresh}

        item = self._resolve_issue(data)
        repo = item["repo"]
        issue_number = int(item["number"])

        if op == "append_work_log":
            comment = client.append_work_log(
                repo,
                issue_number,
                work_completed=str(params.get("work_completed") or ""),
                current_state=str(params.get("current_state") or ""),
                next_steps=str(params.get("next_steps") or ""),
                blockers=str(params.get("blockers") or ""),
                codex_project=str(params.get("codex_project") or ""),
                codex_project_path=str(params.get("codex_project_path") or ""),
                related_local_workspaces=str(params.get("related_local_workspaces") or ""),
                related_github_repos=str(params.get("related_github_repos") or ""),
                useful_context=str(params.get("useful_context") or ""),
            )
        elif op == "add_comment":
            body = str(params.get("body") or "").strip()
            if not body:
                return {"ok": False, "error": "params.body is required"}
            comment = client.add_issue_comment(repo, issue_number, body)
        elif op == "add_labels":
            labels = _list_param(params.get("labels"))
            if not labels:
                return {"ok": False, "error": "params.labels is required"}
            client.add_labels_to_issue(repo, issue_number, labels)
            comment = None
        elif op == "set_project_field":
            field_name = str(params.get("field_name") or "").strip()
            option_name = str(params.get("option_name") or "").strip()
            if not field_name or not option_name:
                return {"ok": False, "error": "params.field_name and params.option_name are required"}
            project = client.get_project(GITHUB_USER, GITHUB_PROJECT_NUMBER)
            client.update_project_field_by_name(project["id"], item["item_id"], project, field_name, option_name)
            comment = None
        elif op == "set_issue_parent":
            parent_issue_number = _coerce_issue_number(params.get("parent_issue_number"))
            parent_repo = str(params.get("parent_repo") or repo).strip()
            client.set_issue_parent_by_number(repo, issue_number, parent_repo, parent_issue_number)
            comment = None
        elif op == "organize_issue":
            self._apply_organize_issue(client, item, params)
            comment = None
        elif op == "update_issue_body":
            body = str(params.get("body") or "")
            client.update_issue_body(repo, issue_number, body)
            comment = None
        elif op == "close_issue":
            reason = str(params.get("reason") or "completed")
            client.close_issue(repo, issue_number, reason)
            comment = None
        else:
            return {"ok": False, "error": f"unsupported op: {op}"}
        self._load_project()
        return {"ok": True, "op": op, "issue": self._issue_summary(item), "comment": comment, "refresh": "queued"}

    def _apply_create_issue(self, client: GitHubClient, data: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        repo = str(data.get("repo") or params.get("repo") or "").strip()
        title = str(data.get("title") or params.get("title") or "").strip()
        body = str(data.get("body") or params.get("body") or "")
        labels = _list_param(data.get("labels") if "labels" in data else params.get("labels"))
        status = str(data.get("status") or params.get("status") or "Backlog").strip()
        priority = str(data.get("priority") or params.get("priority") or "").strip()
        if not repo:
            raise ValueError("repo is required")
        if not title:
            raise ValueError("title is required")

        warnings = []
        issue = client.create_issue(repo, title, body=body, labels=labels)
        project = client.get_project(GITHUB_USER, GITHUB_PROJECT_NUMBER)
        item_id = client.add_issue_to_project(project["id"], issue["node_id"])
        status_result = _try_update_project_field(client, project["id"], item_id, project, "Status", status, warnings)
        priority_result = _try_update_project_field(client, project["id"], item_id, project, "Priority", priority, warnings)
        result = {
            "issue": {
                "repo": repo,
                "number": issue.get("number"),
                "title": issue.get("title"),
                "url": issue.get("html_url"),
                "node_id": issue.get("node_id"),
                "project_item_id": item_id,
                "labels": labels,
                "status": status_result,
                "priority": priority_result,
            }
        }
        if warnings:
            result["warnings"] = warnings
        return result

    def _apply_capture_issue(self, client: GitHubClient, data: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        repo = str(data.get("repo") or params.get("repo") or "").strip()
        title = str(data.get("title") or params.get("title") or "").strip()
        body = build_capture_issue_body(
            body=str(data.get("body") or params.get("body") or ""),
            next_action=str(data.get("next_action") or params.get("next_action") or ""),
            waiting_for=str(data.get("waiting_for") or params.get("waiting_for") or ""),
            source_text=str(data.get("source_text") or params.get("source_text") or ""),
            source_label=str(data.get("source_label") or params.get("source_label") or ""),
        )
        labels = _list_param(data.get("labels") if "labels" in data else params.get("labels"))
        status = str(data.get("status") or params.get("status") or "Backlog").strip()
        priority = str(data.get("priority") or params.get("priority") or "").strip()
        parent_number = data.get("parent_issue_number") if "parent_issue_number" in data else params.get("parent_issue_number")
        parent_repo = str(data.get("parent_repo") or params.get("parent_repo") or repo).strip()
        if not repo:
            raise ValueError("repo is required")
        if not title:
            raise ValueError("title is required")

        warnings = []
        issue = client.create_issue(repo, title, body=body, labels=labels)
        project = client.get_project(GITHUB_USER, GITHUB_PROJECT_NUMBER)
        item_id = client.add_issue_to_project(project["id"], issue["node_id"])
        status_result = _try_update_project_field(client, project["id"], item_id, project, "Status", status, warnings)
        priority_result = _try_update_project_field(client, project["id"], item_id, project, "Priority", priority, warnings)
        parent = _try_set_issue_parent(client, repo, int(issue["number"]), parent_repo, parent_number, warnings)

        result = {
            "issue": {
                "repo": repo,
                "number": issue.get("number"),
                "title": issue.get("title"),
                "url": issue.get("html_url"),
                "node_id": issue.get("node_id"),
                "project_item_id": item_id,
                "labels": labels,
                "status": status_result,
                "priority": priority_result,
                "parent": parent,
            }
        }
        if warnings:
            result["warnings"] = warnings
        return result

    def _apply_organize_issue(self, client: GitHubClient, item: dict[str, Any], params: dict[str, Any]) -> None:
        repo = item["repo"]
        issue_number = int(item["number"])
        labels = _list_param(params.get("labels"))
        if labels:
            client.add_labels_to_issue(repo, issue_number, labels)

        project = None
        status = str(params.get("status") or "").strip()
        priority = str(params.get("priority") or "").strip()
        if status or priority:
            project = client.get_project(GITHUB_USER, GITHUB_PROJECT_NUMBER)
        if status:
            client.update_project_field_by_name(project["id"], item["item_id"], project, "Status", status)
        if priority:
            client.update_project_field_by_name(project["id"], item["item_id"], project, "Priority", priority)

        parent_number = params.get("parent_issue_number")
        if parent_number not in (None, ""):
            parent_issue_number = _coerce_issue_number(parent_number)
            parent_repo = str(params.get("parent_repo") or repo).strip()
            client.set_issue_parent_by_number(repo, issue_number, parent_repo, parent_issue_number)

    def _load_project(self) -> None:
        if self._loading:
            return
        self._loading = True
        self._load_error = ""
        self._load_btn.configure(state="disabled")
        self._set_status(f"Loading {GITHUB_USER} Project #{GITHUB_PROJECT_NUMBER}...")
        self._clear_tree()
        self._show_tree_message("  Loading project items...")

        threading.Thread(target=self._load_project_background, daemon=True).start()

    def _load_project_background(self) -> None:
        try:
            client = GitHubClient()
            project = client.get_project(GITHUB_USER, GITHUB_PROJECT_NUMBER)
            raw_items = client.get_all_items(project["id"])
            items = [client.parse_item(node) for node in raw_items if node]
            items = [item for item in items if item]
            self._load_queue.put(("loaded", (project["title"], items)))
        except Exception as exc:
            self._load_queue.put(("error", str(exc)))

    def _poll_load_queue(self) -> None:
        try:
            while True:
                event, payload = self._load_queue.get_nowait()
                if event == "loaded":
                    project_title, items = payload
                    self._set_loaded(project_title, items)
                elif event == "error":
                    self._set_load_error(str(payload))
                elif event == "comments":
                    item_id, comments = payload
                    self._set_comments_loaded(item_id, comments)
                elif event == "comments_error":
                    item_id, message = payload
                    self._set_comments_error(item_id, str(message))
        except queue.Empty:
            pass
        self.after(100, self._poll_load_queue)

    def _set_loaded(self, project_title: str, items: list[dict[str, Any]]) -> None:
        self._loading = False
        self._load_btn.configure(state="normal")
        self._project_title = project_title
        self._items = items
        self._index, self._children = build_issue_tree(items)
        self._project_label.configure(text=f"{GITHUB_USER} / {project_title} / Project #{GITHUB_PROJECT_NUMBER}")
        self._refresh_area_options()
        self._populate_tree()

    def _set_load_error(self, message: str) -> None:
        self._loading = False
        self._load_error = message
        self._load_btn.configure(state="normal")
        self._clear_tree()
        self._show_tree_message(f"  Error loading project: {message}", tag="error")
        self._set_status(f"Error: {message}", error=True)

    def _refresh_area_options(self) -> None:
        areas = sorted({
            _root_title_for(k, self._index, self._children)
            for k in self._index
        } - {""})
        options = ["All"] + areas
        self._area_menu.configure(values=options)
        if self._area_var.get() not in options:
            self._area_var.set("All")

    def _populate_tree(self) -> None:
        self._clear_tree()
        if not self._items:
            self._show_tree_message("  No issues loaded.")
            self._set_status("No issues loaded.")
            return
        group_by = self._group_by_var.get()
        if group_by == "When":
            self._populate_tree_by_when()
        elif group_by == "Area":
            self._populate_tree_by_area()
        else:
            self._populate_tree_by_hierarchy()

    def _populate_tree_by_hierarchy(self) -> None:
        context_keys = self._visible_hierarchy_keys()
        visible_roots = 0
        visible_nodes = len(context_keys)
        for key in self._children.get(None, []):
            inserted = self._insert_node(key, "", depth=0, context_keys=context_keys)
            if inserted:
                visible_roots += 1
        self._set_status(
            f"Loaded {len(self._items)} issues from {self._project_title or 'project'}; "
            f"showing {visible_nodes} issues across {visible_roots} root trees."
        )
        if visible_nodes == 0:
            self._show_tree_message("  No issues match the current filters.")

    def _populate_tree_by_when(self) -> None:
        HORIZONS = [
            ("when:today",        "Today"),
            ("when:this-week",    "This Week"),
            ("when:this-month",   "This Month"),
            ("when:this-quarter", "This Quarter"),
        ]
        groups: dict[str, set[IssueKey]] = {k: set() for k, _ in HORIZONS}
        for key, item in self._index.items():
            when = _item_when(item)
            if when not in groups:
                continue
            if self._is_visible_grouped(key, item):
                groups[when].add(key)

        total = 0
        for when_key, label in HORIZONS:
            context_keys = self._context_keys_for(groups[when_key])
            if not context_keys:
                continue
            total += len(context_keys)
            header_id = self._tree.insert(
                "", "end",
                text=f"  {label}  ({len(context_keys)})",
                values=("", "", "", "", ""),
                tags=("group_header",),
                open=True,
            )
            for root_key in self._children.get(None, []):
                self._insert_node(root_key, header_id, depth=0, context_keys=context_keys)

        self._set_status(f"Showing {total} issue rows grouped by When horizon.")
        if total == 0:
            self._show_tree_message("  No items match the current filters.")

    def _populate_tree_by_area(self) -> None:
        area_groups: dict[str, set[IssueKey]] = {}
        for key, item in self._index.items():
            if not self._is_visible_grouped(key, item):
                continue
            area = _root_title_for(key, self._index, self._children)
            area_groups.setdefault(area or "(No Area)", set()).add(key)

        total = 0
        for area in sorted(area_groups):
            context_keys = self._context_keys_for(area_groups[area])
            if not context_keys:
                continue
            total += len(context_keys)
            header_id = self._tree.insert(
                "", "end",
                text=f"  {area}  ({len(context_keys)})",
                values=("", "", "", "", ""),
                tags=("group_header",),
                open=True,
            )
            for root_key in self._children.get(None, []):
                root_area = _root_title_for(root_key, self._index, self._children) or "(No Area)"
                if root_area == area:
                    self._insert_node(root_key, header_id, depth=0, context_keys=context_keys)

        self._set_status(f"Showing {total} issue rows grouped by Area.")
        if total == 0:
            self._show_tree_message("  No items match the current filters.")

    def _is_visible_grouped(self, key: IssueKey, item: dict[str, Any]) -> bool:
        """Visibility check for grouped modes — no child bubble-up."""
        if self._hide_done.get() and _is_done_item(item):
            return False
        query = self._search_var.get().strip().lower()
        if query and not (
            query in str(item.get("title") or "").lower()
            or query in str(item.get("number") or "")
            or query in " ".join(item.get("labels") or []).lower()
            or query in str(item.get("repo") or "").lower()
        ):
            return False
        active_whens = {k for k, v in self._when_filter_vars.items() if v.get()}
        if active_whens:
            max_order = max(WHEN_ORDER.get(h, 9) for h in active_whens)
            if WHEN_ORDER.get(_item_when(item), 9) > max_order:
                return False
        checked_phases = {k for k, v in self._phase_filter_vars.items() if v.get()}
        if checked_phases:
            phase = _item_phase(key, item, self._index, self._children)
            if phase not in checked_phases:
                return False
        area = self._area_var.get()
        if area and area != "All":
            if _root_title_for(key, self._index, self._children) != area:
                return False
        return True

    def _insert_node(
        self,
        key: IssueKey,
        parent_id: str,
        depth: int,
        context_keys: set[IssueKey] | None = None,
    ) -> bool:
        if context_keys is None:
            context_keys = self._visible_hierarchy_keys()
        if key not in context_keys:
            return False

        item = self._index[key]
        item_id = self._tree.insert(
            parent_id,
            "end",
            text=f"#{item['number']}  {item['title']}",
            values=(
                item.get("status") or "-",
                item.get("priority") or "-",
                _short_repo(item.get("repo", "")),
                ", ".join(item.get("assignees") or []) or "-",
                ", ".join(item.get("labels") or []) or "-",
            ),
            tags=(self._tag_for(item, depth),),
            open=(depth <= 1),
        )
        if item.get("url"):
            self._item_urls[item_id] = item["url"]
        self._item_keys[item_id] = key

        comments_id = self._tree.insert(
            item_id,
            "end",
            text="Latest comments",
            values=("", "", "", "", "expand"),
            tags=("comment_group",),
            open=False,
        )
        self._comment_group_keys[comments_id] = key
        self._tree.insert(comments_id, "end", text="  Expand to load latest comments", tags=("message",))

        for child_key in self._children.get(key, []):
            self._insert_node(child_key, item_id, depth + 1, context_keys=context_keys)
        return True

    def _is_visible(self, key: IssueKey) -> bool:
        return key in self._visible_hierarchy_keys()

    def _visible_hierarchy_keys(self) -> set[IssueKey]:
        matching_keys = {
            key
            for key, item in self._index.items()
            if self._is_visible_grouped(key, item)
        }
        return self._context_keys_for(matching_keys)

    def _context_keys_for(self, matching_keys: set[IssueKey]) -> set[IssueKey]:
        context_keys: set[IssueKey] = set()
        for key in matching_keys:
            context_keys.update(self._ancestor_keys(key))
            context_keys.update(self._descendant_keys(key))
        return context_keys

    def _ancestor_keys(self, key: IssueKey) -> set[IssueKey]:
        keys: set[IssueKey] = set()
        seen: set[IssueKey] = set()
        cur = key
        while cur not in seen and cur in self._index:
            seen.add(cur)
            keys.add(cur)
            pkey = parent_key(self._index[cur])
            if pkey is None or pkey not in self._index:
                break
            cur = pkey
        return keys

    def _descendant_keys(self, key: IssueKey) -> set[IssueKey]:
        keys: set[IssueKey] = set()
        visiting: set[IssueKey] = set()

        def visit(cur: IssueKey) -> bool:
            if cur in visiting or cur not in self._index:
                return False
            visiting.add(cur)
            has_displayed_child = False
            for child_key in self._children.get(cur, []):
                has_displayed_child = visit(child_key) or has_displayed_child
            visiting.remove(cur)

            hide_done_leaf = self._hide_done.get() and _is_done_item(self._index[cur]) and not has_displayed_child
            if cur == key or not hide_done_leaf:
                keys.add(cur)
                return True
            return False

        visit(key)
        return keys

    def _tag_for(self, item: dict[str, Any], depth: int) -> str:
        if _is_done_item(item):
            return "done"
        if _item_when(item) == "when:this-week":
            return "week_focus"
        priority = item.get("priority")
        if priority == "P1-Critical":
            return "critical"
        if priority == "P2-High":
            return "high"
        if priority == "P3-Medium":
            return "medium"
        if depth == 0:
            return "root"
        return "normal"

    def _clear_tree(self) -> None:
        self._item_urls = {}
        self._item_keys = {}
        self._comment_group_keys = {}
        self._loaded_comment_groups = set()
        for item_id in self._tree.get_children():
            self._tree.delete(item_id)

    def _show_tree_message(self, message: str, *, tag: str = "message") -> None:
        self._tree.insert("", "end", text=message, values=("", "", "", "", ""), tags=(tag,))

    def _open_issue_url(self, item_id: str) -> None:
        url = self._item_urls.get(item_id)
        if url:
            webbrowser.open(url)

    def _on_tree_open(self, _event: tk.Event) -> None:
        item_id = self._tree.focus()
        if item_id not in self._comment_group_keys or item_id in self._loaded_comment_groups:
            return
        key = self._comment_group_keys[item_id]
        item = self._index.get(key)
        if not item:
            return
        self._loaded_comment_groups.add(item_id)
        for child_id in self._tree.get_children(item_id):
            self._tree.delete(child_id)
        self._tree.insert(item_id, "end", text="  Loading latest comments...", tags=("message",))
        threading.Thread(target=self._load_comments_background, args=(item_id, item), daemon=True).start()

    def _load_comments_background(self, item_id: str, item: dict[str, Any]) -> None:
        try:
            comments = GitHubClient().get_issue_comments(item["repo"], int(item["number"]), limit=3)
            self._load_queue.put(("comments", (item_id, comments)))
        except Exception as exc:
            self._load_queue.put(("comments_error", (item_id, str(exc))))

    def _set_comments_loaded(self, item_id: str, comments: list[dict[str, Any]]) -> None:
        if not self._tree.exists(item_id):
            return
        for child_id in self._tree.get_children(item_id):
            self._tree.delete(child_id)
        if not comments:
            self._tree.insert(item_id, "end", text="  No recent comments.", tags=("message",))
            return
        for comment in reversed(comments):
            text = _comment_tree_text(comment)
            row_id = self._tree.insert(
                item_id,
                "end",
                text=f"  {text}",
                values=("", "", "", comment.get("author") or "", comment.get("updated_at") or ""),
                tags=("comment",),
            )
            if comment.get("url"):
                self._item_urls[row_id] = comment["url"]

    def _set_comments_error(self, item_id: str, message: str) -> None:
        if not self._tree.exists(item_id):
            return
        for child_id in self._tree.get_children(item_id):
            self._tree.delete(child_id)
        self._tree.insert(item_id, "end", text=f"  Error loading comments: {message}", tags=("error",))

    def _copy_to_clipboard(self, value: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(value)
        self._set_status("Copied to clipboard.")

    def _set_status(self, message: str, *, error: bool = False) -> None:
        print(f"[project_gui] {message}", flush=True)
        self._status.configure(text=message, text_color=COLORS["red"] if error else COLORS["text"])

    def _resolve_issue(self, data: dict[str, Any]) -> dict[str, Any]:
        issue_number = _coerce_issue_number(data.get("issue_number"))
        repo = str(data.get("repo", "") or "").strip()
        matches = [
            item for item in self._items
            if int(item.get("number") or 0) == issue_number and _repo_matches(str(item.get("repo") or ""), repo)
        ]
        if not matches:
            raise ValueError(f"issue #{issue_number} not found in loaded project")
        if len(matches) > 1:
            options = "; ".join(f"{item['repo']} #{item['number']} {item['title']}" for item in matches)
            raise ValueError(f"issue #{issue_number} is ambiguous; pass repo. Matches: {options}")
        return matches[0]

    def _issues_by_number(self, number: int, *, repo: str = "") -> list[dict[str, Any]]:
        return [
            self._issue_summary(item)
            for item in self._items
            if int(item.get("number") or 0) == number and _repo_matches(str(item.get("repo") or ""), repo)
        ]

    def _issue_summary(self, item: dict[str, Any], *, include_body: bool = False) -> dict[str, Any]:
        summary = {
            "repo": item.get("repo") or "",
            "number": item.get("number"),
            "issue_number": item.get("number"),
            "title": item.get("title") or "",
            "url": item.get("url") or "",
            "state": item.get("state") or "",
            "status": item.get("status") or "",
            "priority": item.get("priority") or "",
            "labels": item.get("labels") or [],
            "assignees": item.get("assignees") or [],
            "parent": item.get("parent"),
            "parent_repo": item.get("parent_repo") or "",
            "fields": item.get("fields") or {},
        }
        if include_body:
            summary["body"] = item.get("body") or ""
        return summary

    def _parent_summary(self, item: dict[str, Any]) -> dict[str, Any] | None:
        pkey = parent_key(item)
        if pkey and pkey in self._index:
            return self._issue_summary(self._index[pkey])
        parent = item.get("parent")
        if not parent:
            return None
        return {
            "repo": item.get("parent_repo") or item.get("repo") or "",
            "number": parent[0],
            "issue_number": parent[0],
            "title": parent[1],
        }


def _short_repo(repo: str) -> str:
    return repo.split("/", 1)[1] if "/" in repo else repo


def _repo_matches(item_repo: str, query_repo: str) -> bool:
    """Return True if query_repo matches item_repo, accepting either the full
    'owner/repo' form or just the 'repo' name."""
    if not query_repo:
        return True
    return item_repo == query_repo or _short_repo(item_repo) == _short_repo(query_repo)


def build_project_context(
    project_title: str,
    project_number: int,
    item: dict[str, Any],
    parent: dict[str, Any] | None,
    children: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the Project/GTD state block returned by issue resume context."""
    return {
        "title": project_title,
        "number": project_number,
        "status": item.get("status") or None,
        "priority": item.get("priority") or None,
        "parent": parent,
        "children": children,
        "fields": item.get("fields") or {},
    }


def build_resume_summary(
    issue: dict[str, Any],
    latest_work_log: dict[str, Any] | None,
    recent_comments: list[dict[str, Any]],
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """Build a compact human-ready resume summary from issue context."""
    parsed = (latest_work_log or {}).get("parsed") or {}
    current_state = parsed.get("current_state") or []
    next_steps = parsed.get("next_steps") or []
    blockers = parsed.get("blockers_open_questions") or []

    where_we_left_off = _first_nonempty(current_state)
    if not where_we_left_off:
        where_we_left_off = _first_nonempty(parsed.get("work_completed") or [])
    if not where_we_left_off:
        where_we_left_off = _first_comment_line(recent_comments)
    if not where_we_left_off:
        where_we_left_off = _first_body_line(issue.get("body") or "")
    if not where_we_left_off:
        where_we_left_off = "No resume details documented yet."

    next_action = _first_nonempty(next_steps)
    if not next_action:
        next_action = "Review the issue body and recent comments to identify the next action."

    return {
        "where_we_left_off": where_we_left_off,
        "next_action": next_action,
        "blockers": blockers,
        "source": "latest_work_log" if latest_work_log else "issue_context",
        "warnings": list(warnings or []),
    }


def _first_nonempty(values: list[str]) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _first_comment_line(comments: list[dict[str, Any]]) -> str:
    for comment in reversed(comments):
        line = _first_body_line(comment.get("body") or "")
        if line:
            return line
    return ""


def _first_body_line(body: str) -> str:
    for raw_line in (body or "").splitlines():
        line = raw_line.strip()
        if line:
            return line
    return ""


def _coerce_issue_number(value: Any) -> int:
    raw = str(value or "").strip().lstrip("#")
    if not raw.isdigit():
        raise ValueError("issue_number must be an integer")
    return int(raw)


def _comment_tree_text(comment: dict[str, Any]) -> str:
    author = comment.get("author") or "unknown"
    updated = (comment.get("updated_at") or comment.get("created_at") or "")[:10]
    first_line = " ".join((comment.get("body") or "").strip().split())
    if len(first_line) > 140:
        first_line = first_line[:137] + "..."
    return f"{updated} {author}: {first_line or '(empty comment)'}"


def _list_param(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return [str(part).strip() for part in value if str(part).strip()]


def build_capture_issue_body(
    body: str = "",
    next_action: str = "",
    waiting_for: str = "",
    source_text: str = "",
    source_label: str = "",
) -> str:
    """Build an issue body for captured GTD source material."""
    body = (body or "").strip()
    next_action = (next_action or "").strip()
    waiting_for = (waiting_for or "").strip()
    source_text = (source_text or "").strip()
    source_label = (source_label or "").strip()

    if not any((body, next_action, waiting_for, source_text, source_label)):
        return ""
    if body and not any((next_action, waiting_for, source_text, source_label)):
        return body

    sections = ["GTD capture item."]
    if next_action:
        sections.extend(["", "## Next Action", next_action])
    if waiting_for:
        sections.extend(["", "## Waiting For", waiting_for])
    if body:
        sections.extend(["", "## Context", body])
    if source_text or source_label:
        sections.extend(["", "## Source", source_label or "Captured source"])
        if source_text:
            sections.extend(["", "```text", source_text, "```"])
    return "\n".join(sections)


def _try_update_project_field(
    client: GitHubClient,
    project_id: str,
    item_id: str,
    project: dict,
    field_name: str,
    option_name: str,
    warnings: list[str],
) -> dict[str, str]:
    if not option_name:
        return {"requested": "", "result": "skipped"}
    try:
        client.update_project_field_by_name(project_id, item_id, project, field_name, option_name)
        return {"requested": option_name, "result": "ok"}
    except Exception as exc:
        message = f"{field_name} skipped: {exc}"
        warnings.append(message)
        return {"requested": option_name, "result": "skipped", "error": str(exc)}


def _try_set_issue_parent(
    client: GitHubClient,
    repo: str,
    issue_number: int,
    parent_repo: str,
    parent_issue_number: Any,
    warnings: list[str],
) -> dict[str, Any] | None:
    if parent_issue_number in (None, ""):
        return None
    try:
        coerced_parent_number = _coerce_issue_number(parent_issue_number)
        client.set_issue_parent_by_number(repo, issue_number, parent_repo, coerced_parent_number)
        return {"repo": parent_repo, "issue_number": coerced_parent_number, "result": "ok"}
    except Exception as exc:
        message = f"Parent skipped: {exc}"
        warnings.append(message)
        result = {"repo": parent_repo, "result": "skipped", "error": str(exc)}
        try:
            result["issue_number"] = _coerce_issue_number(parent_issue_number)
        except Exception:
            result["issue_number"] = parent_issue_number
        return result


def normalize_issue_ref(value: dict[str, Any]) -> tuple[str, int]:
    """Normalize a bulk operation item into (repo, issue_number)."""
    if not isinstance(value, dict):
        raise ValueError("item must be an object")
    repo = str(value.get("repo") or "").strip()
    if not repo:
        raise ValueError("item.repo is required")
    issue_number = _coerce_issue_number(value.get("issue_number") or value.get("number"))
    return repo, issue_number


def build_bulk_organize_plan(items: list[dict[str, Any]], loaded_items: list[dict[str, Any]], params: dict[str, Any]) -> dict:
    """Build a dry-run plan for bulk issue organization."""
    labels = _list_param(params.get("labels"))
    status = str(params.get("status") or "").strip()
    priority = str(params.get("priority") or "").strip()
    parent_issue_number = params.get("parent_issue_number")
    parent_repo = str(params.get("parent_repo") or "").strip()
    parent_number = None if parent_issue_number in (None, "") else _coerce_issue_number(parent_issue_number)
    loaded_index = {
        (str(item.get("repo") or ""), int(item.get("number") or 0)): item
        for item in loaded_items
        if item.get("repo") and item.get("number")
    }

    plan = []
    failed = []
    seen = set()
    for raw_item in items:
        try:
            repo, issue_number = normalize_issue_ref(raw_item)
            key = (repo, issue_number)
            if key in seen:
                failed.append({"repo": repo, "issue_number": issue_number, "error": "duplicate item"})
                continue
            seen.add(key)
            loaded = loaded_index.get(key)
            if not loaded:
                failed.append({"repo": repo, "issue_number": issue_number, "error": "issue not found in loaded project"})
                continue
            plan.append({
                "repo": repo,
                "issue_number": issue_number,
                "title": loaded.get("title", ""),
                "project_item_id": loaded.get("item_id", ""),
                "labels": labels,
                "status": status,
                "priority": priority,
                "parent": (
                    {
                        "repo": parent_repo or repo,
                        "issue_number": parent_number,
                    }
                    if parent_number is not None
                    else None
                ),
            })
        except Exception as exc:
            failed.append({"item": raw_item, "error": str(exc)})

    return {
        "count": len(items),
        "planned": plan,
        "failed": failed,
    }


def apply_bulk_organize_issues(client: GitHubClient, loaded_items: list[dict[str, Any]], params: dict[str, Any]) -> dict:
    """Dry-run or apply labels, project fields, and parent moves across issues."""
    raw_items = params.get("items") or []
    if not isinstance(raw_items, list):
        raise ValueError("params.items must be a list")
    if not raw_items:
        return {"dry_run": bool(params.get("dry_run", True)), "count": 0, "planned": [], "updated": [], "failed": []}

    dry_run = bool(params.get("dry_run", True))
    plan_result = build_bulk_organize_plan(raw_items, loaded_items, params)
    if dry_run:
        return {"dry_run": True, **plan_result, "updated": []}

    project = None
    needs_project = any(item.get("status") or item.get("priority") for item in plan_result["planned"])
    if needs_project:
        project = client.get_project(GITHUB_USER, GITHUB_PROJECT_NUMBER)

    updated = []
    failed = list(plan_result["failed"])
    for item in plan_result["planned"]:
        result = {
            "repo": item["repo"],
            "issue_number": item["issue_number"],
            "title": item["title"],
            "labels": "skipped",
            "status": "skipped",
            "priority": "skipped",
            "parent": "skipped",
        }
        try:
            if item["labels"]:
                client.add_labels_to_issue(item["repo"], item["issue_number"], item["labels"])
                result["labels"] = "ok"
            if item["status"]:
                client.update_project_field_by_name(project["id"], item["project_item_id"], project, "Status", item["status"])
                result["status"] = "ok"
            if item["priority"]:
                client.update_project_field_by_name(project["id"], item["project_item_id"], project, "Priority", item["priority"])
                result["priority"] = "ok"
            if item["parent"]:
                client.set_issue_parent_by_number(
                    item["repo"],
                    item["issue_number"],
                    item["parent"]["repo"],
                    item["parent"]["issue_number"],
                )
                result["parent"] = "ok"
            updated.append(result)
        except Exception as exc:
            result["error"] = str(exc)
            failed.append(result)

    return {
        "dry_run": False,
        "count": len(raw_items),
        "updated": updated,
        "failed": failed,
    }


def diagnose() -> None:
    client = GitHubClient()
    project = client.get_project(GITHUB_USER, GITHUB_PROJECT_NUMBER)
    raw_items = client.get_all_items(project["id"])
    items = [client.parse_item(node) for node in raw_items if node]
    items = [item for item in items if item]
    index, children = build_issue_tree(items)

    print(f"Project: {GITHUB_USER} / {project['title']} / #{GITHUB_PROJECT_NUMBER}")
    print(f"Raw project items: {len(raw_items)}")
    print(f"Issue items: {len(items)}")
    print(f"Root issue trees: {len(children.get(None, []))}")
    print(f"Indexed issues: {len(index)}")


def run() -> None:
    app = ProjectIssueGui()
    app.mainloop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GTD Project issue tree GUI")
    parser.add_argument("--diagnose", action="store_true", help="Fetch project issues and print tree counts without opening the GUI")
    args = parser.parse_args()

    if args.diagnose:
        diagnose()
    else:
        run()
