#!/usr/bin/env python3
"""Console — entry point CLI. Usage: python console.py [init|start|status]"""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent
SETTINGS_FILE = ROOT / "settings.json"
VAULTS_DIR = ROOT / "vaults"
APP_DIR = ROOT / "app"


def ask(prompt, default=""):
    try:
        val = input(f"{prompt}" + (f" [{default}]" if default else "") + ": ").strip()
        return val or default
    except (KeyboardInterrupt, EOFError):
        print()
        sys.exit(0)


def scaffold_vault(vault_id, name, description=""):
    vp = VAULTS_DIR / vault_id
    for folder in ["tasks", "inbox", "outbox", "sessions"]:
        (vp / folder).mkdir(parents=True, exist_ok=True)
    (vp / "inbox" / "inbox.md").write_text(
        "---\ntype: inbox\n---\n\n# Inbox\n\n"
        "| Date | Task | Priority | Status | Agent |\n"
        "|------|------|----------|--------|-------|\n",
        encoding="utf-8",
    )
    (vp / "outbox" / "outbox.md").write_text(
        "---\ntype: outbox\n---\n\n# Outbox\n\nDrafts awaiting review.\n",
        encoding="utf-8",
    )
    (vp / "vault.json").write_text(
        json.dumps({"id": vault_id, "name": name, "description": description}, indent=2),
        encoding="utf-8",
    )
    print(f"  ✓ vault/{vault_id}/")


def cmd_init():
    print("\nConsole — first-time setup\n")

    if SETTINGS_FILE.exists():
        overwrite = ask("settings.json already exists. Reinitialise? (y/N)", "N")
        if overwrite.lower() != "y":
            print("Aborted.")
            return

    user_name  = ask("Your name", "Console User")
    user_email = ask("Your email (optional)", "")
    console_name = ask("Console name", "My Console")
    port = ask("Port", "7842")
    try:
        port = int(port)
    except ValueError:
        port = 7842

    print("\nVault setup — vaults separate work from personal tasks.")
    print("You can add more vaults later from the dashboard.\n")

    vaults = []
    vault_id = ask("First vault ID (no spaces)", "personal")
    vault_name = ask("Vault display name", vault_id.capitalize())
    vault_desc = ask("Vault description (optional)", "")
    vaults.append({"id": vault_id, "name": vault_name, "description": vault_desc})

    add_more = ask("Add another vault? (y/N)", "N")
    while add_more.lower() == "y":
        vid  = ask("Vault ID", "")
        if not vid:
            break
        vn   = ask("Display name", vid.capitalize())
        vd   = ask("Description (optional)", "")
        vaults.append({"id": vid, "name": vn, "description": vd})
        add_more = ask("Add another? (y/N)", "N")

    settings = {
        "user":         {"name": user_name, "email": user_email},
        "console":      {"name": console_name, "port": port},
        "active_vault": vaults[0]["id"],
        "vaults":       vaults,
        "integrations": {"email": {"provider": None, "address": None}},
    }
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n  ✓ settings.json")

    print("\nScaffolding vaults...")
    for v in vaults:
        scaffold_vault(v["id"], v["name"], v["description"])

    print(f"\nDone. Run `python console.py start` to launch Console on port {port}.\n")


def cmd_start():
    if not SETTINGS_FILE.exists():
        print("No settings.json found. Run `python console.py init` first.")
        sys.exit(1)
    server_path = APP_DIR / "server.py"
    if not server_path.exists():
        print(f"server.py not found at {server_path}")
        sys.exit(1)
    os.execv(sys.executable, [sys.executable, str(server_path)])


def cmd_status():
    if not SETTINGS_FILE.exists():
        print("Not initialised. Run: python console.py init")
        return
    settings = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    port = settings.get("console", {}).get("port", 7842)
    active = settings.get("active_vault", "—")
    vaults = [v["id"] for v in settings.get("vaults", [])]
    print(f"Console: {settings['console']['name']}")
    print(f"Port:    {port}  →  http://localhost:{port}")
    print(f"Active vault: {active}")
    print(f"Vaults: {', '.join(vaults)}")
    print(f"Agents: {len(list((ROOT / 'agents').glob('*.md')))}")


COMMANDS = {"init": cmd_init, "start": cmd_start, "status": cmd_status}

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "start"
    if cmd not in COMMANDS:
        print(f"Usage: python console.py [{' | '.join(COMMANDS)}]")
        sys.exit(1)
    COMMANDS[cmd]()
