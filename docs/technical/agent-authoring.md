# Agent Authoring

Agents in Console are plain `.md` files with YAML frontmatter. The model reads the profile and adopts that persona for the duration of the task. There is no code to write — only a document that describes who the agent is and how they work.

---

## Where agents live

```
agents/                        ← global agents (all vaults)
    Orchestrator.md
    Helm.md
    Scout.md

vaults/<id>/agents/            ← vault-scoped agents (this vault only)
    Herald.md
    Scout.md
    BookWorm.md
```

Vault-scoped agents override globals of the same name. If both `agents/Scout.md` and `vaults/personal/agents/Scout.md` exist, the vault version wins for all tasks in the `personal` vault.

Use global agents for infrastructure roles that apply everywhere (Orchestrator, Helm). Use vault-scoped agents for roles where context matters — a Herald with personal email credentials, a Scout with domain-specific instructions.

---

## Frontmatter fields

```yaml
---
type: agent-profile
agent: AgentName
role: Short role description
status: Active
emoji: 🔍
reports_to: Orchestrator
---
```

| Field | Required | Description |
|-------|----------|-------------|
| `type` | Yes | Must be `agent-profile` |
| `agent` | Yes | The agent's name (PascalCase). Used to match profiles to task assignments |
| `role` | Yes | One-line role description. Shown in the Agents tab and org chart |
| `status` | No | `Active` (default) or `Inactive`. Inactive agents still appear but are visually dimmed |
| `emoji` | No | Single emoji shown on agent cards. Falls back to 🤖 if omitted |
| `reports_to` | No | Name of the parent agent in the org chart. Falls back to the `ORG_REPORTS_TO` table in `server.py` |

---

## Profile structure

A typical agent profile follows this layout:

```markdown
---
type: agent-profile
agent: Scout
role: Research Agent
status: Active
emoji: 🔍
reports_to: Orchestrator
---

# 🔍 Scout — Research Agent

> *"No question too obscure, no source unchecked."*

---

## Role

One or two paragraphs describing what Scout does and why they exist.

---

## Personality

How Scout communicates. Tone, voice, tendencies. This shapes how the model writes outputs.

---

## Responsibilities

- Bullet list of what Scout handles
- Be specific enough that routing is unambiguous

---

## Research Process

Step-by-step instructions for how Scout approaches a task.

1. Clarify scope — what exactly is being researched and why
2. Identify sources — web search, document review, synthesis
3. Cross-check key claims
4. Write a structured output with sources listed

---

## Output Standards

What a well-formed Scout output looks like:
- Executive summary first
- Sources cited inline
- Confidence indicators where appropriate

---

## Scope

What Scout handles and what it explicitly does not handle (to avoid scope creep between agents).
```

---

## Tagline

The line `> *"Quoted tagline here."*` is parsed by the server and shown on agent cards in the dashboard. Keep it short — one sentence, in character.

---

## Practical guidelines

**Be specific about responsibilities.** Vague profiles produce vague outputs. "Handle research" is worse than "Use web search to find primary sources, cross-check with at least two sources, and produce a structured summary with inline citations."

**Include output format instructions.** The model will follow them. If you want a specific structure — executive summary, then sources, then confidence rating — say so explicitly in the profile.

**Define scope boundaries.** Tell the agent what it does NOT handle. This is especially important for agents that overlap (Scout vs. Analyst, Herald vs. Scribe).

**Match personality to purpose.** A Herald writing client-facing emails should have different personality instructions than a Scout producing internal research notes.

**Avoid tool instructions that don't exist.** The agent can read and write files (via `--permission-mode bypassPermissions`), run web searches (via Claude's built-in tools), and interact with the filesystem. Don't instruct the agent to call APIs or run commands it doesn't have access to.

---

## Global infrastructure agents

These three agents should not be modified without understanding their role in the dispatch flow:

**Orchestrator** — reads the task queue, triages by complexity (trivial tasks handled directly; substantive tasks dispatched), routes to the correct agent, writes outputs back to task files. The entry point for all dispatch cycles.

**Helm** — resource manager. When the Orchestrator identifies a capability gap, it routes to Helm. Helm either identifies an existing agent that fits or designs a new profile. The Helm tab in the dashboard uses Helm's profile to power the review and create-agent flows.

**Scout** (global) — general-purpose research fallback. Vault-scoped Scouts override this with domain-specific instructions.

---

## Vault-scoped agent conventions

**Herald** — email and communications. Configure with the vault's email provider, address, and tone. The personal Herald knows it's writing from `chris@example.com` via Zoho; the work Herald knows it's writing from a corporate M365 account with formal tone.

**Scout** — domain-specific research. The personal Scout handles consumer topics; the work Scout handles competitive and industry research.

**BookWorm** — vault librarian. Files completed task outputs to `vaults/<id>/notes/`. Knows the five categories (`Daily Briefs`, `Research`, `Reference`, `Decisions`, `Inbox`) and the portable note format. Should never use `[[wikilinks]]` or Obsidian callout blocks.

---

## Creating an agent via the dashboard

1. Go to the **Helm** tab
2. Under **Create new agent**, describe the capability you need
3. Helm designs a profile and shows it for review
4. Edit if needed, then click **Save agent**

The agent appears immediately in the Agents tab and is available for task assignment.

---

## Creating an agent manually

Create a `.md` file in `agents/` (global) or `vaults/<id>/agents/` (vault-scoped):

```bash
# Global
touch agents/Analyst.md

# Vault-scoped
touch vaults/personal/agents/Analyst.md
```

Then edit the file using the Files tab or your editor. The agent appears in the dashboard immediately — no restart required.

To wire a new agent into the org chart, either:
- Add `reports_to: Orchestrator` to its frontmatter (preferred), or
- Add it to the `ORG_REPORTS_TO` dict in `app/server.py`

---

## Note format (BookWorm standard)

Every note filed by BookWorm must follow this format:

```markdown
---
date: YYYY-MM-DD
type: daily-brief | research | reference | decision | misc
source: TASK-NNN | scheduled
tags: [tag1, tag2]
---

# Title

Content in plain CommonMark.
No [[wikilinks]].
No > [!callout] blocks.
```

Filed to `vaults/<id>/notes/<Category>/YYYY-MM-DD - Title.md` for dated content, or `Topic.md` for reference material without a date.
