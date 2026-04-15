#!/usr/bin/env python3
"""PostToolUse hook for obsidian-master-kit.

Detects writes inside a vault marked with `.obsidian-master/marker.json` and injects
additionalContext into the conversation, prompting the Claude agent to invoke the
`obsidian-librarian` skill to sync the vault.

The hook does NOT invoke skills directly — Claude Code hooks can't call skills.
It only signals the agent that a sync is needed. This is the documented pattern.

Deduplication: emits context at most once per 5 seconds per vault, to avoid looping
when the agent makes a burst of edits.
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

DEDUPE_WINDOW_SECONDS = 5
RELEVANT_TOOLS = {"Write", "Edit", "NotebookEdit"}
MARKER_REL = pathlib.Path(".obsidian-master") / "marker.json"


def find_vault_root(file_path: pathlib.Path) -> pathlib.Path | None:
    cur = file_path.parent
    while cur != cur.parent:
        if (cur / MARKER_REL).exists():
            return cur
        cur = cur.parent
    return None


def should_emit(vault_root: pathlib.Path) -> bool:
    tracker = vault_root / ".obsidian-master" / "last-hook.txt"
    now = int(time.time())
    if tracker.exists():
        try:
            last = int(tracker.read_text().strip())
            if now - last < DEDUPE_WINDOW_SECONDS:
                return False
        except ValueError:
            pass
    tracker.parent.mkdir(parents=True, exist_ok=True)
    tracker.write_text(str(now))
    return True


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    tool_name = payload.get("tool_name", "")
    if tool_name not in RELEVANT_TOOLS:
        return 0

    tool_input = payload.get("tool_input", {}) or {}
    raw_path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    if not raw_path:
        return 0

    file_path = pathlib.Path(raw_path)
    vault_root = find_vault_root(file_path)
    if vault_root is None:
        return 0

    if not should_emit(vault_root):
        return 0

    message = (
        f"Voce acabou de escrever em um vault obsidian-master-kit "
        f"(raiz: `{vault_root}`). Arquivo modificado: `{file_path}`. "
        f"Invoque agora a skill `obsidian-librarian` para sincronizar o vault "
        f"(valida frontmatter, atualiza _INDEX.md, detecta orfas). "
        f"Execute: python3 ${{CLAUDE_PLUGIN_ROOT}}/skills/obsidian-librarian/"
        f"scripts/update_index.py --vault \"{vault_root}\""
    )

    output = {
        "continue": True,
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": message,
        },
    }
    sys.stdout.write(json.dumps(output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
