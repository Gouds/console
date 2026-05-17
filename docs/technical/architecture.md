# Architecture

Console is a Python HTTP server backed by plain files. There is no database, no message queue, no inter-process communication. The design was built around three constraints: local-first, portable, and human-readable at every layer.

---

## Single agent instance, persona switching

Most agent frameworks (CrewAI, AutoGen, LangGraph) spin up a separate model instance per agent. Console does not. A single `claude --print` call reads the task queue, reads the relevant agent profile, adopts that persona, and does the work.

```
claude --print --permission-mode bypassPermissions
```

Run from the Console root directory so the agent can read and write vault files directly.

**Why:**
- One API call per dispatch cycle, not one per agent
- Full shared context — when BookWorm files a note, it has awareness of what the Orchestrator decided; separate instances would need to serialize that context
- The task file *is* the inter-agent protocol; no custom message passing needed
- Agent personas are `.md` files; swapping the underlying model is one line of code

---

## Two-tier agent system

Agents exist at two levels:

```
agents/                        ← global (infrastructure, always available)
    Orchestrator.md
    Helm.md
    Scout.md

vaults/<id>/agents/            ← vault-scoped (override globals of same name)
    Herald.md
    Scout.md
    BookWorm.md
```

When resolving an agent, vault-scoped takes priority over global. This lets each vault have a Herald with the right email integration and tone, while sharing Orchestrator and Helm across all contexts.

Resolution logic in `server.py → get_agent_content()`:

1. Check `vaults/<vault_id>/agents/<Name>.md`
2. Fall back to `agents/<Name>.md`
3. Return `(content, scope)` — scope is `"vault"` or `"global"`

---

## Files as state

Every piece of state is a file:

| What | Path |
|------|------|
| Tasks | `vaults/<id>/tasks/TASK-NNN-slug.md` |
| Notes | `vaults/<id>/notes/<Category>/YYYY-MM-DD - Title.md` |
| Outbox drafts | `vaults/<id>/outbox/outbox.md` |
| Chat sessions | `vaults/<id>/sessions/YYYY-MM-DD HH-MM - Title.md` |
| Agent profiles | `agents/` (global) · `vaults/<id>/agents/` (vault-scoped) |
| Schedules | `schedules.json` |
| Vault config | `vaults/<id>/vault.json` (gitignored) |
| Settings | `settings.json` (gitignored) |
| Activity log | `console.log` (JSONL, one entry per line) |

All writes go through `_atomic_write()` — write to `.tmp`, then `rename()` — so a crash never produces a half-written file.

---

## Task file format

```markdown
---
id: TASK-001
title: Task title here
status: pending
assigned_to: Orchestrator
priority: Medium
created: 2026-05-17
updated: 2026-05-17
qa_score: 4
user_rating: 5
type: task
---

## Request

What the user asked for.

---

## Context

Any background the user provided. Defaults to `—`.

---

## Progress Log

- **2026-05-17 13:00** — Task created. Assigned to Orchestrator.
- **2026-05-17 13:05** — Status → in-progress.
- **2026-05-17 13:07** — Status → done.
- **2026-05-17 13:08** — QA: ★★★★☆ (4/5) — Thorough answer with clear reasoning.

---

## Output

Agent output goes here.
```

`qa_score` and `user_rating` are optional frontmatter fields added after the task completes. Both are 1–5 integers.

---

## Note file format

BookWorm files all completed task outputs as notes. The format is portable CommonMark — no `[[wikilinks]]`, no Obsidian callout blocks, no dataview. YAML frontmatter + plain markdown.

```markdown
---
date: 2026-05-17
type: research
source: TASK-042
tags: [research, competitors]
---

# Title

Content in plain CommonMark.
```

Notes are filed to `vaults/<id>/notes/<Category>/` where Category is one of:

- `Daily Briefs`
- `Research`
- `Reference`
- `Decisions`
- `Inbox`

---

## Background threads

Two threads run for the lifetime of the server process.

### TaskWatcher

Polls the task queue on a configurable interval (default: 60 seconds). When `auto_dispatch: true` and pending tasks exist, fires a dispatch cycle.

```python
class TaskWatcher(threading.Thread):
    def _check(self, settings):      # count tasks, maybe dispatch
    def _dispatch(self, vault_id):   # run claude --print, then _post_dispatch_hooks()
    def force_dispatch(vault_id):    # called by the dashboard Dispatch button
```

After every dispatch cycle, `_post_dispatch_hooks()` scans for tasks that became `done` during the cycle (the agent writes files directly, bypassing `set_task_status()`). For each unscored done task it fires QA and BookWorm in background threads.

### Scheduler

Wakes every 60 seconds. For each enabled schedule, checks if it is due (`last_run < today` and `current_time >= scheduled_time`). If due, creates a task and calls `watcher.force_dispatch()`.

```python
class Scheduler(threading.Thread):
    def _tick(self):    # check all schedules, fire if due
    def _fire(sched):   # create_task() + watcher.force_dispatch()
```

---

## QA and auto-filing

When a task moves to `done` (either via the dashboard status button or the post-dispatch hook), two background threads fire:

**`_qa_task_output(task_id, vault_id)`**

Sends the task request + output to Claude with a structured scoring prompt. Parses `SCORE: N` and `SUMMARY: ...` from the response and writes `qa_score` back to the task frontmatter. Timeout: 60 seconds.

**`_file_task_output(task_id, vault_id)`**

Asks Claude to act as BookWorm, read the task, determine the right category and title, and file the output as a note. BookWorm has full filesystem access via `--permission-mode bypassPermissions`. Timeout: 180 seconds.

Both threads are daemon threads — they don't block server shutdown.

---

## Chat sessions

Chat history is stored as JSONL-formatted `.md` files in `vaults/<id>/sessions/`. The filename is derived from the first user message and locked in on the first save — subsequent saves overwrite the same file.

Session file format:
```markdown
---
date: 2026-05-17
type: chat
tags: [chat]
---

# Session title from first message

**You** · 13:05

User message here.

---

**Orchestrator** · 13:05

Agent response here.
```

---

## Security model

All vault file access goes through path traversal checks:

- `safe_vault_file_path()` — validates the resolved path is inside the vault root; requires the file to exist (read operations)
- `safe_vault_write_path()` — same validation but does not require existence (write/create operations)

Both resolve symlinks before checking, so `../` tricks and symlink escapes are blocked.

The `claude --print` subprocess runs with `--permission-mode bypassPermissions` from the Console root directory. This gives the agent full read/write access to the Console directory tree. It does not give access outside that directory unless explicitly pathed.

---

## Settings structure

`settings.json` (copy from `settings.example.json`):

```json
{
  "user": {
    "name": "Your Name",
    "email": "you@example.com"
  },
  "console": {
    "name": "My Console",
    "port": 7843
  },
  "active_vault": "personal",
  "vaults": [
    {"id": "personal", "name": "Personal", "description": ""},
    {"id": "work",     "name": "Work",     "description": ""}
  ],
  "dispatch": {
    "poll_interval": 60,
    "auto_dispatch": false
  }
}
```

`vaults/<id>/vault.json` (gitignored — contains credentials):

```json
{
  "id": "personal",
  "integrations": {
    "email":    {"provider": "zoho", "address": "user@example.com"},
    "calendar": {"provider": null,   "address": null}
  },
  "model": {
    "api_key":  null,
    "model_id": "claude-sonnet-4-6"
  },
  "apps": []
}
```

If `model.api_key` is set for a vault, it is passed as `ANTHROPIC_API_KEY` when running Claude for that vault's tasks. Otherwise the environment's key is used.
