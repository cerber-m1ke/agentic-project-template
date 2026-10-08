"""tb hook <name> — handlers for agent hooks. A hook must never block the user: always exit 0."""

from __future__ import annotations

import argparse
import json
import sys

import common

MIN_PROMPT_CHARS = 12
MAX_QUERY_CHARS = 2000
SUGGEST_LIMIT = 3
MIN_SCORE = 3.0        # BM25 score that qualifies a single-term match on its own
MIN_RELATIVE = 0.5     # a suggestion must score at least this share of the best match
HEADER = "Knowledge notes that may be relevant (open with: Toolbox/tb kb show <path>):"


def read_prompt() -> str:
    if sys.stdin is None or sys.stdin.isatty():
        return ""
    raw = sys.stdin.buffer.read().decode("utf-8", errors="replace").strip()
    if not raw:
        return ""
    try:
        data = json.loads(raw)
    except ValueError:
        return raw
    if isinstance(data, dict):
        prompt = data.get("prompt")
        return prompt if isinstance(prompt, str) else ""
    return data if isinstance(data, str) else ""


def suggest(prompt: str) -> list[tuple[str, str]]:
    """Return [(path, title)] of notes worth mentioning for this prompt."""
    import kb

    prompt = prompt.strip()
    if len(prompt) < MIN_PROMPT_CHARS or prompt[0] in "/$":
        return []
    notes = kb.load_notes(warn_missing=False)
    if not notes:
        return []
    hits = kb.run_search(prompt[:MAX_QUERY_CHARS], notes, limit=SUGGEST_LIMIT * 2, snippets=False)
    if not hits:
        return []
    # BM25 scores grow with corpus size (idf), so a small Knowledge base never reaches an absolute floor:
    # accept a hit by term coverage (2+ query terms, one of them in title/aliases/tags/description) or by score.
    floor = hits[0].score * MIN_RELATIVE
    good = [h for h in hits
            if h.score >= floor and h.strong and (len(h.matched) >= 2 or h.score >= MIN_SCORE)]
    return [(h.note.rel, h.note.title) for h in good[:SUGGEST_LIMIT]]


def kb_suggest(_args: argparse.Namespace) -> None:
    found = suggest(read_prompt())
    if found:
        common.out(HEADER)
        for path, title in found:
            common.out(f"- {path} — {title}")


HANDLERS = {"kb-suggest": kb_suggest}


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
