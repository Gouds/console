# Console

A local-first AI agent operating system. Tasks live as plain Markdown files. A small team of named agents processes them via `claude --print`. You review everything before it goes anywhere.

No cloud services required. No database. Everything is a file.

---

## Quick start

```bash
git clone https://github.com/yourusername/console
cd console
python console.py init    # first-time setup: creates settings.json + vault folders
python console.py start   # launches the dashboard at http://localhost:7843
```

Python 3.9+ is all you need. No dependencies to install.

---

## How it works

```
Console/
├── console.py              ← CLI entry point (init, start, status)
├── settings.json           ← your config (gitignored)
├── schedules.json          ← scheduled task definitions
├── agents/                 ← global agent profiles (.md files)
│   ├── Orchestrator.md
│   ├── Helm.md
│   └── Scout.md
├── app/
│   ├── server.py           ← HTTP server + all API logic (single file)
│   └── dashboard.html      ← single-page web UI (vanilla JS, no build step)
└── vaults/                 ← your data (gitignored)
    ├── personal/
    │   ├── agents/         ← vault-scoped agents (override globals)
    │   ├── tasks/
    │   ├── notes/
    │   ├── inbox/
    │   ├── outbox/
    │   └── sessions/
    └── work/
        └── …
```

**Vaults** isolate data by context — personal vs. work, or any other separation you need. Switch between them in the top-right dropdown.

**Tasks** are `.md` files with YAML frontmatter. Each task records its status, assigned agent, full request, progress log, and output — all in one human-readable file.

**Agents** are `.md` profiles that define a role, personality, and responsibilities. When a dispatch runs, Claude adopts each agent's persona and works through the task queue. There is one `claude --print` process per dispatch — not one per agent.

**Outbox** holds communication drafts staged by agents for your review. Nothing sends automatically.

---

## Task flow

1. **Create** a task from the dashboard (Tasks tab → New Task)
2. **Dispatch** — the Orchestrator reads the queue, routes each task to the right agent persona, does the work, and writes results back to the task file
3. **Review** — check outputs on the Kanban board; email drafts appear in the Outbox tab
4. **Answer** — if a task is `waiting-input`, the card shows the agent's question; type your answer to requeue it
5. **Auto-file** — when a task is marked `done`, BookWorm automatically files the output to `vaults/<id>/notes/`

---

## Task statuses

| Status | Meaning |
|--------|---------|
| `pending` | Queued, not yet picked up |
| `in-progress` | Agent is working on it |
| `waiting-input` | Parked — agent needs your answer before continuing |
| `blocked` | Cannot proceed, needs investigation |
| `done` | Complete — BookWorm and QA fire automatically |

---

## Dashboard tabs

| Tab | What it does |
|-----|-------------|
| **Tasks** | Kanban board across all statuses. Click any card to open the full task |
| **Outbox** | Email and message drafts staged for review |
| **Agents** | View and edit agent profiles; org chart |
| **Helm** | Agent health roster, Helm review, create new agents |
| **Files** | Browse and edit files in the active vault |
| **Terminal** | Run agent prompts or shell commands directly |
| **Schedules** | Create and manage recurring scheduled tasks |
| **Notes** | Browse auto-filed task outputs; filter and full-text search |
| **Chat** | Live conversational interface with the Orchestrator |
| **Settings** | Console config, vault management, dispatch settings |

---

## CLI commands

```bash
python console.py init     # interactive first-time setup
python console.py start    # start the server
python console.py status   # show current config without starting
```

---

## Technical docs

- [Architecture](docs/technical/architecture.md) — design decisions, background threads, file formats
- [API Reference](docs/technical/api-reference.md) — all endpoints with request/response shapes
- [Agent Authoring](docs/technical/agent-authoring.md) — how to write and customise agent profiles

---

## Philosophy

- **Local first** — your data never leaves your machine unless you choose to send something
- **Files over databases** — every task, draft, and session is a plain text file you can read, edit, or version-control directly
- **Humans stay in the loop** — agents draft, stage, and recommend; you approve, answer, and send
- **One Python file** — the entire server is `app/server.py`; no frameworks, no build step, no npm
- **Portable agents** — personas are `.md` files; take them to any model or editor
