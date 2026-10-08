# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml>=6", "tomli-w>=1", "snowballstemmer>=2.2"]
# [tool.uv]
# exclude-newer = "2026-10-01T00:00:00Z"
# ///
"""tb — Toolbox entry point of an Agentic Project. Run via Toolbox/tb (or Toolbox\\tb.cmd)."""

from __future__ import annotations

import argparse
import importlib
import platform
import sys

import common

COMMAND_MODULES = ("kb", "agents", "resources", "machine", "obsidian", "update_cmd", "hook", "secret_scan")


def cmd_version(_args: argparse.Namespace) -> int:
    lock = common.load_lock()
    if not lock:
        common.out("agentic project: not initialized (no .agents/agentic.lock)")
    else:
        tpl, prj = lock.get("template", {}), lock.get("project", {})
        common.out(f"template: v{tpl.get('version', '?')} ({tpl.get('source') or 'unknown source'})")
        common.out(f"project:  {prj.get('name', '?')} [{prj.get('profile', '?')}, {prj.get('language', '?')}]")
        common.out(f"modules:  {', '.join(prj.get('modules', []))}")
    common.out(f"python:   {platform.python_version()}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tb", description="Agentic Project toolbox.")
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    sub.add_parser("version", help="show template and project info").set_defaults(func=cmd_version)
    for name in COMMAND_MODULES:
        try:
            module = importlib.import_module(name)
        except ModuleNotFoundError as exc:
            if exc.name == name:
                continue
            raise
        module.register(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    argv = sys.argv[1:] if argv is None else argv
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        # Agents run `tb hook …` on every prompt; exit code 2 would block the user's prompt in Claude Code.
        if argv[:1] == ["hook"] and exc.code:
            return 0
        raise
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
