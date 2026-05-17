# Console

A local-first AI agent operating system. Tasks live as plain Markdown files. A small team of named agents processes them. You review everything before it goes anywhere.

No cloud services required. No database. Everything is a file.

---

## Quick start

```bash
git clone https://github.com/yourusername/console
cd console
python console.py init    # first-time setup: creates settings.json + vault folders
python console.py start   # launches the dashboard at http://localhost:7842
```

Python 3.9+ is all you need. No dependencies to install.

---

## How it works

```
Console/
├── console.py          ← CLI entry point
├── settings.json       ← your config (gitignored)
├── agents/             ← agent profiles (.md files)
│   ├── Orchestrator.md
│   ├── Scout.md
│   └── Herald.md
├── app/
│   ├── server.py       ← HTTP server + all API logic
│   └── dashboard.html  ← single-file web UI
└── vaults/             ← your data (gitignored)
    ├── personal/
    │   ├── tasks/
    │   ├── inbox/
    │   ├── outbox/
    │   └── sessions/
    └── work/
        └── …
```

**Vaults** keep contexts separate. Personal tasks stay in `vaults/personal/`, work tasks in `vaults/work/`. Agents are shared across all vaults.

**Tasks** are `.md` files with frontmatter. Each task records its status, who it's assigned to, the full request, progress log, and output — all in one human-readable file.

**Agents** are `.md` profiles that define a role, personality, and responsibilities. When you run a dispatch cycle (via Claude Code's `/dispatch` skill), Claude adopts each agent's persona and works through the queue.

**Outbox** holds communication drafts (emails, messages) staged by agents for your review. Nothing sends automatically.

---

## Task flow

1. **Create** a task from the dashboard or by writing a `.md` file directly into `vaults/<vault>/tasks/`
2. **Dispatch** — run `/dispatch` in Claude Code to process the queue. Claude reads each task, adopts the assigned agent's persona, does the work, and writes results back to the file
3. **Review** — check outputs on the Kanban board. If an agent drafted an email, it appears in the Outbox tab
4. **Answer** — if a task is `waiting-input`, the dashboard shows the agent's question. Type your answer and requeue it

---

## Task statuses

| Status | Meaning |
|--------|---------|
| `pending` | Queued, not yet picked up |
| `in-progress` | Agent is working on it |
| `waiting-input` | Parked — agent needs your answer before continuing |
| `blocked` | Cannot proceed, needs investigation |
| `done` | Complete |

---

## Adding an agent

Create a `.md` file in `agents/`:

```markdown
---
type: agent-profile
agent: Analyst
role: Data Analyst
status: Active
emoji: 📊
---

# 📊 Analyst — Data Analyst

> *"The numbers always have something to say."*

## Role
Handles data analysis tasks…

## Responsibilities
- …
```

The agent will appear in the dashboard immediately. To wire it into the org chart, add it to `ORG_REPORTS_TO` in `app/server.py`.

---

## Dashboard tabs

| Tab | What it does |
|-----|-------------|
| **Tasks** | Kanban board across all statuses. Click any card to open the full task |
| **Outbox** | Email and message drafts staged for review. Copy to send manually |
| **Agents** | View and edit agent profiles directly in the browser |
| **Org** | Visual org chart built from agent profiles |
| **Files** | Browse and edit files in the active vault |
| **Settings** | Console name, port, user info, vault management |

---

## CLI commands

```bash
python console.py init     # interactive first-time setup
python console.py start    # start the server (wraps app/server.py)
python console.py status   # show current config without starting
```

---

## Vaults

Vaults isolate data by context. Switch between them with the dropdown in the top-right corner, or via Settings → Vaults.

To add a vault programmatically:

```bash
curl -X POST http://localhost:7842/api/vault-add \
  -H "Content-Type: application/json" \
  -d '{"id":"client-x","name":"Client X","description":"Consulting project"}'
```

---

## API reference

All endpoints accept `?vault=<id>` to target a specific vault (defaults to `active_vault` in settings).

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/tasks` | List all tasks |
| GET | `/api/task-read?id=TASK-001` | Full task detail |
| POST | `/api/task-create` | Create a task |
| POST | `/api/task-status` | Update task status |
| POST | `/api/task-answer` | Answer a waiting-input task |
| GET | `/api/outbox` | List outbox drafts |
| POST | `/api/outbox-add` | Stage a draft |
| POST | `/api/outbox-discard` | Discard a draft |
| GET | `/api/agents` | List agents |
| GET | `/api/agent-read?name=Scout` | Read agent profile |
| POST | `/api/agent-save` | Save agent profile |
| GET | `/api/org-chart` | Org chart tree |
| GET | `/api/vaults` | List vaults |
| POST | `/api/vault-add` | Add a vault |
| POST | `/api/vault-switch` | Set active vault |
| GET | `/api/settings` | Read settings |
| POST | `/api/settings-save` | Save settings |
| GET | `/api/vault-tree` | File tree for active vault |
| GET | `/api/vault-raw?path=…` | Raw file content |
| POST | `/api/vault-file-save` | Save a vault file |

---

## Philosophy

- **Local first** — your data never leaves your machine unless you choose to send something
- **Files over databases** — every task, draft, and session is a plain text file you can read, edit, or version-control directly
- **Humans stay in the loop** — agents draft, stage, and recommend. You approve, answer, and send
- **One Python file** — the entire server is `app/server.py`. No frameworks, no build step, no npm
