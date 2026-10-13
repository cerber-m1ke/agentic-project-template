"""tb setup — prepare this machine for the project. Idempotent: rerun any time.

uv and Python are already provisioned into Runtime/ by Toolbox/tb before this runs.
Steps: git config, executable bits, agent adapters, Obsidian (if the module is installed), IDE excludes,
resources status (and optional clone).
"""

from __future__ import annotations

import argparse
import os
import platform
from pathlib import Path

import adapters
import agents
import common
import ide
import obsidian
import resources

GIT_HOOKS_DIR = ".agents/git-hooks"


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("setup", help="set up this machine: git, agents, Obsidian, IDE, resources",
                            description="Prepare this machine for the project (safe to rerun).")
    parser.add_argument("--agents", metavar="A,B",
                        help="adapters to link, comma-separated (default: .agents/local.toml)")
    parser.add_argument("--clone-missing", action="store_true",
                        help="clone catalogued git resources that are not cloned yet")
    parser.set_defaults(func=cmd_setup)


def _section(title: str) -> None:
    common.out(f"\n[{title}]")


def _git_config(root: Path) -> tuple[str, str]:
    top = common.git("rev-parse", "--show-toplevel")
    if top.returncode != 0 or Path(top.stdout.strip()).resolve() != root.resolve():
        common.out("  ! not the root of a git repository, skipped")
        return "!", "git config skipped: not a git repository root"
    wanted = {"core.hooksPath": GIT_HOOKS_DIR, "core.quotePath": "false"}
    if common.is_windows():
        wanted["core.longpaths"] = "true"
    changed = 0
    for key, value in wanted.items():
        if common.git("config", "--local", "--get", key).stdout.strip() == value:
            common.out(f"  ✓ {key} = {value}")
            continue
        result = common.git("config", "--local", key, value)
        if result.returncode != 0:
            common.fail(f"git config {key} {value}: {result.stderr.strip()}")
            return "✗", f"git config: cannot set {key}"
        common.out(f"  + {key} = {value}")
        changed += 1
    return "✓", f"git config{f' ({changed} changed)' if changed else ''}"


def _executable_bits(root: Path) -> tuple[str, str] | None:
    if common.is_windows():
        return None
    hooks_dir = root / GIT_HOOKS_DIR
    paths = [root / "Toolbox" / "tb"]
    if hooks_dir.is_dir():
        paths += sorted(p for p in hooks_dir.iterdir()
                        if p.is_file() and not p.name.startswith(".") and p.suffix != ".md")
    fixed = 0
    for path in paths:
        if not path.is_file():
            common.out(f"  ✗ {common.rel(path)} missing")
            return "✗", f"executable bits: {common.rel(path)} missing"
        if os.access(path, os.X_OK):
            continue
        path.chmod(path.stat().st_mode | 0o111)
        common.out(f"  + chmod +x {common.rel(path)}")
        fixed += 1
    if not fixed:
        common.out(f"  ✓ {len(paths)} file(s) executable")
    return "✓", f"executable bits{f' ({fixed} fixed)' if fixed else ''}"


def cmd_setup(args: argparse.Namespace) -> int:
    root = common.project_root()
    lock = common.load_lock() or {}
    project = lock.get("project", {})
    common.out(f"Setting up {project.get('name') or root.name} on this machine")
    summary: list[tuple[str, str]] = [("✓", f"runtime: Python {platform.python_version()} (uv)")]
    if not lock:
        summary.append(("!", f"{common.LOCK_PATH} missing: not initialized from the template"))

    _section("git")
    summary.append(_git_config(root))
    if not common.is_windows():
        _section("file modes")
    bits = _executable_bits(root)
    if bits:
        summary.append(bits)

    _section("agents")
    names = [n.strip() for n in args.agents.split(",") if n.strip()] if args.agents else None
    if not names and not agents.local_agents():
        available = ", ".join(adapters.discover(root)) or "none"
        common.out(f"  ! no agents selected — rerun: Toolbox/tb setup --agents <a,b> "
                   f"(available: {available})")
        summary.append(("!", "agents: none linked"))
    else:
        code = agents.link(names)
        linked = ", ".join(agents.local_agents())
        summary.append(("✓", f"agents: {linked}") if code == 0 else ("✗", f"agents: {linked} (see above)"))

    if "obsidian" in project.get("modules", []):
        _section("obsidian")
        code = obsidian.setup()
        summary.append(("✓", "obsidian vault config") if code == 0 else ("✗", "obsidian (see above)"))

    _section("ide")
    code = ide.setup()
    summary.append(("✓", f"ide: {', '.join(ide.EXCLUDED)} excluded from indexing") if code == 0
                   else ("✗", "ide (see above)"))

    _section("resources")
    missing, ok = resources.print_status()
    if not ok:
        summary.append(("✗", f"resources: {resources.CATALOG} is invalid"))
    elif missing and args.clone_missing:
        code = resources.clone(missing)
        summary.append(("✓", f"resources: cloned {len(missing)}") if code == 0
                       else ("✗", "resources: clone failed (see above)"))
    elif missing:
        summary.append(("!", f"resources: {len(missing)} not cloned — "
                             "Toolbox/tb resources clone <name> | --all"))
    else:
        summary.append(("✓", "resources: nothing to clone"))

    _section("summary")
    for mark, text in summary:
        common.out(f"  {mark} {text}")
    common.out("Next: Toolbox/tb agents doctor")
    return 1 if any(mark == "✗" for mark, _ in summary) else 0
