#!/usr/bin/env python3
"""Console — local-first AI agent operating system. HTTP server."""

import collections
import datetime
import json
import os
import re
import socketserver
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT          = Path(__file__).parent.parent   # Console/
AGENTS_DIR    = ROOT / "agents"
VAULTS_DIR    = ROOT / "vaults"
SETTINGS_FILE = ROOT / "settings.json"
SCHEDULES_FILE = ROOT / "schedules.json"
LOG_FILE      = ROOT / "console.log"
APP_DIR       = Path(__file__).parent

# ── Activity log ──────────────────────────────────────────────────────────

_log_buf  = collections.deque(maxlen=500)
_log_seq  = 0
_log_lock = threading.Lock()

def log_event(event_type, msg, level="info"):
    global _log_seq
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _log_lock:
        _log_seq += 1
        entry = {"seq": _log_seq, "ts": ts, "level": level, "type": event_type, "msg": msg}
        _log_buf.append(entry)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except Exception:
        pass

def get_log_entries(since=0):
    with _log_lock:
        return [e for e in _log_buf if e["seq"] > since]

# ── Settings ──────────────────────────────────────────────────────────────

def load_settings():
    if SETTINGS_FILE.exists():
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    else:
        data = {
            "user": {"name": "Console User", "email": ""},
            "console": {"name": "My Console", "port": 7842},
            "active_vault": "personal",
            "vaults": [{"id": "personal", "name": "Personal", "description": ""}],
        }
    data.setdefault("dispatch", {"poll_interval": 60, "auto_dispatch": False})
    return data

def save_settings(data):
    _atomic_write(SETTINGS_FILE, json.dumps(data, indent=2, ensure_ascii=False))

# ── Schedules ─────────────────────────────────────────────────────────────

def load_schedules():
    if SCHEDULES_FILE.exists():
        return json.loads(SCHEDULES_FILE.read_text(encoding="utf-8"))
    return {"schedules": []}

def save_schedules(data):
    _atomic_write(SCHEDULES_FILE, json.dumps(data, indent=2, ensure_ascii=False))

def next_schedule_id():
    data = load_schedules()
    nums = [int(m.group()) for s in data.get("schedules", [])
            for m in [re.search(r"\d+", s.get("id", ""))] if m]
    return f"SCH-{(max(nums) + 1):03d}" if nums else "SCH-001"

def get_vault_path(vault_id=None):
    if vault_id is None:
        vault_id = load_settings().get("active_vault", "personal")
    return VAULTS_DIR / vault_id

def get_port():
    return load_settings().get("console", {}).get("port", 7842)

# ── Helpers ───────────────────────────────────────────────────────────────

def today():
    return datetime.date.today().isoformat()

def now_ts():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

def _atomic_write(path, content):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)

def parse_frontmatter(text):
    m = re.match(r"^---\n(.*?)\n---\n?", text, re.DOTALL)
    if not m:
        return {}
    fm = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip()
    return fm

# ── Task helpers ──────────────────────────────────────────────────────────

VALID_STATUSES = {"pending", "in-progress", "waiting-input", "blocked", "done"}

def tasks_dir(vault_id=None):
    return get_vault_path(vault_id) / "tasks"

def next_task_id(vault_id=None):
    td = tasks_dir(vault_id)
    td.mkdir(parents=True, exist_ok=True)
    nums = []
    for f in td.glob("TASK-*.md"):
        m = re.search(r"TASK-(\d+)", f.stem)
        if m:
            nums.append(int(m.group(1)))
    return f"TASK-{(max(nums) + 1):03d}" if nums else "TASK-001"

def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48]

def build_task_file(fm, sections):
    waiting_section = ""
    if fm.get("status") == "waiting-input" or sections.get("waiting_for_input"):
        wfi = sections.get("waiting_for_input") or ""
        waiting_section = f"\n---\n\n## Waiting For Input\n\n{wfi}\n"
    qa_score_line    = f"\nqa_score: {fm['qa_score']}"       if fm.get("qa_score")    else ""
    user_rating_line = f"\nuser_rating: {fm['user_rating']}" if fm.get("user_rating") else ""
    return f"""---
id: {fm.get('id', '')}
title: {fm.get('title', '')}
status: {fm.get('status', 'pending')}
assigned_to: {fm.get('assigned_to', 'Orchestrator')}
priority: {fm.get('priority', 'Medium')}
created: {fm.get('created', today())}
updated: {fm.get('updated', today())}{qa_score_line}{user_rating_line}
type: task
---

## Request

{sections.get('request', '').strip()}

---

## Context

{sections.get('context', '—').strip()}

---

## Progress Log

{sections.get('progress_log', '').strip()}
{waiting_section}
---

## Output

{sections.get('output', '*Pending.*').strip()}
"""

def parse_task_file(text):
    fm = parse_frontmatter(text)
    body = re.sub(r"^---\n.*?\n---\n?", "", text, flags=re.DOTALL).strip()

    def extract(heading):
        pattern = rf"## {heading}\n(.*?)(?=\n---\n|\Z)"
        m = re.search(pattern, body, re.DOTALL)
        return m.group(1).strip() if m else ""

    return fm, {
        "request":           extract("Request"),
        "context":           extract("Context"),
        "progress_log":      extract("Progress Log"),
        "waiting_for_input": extract("Waiting For Input"),
        "output":            extract("Output"),
    }

def find_task_file(task_id, vault_id=None):
    td = tasks_dir(vault_id)
    safe = re.sub(r"[^A-Z0-9-]", "", task_id.upper())
    matches = list(td.glob(f"{safe}-*.md"))
    if matches:
        return matches[0]
    exact = td / f"{safe}.md"
    return exact if exact.exists() else None

def _output_preview(output_text):
    text = output_text.strip()
    if not text or text in ("*Pending.*", "*In progress.*"):
        return ""
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*{1,2}(.+?)\*{1,2}", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    for line in text.splitlines():
        line = line.strip().lstrip("-•1234567890. ")
        if line and (" " in line or len(line) > 30):
            return line[:120] + ("…" if len(line) > 120 else "")
    return ""

def _extract_question(wfi_text):
    m = re.search(r"\*\*Question:\*\*\s*(.+?)(?:\n|$)", wfi_text)
    return m.group(1).strip() if m else ""

# ── Task CRUD ─────────────────────────────────────────────────────────────

def get_tasks(vault_id=None):
    td = tasks_dir(vault_id)
    td.mkdir(parents=True, exist_ok=True)
    result = []
    for f in sorted(td.glob("TASK-*.md")):
        text = f.read_text(encoding="utf-8")
        fm, sections = parse_task_file(text)
        result.append({
            "id":             fm.get("id", f.stem),
            "title":          fm.get("title", ""),
            "status":         fm.get("status", "pending"),
            "assigned_to":    fm.get("assigned_to", ""),
            "priority":       fm.get("priority", "Medium"),
            "created":        fm.get("created", ""),
            "updated":        fm.get("updated", ""),
            "file":           f.name,
            "waiting_question": _extract_question(sections.get("waiting_for_input", "")),
            "output_preview": _output_preview(sections.get("output", "")),
            "qa_score":       fm.get("qa_score"),
            "user_rating":    fm.get("user_rating"),
        })
    return result

def get_task(task_id, vault_id=None):
    f = find_task_file(task_id, vault_id)
    if not f:
        return None
    text = f.read_text(encoding="utf-8")
    fm, sections = parse_task_file(text)
    return {**fm, "sections": sections, "file": f.name}

def create_task(title, request, context="", priority="Medium", assigned_to="Orchestrator", vault_id=None):
    task_id = next_task_id(vault_id)
    fm = {"id": task_id, "title": title, "status": "pending",
          "assigned_to": assigned_to, "priority": priority,
          "created": today(), "updated": today()}
    sections = {
        "request": request, "context": context or "—",
        "progress_log": f"- **{now_ts()}** — Task created. Assigned to {assigned_to}.",
        "waiting_for_input": "", "output": "*Pending.*",
    }
    dest = tasks_dir(vault_id) / f"{task_id}-{slugify(title)}.md"
    dest.write_text(build_task_file(fm, sections), encoding="utf-8")
    log_event("task", f"{task_id} created: {title!r} → {assigned_to} [{vault_id or 'active'}]")
    return task_id

def append_progress(task_id, entry, vault_id=None):
    f = find_task_file(task_id, vault_id)
    if not f:
        return False
    text = f.read_text(encoding="utf-8")
    fm, sections = parse_task_file(text)
    log = sections.get("progress_log", "").strip()
    sections["progress_log"] = f"{log}\n- **{now_ts()}** — {entry}".strip()
    fm["updated"] = today()
    _atomic_write(f, build_task_file(fm, sections))
    return True

def set_task_status(task_id, new_status, vault_id=None):
    if new_status not in VALID_STATUSES:
        return False, f"Invalid status: {new_status}"
    f = find_task_file(task_id, vault_id)
    if not f:
        return False, "Task not found"
    text = f.read_text(encoding="utf-8")
    fm, sections = parse_task_file(text)
    old_status = fm.get("status", "pending")
    if old_status == "waiting-input" and new_status != "waiting-input":
        wfi = sections.get("waiting_for_input", "").strip()
        if wfi:
            q = _extract_question(wfi)
            log = sections.get("progress_log", "").strip()
            sections["progress_log"] = f"{log}\n- **{now_ts()}** — Left waiting-input. Question: {q[:80]}".strip()
        sections["waiting_for_input"] = ""
    fm["status"] = new_status
    fm["updated"] = today()
    log = sections.get("progress_log", "").strip()
    sections["progress_log"] = f"{log}\n- **{now_ts()}** — Status → {new_status}.".strip()
    _atomic_write(f, build_task_file(fm, sections))
    log_event("task", f"{task_id} status: {old_status!r} → {new_status!r}")
    if new_status == "done":
        resolved_vault = vault_id or load_settings().get("active_vault", "personal")
        threading.Thread(target=_file_task_output, args=(task_id, resolved_vault), daemon=True).start()
        threading.Thread(target=_qa_task_output,   args=(task_id, resolved_vault), daemon=True).start()
    return True, "ok"

def answer_task(task_id, answer, vault_id=None):
    f = find_task_file(task_id, vault_id)
    if not f:
        return False
    text = f.read_text(encoding="utf-8")
    fm, sections = parse_task_file(text)
    wfi = sections.get("waiting_for_input", "")
    if "**Your Answer:**" in wfi:
        wfi = re.sub(r"\*\*Your Answer:\*\*.*", f"**Your Answer:** {answer}", wfi, flags=re.DOTALL)
    else:
        wfi = f"{wfi}\n\n**Your Answer:** {answer}"
    sections["waiting_for_input"] = wfi.strip()
    short = answer[:80] + ("…" if len(answer) > 80 else "")
    log = sections.get("progress_log", "").strip()
    sections["progress_log"] = f"{log}\n- **{now_ts()}** — User answered: {short}. Status → in-progress.".strip()
    fm["status"] = "in-progress"
    fm["updated"] = today()
    _atomic_write(f, build_task_file(fm, sections))
    log_event("task", f"{task_id} answered → in-progress")
    return True

def rate_task(task_id, rating, vault_id=None):
    f = find_task_file(task_id, vault_id)
    if not f:
        return False
    rating = max(1, min(5, int(rating)))
    text = f.read_text(encoding="utf-8")
    fm, sections = parse_task_file(text)
    fm["user_rating"] = rating
    fm["updated"] = today()
    log = sections.get("progress_log", "").strip()
    stars = "★" * rating + "☆" * (5 - rating)
    sections["progress_log"] = f"{log}\n- **{now_ts()}** — User rating: {stars} ({rating}/5).".strip()
    _atomic_write(f, build_task_file(fm, sections))
    log_event("task", f"{task_id} rated {rating}/5")
    return True

def _qa_task_output(task_id, vault_id):
    """Background: run a QA evaluation on a completed task output."""
    f = find_task_file(task_id, vault_id)
    if not f:
        return
    text = f.read_text(encoding="utf-8")
    fm, sections = parse_task_file(text)
    request = sections.get("request", "").strip()[:500]
    output  = sections.get("output",  "").strip()[:1500]
    agent   = fm.get("assigned_to", "Orchestrator")
    if not output or output in ("*Pending.*", "*In progress.*"):
        return
    prompt = (
        f"You are a QA reviewer for an AI agent operating system.\n\n"
        f"Task: {fm.get('title','')}\nAssigned agent: {agent}\n\n"
        f"Original request:\n{request}\n\nAgent output:\n{output}\n\n"
        f"Rate the output 1-5 and give a one-sentence summary.\n"
        f"1=Failed 2=Poor 3=Adequate 4=Good 5=Excellent\n\n"
        f"Respond in this exact format (nothing else):\n"
        f"SCORE: [number]\nSUMMARY: [one sentence]"
    )
    log_event("qa", f"QA evaluating {task_id} ({agent})")
    try:
        stdout, _, code = run_claude(prompt, timeout=60, vault_id=vault_id)
        score_m   = re.search(r"SCORE:\s*([1-5])", stdout or "")
        summary_m = re.search(r"SUMMARY:\s*(.+)", stdout or "")
        if score_m:
            score = int(score_m.group(1))
            summary = summary_m.group(1).strip() if summary_m else ""
            # Re-read file in case it changed (BookWorm may have run too)
            text2 = f.read_text(encoding="utf-8")
            fm2, sections2 = parse_task_file(text2)
            fm2["qa_score"] = score
            fm2["updated"]  = today()
            log2 = sections2.get("progress_log", "").strip()
            stars = "★" * score + "☆" * (5 - score)
            sections2["progress_log"] = f"{log2}\n- **{now_ts()}** — QA: {stars} ({score}/5) — {summary}".strip()
            _atomic_write(f, build_task_file(fm2, sections2))
            log_event("qa", f"{task_id} scored {score}/5: {summary[:80]}")
        else:
            log_event("qa", f"{task_id} QA parse failed", level="warn")
    except Exception as e:
        log_event("qa", f"{task_id} QA error: {e}", level="error")

def get_agent_stats(vault_id=None):
    """Aggregate qa_score and user_rating per agent across completed tasks."""
    tasks = get_tasks(vault_id)
    stats = {}
    for task in tasks:
        if task.get("status") != "done":
            continue
        agent = task.get("assigned_to") or "Orchestrator"
        if agent not in stats:
            stats[agent] = {"task_count": 0, "qa_scores": [], "user_ratings": []}
        stats[agent]["task_count"] += 1
        try:
            if task.get("qa_score"):
                stats[agent]["qa_scores"].append(float(task["qa_score"]))
        except (ValueError, TypeError):
            pass
        try:
            if task.get("user_rating"):
                stats[agent]["user_ratings"].append(float(task["user_rating"]))
        except (ValueError, TypeError):
            pass

    threshold, min_scored = 3.5, 3
    result = []
    for name, data in stats.items():
        all_scores = data["qa_scores"] + data["user_ratings"]
        qa_avg  = sum(data["qa_scores"])    / len(data["qa_scores"])    if data["qa_scores"]    else None
        rat_avg = sum(data["user_ratings"]) / len(data["user_ratings"]) if data["user_ratings"] else None
        overall = sum(all_scores) / len(all_scores) if all_scores else None
        needs_review = bool(overall and overall < threshold and len(all_scores) >= min_scored)
        result.append({
            "name":         name,
            "task_count":   data["task_count"],
            "qa_avg":       round(qa_avg,  2) if qa_avg  is not None else None,
            "rating_avg":   round(rat_avg, 2) if rat_avg is not None else None,
            "overall_avg":  round(overall, 2) if overall is not None else None,
            "scored_tasks": len(all_scores),
            "needs_review": needs_review,
        })
    result.sort(key=lambda x: (not x["needs_review"], -x["task_count"]))
    return result

# ── Agent data ────────────────────────────────────────────────────────────

AGENT_EMOJIS = {
    "Orchestrator": "🎯", "Scout": "🔍", "Herald": "✉️",
    "Helm": "🧭", "Scribe": "✍️", "Analyst": "📊",
}

# Global fallback — agents can also declare reports_to in their frontmatter
ORG_REPORTS_TO = {
    "Orchestrator": None,
    "Helm":         "Orchestrator",
    "Scout":        "Orchestrator",
    "Herald":       "Orchestrator",
}

def vault_agents_dir(vault_id=None):
    return get_vault_path(vault_id) / "agents"

def _read_agent_file(f, scope, vault_id=None):
    text = f.read_text(encoding="utf-8")
    fm = parse_frontmatter(text)
    name = fm.get("agent", f.stem)
    tagline_match = re.search(r'> \*"(.+?)"\*', text)
    reports_to = fm.get("reports_to") or ORG_REPORTS_TO.get(name)
    return {
        "name":       name,
        "role":       fm.get("role", ""),
        "status":     fm.get("status", "Active"),
        "emoji":      fm.get("emoji", AGENT_EMOJIS.get(name, "🤖")),
        "tagline":    tagline_match.group(1) if tagline_match else "",
        "file":       f.name,
        "reports_to": reports_to,
        "scope":      scope,
        "vault":      vault_id if scope == "vault" else None,
    }

def get_agents(vault_id=None):
    agents = {}
    # Global agents first
    for f in sorted(AGENTS_DIR.glob("*.md")):
        a = _read_agent_file(f, "global")
        agents[a["name"]] = a
    # Vault agents override globals of the same name
    vad = vault_agents_dir(vault_id)
    if vad.exists():
        resolved_id = vault_id or load_settings().get("active_vault", "personal")
        for f in sorted(vad.glob("*.md")):
            a = _read_agent_file(f, "vault", resolved_id)
            agents[a["name"]] = a
    return sorted(agents.values(), key=lambda a: a["name"])

def get_org_chart(vault_id=None):
    agent_map = {a["name"]: {**a, "children": []} for a in get_agents(vault_id)}
    root = None
    for name, agent in agent_map.items():
        parent = agent.get("reports_to")
        if parent is None:
            root = name
        elif parent in agent_map:
            agent_map[parent]["children"].append(agent)
    return agent_map.get(root or "Orchestrator", {})

def get_agent_content(name, vault_id=None):
    safe = re.sub(r"[^A-Za-z0-9 _-]", "", name)
    # Vault-specific agent takes priority
    if vault_id:
        vf = vault_agents_dir(vault_id) / f"{safe}.md"
        if vf.exists():
            return vf.read_text(encoding="utf-8"), "vault"
    gf = AGENTS_DIR / f"{safe}.md"
    if gf.exists():
        return gf.read_text(encoding="utf-8"), "global"
    return None, None

def save_agent_content(name, content, vault_id=None, scope="vault"):
    safe = re.sub(r"[^A-Za-z0-9 _-]", "", name)
    if scope == "vault" and vault_id:
        d = vault_agents_dir(vault_id)
        d.mkdir(parents=True, exist_ok=True)
        f = d / f"{safe}.md"
    else:
        f = AGENTS_DIR / f"{safe}.md"
    f.write_text(content, encoding="utf-8")
    return True

# ── Inbox ─────────────────────────────────────────────────────────────────

def get_inbox(vault_id=None):
    inbox_file = get_vault_path(vault_id) / "inbox" / "inbox.md"
    if not inbox_file.exists():
        return []
    text = inbox_file.read_text(encoding="utf-8")
    tasks, in_table = [], False
    for line in text.splitlines():
        if line.startswith("| Date |"):
            in_table = True; continue
        if in_table and line.startswith("|---"):
            continue
        if in_table and line.startswith("|"):
            cols = [c.strip() for c in line.strip("|").split("|")]
            if len(cols) >= 5 and any(cols):
                date, task, priority, status, agent = (cols + [""] * 5)[:5]
                if task:
                    tasks.append({"date": date, "task": task,
                                  "priority": priority or "Medium",
                                  "status": status or "Pending", "agent": agent})
        elif in_table:
            in_table = False
    return tasks

# ── Outbox ────────────────────────────────────────────────────────────────

def outbox_file(vault_id=None):
    return get_vault_path(vault_id) / "outbox" / "outbox.md"

def parse_outbox(vault_id=None):
    of = outbox_file(vault_id)
    if not of.exists():
        return []
    text = of.read_text(encoding="utf-8")
    text = re.sub(r"^---\n.*?\n---\n?", "", text, flags=re.DOTALL).strip()
    blocks = re.split(r"\n---\n", text)
    entries = []
    for block in blocks:
        block = block.strip()
        if not block or block.startswith("#"):
            continue
        block = re.sub(r"^-{3,}\n+", "", block)
        if not block:
            continue
        parts = re.split(r"\n\n", block, maxsplit=1)
        header = parts[0]
        body = parts[1].strip() if len(parts) > 1 else ""
        entry = {}
        for m in re.finditer(r"\*\*(\w+):\*\*\s*([^|*\n]+)", header):
            entry[m.group(1).lower()] = m.group(2).strip()
        if not entry.get("id"):
            continue
        entry["body"] = body
        entries.append(entry)
    return entries

def next_outbox_id(vault_id=None):
    entries = parse_outbox(vault_id)
    nums = [int(m.group()) for e in entries
            for m in [re.search(r"\d+", e.get("id", ""))] if m]
    return f"OUT-{(max(nums) + 1):03d}" if nums else "OUT-001"

def add_outbox_entry(task_id, agent, entry_type, to_addr, subject, body, vault_id=None):
    oid = next_outbox_id(vault_id)
    block = (
        f"\n---\n\n"
        f"**id:** {oid} | **task:** {task_id} | **agent:** {agent} | **date:** {today()}\n"
        f"**type:** {entry_type}\n**to:** {to_addr}\n**subject:** {subject}\n\n{body}\n"
    )
    of = outbox_file(vault_id)
    if not of.exists():
        of.write_text("---\ntype: outbox\n---\n\n# Outbox\n\nDrafts awaiting review.\n" + block, encoding="utf-8")
    else:
        current = re.sub(r'\n-{3,}\s*$', '', of.read_text(encoding="utf-8").rstrip())
        _atomic_write(of, current + block)
    return oid

def discard_outbox_entry(oid, vault_id=None):
    of = outbox_file(vault_id)
    if not of.exists():
        return False
    text = of.read_text(encoding="utf-8")
    fm_match = re.match(r"^(---\n.*?\n---\n?)(.*)", text, re.DOTALL)
    fm_header, body = (fm_match.group(1), fm_match.group(2)) if fm_match else ("", text)
    parts = body.split("\n---\n")
    filtered = [p for p in parts if f"**id:** {oid}" not in p]
    _atomic_write(of, fm_header + "\n---\n".join(filtered))
    return True

# ── Sessions ──────────────────────────────────────────────────────────────

def get_sessions(vault_id=None):
    sessions_dir = get_vault_path(vault_id) / "sessions"
    if not sessions_dir.exists():
        return []
    result = []
    for f in sorted(sessions_dir.glob("*.md"), reverse=True)[:20]:
        text = f.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        result.append({
            "title":  f.stem,
            "date":   fm.get("creation date", fm.get("date", "")),
            "domain": fm.get("domain", ""),
            "topic":  fm.get("topic", f.stem),
        })
    return result

# ── Vault info ────────────────────────────────────────────────────────────

EMPTY_INTEGRATIONS = {
    "email":    {"provider": None, "address": None},
    "calendar": {"provider": None, "address": None},
}

DEFAULT_MODEL = {"api_key": None, "model_id": "claude-sonnet-4-6"}

def get_vault_config(vault_id=None):
    if vault_id is None:
        vault_id = load_settings().get("active_vault", "personal")
    vf = VAULTS_DIR / vault_id / "vault.json"
    if vf.exists():
        data = json.loads(vf.read_text(encoding="utf-8"))
    else:
        data = {"id": vault_id, "integrations": {}, "apps": []}
    # Ensure integrations keys always present
    data.setdefault("integrations", {})
    for key, default in EMPTY_INTEGRATIONS.items():
        data["integrations"].setdefault(key, dict(default))
    data.setdefault("apps", [])
    data.setdefault("model", dict(DEFAULT_MODEL))
    return data

def save_vault_config(vault_id, data):
    vf = VAULTS_DIR / vault_id / "vault.json"
    _atomic_write(vf, json.dumps(data, indent=2, ensure_ascii=False))

def get_vaults():
    settings = load_settings()
    active = settings.get("active_vault", "personal")
    result = []
    for v in settings.get("vaults", []):
        cfg = get_vault_config(v["id"])
        model_cfg = dict(cfg.get("model", DEFAULT_MODEL))
        model_cfg.pop("api_key", None)  # never send the key to the frontend via vault list
        result.append({
            **v,
            "active": v["id"] == active,
            "integrations": cfg.get("integrations", {}),
            "model": model_cfg,
            "has_api_key": bool(cfg.get("model", {}).get("api_key")),
        })
    return result

# ── Notes ─────────────────────────────────────────────────────────────────

NOTES_CATEGORIES = ["Daily Briefs", "Research", "Reference", "Decisions", "Inbox"]

def notes_dir(vault_id=None):
    return get_vault_path(vault_id) / "notes"

def get_notes(vault_id=None):
    nd = notes_dir(vault_id)
    result = []
    for category in NOTES_CATEGORIES:
        cat_dir = nd / category
        if not cat_dir.exists():
            continue
        for f in sorted(cat_dir.glob("*.md"), reverse=True):
            text = f.read_text(encoding="utf-8")
            fm = parse_frontmatter(text)
            result.append({
                "title":    f.stem,
                "category": category,
                "path":     f"{category}/{f.name}",
                "date":     fm.get("date", ""),
                "type":     fm.get("type", ""),
                "source":   fm.get("source", ""),
                "tags":     fm.get("tags", ""),
            })
    return result

def get_note(rel_path, vault_id=None):
    nd = notes_dir(vault_id)
    f = (nd / rel_path).resolve()
    if not str(f).startswith(str(nd.resolve())):
        return None
    return f.read_text(encoding="utf-8") if f.exists() else None

# ── File browser ──────────────────────────────────────────────────────────

TREE_EXCLUDE_DIRS = {".git", ".trash", "__pycache__", "node_modules", ".tmp"}
TREE_EXCLUDE_EXTS = {".tmp", ".pyc", ".pyo"}

MIME_MAP = {
    "md":"text/plain; charset=utf-8", "txt":"text/plain; charset=utf-8",
    "py":"text/plain; charset=utf-8", "js":"text/plain; charset=utf-8",
    "json":"text/plain; charset=utf-8", "html":"text/plain; charset=utf-8",
    "css":"text/plain; charset=utf-8", "sh":"text/plain; charset=utf-8",
    "yaml":"text/plain; charset=utf-8", "yml":"text/plain; charset=utf-8",
    "csv":"text/plain; charset=utf-8", "toml":"text/plain; charset=utf-8",
    "pdf":"application/pdf",
    "png":"image/png", "jpg":"image/jpeg", "jpeg":"image/jpeg",
    "gif":"image/gif", "webp":"image/webp", "svg":"image/svg+xml",
}

def build_vault_tree(vault_id=None):
    root = get_vault_path(vault_id)
    return _tree_children(root, "")

def _tree_children(path, rel):
    children = []
    try:
        items = sorted(path.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
    except PermissionError:
        return []
    for item in items:
        name = item.name
        if name.startswith(".") or name in TREE_EXCLUDE_DIRS:
            continue
        rel_path = f"{rel}/{name}" if rel else name
        if item.is_dir():
            children.append({"name": name, "path": rel_path, "type": "dir",
                              "children": _tree_children(item, rel_path)})
        elif item.is_file():
            if item.suffix.lower() in TREE_EXCLUDE_EXTS or name in TREE_EXCLUDE_EXTS:
                continue
            children.append({"name": name, "path": rel_path, "type": "file",
                              "ext": item.suffix.lower().lstrip(".")})
    return children

def safe_vault_file_path(rel_path, vault_id=None):
    """Validate path for reading — file must exist."""
    root = get_vault_path(vault_id).resolve()
    resolved = (root / rel_path).resolve()
    if not str(resolved).startswith(str(root)):
        raise ValueError("Path outside vault")
    if not resolved.exists():
        raise FileNotFoundError("File not found")
    return resolved

def safe_vault_write_path(rel_path, vault_id=None):
    """Validate path for writing — file need not exist yet."""
    root = get_vault_path(vault_id).resolve()
    resolved = (root / rel_path).resolve()
    if not str(resolved).startswith(str(root)):
        raise ValueError("Path outside vault")
    return resolved

def save_vault_file(rel_path, content, vault_id=None):
    p = safe_vault_write_path(rel_path, vault_id)
    editable = {".md", ".txt", ".json", ".yaml", ".yml", ".py", ".sh", ".css", ".js"}
    if p.suffix.lower() not in editable:
        raise ValueError("File type not editable")
    p.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(p, content)
    return True

# ── Auto-filing ───────────────────────────────────────────────────────────

def _file_task_output(task_id, vault_id):
    """Background: ask Claude to file a completed task output via BookWorm."""
    prompt = (
        f"A task has just completed: {task_id} in the {vault_id} vault. "
        f"Act as BookWorm. Read the task file from vaults/{vault_id}/tasks/, "
        f"read the BookWorm agent profile at vaults/{vault_id}/agents/BookWorm.md, "
        f"determine the correct category and title, then create the note at "
        f"vaults/{vault_id}/notes/[Category]/[Title].md using the standard portable "
        f"note format (YAML frontmatter + CommonMark only, no wikilinks or callouts)."
    )
    log_event("bookworm", f"Filing {task_id} ({vault_id} vault)…")
    try:
        stdout, stderr, code = run_claude(prompt, timeout=180, vault_id=vault_id)
        if code == 0:
            log_event("bookworm", f"Filed {task_id} ✓")
        else:
            log_event("bookworm", f"Filed {task_id} — exit {code}: {(stderr or stdout)[:200]}", level="warn")
    except Exception as e:
        log_event("bookworm", f"Failed to file {task_id}: {e}", level="error")

# ── Task watcher ──────────────────────────────────────────────────────────

CLAUDE_BIN = subprocess.run(
    ["which", "claude"], capture_output=True, text=True
).stdout.strip() or "claude"

def run_claude(prompt, timeout=300, vault_id=None):
    """Run claude --print non-interactively from the Console root.
    If the vault has an api_key configured, it is passed as ANTHROPIC_API_KEY."""
    env = None
    if vault_id:
        key = get_vault_config(vault_id).get("model", {}).get("api_key")
        if key:
            env = {**os.environ, "ANTHROPIC_API_KEY": key}
    result = subprocess.run(
        f'echo {json.dumps(prompt)} | {CLAUDE_BIN} --print --permission-mode bypassPermissions',
        shell=True, cwd=str(ROOT), capture_output=True, text=True, timeout=timeout, env=env,
    )
    return result.stdout, result.stderr, result.returncode


def _post_dispatch_hooks(vault_id):
    """After dispatch, fire QA + BookWorm for tasks that became done via file writes
    (bypassing set_task_status). Only targets tasks with no qa_score yet."""
    try:
        tasks = get_tasks(vault_id)
        for t in tasks:
            if t.get("status") == "done" and not t.get("qa_score"):
                tid = t["id"]
                log_event("qa", f"Post-dispatch QA for {tid}")
                threading.Thread(target=_qa_task_output,   args=(tid, vault_id), daemon=True).start()
                threading.Thread(target=_file_task_output, args=(tid, vault_id), daemon=True).start()
    except Exception as e:
        log_event("system", f"_post_dispatch_hooks error: {e}", level="warn")


class TaskWatcher(threading.Thread):
    """Background thread: polls task folders, auto-dispatches when configured."""

    def __init__(self):
        super().__init__(daemon=True, name="TaskWatcher")
        self._lock = threading.Lock()
        self._status = {
            "pending": 0,
            "in_progress": 0,
            "waiting_input": 0,
            "last_check": None,
            "last_dispatch": None,
            "dispatching": False,
            "poll_interval": 0,
            "watching": False,
        }

    def run(self):
        while True:
            settings = load_settings()
            interval = int(settings.get("dispatch", {}).get("poll_interval", 0))
            if interval > 0:
                self._check(settings)
                time.sleep(interval)
            else:
                time.sleep(15)

    def _count_tasks(self, settings):
        counts = {"pending": 0, "in_progress": 0, "waiting_input": 0}
        for vault in settings.get("vaults", []):
            for task in get_tasks(vault["id"]):
                s = task.get("status", "")
                if s == "pending":         counts["pending"]       += 1
                elif s == "in-progress":   counts["in_progress"]   += 1
                elif s == "waiting-input": counts["waiting_input"] += 1
        return counts

    def _check(self, settings):
        counts = self._count_tasks(settings)
        auto = settings.get("dispatch", {}).get("auto_dispatch", False)
        with self._lock:
            self._status.update({
                **counts,
                "last_check": now_ts(),
                "poll_interval": int(settings.get("dispatch", {}).get("poll_interval", 0)),
                "watching": True,
            })
        if auto and counts["pending"] > 0:
            self._dispatch()

    def _dispatch(self, vault_id=None):
        with self._lock:
            if self._status.get("dispatching"):
                return  # already running
            self._status["dispatching"] = True
        effective_vault = vault_id or load_settings().get("active_vault", "personal")
        log_event("dispatch", f"Dispatch started [{effective_vault}]")
        try:
            stdout, stderr, code = run_claude("/dispatch", vault_id=effective_vault)
            first_line = (stdout or "").strip().splitlines()[0][:120] if (stdout or "").strip() else ""
            if code == 0:
                log_event("dispatch", f"Dispatch complete ✓{' — ' + first_line if first_line else ''}")
            else:
                log_event("dispatch", f"Dispatch exit {code}: {(stderr or first_line)[:200]}", level="warn")
            with self._lock:
                self._status["last_dispatch"] = {
                    "time": now_ts(),
                    "output": stdout[-3000:] if stdout else "",
                    "error": stderr[-500:] if stderr else "",
                    "exit_code": code,
                }
        except subprocess.TimeoutExpired:
            log_event("dispatch", "Dispatch timed out", level="error")
            with self._lock:
                self._status["last_dispatch"] = {
                    "time": now_ts(), "output": "", "error": "Dispatch timed out", "exit_code": -1
                }
        finally:
            with self._lock:
                self._status["dispatching"] = False
            # Re-count after dispatch
            self._check(load_settings())
            # Fire QA + BookWorm for any tasks that became done without going
            # through set_task_status (claude --print writes files directly)
            _post_dispatch_hooks(effective_vault)

    def get_status(self):
        with self._lock:
            return dict(self._status)

    def force_check(self):
        self._check(load_settings())

    def force_dispatch(self, vault_id=None):
        threading.Thread(target=self._dispatch, args=(vault_id,), daemon=True).start()


watcher = TaskWatcher()
watcher.start()

# ── Scheduler ─────────────────────────────────────────────────────────────

class Scheduler(threading.Thread):
    """Background thread: fires scheduled tasks at configured times."""

    def __init__(self):
        super().__init__(daemon=True, name="Scheduler")

    def run(self):
        while True:
            try:
                self._tick()
            except Exception:
                pass
            time.sleep(60)

    def _tick(self):
        data = load_schedules()
        now = datetime.datetime.now()
        today_str = now.date().isoformat()
        current_hhmm = now.strftime("%H:%M")
        changed = False

        for sched in data.get("schedules", []):
            if not sched.get("enabled", True):
                continue
            last_run = sched.get("last_run") or ""
            sched_time = sched.get("time", "08:00")
            frequency = sched.get("schedule", "daily")

            due = False
            if frequency == "daily":
                due = last_run < today_str and current_hhmm >= sched_time

            if due:
                self._fire(sched)
                sched["last_run"] = today_str
                changed = True

        if changed:
            save_schedules(data)

    def _fire(self, sched):
        vault_id = sched.get("vault", "personal")
        log_event("schedule", f"Firing schedule: {sched.get('name')!r} ({vault_id} vault, {sched.get('schedule','daily')} @ {sched.get('time','08:00')})")
        create_task(
            sched.get("name", "Scheduled Task"),
            sched.get("prompt", ""),
            context=f"Scheduled {sched.get('schedule','daily')} at {sched.get('time','08:00')}",
            vault_id=vault_id,
        )
        watcher.force_dispatch(vault_id=vault_id)


scheduler = Scheduler()
scheduler.start()

# ── HTTP Handler ───────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def vault_id(self, qs):
        return qs.get("vault", [None])[0]

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        path = parsed.path
        vid = self.vault_id(qs)

        simple_routes = {
            "/api/agents":       lambda: get_agents(vid),
            "/api/org-chart":    lambda: get_org_chart(vid),
            "/api/vaults":       lambda: get_vaults(),
            "/api/settings":     lambda: load_settings(),
            "/api/vault-config": lambda: get_vault_config(vid),
            "/api/tasks":        lambda: get_tasks(vid),
            "/api/inbox":        lambda: get_inbox(vid),
            "/api/outbox":       lambda: parse_outbox(vid),
            "/api/sessions":     lambda: get_sessions(vid),
            "/api/vault-tree":   lambda: build_vault_tree(vid),
            "/api/status":       lambda: watcher.get_status(),
            "/api/schedules":    lambda: load_schedules(),
            "/api/notes":        lambda: get_notes(vid),
            "/api/agent-stats":  lambda: get_agent_stats(vid),
        }

        if path == "/api/log":
            since = int(qs.get("since", [0])[0])
            self.send_json({"entries": get_log_entries(since)})
            return

        if path == "/api/session-read":
            fname = qs.get("file", [""])[0]
            vault_id_s = vid or load_settings().get("active_vault", "personal")
            safe = re.sub(r"[^A-Za-z0-9 _\-.]", "", fname)
            # Sessions list returns f.stem (no extension) — always resolve to .md
            sf = VAULTS_DIR / vault_id_s / "sessions" / safe
            if sf.suffix != ".md":
                sf = sf.with_suffix(".md")
            if sf.exists():
                self.send_json({"content": sf.read_text(encoding="utf-8")})
            else:
                self.send_json({"error": "not found"}, 404)
            return

        if path in simple_routes:
            self.send_json(simple_routes[path]())

        elif path == "/api/agent-read":
            name = qs.get("name", [""])[0]
            content, scope = get_agent_content(name, vid)
            if content:
                self.send_json({"name": name, "content": content, "scope": scope, "vault": vid})
            else:
                self.send_json({"error": "not found"}, 404)

        elif path == "/api/task-read":
            task_id = re.sub(r"[^A-Z0-9-]", "", qs.get("id", [""])[0].upper())
            task = get_task(task_id, vid)
            self.send_json(task if task else {"error": "not found"}, 200 if task else 404)

        elif path == "/api/note-read":
            rel = qs.get("path", [""])[0]
            content = get_note(rel, vid)
            if content is not None:
                self.send_json({"path": rel, "content": content})
            else:
                self.send_json({"error": "not found"}, 404)

        elif path == "/api/vault-raw":
            rel = qs.get("path", [""])[0]
            try:
                f = safe_vault_file_path(rel, vid)
                ext = f.suffix.lower().lstrip(".")
                mime = MIME_MAP.get(ext, "application/octet-stream")
                data = f.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", len(data))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(data)
            except (ValueError, FileNotFoundError) as e:
                self.send_json({"error": str(e)}, 404)

        elif path in ("/", "/index.html"):
            html = (APP_DIR / "dashboard.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", len(html))
            self.end_headers()
            self.wfile.write(html)

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        vid = self.vault_id(qs)
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            self.send_json({"ok": False, "error": "invalid JSON"}, 400)
            return

        try:
            p = parsed.path
            if p == "/api/task-create":
                task_id = create_task(data["title"], data["request"],
                                      data.get("context", ""), data.get("priority", "Medium"),
                                      data.get("assigned_to", "Orchestrator"), vid)
                self.send_json({"ok": True, "id": task_id})

            elif p == "/api/task-answer":
                self.send_json({"ok": answer_task(data["id"], data["answer"], vid)})

            elif p == "/api/task-status":
                ok, msg = set_task_status(data["id"], data["status"], vid)
                self.send_json({"ok": ok, "msg": msg})

            elif p == "/api/task-progress":
                self.send_json({"ok": append_progress(data["id"], data["entry"], vid)})

            elif p == "/api/agent-save":
                scope = data.get("scope", "vault")
                target_vault = data.get("vault") or vid
                ok = save_agent_content(data["name"], data["content"], vault_id=target_vault, scope=scope)
                if ok:
                    log_event("agent", f"Saved agent {data['name']!r} ({scope}, {target_vault or 'global'})")
                self.send_json({"ok": ok})

            elif p == "/api/outbox-add":
                oid = add_outbox_entry(data["task_id"], data["agent"],
                                       data.get("type", "email"), data["to"],
                                       data["subject"], data["body"], vid)
                log_event("outbox", f"{oid} added: {data.get('type','email')} to {data.get('to','?')} — {data.get('subject','')[:60]}")
                self.send_json({"ok": True, "id": oid})

            elif p == "/api/outbox-discard":
                ok = discard_outbox_entry(data["id"], vid)
                if ok:
                    log_event("outbox", f"{data['id']} discarded")
                self.send_json({"ok": ok})

            elif p == "/api/vault-file-save":
                ok = save_vault_file(data["path"], data["content"], vid)
                if ok:
                    log_event("files", f"Saved {data['path']}")
                self.send_json({"ok": ok})

            elif p == "/api/settings-save":
                data.pop("integrations", None)
                save_settings(data)
                watcher.force_check()  # pick up new interval immediately
                log_event("system", "Settings saved")
                self.send_json({"ok": True})

            elif p == "/api/chat":
                message = data.get("message", "").strip()
                history = data.get("history", [])
                vault_id = data.get("vault") or vid or load_settings().get("active_vault", "personal")
                if not message:
                    self.send_json({"ok": False, "error": "no message"}, 400)
                    return
                orch_content, _ = get_agent_content("Orchestrator", vault_id)
                parts = []
                if orch_content:
                    parts.append(orch_content.strip())
                    parts.append("---")
                parts.append(
                    f"You are in a live chat session with your user through the Console dashboard ({vault_id} vault). "
                    "Respond conversationally and concisely. Use markdown formatting where it helps. "
                    "You can answer questions, suggest creating a task (but wait for confirmation before doing so), "
                    "or route to the right persona. Do not repeat the user's question back to them."
                )
                recent = history[-20:]  # last 10 exchanges
                if recent:
                    parts.append("\n## Conversation so far:")
                    for turn in recent:
                        label = "User" if turn["role"] == "user" else "Orchestrator"
                        parts.append(f"{label}: {turn['content']}")
                parts.append(f"\n## Current message:\nUser: {message}\n\nOrchestrator:")
                prompt = "\n\n".join(parts)
                log_event("chat", f"[{vault_id}] {message[:120]}")
                try:
                    stdout, stderr, code = run_claude(prompt, timeout=120, vault_id=vault_id)
                    response = (stdout or "").strip() or "(no response)"
                    log_event("chat", f"Response (exit {code}): {response[:100]}")
                    self.send_json({"ok": True, "response": response})
                except subprocess.TimeoutExpired:
                    log_event("chat", "Chat response timed out", level="error")
                    self.send_json({"ok": False, "error": "Timed out after 120s"})

            elif p == "/api/watcher-check":
                watcher.force_check()
                self.send_json({"ok": True, **watcher.get_status()})

            elif p == "/api/dispatch":
                watcher.force_dispatch(vault_id=vid)
                self.send_json({"ok": True, "msg": "Dispatch started in background"})

            elif p == "/api/claude":
                prompt = data.get("prompt", "").strip()
                if not prompt:
                    self.send_json({"ok": False, "error": "no prompt"}, 400)
                    return
                log_event("claude", f"Prompt: {prompt[:150]}")
                try:
                    stdout, stderr, code = run_claude(prompt, timeout=120, vault_id=vid)
                    first = (stdout or "").strip().splitlines()[0][:150] if (stdout or "").strip() else ""
                    log_event("claude", f"Response (exit {code})" + (f": {first}" if first else ""),
                              level="warn" if code != 0 else "info")
                    self.send_json({
                        "ok": code == 0,
                        "output": stdout,
                        "stderr": stderr,
                        "exit_code": code,
                    })
                except subprocess.TimeoutExpired:
                    log_event("claude", "Prompt timed out (120s)", level="error")
                    self.send_json({"ok": False, "output": "", "error": "Timed out (120s)", "exit_code": -1})

            elif p == "/api/vault-config-save":
                target_id = data.get("id") or vid or load_settings().get("active_vault")
                save_vault_config(target_id, data)
                log_event("system", f"Vault config saved: {target_id}")
                self.send_json({"ok": True})

            elif p == "/api/vault-add":
                settings = load_settings()
                new_vault = {"id": data["id"], "name": data["name"],
                             "description": data.get("description", "")}
                settings["vaults"].append(new_vault)
                save_settings(settings)
                vault_path = VAULTS_DIR / data["id"]
                for folder in ["tasks", "inbox", "outbox", "sessions"]:
                    (vault_path / folder).mkdir(parents=True, exist_ok=True)
                (vault_path / "inbox" / "inbox.md").write_text(
                    "---\ntype: inbox\n---\n\n# Inbox\n\n| Date | Task | Priority | Status | Agent |\n|------|------|----------|--------|-------|\n")
                (vault_path / "outbox" / "outbox.md").write_text(
                    "---\ntype: outbox\n---\n\n# Outbox\n\nDrafts awaiting review.\n")
                vault_config = {
                    **new_vault,
                    "integrations": dict(EMPTY_INTEGRATIONS),
                    "apps": [],
                }
                (vault_path / "vault.json").write_text(json.dumps(vault_config, indent=2))
                log_event("system", f"Vault created: {data['id']!r} ({data.get('name','')})")
                self.send_json({"ok": True})

            elif p == "/api/vault-switch":
                settings = load_settings()
                settings["active_vault"] = data["id"]
                save_settings(settings)
                log_event("system", f"Active vault → {data['id']}")
                self.send_json({"ok": True})

            elif p == "/api/schedule-save":
                sched_data = load_schedules()
                schedules = sched_data.get("schedules", [])
                sched = data.copy()
                if not sched.get("id"):
                    sched["id"] = next_schedule_id()
                existing = next((i for i, s in enumerate(schedules) if s["id"] == sched["id"]), None)
                if existing is not None:
                    old = schedules[existing]
                    time_changed = old.get("time") != sched.get("time") or old.get("schedule") != sched.get("schedule")
                    new_time_future = datetime.datetime.now().strftime("%H:%M") < sched.get("time", "00:00")
                    if time_changed and new_time_future:
                        sched["last_run"] = None  # new time is still ahead today — allow it to fire
                    schedules[existing] = sched
                    log_event("schedule", f"Updated schedule {sched['id']}: {sched.get('name','')!r} @ {sched.get('time','?')}")
                else:
                    schedules.append(sched)
                    log_event("schedule", f"Created schedule {sched['id']}: {sched.get('name','')!r} @ {sched.get('time','?')}")
                sched_data["schedules"] = schedules
                save_schedules(sched_data)
                self.send_json({"ok": True, "id": sched["id"]})

            elif p == "/api/schedule-delete":
                sched_data = load_schedules()
                sched_data["schedules"] = [s for s in sched_data.get("schedules", []) if s["id"] != data["id"]]
                save_schedules(sched_data)
                log_event("schedule", f"Deleted schedule {data['id']}", level="warn")
                self.send_json({"ok": True})

            elif p == "/api/schedule-toggle":
                sched_data = load_schedules()
                for s in sched_data.get("schedules", []):
                    if s["id"] == data["id"]:
                        s["enabled"] = not s.get("enabled", True)
                        log_event("schedule", f"Schedule {data['id']} {'enabled' if s['enabled'] else 'disabled'}")
                        break
                save_schedules(sched_data)
                self.send_json({"ok": True})

            elif p == "/api/schedule-run":
                sched_data = load_schedules()
                sched = next((s for s in sched_data.get("schedules", []) if s["id"] == data["id"]), None)
                if sched:
                    threading.Thread(target=scheduler._fire, args=(sched,), daemon=True).start()
                    self.send_json({"ok": True})
                else:
                    self.send_json({"ok": False, "error": "not found"}, 404)

            elif p == "/api/terminal":
                cmd = data.get("cmd", "").strip()
                if not cmd:
                    self.send_json({"stdout": "", "stderr": "", "exit_code": 0, "cwd": str(ROOT)})
                    return
                log_event("terminal", f"$ {cmd[:200]}")
                try:
                    result = subprocess.run(
                        cmd, shell=True, cwd=str(ROOT),
                        capture_output=True, text=True, timeout=30
                    )
                    out = (result.stdout or result.stderr or "").strip()
                    log_event("terminal", f"exit {result.returncode}" + (f": {out[:300]}" if out else ""),
                              level="error" if result.returncode != 0 else "info")
                    self.send_json({
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                        "exit_code": result.returncode,
                        "cwd": str(ROOT),
                    })
                except subprocess.TimeoutExpired:
                    log_event("terminal", f"Command timed out: {cmd[:80]}", level="error")
                    self.send_json({"stdout": "", "stderr": "Command timed out (30s limit)", "exit_code": 124, "cwd": str(ROOT)})

            elif p == "/api/log-clear":
                with _log_lock:
                    _log_buf.clear()
                self.send_json({"ok": True})

            elif p == "/api/task-rate":
                self.send_json({"ok": rate_task(data["id"], data["rating"], vid)})

            elif p == "/api/helm-review":
                agent_name = (data.get("agent_name") or data.get("agent") or "").strip()
                vault_id   = data.get("vault") or vid or load_settings().get("active_vault", "personal")
                if not agent_name:
                    self.send_json({"ok": False, "error": "no agent"}); return
                # Gather recent completed tasks for this agent
                tasks = [t for t in get_tasks(vault_id)
                         if t.get("status") == "done" and t.get("assigned_to") == agent_name][-15:]
                task_summaries = []
                for t in tasks:
                    full = get_task(t["id"], vault_id) or {}
                    req  = (full.get("sections") or {}).get("request", "")[:200]
                    out  = (full.get("sections") or {}).get("output",  "")[:300]
                    qa   = t.get("qa_score", "?")
                    rat  = t.get("user_rating", "?")
                    task_summaries.append(
                        f"- {t['id']}: {t['title']}\n  Request: {req}\n  Output: {out}\n  QA: {qa}/5  User: {rat}/5"
                    )
                profile_content, _ = get_agent_content(agent_name, vault_id)
                stats = next((s for s in get_agent_stats(vault_id) if s["name"] == agent_name), {})
                prompt = (
                    f"You are Helm, the Resource & Team Manager for Console.\n"
                    f"Review the {agent_name} agent's recent performance and rewrite their profile to improve it.\n\n"
                    f"## Current profile:\n{profile_content or '(none)'}\n\n"
                    f"## Recent completed tasks ({len(tasks)}):\n" + "\n".join(task_summaries) + "\n\n"
                    f"Performance: overall avg {stats.get('overall_avg','?')}/5 across {stats.get('scored_tasks',0)} scored tasks.\n\n"
                    f"Identify the patterns causing underperformance and rewrite the profile to address them.\n"
                    f"Respond in this exact format:\n\n"
                    f"DESCRIPTION: [2-3 sentences: what patterns you found and what you changed]\nPROFILE:\n[complete rewritten agent profile]"
                )
                log_event("helm", f"Reviewing agent: {agent_name}")
                try:
                    stdout, _, code = run_claude(prompt, timeout=120, vault_id=vault_id)
                    desc_m    = re.search(r"DESCRIPTION:\s*(.+?)(?=\nPROFILE:)", stdout or "", re.DOTALL)
                    profile_m = re.search(r"PROFILE:\n([\s\S]+)",                stdout or "")
                    if desc_m and profile_m:
                        log_event("helm", f"Review complete for {agent_name}")
                        self.send_json({
                            "ok": True,
                            "description": desc_m.group(1).strip(),
                            "profile":     profile_m.group(1).strip(),
                        })
                    else:
                        self.send_json({"ok": False, "error": "Could not parse Helm response", "raw": stdout})
                except subprocess.TimeoutExpired:
                    self.send_json({"ok": False, "error": "Timed out"})

            elif p == "/api/helm-create":
                description = data.get("description", "").strip()
                vault_id    = data.get("vault") or vid or load_settings().get("active_vault", "personal")
                if not description:
                    self.send_json({"ok": False, "error": "no description"}); return
                existing = "\n".join(
                    f"- {a['name']}: {a['role']}" for a in get_agents(vault_id)
                )
                prompt = (
                    f"You are Helm, the Resource & Team Manager for Console.\n"
                    f"A new capability is needed for the {vault_id} vault.\n\n"
                    f"## Existing agents:\n{existing}\n\n"
                    f"## Requested capability:\n{description}\n\n"
                    f"Create a new agent profile that fills this gap without duplicating existing agents.\n"
                    f"Respond in this exact format:\n\n"
                    f"AGENT_NAME: [PascalCase name]\n"
                    f"DESCRIPTION: [2-3 sentences: what gap this fills]\n"
                    f"PROFILE:\n[complete agent profile in markdown]"
                )
                log_event("helm", f"Creating new agent for: {description[:60]}")
                try:
                    stdout, _, code = run_claude(prompt, timeout=120, vault_id=vault_id)
                    name_m    = re.search(r"AGENT_NAME:\s*(\S+)",                   stdout or "")
                    desc_m    = re.search(r"DESCRIPTION:\s*(.+?)(?=\nPROFILE:)",    stdout or "", re.DOTALL)
                    profile_m = re.search(r"PROFILE:\n([\s\S]+)",                   stdout or "")
                    if name_m and desc_m and profile_m:
                        log_event("helm", f"New agent designed: {name_m.group(1)}")
                        self.send_json({
                            "ok":          True,
                            "agent_name":  name_m.group(1).strip(),
                            "description": desc_m.group(1).strip(),
                            "profile":     profile_m.group(1).strip(),
                        })
                    else:
                        self.send_json({"ok": False, "error": "Could not parse Helm response", "raw": stdout})
                except subprocess.TimeoutExpired:
                    self.send_json({"ok": False, "error": "Timed out"})

            else:
                self.send_response(404)
                self.end_headers()

        except KeyError as e:
            self.send_json({"ok": False, "error": f"missing field: {e}"}, 400)
        except Exception as e:
            self.send_json({"ok": False, "error": str(e)}, 500)


class _ReuseServer(socketserver.ThreadingMixIn, HTTPServer):
    allow_reuse_address = True
    daemon_threads = True  # don't block shutdown on in-flight requests

    def server_bind(self):
        import socket as _socket
        self.socket.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEPORT, 1)
        super().server_bind()


if __name__ == "__main__":
    port = get_port()
    server = _ReuseServer(("localhost", port), Handler)
    log_event("system", f"Console started on port {port}")
    print(f"Console → http://localhost:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log_event("system", "Console stopped")
        print("\nStopped.")
