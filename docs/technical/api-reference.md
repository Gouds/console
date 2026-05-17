# API Reference

All endpoints are served by `app/server.py` on `http://localhost:<port>` (default 7843).

Most endpoints accept a `?vault=<id>` query parameter to target a specific vault. If omitted, the `active_vault` from `settings.json` is used.

All POST endpoints accept and return `application/json`. All responses include `Access-Control-Allow-Origin: *`.

---

## GET endpoints

### Tasks

#### `GET /api/tasks?vault=<id>`

Returns all tasks in the vault as a list, sorted by filename.

```json
[
  {
    "id": "TASK-001",
    "title": "Research task",
    "status": "done",
    "assigned_to": "Scout",
    "priority": "Medium",
    "created": "2026-05-17",
    "updated": "2026-05-17",
    "file": "TASK-001-research-task.md",
    "waiting_question": "",
    "output_preview": "First meaningful sentence of the output…",
    "qa_score": 4,
    "user_rating": 5
  }
]
```

`output_preview` is the first non-trivial sentence of the `## Output` section (stripped of markdown). Empty if the task is still pending.

`waiting_question` is the `**Question:**` extracted from `## Waiting For Input` when status is `waiting-input`.

#### `GET /api/task-read?id=TASK-001&vault=<id>`

Returns the full task including section content.

```json
{
  "id": "TASK-001",
  "title": "Research task",
  "status": "done",
  "assigned_to": "Scout",
  "priority": "Medium",
  "created": "2026-05-17",
  "updated": "2026-05-17",
  "qa_score": 4,
  "user_rating": 5,
  "file": "TASK-001-research-task.md",
  "sections": {
    "request": "Full request text",
    "context": "Context text",
    "progress_log": "- **2026-05-17 13:00** — Task created…",
    "waiting_for_input": "",
    "output": "Agent output text"
  }
}
```

Returns `404` if the task ID is not found.

---

### Agents

#### `GET /api/agents?vault=<id>`

Returns the merged agent list. Vault-scoped agents override globals of the same name.

```json
[
  {
    "name": "Orchestrator",
    "role": "Task Router & Team Manager",
    "status": "Active",
    "emoji": "🎯",
    "tagline": "Every task finds its agent.",
    "file": "Orchestrator.md",
    "reports_to": null,
    "scope": "global",
    "vault": null
  },
  {
    "name": "Herald",
    "role": "Communications Agent",
    "status": "Active",
    "emoji": "✉️",
    "tagline": "…",
    "file": "Herald.md",
    "reports_to": "Orchestrator",
    "scope": "vault",
    "vault": "personal"
  }
]
```

`scope` is `"global"` or `"vault"`. `vault` is `null` for global agents.

#### `GET /api/agent-read?name=Scout&vault=<id>`

Returns the raw content and scope of an agent profile.

```json
{
  "name": "Scout",
  "content": "---\ntype: agent-profile\n…",
  "scope": "vault",
  "vault": "personal"
}
```

Returns `404` if the agent is not found.

#### `GET /api/org-chart?vault=<id>`

Returns the org chart as a nested tree structure rooted at Orchestrator.

```json
{
  "name": "Orchestrator",
  "role": "Task Router & Team Manager",
  "children": [
    {"name": "Helm", "children": []},
    {"name": "Scout", "children": []},
    {"name": "Herald", "children": []}
  ]
}
```

#### `GET /api/agent-stats?vault=<id>`

Returns performance statistics per agent, aggregated from completed tasks.

```json
[
  {
    "name": "Scout",
    "task_count": 12,
    "qa_avg": 4.2,
    "rating_avg": 4.5,
    "overall_avg": 4.35,
    "scored_tasks": 10,
    "needs_review": false
  }
]
```

`needs_review` is `true` when `overall_avg < 3.5` and `scored_tasks >= 3`. Agents flagged for review sort to the top of the list.

---

### Vaults

#### `GET /api/vaults`

Returns all vaults with integration status and model config.

```json
[
  {
    "id": "personal",
    "name": "Personal",
    "description": "",
    "active": true,
    "integrations": {
      "email":    {"provider": "zoho", "address": "user@example.com"},
      "calendar": {"provider": null,   "address": null}
    },
    "model": {"model_id": "claude-sonnet-4-6"},
    "has_api_key": false
  }
]
```

`has_api_key` indicates whether `vault.json` contains a model API key. The key itself is never returned.

#### `GET /api/vault-config?vault=<id>`

Returns the full `vault.json` for the specified vault, including the API key.

#### `GET /api/vault-tree?vault=<id>`

Returns the vault's file tree as a nested array.

```json
[
  {"name": "agents", "path": "agents", "type": "dir", "children": [
    {"name": "Herald.md", "path": "agents/Herald.md", "type": "file", "ext": "md"}
  ]},
  {"name": "tasks", "path": "tasks", "type": "dir", "children": []}
]
```

Hidden files (`.`-prefixed) and certain directories (`.git`, `__pycache__`, etc.) are excluded.

#### `GET /api/vault-raw?path=<rel_path>&vault=<id>`

Returns the raw bytes of a vault file with the appropriate MIME type. Path must be inside the vault root. Returns `404` if the file does not exist or the path is outside the vault.

---

### Notes

#### `GET /api/notes?vault=<id>`

Returns all notes across all five categories, sorted newest-first within each category.

```json
[
  {
    "title": "2026-05-17 - Daily Brief",
    "category": "Daily Briefs",
    "path": "Daily Briefs/2026-05-17 - Daily Brief.md",
    "date": "2026-05-17",
    "type": "daily-brief",
    "source": "scheduled",
    "tags": "[daily-brief, news]"
  }
]
```

#### `GET /api/note-read?path=<rel_path>&vault=<id>`

Returns the content of a note file. `path` is relative to `vaults/<id>/notes/` (e.g. `Daily Briefs/2026-05-17 - Daily Brief.md`).

```json
{
  "path": "Daily Briefs/2026-05-17 - Daily Brief.md",
  "content": "---\ndate: 2026-05-17\n…"
}
```

Returns `404` if the file does not exist or the path traverses outside the notes directory.

#### `GET /api/notes-search?q=<query>&vault=<id>`

Full-text search across all note content. Returns matching notes with a contextual snippet (60 chars before match, 100 after).

```json
[
  {
    "title": "2026-05-17 - Daily Brief",
    "category": "Daily Briefs",
    "path": "Daily Briefs/2026-05-17 - Daily Brief.md",
    "date": "2026-05-17",
    "type": "daily-brief",
    "source": "scheduled",
    "tags": "[daily-brief]",
    "snippet": "…before the match here **matched term** and after the match…"
  }
]
```

Returns an empty array for empty queries.

---

### Schedules

#### `GET /api/schedules`

Returns all schedules from `schedules.json`.

```json
{
  "schedules": [
    {
      "id": "SCH-001",
      "name": "Daily Brief",
      "prompt": "Act as Orchestrator…",
      "schedule": "daily",
      "time": "08:00",
      "vault": "personal",
      "enabled": true,
      "last_run": "2026-05-17"
    }
  ]
}
```

---

### System

#### `GET /api/status`

Returns TaskWatcher state and task counts.

```json
{
  "pending": 2,
  "in_progress": 1,
  "waiting_input": 0,
  "last_check": "2026-05-17 13:05",
  "last_dispatch": {
    "time": "2026-05-17 13:04",
    "output": "Dispatch output…",
    "error": "",
    "exit_code": 0
  },
  "dispatching": false,
  "poll_interval": 60,
  "watching": true
}
```

#### `GET /api/settings`

Returns the full `settings.json` object.

#### `GET /api/sessions?vault=<id>`

Returns the last 20 chat sessions (most recent first).

```json
[
  {
    "title": "2026-05-17 13-05 - Research on competitors",
    "date": "2026-05-17",
    "domain": "",
    "topic": "Research on competitors"
  }
]
```

#### `GET /api/session-read?file=<filename>&vault=<id>`

Returns the content of a session file. `file` is the stem without extension (as returned by `/api/sessions`).

```json
{"content": "---\ndate: 2026-05-17\ntype: chat\n…"}
```

#### `GET /api/outbox?vault=<id>`

Returns outbox draft entries.

```json
[
  {
    "id": "OUT-001",
    "task": "TASK-005",
    "agent": "Herald",
    "date": "2026-05-17",
    "type": "email",
    "to": "recipient@example.com",
    "subject": "Subject line",
    "body": "Email body…"
  }
]
```

#### `GET /api/log?since=<seq>`

Returns activity log entries since sequence number `since` (default 0). Used by the live log panel. Up to 500 entries are kept in memory.

```json
{
  "entries": [
    {"seq": 42, "ts": "2026-05-17 13:05:00", "level": "info", "type": "dispatch", "msg": "Dispatch complete ✓"}
  ]
}
```

---

## POST endpoints

All POST endpoints return `{"ok": true}` on success or `{"ok": false, "error": "…"}` on failure.

### Tasks

#### `POST /api/task-create`

```json
{
  "title": "Task title",
  "request": "Full request text",
  "context": "Optional background",
  "priority": "High",
  "assigned_to": "Scout",
  "vault": "personal"
}
```

`priority` defaults to `"Medium"`. `assigned_to` defaults to `"Orchestrator"`.

Response: `{"ok": true, "id": "TASK-003"}`

#### `POST /api/task-status`

```json
{"id": "TASK-003", "status": "done", "vault": "personal"}
```

Valid statuses: `pending`, `in-progress`, `waiting-input`, `blocked`, `done`.

When status moves to `done`, QA and BookWorm fire automatically in background threads.

#### `POST /api/task-answer`

```json
{"id": "TASK-003", "answer": "Your answer here", "vault": "personal"}
```

Fills in `**Your Answer:**` in the `## Waiting For Input` section and sets status to `in-progress`.

#### `POST /api/task-progress`

```json
{"id": "TASK-003", "entry": "Progress note to append", "vault": "personal"}
```

Appends a timestamped entry to the `## Progress Log` section.

#### `POST /api/task-rate`

```json
{"id": "TASK-003", "rating": 4, "vault": "personal"}
```

Sets `user_rating` in task frontmatter (1–5). Appends a star-rating entry to the progress log.

---

### Agents

#### `POST /api/agent-save`

```json
{
  "name": "Scout",
  "content": "---\ntype: agent-profile\n…",
  "scope": "vault",
  "vault": "personal"
}
```

`scope` is `"vault"` or `"global"`. Vault-scoped agents are saved to `vaults/<id>/agents/`; global agents to `agents/`.

---

### Helm

#### `POST /api/helm-review`

Ask Helm to review an agent's recent performance and rewrite their profile.

```json
{"agent_name": "Scout", "vault": "personal"}
```

Response:

```json
{
  "ok": true,
  "description": "2-3 sentences: what patterns were found and what changed",
  "profile": "Complete rewritten agent profile in markdown"
}
```

Helm reads the last 15 completed tasks for the agent and uses QA scores to identify patterns.

#### `POST /api/helm-create`

Ask Helm to design a new agent profile for a described capability gap.

```json
{"description": "An agent that analyses spreadsheet data and produces summaries", "vault": "personal"}
```

Response:

```json
{
  "ok": true,
  "agent_name": "Analyst",
  "description": "2-3 sentences: what gap this fills",
  "profile": "Complete new agent profile in markdown"
}
```

Helm checks existing agents before designing the new one to avoid duplication.

---

### Chat

#### `POST /api/chat`

Send a message to the Orchestrator in chat mode.

```json
{
  "message": "What tasks are pending?",
  "history": [
    {"role": "user",      "content": "Previous message"},
    {"role": "assistant", "content": "Previous response"}
  ],
  "vault": "personal"
}
```

`history` is used to provide conversation context (last 20 turns). The Orchestrator profile is prepended to the prompt.

Response:

```json
{"ok": true, "response": "Orchestrator's reply in markdown"}
```

Timeout: 120 seconds.

---

### Outbox

#### `POST /api/outbox-add`

```json
{
  "task_id": "TASK-003",
  "agent": "Herald",
  "type": "email",
  "to": "recipient@example.com",
  "subject": "Subject line",
  "body": "Email body",
  "vault": "personal"
}
```

Response: `{"ok": true, "id": "OUT-002"}`

#### `POST /api/outbox-discard`

```json
{"id": "OUT-002", "vault": "personal"}
```

---

### Files

#### `POST /api/vault-file-save`

```json
{
  "path": "sessions/2026-05-17 13-05 - Topic.md",
  "content": "File content here",
  "vault": "personal"
}
```

Editable file types: `.md`, `.txt`, `.json`, `.yaml`, `.yml`, `.py`, `.sh`, `.css`, `.js`. Parent directories are created automatically. Path must resolve inside the vault root.

---

### Vaults

#### `POST /api/vault-add`

```json
{"id": "client-x", "name": "Client X", "description": "Consulting project"}
```

Creates the vault directory structure, default `inbox.md` and `outbox.md`, and `vault.json`.

#### `POST /api/vault-switch`

```json
{"id": "work"}
```

Sets `active_vault` in `settings.json`.

#### `POST /api/vault-config-save`

Saves the full `vault.json` for a vault. Body should be the complete vault config object including `id`, `integrations`, `model`, and `apps`.

---

### Schedules

#### `POST /api/schedule-save`

Create or update a schedule. If `id` is omitted, a new ID is assigned.

```json
{
  "id": "SCH-001",
  "name": "Daily Brief",
  "prompt": "Act as Orchestrator…",
  "schedule": "daily",
  "time": "08:00",
  "vault": "personal",
  "enabled": true
}
```

If the scheduled time changes to a future time, `last_run` is cleared so it fires today.

#### `POST /api/schedule-delete`

```json
{"id": "SCH-001"}
```

#### `POST /api/schedule-toggle`

```json
{"id": "SCH-001"}
```

Toggles `enabled` between `true` and `false`.

#### `POST /api/schedule-run`

```json
{"id": "SCH-001"}
```

Fires the schedule immediately regardless of time or `enabled` state. Creates a task and dispatches.

---

### System

#### `POST /api/dispatch`

Triggers a dispatch cycle in the background for the active vault (or `?vault=<id>`).

Response: `{"ok": true, "msg": "Dispatch started in background"}`

#### `POST /api/watcher-check`

Forces an immediate task count check and returns the current watcher status (same shape as `GET /api/status`).

#### `POST /api/claude`

Run an arbitrary prompt through `claude --print` and return the output.

```json
{"prompt": "Summarise the current task queue", "vault": "personal"}
```

Response:

```json
{
  "ok": true,
  "output": "Claude's response",
  "stderr": "",
  "exit_code": 0
}
```

Timeout: 120 seconds.

#### `POST /api/terminal`

Run a shell command from the Console root directory.

```json
{"cmd": "ls vaults/personal/tasks"}
```

Response:

```json
{
  "stdout": "TASK-001-research.md\n",
  "stderr": "",
  "exit_code": 0,
  "cwd": "/path/to/Console"
}
```

Timeout: 30 seconds.

#### `POST /api/settings-save`

Save the full `settings.json`. Body should be the complete settings object. Triggers an immediate TaskWatcher check to pick up any interval changes.

#### `POST /api/log-clear`

Clears the in-memory log buffer. Does not clear `console.log` on disk.
