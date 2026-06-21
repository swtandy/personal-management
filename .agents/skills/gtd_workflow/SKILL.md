---
name: gtd_workflow
description: Use when the user wants Codex to help run a Getting Things Done workflow for Scott T's personal management, including capture, clarify, organize, reflect, engage, choosing next actions, reviewing projects, identifying waiting-for items, and mapping personal life areas into GitHub issue structure. Use gtd_mgmt when GitHub Project or issue reads/writes are needed.
---

# gtd_workflow

Use this skill as the operating model for Scott's GTD system. It decides what work means, where it belongs, and what the next action should be. Use `gtd_mgmt` for GitHub issue mechanics when available.

## Skill Family

- `gtd_workflow`: GTD method, planning, review, triage, next-action decisions, responsibility taxonomy.
- `gtd_mgmt`: GitHub Project/issue search, context reads, labels/fields, work logs, GUI/MCP operations.

When issue state must be read or written, use `gtd_mgmt` if it is available. If it is not available, proceed with a manual workflow recommendation and tell the user what issue update should be made.

## GTD Workflow

Use the five GTD steps:

1. **Capture**: collect everything that has the user's attention into an inbox without over-organizing it.
2. **Clarify**: decide what each item means and whether it is actionable.
3. **Organize**: put the item into the right bucket: project, next action, waiting for, someday/maybe, reference, or trash.
4. **Reflect**: review the system for stale work, missing next actions, blockers, priorities, and commitments.
5. **Engage**: help the user choose the next concrete action based on context, time, energy, priority, and dependencies.

## GTD Object Model

- **Area of Focus**: an ongoing responsibility, not finishable by itself.
- **Project**: a desired outcome that takes more than one action.
- **Next Action**: the next visible, physical, concrete action that moves a project forward.
- **Waiting For**: an external dependency or delegated outcome.
- **Someday/Maybe**: potentially valuable work intentionally deferred.
- **Reference**: useful non-actionable information.
- **Project Support**: plans, notes, decisions, links, constraints, and context that help execute a project.

Use outcome-oriented names for projects:

- Good: `Publish 2026 Platform Support Plan`
- Weak: `Platform Support`

Every active project should have at least one next action or a documented waiting-for item.

## Scott T Areas Of Focus

- **Home And Property** (#71): the deck at 85 Joaquin Road, home maintenance, repairs, garden, and all physical property work.
- **Workshop And Making** (#72): woodworking, tools, and fabrication projects (grinder cart, bandsaw, etc.).
- **Health And Wellbeing** (#73): medical, eye care, fitness, diet, and mental health.
- **Travel And Leisure** (#74): vacations, timeshares (Westin Maui), trips, events, and recreational activities.
- **Career And Finance** (#75): professional work, skills, learning, budgeting, investments, taxes, and estate planning.
- **Relationships And Social** (#76): family, friends, community, and social commitments.

Most projects live under exactly one Area root. Domain is inferred from the root title — no label needed. Note cross-cutting work in the issue body or comments.

## Recommended GitHub Shape

Use hierarchy for orientation and labels for scheduling only:

```text
[Scott T] <Area of Focus>          ← Area roots (parent = null)
  Project / Desired Outcome
    Deliverable / Task
      gtd_mgmt session work logs
```

The project has Area root issues + **`[Scott T] Inbox`** (issue #70).

### Label scheme — 6 labels, 2 namespaces

```text
when:today        Act today             — review daily
when:this-week    This week             — review weekly
when:this-month   This month            — review monthly
when:this-quarter This quarter          — review quarterly

gtd:waiting-for   Blocked on external dependency
gtd:someday-maybe Deliberately deferred
```

Assign the **tightest** applicable `when:` horizon — one value per item.  
**Priority (P1–P4)** is a sort tie-breaker within a horizon, not a primary scheduling axis.

### Derived attributes — no labels needed

| Attribute | Derived from |
|---|---|
| **Domain / Area** | Title of the root ancestor issue |
| **Inbox** (untriaged) | Root is `[Scott T] Inbox` (#70) |
| **Project** | Issue has sub-issues |
| **Done** | Issue is closed |
| **Next Action** | Open leaf with a `when:` label, not `waiting-for`/`someday-maybe` |

### Capture and triage

New issues captured via `capture_issue` default under **`[Scott T] Inbox` (#70)**.  
Triage = re-parent from Inbox to the correct Area root. Domain is then derived automatically.

## Common Workflows

### Cross-Project Resume Handoff

Use this workflow when Scott wants to resume work on a specific GTD issue in a
separate Codex project/workspace.

1. Identify the exact source issue, preferably as `owner/repo#123`.
2. Use `gtd_mgmt` to read the issue context and latest structured work log.
3. Treat the structured `latest_work_log.parsed` data as the primary "where I
   left off" memory. Fall back to issue body, recent comments, and Project
   fields only when no structured work log exists.
4. Produce a Markdown workdown/handoff file for the target Codex project. Prefer
   `gtd_mgmt.create_resume_handoff` when available.
5. Highlight which Codex project/workspace Scott should switch to. If the target
   project cannot be resolved confidently, say so and ask Scott to choose.
6. Make the handoff file self-directing and support two modes:
   - **Orientation-only mode**: a pasteable prompt Scott can put into any Codex
     chat to decide which Codex application project should be used. This prompt
     must explicitly prohibit implementation, target-repo inspection, tests,
     edits, handoff creation, and GitHub updates. It should ask Codex to return
     only the recommended Codex app project name, Codex app project path,
     confidence, and reason, using the `Recommended Codex Project` section as
     the canonical source when present. Related local workspaces and GitHub repos
     should be returned only as supporting context.
   - **Execution-after-switch mode**: a separate pasteable prompt Scott can use
     only after switching to the recommended Codex app project. This prompt must
     orient Codex to the Recommended Codex Project, Related Local Workspaces,
     Related GitHub Repositories, source issue, latest work log, blockers, and
     End-Of-Session section before any implementation. It may tell Codex to
     inspect only enough local repository state to understand the current working
     context, but it must prohibit edits, broad tests, commits, handoff creation,
     and GitHub updates during orientation. It must tell Codex to stop after
     orientation, summarize workspace/repo state and next-step options, recommend
     a plan, and align with Scott before implementation work.
   The file must then include the next action, blockers, and end-of-session GTD
   update instructions.
7. Make clear that the generated Markdown is already the handoff. If the source
   issue's latest next action says to create a handoff, the target thread should
   not create another handoff unless Scott explicitly asks; it should continue
   the underlying project work or fix the handoff tooling itself.
8. Creating a handoff automatically promotes the issue to `when:this-week` (promote-only — skipped if already `when:today`). During resume, do not make other GitHub issue updates unless Scott explicitly asks.
   The target project thread should return `append_work_log` fields for Scott or
   the originating GTD thread to apply. Include `codex_project` with the Codex
   app project name/container and `codex_project_path` with the Codex app project
   path. Keep related local workspaces and GitHub repos in separate fields.

The orientation-only prompt should look like:

```text
Use gtd_workflow and gtd_mgmt only to decide which Codex application project Scott should use for owner/repo#123. Do not start implementation, inspect or edit repositories, run tests, create another handoff, or update GitHub. Codex project means the project name/container in the Codex application, not a GitHub repo and not merely a source checkout. Use only the "Recommended Codex Project" section for the Codex project answer. Return exactly: Recommended Codex project: <codex_project>; Codex project path: <codex_project_path>; Confidence: <confidence>; Reason: <reason>.
```

The execution-after-switch prompt should look like:

```text
Use this handoff/workdown context to orient yourself to owner/repo#123. You are now in the recommended Codex application project, but the actual implementation work may live in one or more related local workspaces or GitHub repositories listed later in this handoff. First, read the handoff sections in this order: Recommended Codex Project, Related Local Workspaces, Related GitHub Repositories, Source Issue, Where We Left Off, Next Action, Blockers / Open Questions, Latest Structured Work Log, and End-Of-Session GTD Update. Then inspect only enough local repository state to understand the current working context: current directories, git status, branch, remotes, and relevant files in the listed related local workspaces. Do not edit files, run broad tests, create commits, create another handoff, or update GitHub during orientation. After orientation, stop and summarize the coordinating Codex app project, implementation workspace(s), GitHub repo(s), current repo state, possible next actions, and your recommended plan. Your first step after orientation is to align with Scott on the plan. Ask for confirmation before implementation work or GTD/GitHub updates.
```

The workdown file must also tell the target project thread which GTD issue to
prepare an update for when the work session ends and what `append_work_log`
fields to return, including the local `codex_project` path used by the work
session.

### Capture

When the user gives a raw thought, meeting note, request, or interruption:

1. Restate it briefly.
2. Decide if it is actionable now, needs clarification, or is reference.
3. Suggest the likely domain.
4. If using issues, create or update an inbox issue via `gtd_mgmt`.

### Clarify

For each inbox item, ask:

- What is the desired outcome?
- Is there a concrete next action?
- Is this waiting on someone or something?
- Does it belong to an existing project?
- Is it worth doing now, later, or not at all?

### Organize

Map clarified work to:

- New or existing project issue (re-parent from Inbox to the right Area root).
- Open leaf with `when:this-week` or tighter → Next Action.
- `gtd:waiting-for` label → Waiting For.
- `gtd:someday-maybe` label → Someday/Maybe.
- Reference note or project support comment.

### Reflect

During reviews, look for:

- Active projects without a `when:` label on any leaf (missing next action).
- `gtd:waiting-for` items with no owner or no follow-up date.
- Issues still in Inbox (root = `[Scott T] Inbox`) that should be triaged.
- P1/P2 work not labeled `when:today` or `when:this-week`.
- Completed work that needs a work log, closure, or stakeholder update.
- `gtd:someday-maybe` items that should be activated or discarded.

### Engage

When choosing what to do next, weigh:

- Priority and deadline.
- Whether the next action is clear.
- Available time and energy.
- Blockers and waiting-for status.
- Strategic importance to Scott's responsibility domains.

Recommend one immediate action, not a broad menu, unless the user asks for options.

## Response Patterns

For resume requests:

1. Identify the project/issue if available.
2. If Scott asks only where to work, which project to use, or for a suggestion,
   treat it as orientation-only: read the handoff/issue context, return the
   recommended project/workspace path, confidence, and a short reason, then stop.
   Do not inspect the target repository or begin implementation.
3. If the work should happen in another Codex project, create a resume handoff
   file and highlight the target project path.
4. Summarize current state.
5. Name the next action.
6. Call out waiting-for items or blockers.
7. Recommend the immediate action.

For review requests:

1. Group by responsibility domain.
2. Highlight projects missing next actions.
3. Highlight waiting-for follow-ups.
4. Suggest promotions/demotions between inbox, active, waiting, and someday/maybe.

For issue updates:

1. State the GTD classification.
2. State the domain and any waiting-for owner.
3. Use `gtd_mgmt` to update issues when available.
4. Confirm exactly what changed.
