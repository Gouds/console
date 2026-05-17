# Console — Development Context

Console is a **local-first AI agent OS** running as a Python HTTP server with a single-page dashboard. Agents are plain `.md` files. State is plain files. No database. No cloud dependency.

---

## Quick Start

```bash
cd /path/to/Console
cp settings.example.json settings.json   # first time only — edit with your details
python3 app/server.py
# → http://localhost:7843
```

Port is set in `settings.json → console.port`. Default: **7843**.

---

## Architecture

### Single agent instance, persona switching

Console does **not** spin up separate agent processes. A single `claude --print` call reads a persona file (`.md`) and adopts it for the task. The Orchestrator reads the task, picks the right agent profile, and acts as that agent.

This is a deliberate design choice — cheaper, simpler, shared context across the "team", and the agents are portable plain-text files that work with any model.

### Files as state

Every piece of state is a file:

| What | Where |
|------|-------|
| Tasks | `vaults/<id>/tasks/TASK-NNN-slug.md` |
| Agent profiles | `agents/` (global) · `vaults/<id>/agents/` (vault-scoped) |
| Filed notes | `vaults/<id>/notes/<Category>/` |
| Outbox drafts | `vaults/<id>/outbox/outbox.md` |
| Schedules | `schedules.json` |
| Vault config + integrations | `vaults/<id>/vault.json` (gitignored — has email/provider) |
| Settings | `settings.json` (gitignored — copy from settings.example.json) |

### Two-tier agent system

**Global agents** (`agents/`) are infrastructure — always available across all vaults:
- `Orchestrator` — routes tasks, manages dispatch
- `Helm` — HR/resource manager, provisions new agents when a task needs a capability that doesn't exist
- `Scout` — global research fallback

**Vault agents** (`vaults/<id>/agents/`) are specialists that **override globals of the same name**:
- `Herald` — email/comms (personal vault = Zoho; work vault = M365)
- `Scout` — domain-specific research (personal = consumer; work = competitive/industry)
- `BookWorm` — vault librarian, files completed task outputs to `notes/`

When a new vault needs a capability not covered, the Orchestrator routes to **Helm** to provision a new agent.

---

## File Map

```
Console/
├── app/
│   ├── server.py          # HTTP server — all logic lives here
│   └── dashboard.html     # Single-page app (vanilla JS, no build step)
├── console.py             # CLI: init, start, status
├── agents/                # Global agent profiles (synced via git)
│   ├── Orchestrator.md
│   ├── Helm.md
│   └── Scout.md
├── vaults/
│   ├── personal/
│   │   ├── agents/        # Vault-scoped agents (synced via git)
│   │   │   ├── Herald.md
│   │   │   ├── Scout.md
│   │   │   └── BookWorm.md
│   │   ├── tasks/         # gitignored — personal data
│   │   ├── notes/         # gitignored — personal data
│   │   │   ├── Daily Briefs/
│   │   │   ├── Research/
│   │   │   ├── Reference/
│   │   │   ├── Decisions/
│   │   │   └── Inbox/
│   │   ├── inbox/         # gitignored
│   │   ├── outbox/        # gitignored
│   │   └── sessions/      # gitignored
│   └── work/
│       ├── agents/        # Vault-scoped agents (synced via git)
│       │   ├── Herald.md
│       │   ├── Scout.md
│       │   └── BookWorm.md
│       └── (same structure)
├── schedules.json         # Scheduled task definitions
├── settings.example.json  # Template — copy to settings.json on new machines
├── .gitignore
└── CLAUDE.md              # This file
```

---

## server.py — Key Functions

### Settings & config
- `load_settings()` / `save_settings(data)` — reads/writes `settings.json`
- `get_vault_config(vault_id)` / `save_vault_config(id, data)` — reads/writes `vaults/<id>/vault.json`; always merges `EMPTY_INTEGRATIONS` defaults so keys are present
- `load_schedules()` / `save_schedules(data)` — reads/writes `schedules.json`

### Tasks
- `create_task(title, request, context, priority, assigned_to, vault_id)` → task_id
- `get_tasks(vault_id)` → list with output preview + waiting question extracted
- `get_task(task_id, vault_id)` → full task with sections dict
- `set_task_status(task_id, new_status, vault_id)` — when status → `done`, fires `_file_task_output()` in background thread
- `answer_task(task_id, answer, vault_id)` — fills in `**Your Answer:**` block, sets status → in-progress
- `append_progress(task_id, entry, vault_id)`

### Agents
- `get_agents(vault_id)` → merged list, vault agents override globals of same name, each has `scope` field
- `get_agent_content(name, vault_id)` → `(content, scope)` tuple, vault takes priority
- `save_agent_content(name, content, vault_id, scope)`

### Notes
- `get_notes(vault_id)` → list across all 5 categories with metadata
- `get_note(rel_path, vault_id)` → content string (path traversal protected)
- Categories: `Daily Briefs`, `Research`, `Reference`, `Decisions`, `Inbox`

### Claude dispatch
- `run_claude(prompt, timeout=300)` — `echo {prompt} | claude --print --permission-mode bypassPermissions` run from Console ROOT. Fully functional non-interactively — reads and writes files.
- `_file_task_output(task_id, vault_id)` — background thread, asks Claude to act as BookWorm and file the completed task output to `vaults/<id>/notes/`

### Background threads
- `TaskWatcher` — polls task counts every `poll_interval` seconds; fires `_dispatch()` when `auto_dispatch: true` and pending tasks exist
- `Scheduler` — wakes every 60s; fires daily schedules at configured time by creating a task + calling `watcher.force_dispatch()`

---

## API Endpoints

### GET
| Endpoint | Description |
|----------|-------------|
| `/api/tasks?vault=<id>` | All tasks in vault |
| `/api/task-read?id=TASK-NNN&vault=<id>` | Single task with sections |
| `/api/agents?vault=<id>` | All agents (global + vault merged) |
| `/api/agent-read?name=X&vault=<id>` | Agent profile content + scope |
| `/api/org-chart?vault=<id>` | Org tree |
| `/api/vaults` | All vaults with integration status |
| `/api/vault-config?vault=<id>` | Vault integrations config |
| `/api/vault-tree?vault=<id>` | File tree for browser |
| `/api/vault-raw?path=X&vault=<id>` | Raw file content |
| `/api/outbox?vault=<id>` | Outbox draft entries |
| `/api/sessions?vault=<id>` | Session files list |
| `/api/settings` | Global settings |
| `/api/status` | TaskWatcher status + task counts |
| `/api/schedules` | All schedules |
| `/api/notes?vault=<id>` | All filed notes with metadata |
| `/api/note-read?path=X&vault=<id>` | Read a specific note |

### POST
| Endpoint | Body | Description |
|----------|------|-------------|
| `/api/task-create` | `{title, request, context, priority, assigned_to}` | Create task |
| `/api/task-status` | `{id, status}` | Set task status |
| `/api/task-answer` | `{id, answer}` | Answer waiting-input task |
| `/api/task-progress` | `{id, entry}` | Append progress log entry |
| `/api/agent-save` | `{name, content, scope, vault}` | Save agent profile |
| `/api/outbox-add` | `{task_id, agent, type, to, subject, body}` | Add outbox draft |
| `/api/outbox-discard` | `{id}` | Remove outbox entry |
| `/api/vault-file-save` | `{path, content}` | Save editable vault file |
| `/api/vault-config-save` | vault config object | Save vault integrations |
| `/api/vault-add` | `{id, name, description}` | Create new vault |
| `/api/vault-switch` | `{id}` | Set active vault |
| `/api/settings-save` | settings object | Save global settings |
| `/api/dispatch` | — | Trigger dispatch in background |
| `/api/watcher-check` | — | Force task count check |
| `/api/claude` | `{prompt}` | Run claude --print, returns output |
| `/api/terminal` | `{cmd}` | Run shell command, returns stdout/stderr |
| `/api/schedule-save` | schedule object | Create/update schedule |
| `/api/schedule-delete` | `{id}` | Delete schedule |
| `/api/schedule-toggle` | `{id}` | Toggle enabled/disabled |
| `/api/schedule-run` | `{id}` | Fire schedule immediately |

---

## Dashboard — Tab Overview

| Tab | View ID | Key JS functions |
|-----|---------|-----------------|
| Tasks | `view-tasks` | `renderKanban()`, `openTaskModal()`, `submitNewTask()` |
| Outbox | `view-outbox` | `renderOutbox()`, `discardOutbox()` |
| Agents | `view-agents` | `renderAgents()`, `openAgentModal()`, `saveAgentContent()` |
| Org | `view-org` | `loadOrgChart()`, `renderOrgNode()` |
| Files | `view-files` | `loadFileTree()`, `openVaultFile()`, `saveVaultFile()` |
| Terminal | `view-terminal` | `termRun()` — agent mode default; `!cmd` prefix for shell |
| Schedules | `view-schedules` | `loadSchedules()`, `renderSchedules()`, `toggleSchedule()` |
| Notes | `view-notes` | `loadNotes()`, `openNote()`, `filterNotes()` |
| Chat | `view-chat` | Coming soon placeholder |
| Settings | `view-settings` | `loadSettings()`, `saveSettings()`, `saveVaultIntegrations()` |

---

## Design Principles

1. **Local-first** — all state in plain files; no cloud, no database, no lock-in
2. **Single agent instance** — one `claude --print` call adopts a persona; not separate processes
3. **Portable notes** — CommonMark + YAML frontmatter only; no `[[wikilinks]]`, no Obsidian callouts, no dataview. Notes must be readable in any editor
4. **Vault portability** — users can take their agents and vault to any model or editor; Console is a convenience layer, not a prison
5. **Helm guards resourcing** — Orchestrator checks capable agent exists before routing; if not, Helm provisions one
6. **BookWorm files everything** — every `done` task gets auto-filed to `vaults/<id>/notes/`; institutional knowledge is cumulative

---

## Why We Built It This Way (Founding Decisions)

These were explicit design conversations — record them so future sessions don't re-litigate them.

### Why single-agent instance instead of multi-agent?

Most frameworks (CrewAI, AutoGen, LangGraph) spin up separate model instances per agent. Console deliberately doesn't. Reasons:

- **Cost** — one `claude --print` call per dispatch, not N calls
- **Shared context** — when BookWorm files a note it has full awareness of what Orchestrator decided; separate instances have to serialize that
- **Simplicity** — no inter-agent communication protocol; the task file *is* the protocol
- **The model already does this** — Claude contains every persona's capability; you're routing to facets of the same model
- **Portability** — personas are `.md` files; swap in any model by changing one line

Competitive landscape check (May 2026): no well-known project combines local-first + single-instance persona switching + OS-level scheduling + plain markdown portability. MemGPT/Letta is closest philosophically but not local-first and doesn't do persona routing.

### Why vault-scoped agents?

The user has two contexts — personal (Zoho Mail, consumer focus) and work (M365, professional tone). Each vault gets its own Herald with the right integration and voice. Vault agents override globals of the same name — clean separation without duplicating infrastructure agents (Orchestrator, Helm).

### Why plain markdown, no Obsidian syntax?

The user explicitly doesn't want lock-in. Notes must be readable in any editor, importable anywhere, usable with any model. `[[wikilinks]]` and callout blocks break that. YAML frontmatter + CommonMark is the universal baseline. Users can leave Console and take everything with them.

### Why files as state, no database?

- No setup friction on new machines
- Git-syncable across systems
- Human-readable and manually editable (the user edits files directly sometimes)
- The agent team already knows how to work with files

### The user's context

- **Personal vault**: Zoho Mail (`chris@goudie.me`), consumer/general focus
- **Work vault**: Microsoft 365, professional/competitive research focus
- Console was built alongside an existing Obsidian vault (`/home/gouds/Documents/Gouds`) — they are separate systems; the Gouds vault has its own agent team (Pickles, Cipher, Hermes etc.)
- **Development sessions**: open Claude Code from `/home/gouds/Console/` — this CLAUDE.md loads automatically and provides full context to hit the ground running

---

## Note Format (BookWorm standard)

```markdown
---
date: YYYY-MM-DD
type: daily-brief | research | reference | decision | misc
source: TASK-NNN | scheduled
tags: [tag1, tag2]
---

# Title

Content in plain CommonMark. No [[wikilinks]]. No > [!callout] blocks.
```

Filed to `vaults/<id>/notes/<Category>/YYYY-MM-DD - Title.md` for dated content, or `Topic.md` for reference material.

---

## Setting Up on a New Machine

```bash
git clone <your-repo-url> Console
cd Console
cp settings.example.json settings.json
# Edit settings.json: set your name, email, port if needed
# Create vault data dirs (gitignored):
mkdir -p vaults/personal/{tasks,inbox,outbox,sessions,notes/{Daily\ Briefs,Research,Reference,Decisions,Inbox}}
mkdir -p vaults/work/{tasks,inbox,outbox,sessions,notes/{Daily\ Briefs,Research,Reference,Decisions,Inbox}}
# Create vault.json files (gitignored):
echo '{"id":"personal","integrations":{"email":{"provider":null,"address":null},"calendar":{"provider":null,"address":null}},"apps":[]}' > vaults/personal/vault.json
echo '{"id":"work","integrations":{"email":{"provider":null,"address":null},"calendar":{"provider":null,"address":null}},"apps":[]}' > vaults/work/vault.json
# Run
python3 app/server.py
```

---

## Working on Console with Claude Code

Open a Claude Code session from the Console directory:
```bash
cd /path/to/Console
claude
```

This session will pick up this `CLAUDE.md` automatically, giving full project context. The Gouds vault session (`/home/gouds/Documents/Gouds`) is a separate context for the Gouds personal vault — keep them separate.

---

## Current State (2026-05-17)

**Built and working:**
- Full task board (Kanban) with modal, create, answer, status transitions
- Agent team: global (Orchestrator, Helm, Scout) + vault-scoped (Herald, Scout, BookWorm) per personal + work vault
- Two-tier agent resolution (vault overrides global)
- Org chart, file browser, terminal (agent + shell mode), outbox
- Per-vault integrations (email provider/address in vault.json)
- TaskWatcher: polls task counts, auto-dispatch via `claude --print`
- Scheduler: daily brief fires at 08:00, creates task + dispatches
- BookWorm: auto-files every `done` task to `notes/` via background Claude call
- Notes tab: browse by category, search, read markdown
- Schedules tab: list, toggle, run now, delete, create new
- Chat tab: coming soon placeholder

**Not yet built:**
- Real email send/read via Herald (IMAP/SMTP endpoints)
- Calendar integration
- Helm auto-provisioning flow in dashboard (agent creation wizard)
- API key management (for when Chat tab launches)
- Multi-model support (swap Claude for Ollama/other)
- Notes search (full-text, not just title/tag filter)
- Session save from within Console (currently done in Gouds vault)

---

## Pending: Email (TASK-003 in personal vault)

User: Zoho Mail, chris@goudie.me, read + send scope.
Required: IMAP (`imap.zoho.com:993`), SMTP (`smtp.zoho.com:465`), Zoho App Password.
New endpoints needed: `/api/email-inbox`, `/api/email-send`.
Dashboard: Inbox view, compose panel.
Status: waiting on build decision from user — see `vaults/personal/tasks/TASK-003-*.md`.
