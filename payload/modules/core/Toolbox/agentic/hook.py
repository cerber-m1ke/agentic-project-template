"""tb hook <name> — handlers for agent hooks. A hook must never block the user: always exit 0."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import common

MIN_PROMPT_CHARS = 12
MAX_QUERY_CHARS = 2000
SUGGEST_LIMIT = 3
REMINDER_LIMIT = 2
MIN_SCORE = 3.0        # BM25 score that qualifies a single-term match on its own
MIN_RELATIVE = 0.5     # a suggestion must score at least this share of the best match
HEADER = "Knowledge notes that may be relevant (open with: Toolbox/tb kb show <path>):"
REMINDER_HEADER = "Reminders that overlap this request (mention them to the human if they fit the work):"
PATH_KEYS = ("file_path", "notebook_path", "path")
_PATCH_RE = re.compile(r"^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+?)\s*$", re.MULTILINE)


def read_input() -> dict | str:
    """Hook input: the JSON object agents send on stdin, or raw text."""
    if sys.stdin is None or sys.stdin.isatty():
        return ""
    raw = sys.stdin.buffer.read().decode("utf-8", errors="replace").strip()
    if not raw:
        return ""
    try:
        data = json.loads(raw)
    except ValueError:
        return raw
    return data if isinstance(data, (dict, str)) else ""


def read_prompt() -> str:
    data = read_input()
    if isinstance(data, dict):
        prompt = data.get("prompt")
        return prompt if isinstance(prompt, str) else ""
    return data


def _good(hits: list, limit: int) -> list:
    # BM25 scores grow with corpus size (idf), so a small Knowledge base never reaches an absolute floor:
    # accept a hit by term coverage (2+ query terms, one of them in title/aliases/tags/description) or by score.
    if not hits:
        return []
    floor = hits[0].score * MIN_RELATIVE
    return [h for h in hits
            if h.score >= floor and h.strong and (len(h.matched) >= 2 or h.score >= MIN_SCORE)][:limit]


def suggest_all(prompt: str) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """([(path, title)] of notes, [(path, title)] of reminders) worth mentioning for this prompt."""
    import kb

    prompt = prompt.strip()
    if len(prompt) < MIN_PROMPT_CHARS or prompt[0] in "/$":
        return [], []
    notes = kb.load_notes(warn_missing=False)
    if not notes:
        return [], []
    hits, _ = kb.SearchIndex(notes).search(prompt[:MAX_QUERY_CHARS])
    found = _good([h for h in hits if h.note.type != "reminder"], SUGGEST_LIMIT)
    reminders = _good([h for h in hits if h.note.type == "reminder"], REMINDER_LIMIT)

    def label(h) -> str:
        due = h.note.meta.get("due")
        return f"{h.note.title} (due {due})" if due else h.note.title

    return [(h.note.rel, h.note.title) for h in found], [(h.note.rel, label(h)) for h in reminders]


def suggest(prompt: str) -> list[tuple[str, str]]:
    """Return [(path, title)] of notes worth mentioning for this prompt."""
    return suggest_all(prompt)[0]


def kb_suggest(_args: argparse.Namespace) -> None:
    found, reminders = suggest_all(read_prompt())
    for header, items in ((HEADER, found), (REMINDER_HEADER, reminders)):
        if items:
            common.out(header)
            for path, title in items:
                common.out(f"- {path} — {title}")


# --- Knowledge commit guard: after-tool tracks edits, stop asks to commit them ---------------------

def edited_paths(data: dict) -> list[str]:
    """Knowledge files (root-relative) that an edit tool call touched, from the hook input."""
    root = common.project_root()
    base = Path(data["cwd"]) if isinstance(data.get("cwd"), str) else root
    raw: list[str] = []

    def walk(value) -> None:
        if isinstance(value, dict):
            for k, v in value.items():
                if k in PATH_KEYS and isinstance(v, str):
                    raw.append(v)
                else:
                    walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)
        elif isinstance(value, str) and "*** " in value:  # apply_patch text
            raw.extend(_PATCH_RE.findall(value))

    walk(data.get("tool_input"))
    result = []
    for item in raw:
        p = Path(item)
        rel = Path(os.path.relpath(os.path.abspath(p if p.is_absolute() else base / p), root)).as_posix()
        parts = rel.split("/")
        if parts[0] == common.KNOWLEDGE_DIR and len(parts) > 1 and ".obsidian" not in parts:
            result.append(rel)
    return list(dict.fromkeys(result))


def _session(data, args: argparse.Namespace) -> str | None:
    if not isinstance(data, dict) or not isinstance(data.get("session_id"), str) or not data["session_id"]:
        return None
    return f"{args.agent or 'agent'}:{data['session_id']}"


def kb_track(args: argparse.Namespace) -> None:
    import kb_git

    data = read_input()
    session = _session(data, args)
    if session and (paths := edited_paths(data)):
        kb_git.track(session, paths)


def kb_uncommitted(args: argparse.Namespace) -> None:
    import kb_git

    data = read_input()
    session = _session(data, args)
    if session is None or data.get("stop_hook_active"):
        return
    paths = kb_git.dirty(kb_git.tracked(session))
    marker = kb_git.session_file(session).with_suffix(".nudged")
    if not paths:
        marker.unlink(missing_ok=True)
        return
    state = kb_git.dirty_state(paths)
    if marker.is_file() and common.read_text(marker).strip() == state:
        return  # already asked about exactly these edits; the agent decided
    common.write_text(marker, state + "\n")
    reason = ("Knowledge notes edited in this session are not committed: " + ", ".join(paths) + ". "
              "Commit them now: Toolbox/tb kb commit <paths> -m \"<gist>\" [-m \"- point\"] "
              "(--amend corrects this session's earlier commit), then tell the human the commit. "
              "If they must stay uncommitted, tell the human why.")
    common.out(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))


HANDLERS = {"kb-suggest": kb_suggest, "kb-track": kb_track, "kb-uncommitted": kb_uncommitted}


def cmd_hook(args: argparse.Namespace) -> int:
    handler = HANDLERS.get(args.name or "")
    if handler is None:
        common.warn(f"unknown hook '{args.name or ''}' (known: {', '.join(HANDLERS)}); ignored")
        return 0
    try:
        handler(args)
    except Exception:  # never block the agent because of a hook
        pass
    return 0


def register(sub) -> None:
    p = sub.add_parser("hook", help="agent hook handlers (called by agent adapters)")
    p.add_argument("name", nargs="?", help="hook name: " + ", ".join(HANDLERS))
    p.add_argument("--agent", default="", help="calling agent (claude, codex, …)")
    p.set_defaults(func=cmd_hook)
