"""tb agents — connect agent adapters on this machine: list, link, unlink, doctor.

Adapters: `.agents/adapters/<name>/adapter.toml` + renderer `adapters/<name>.py`.
Agents linked on this machine are stored in `.agents/local.toml` (`agents = [...]`), with the
sha256 of every file tb wrote (`[generated] "<path>" = "<sha>"`). A generated file is replaced or
removed only while its content still matches that hash (or, with no hash recorded, equals a fresh
render); a file changed outside tb is left alone and reported until the user resolves it or reruns
with --force (the old file is kept as `<file>.bak`).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

import adapters
import common

LINK_HINT = "run Toolbox/tb agents link"
GENERATED_KEY = "generated"


def _modified(verb: str = "link") -> str:
    return ("modified outside tb, left untouched — move your changes into .agents/ (or a local "
            "override such as .claude/settings.local.json), then delete the file or run "
            f"Toolbox/tb agents {verb} --force (keeps a .bak copy)")

SHADOW_FILES = ("CLAUDE.md", ".claude/CLAUDE.md", "CLAUDE.local.md")


# --- CLI ---------------------------------------------------------------------------

def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("agents", help="agent adapters: list | link | unlink | doctor",
                            description="Connect agents (Claude Code, Codex, …) to this project.")
    actions = parser.add_subparsers(dest="agents_action", metavar="<action>")
    actions.add_parser("list", help="available adapters and whether they are linked here") \
        .set_defaults(func=cmd_list)
    p = actions.add_parser("link", help="create links and generate agent configs (idempotent)")
    p.add_argument("names", nargs="*", metavar="agent",
                   help="adapters to link (default: agents from .agents/local.toml)")
    p.add_argument("--force", action="store_true",
                   help="also replace generated files changed outside tb (saved as <file>.bak)")
    p.set_defaults(func=cmd_link)
    p = actions.add_parser("unlink", help="remove generated configs and links of agents")
    p.add_argument("names", nargs="*", metavar="agent",
                   help="adapters to unlink (default: agents from .agents/local.toml)")
    p.add_argument("--force", action="store_true",
                   help="also remove generated files changed outside tb (moved to <file>.bak)")
    p.set_defaults(func=cmd_unlink)
    actions.add_parser("doctor", help="check that links and generated files are in place") \
        .set_defaults(func=cmd_doctor)
    parser.set_defaults(func=lambda _args: (parser.print_help(), 0)[1])


def cmd_list(_args: argparse.Namespace) -> int:
    available = adapters.discover(common.project_root())
    linked = local_agents()
    if not available:
        common.out(f"No adapters in {adapters.ADAPTERS_DIR}/.")
        return 0
    rows = [(name, str(m.get("title", name)), f"tier {m.get('tier', '?')}",
             "linked" if name in linked else "not linked") for name, m in available.items()]
    widths = [max(len(row[i]) for row in rows) for i in range(3)]
    for row in rows:
        common.out("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row[:3])) + "  " + row[3])
    for name in linked:
        if name not in available:
            common.warn(f"{common.LOCAL_PATH} lists {name!r}, but there is no such adapter")
    return 0


def cmd_link(args: argparse.Namespace) -> int:
    return link(args.names or None, force=args.force)


def cmd_unlink(args: argparse.Namespace) -> int:
    return unlink(args.names or None, force=args.force)


# --- local.toml ------------------------------------------------------------------------

def local_agents() -> list[str]:
    agents = common.load_local().get("agents", [])
    return [str(a) for a in agents] if isinstance(agents, list) else []


def generated_hashes() -> dict[str, str]:
    """local.toml [generated]: path relative to the root -> sha256 of the content tb wrote."""
    table = common.load_local().get(GENERATED_KEY, {})
    return {str(k): str(v) for k, v in table.items()} if isinstance(table, dict) else {}


def _save_local(names: list[str], generated: dict[str, str]) -> None:
    data = common.load_local()
    new = dict(data)
    if names or "agents" in data:
        new["agents"] = names
    new.pop(GENERATED_KEY, None)
    if generated:
        new[GENERATED_KEY] = dict(sorted(generated.items()))
    if new != data:
        common.save_local(new)


# --- skill links ----------------------------------------------------------------------------

def _link_parts(link: Path) -> tuple[str, ...]:
    try:
        return Path(os.readlink(link)).parts
    except (OSError, ValueError):
        return ()


def _is_skill_link(link: Path) -> bool:
    """A link made by tb: it points to .../.agents/skills/<name>."""
    return common.is_link(link) and _link_parts(link)[-3:-1] == (".agents", "skills")


def _is_skills_dir_link(link: Path) -> bool:
    """An old-style link of the whole skills directory: .../.agents/skills."""
    return common.is_link(link) and _link_parts(link)[-2:] == (".agents", "skills")


def _sync_skills(root: Path, manifest: dict[str, Any], skills: list[str],
                 apply: bool) -> tuple[list[str], list[str], int]:
    """Per-skill links. Returns (changes, problems, links_ok). Never touches non-link entries."""
    changes: list[str] = []
    problems: list[str] = []
    section = manifest.get("skills", {})
    if section.get("mode") != "link":
        return changes, problems, 0
    if section.get("granularity", "per-skill") != "per-skill":
        problems.append(f"[skills] granularity {section.get('granularity')!r} is not supported")
        return changes, problems, 0
    target_rel = str(section["target"])
    target = root / target_rel
    source_rel = adapters.SKILLS_DIR

    if common.is_link(target):
        if not _is_skills_dir_link(target):
            problems.append(f"{target_rel}: a link to elsewhere, skills not linked")
            return changes, problems, 0
        if not apply:
            problems.append(f"{target_rel}: links the whole skills directory — {LINK_HINT}")
            return changes, problems, 0
        common.remove_link(target)
        changes.append(f"- remove {target_rel} (directory link, replaced by per-skill links)")
    elif target.exists() and not target.is_dir():
        problems.append(f"{target_rel}: not a directory, skills not linked")
        return changes, problems, 0

    ok = 0
    for name in skills:
        link, want, shown = target / name, root / source_rel / name, f"{target_rel}/{name}"
        if common.link_points_to(link, want):
            ok += 1
            continue
        if common.is_link(link) and not _is_skill_link(link):
            problems.append(f"{shown}: a link to elsewhere, left untouched")
        elif not common.is_link(link) and link.exists():
            problems.append(f"{shown}: not a link, shadows {source_rel}/{name} (remove or rename it)")
        elif not apply:
            problems.append(f"{shown}: link {'points elsewhere' if common.is_link(link) else 'missing'}"
                            f" — {LINK_HINT}")
        else:
            relinked = common.is_link(link)
            try:
                if relinked:
                    common.remove_link(link)
                kind = common.make_dir_link(link, want)
            except OSError as exc:
                problems.append(f"{shown}: cannot create link: {exc}")
                continue
            note = " (junction)" if kind == "junction" else ""
            changes.append(f"{'~ relink' if relinked else '+ link'} {shown} -> {source_rel}/{name}{note}")
            ok += 1

    if target.is_dir() and not common.is_link(target):
        for entry in sorted(target.iterdir()):
            if entry.name in skills or not _is_skill_link(entry) or entry.exists():
                continue
            shown = f"{target_rel}/{entry.name}"
            if apply:
                common.remove_link(entry)
                changes.append(f"- remove {shown} (target vanished)")
            else:
                problems.append(f"{shown}: stale link, target vanished — {LINK_HINT}")
    return changes, problems, ok


# --- generated files ----------------------------------------------------------------------------

def _read(path: Path) -> str | None:
    if not path.is_file() or path.is_symlink():
        return None
    try:
        return common.normalize_newlines(common.read_text(path))
    except (OSError, UnicodeDecodeError):
        return None


def _ownership(root: Path, path: str, rendered: str | None, generated: dict[str, str]) -> str:
    """absent | directory | ours | modified (changed outside tb) | foreign (never tb's file)."""
    file = root / path
    if not (file.exists() or common.is_link(file)):
        return "absent"
    if file.is_dir() and not common.is_link(file):
        return "directory"
    current = _read(file)  # None for links and unreadable files
    recorded = generated.get(path)
    if current is not None:
        if rendered is not None and current == rendered:
            return "ours"
        if recorded is not None and common.sha256_text(current) == recorded:
            return "ours"
    if recorded is None and rendered is None and (current is None or adapters.GENERATED_NOTE
                                                  not in current[:1000]):
        return "foreign"
    return "modified"


def _backup(root: Path, path: str) -> str:
    """Move <path> to <path>.bak (replacing an older .bak). Returns the backup path."""
    file = root / path
    bak = file.with_name(file.name + ".bak")
    if common.is_link(bak):
        common.remove_link(bak)
    elif bak.is_dir():
        raise OSError(f"{path}.bak is a directory")
    os.replace(file, bak)
    return f"{path}.bak"


def _sync_files(root: Path, manifest: dict[str, Any], rendered: dict[str, str],
                generated: dict[str, str], apply: bool,
                force: bool = False) -> tuple[list[str], list[str]]:
    """Write rendered files and remove obsolete ones, never touching files changed outside tb
    (unless forced). Updates `generated` (path -> sha256) when applying."""
    changes: list[str] = []
    problems: list[str] = []
    for path, content in rendered.items():
        file = root / path
        state = _ownership(root, path, content, generated)
        if state == "ours" and _read(file) == content:
            if apply:
                generated[path] = common.sha256_text(content)
            continue
        if state == "directory":
            problems.append(f"{path}: is a directory, not written")
            continue
        if state == "modified" and not force:
            problems.append(f"{path}: {_modified()}")
            continue
        if not apply:
            problems.append(f"{path}: {'missing' if state == 'absent' else 'stale'} — {LINK_HINT}")
            continue
        note = ""
        try:
            if state == "modified":
                note = f" (previous content saved to {_backup(root, path)})"
            common.write_text(file, content)
        except OSError as exc:
            problems.append(f"{path}: cannot write: {exc}")
            continue
        generated[path] = common.sha256_text(content)
        changes.append(f"{'+ write' if state == 'absent' else '~ update'} {path}{note}")
    for path in adapters.owned_files(root, manifest, generated):
        if path in rendered:
            continue
        state = _ownership(root, path, None, generated)
        if state in ("absent", "directory", "foreign"):
            if apply and state == "absent":
                generated.pop(path, None)
            continue
        if state == "modified" and not force:
            problems.append(f"{path}: no longer generated, but {_modified()}")
            continue
        if not apply:
            problems.append(f"{path}: obsolete generated file — {LINK_HINT}")
            continue
        try:
            if state == "modified":
                changes.append(f"- remove {path} (no longer generated; moved to {_backup(root, path)})")
            else:
                (root / path).unlink()
                changes.append(f"- remove {path} (no longer generated)")
        except OSError as exc:
            problems.append(f"{path}: cannot remove: {exc}")
            continue
        generated.pop(path, None)
    return changes, problems


def _remove_empty_dirs(root: Path, paths: list[str]) -> list[str]:
    """Remove empty directories on the given paths (deepest first), never under .agents/."""
    candidates: set[Path] = set()
    for path in paths:
        current = root / path
        while current != root and root in current.parents:
            if current.relative_to(root).parts[0] != ".agents":
                candidates.add(current)
            current = current.parent
    removed = []
    for folder in sorted(candidates, key=lambda p: len(p.parts), reverse=True):
        if folder.is_dir() and not common.is_link(folder) and not any(folder.iterdir()):
            folder.rmdir()
            removed.append(f"- remove {common.rel(folder)}/ (empty)")
    return removed


# --- link / unlink -----------------------------------------------------------------------------

def _resolve_names(names: list[str] | None, available: dict[str, dict], verb: str) -> list[str] | None:
    explicit = bool(names)
    names = list(dict.fromkeys(names or local_agents()))
    choices = ", ".join(available) or "none"
    if not names:
        common.fail(f"no agents selected — name them: Toolbox/tb agents {verb} <agent>… "
                    f"(available: {choices})")
        return None
    unknown = [n for n in names if n not in available]
    if unknown and verb == "link":
        if explicit:
            common.fail(f"unknown agent(s): {', '.join(unknown)} (available: {choices})")
            return None
        common.warn(f"{common.LOCAL_PATH} lists unknown agent(s) {', '.join(unknown)}, skipped "
                    f"— remove with Toolbox/tb agents unlink {' '.join(unknown)}")
        names = [n for n in names if n in available]
    return names


def link(names: list[str] | None = None, force: bool = False) -> int:
    """Link adapters on this machine (default: those in local.toml). Returns an exit code.
    force: also replace generated files changed outside tb (keeping <file>.bak)."""
    root = common.project_root()
    available = adapters.discover(root)
    selected = _resolve_names(names, available, "link")
    if selected is None:
        return 1
    failed = False
    generated = generated_hashes()
    for name in selected:
        manifest = available[name]
        ctx = adapters.load_context(root, name, manifest)
        rendered = adapters.render(ctx)
        changes, problems, _ = _sync_skills(root, manifest, ctx.skills, apply=True)
        file_changes, file_problems = _sync_files(root, manifest, rendered, generated,
                                                  apply=True, force=force)
        changes += file_changes
        problems += file_problems
        common.out(f"{name} ({manifest.get('title', name)})")
        for line in changes:
            common.out(f"  {line}")
        for line in problems:
            common.out(f"  ✗ {line}")
        if not changes and not problems:
            common.out("  ✓ up to date")
        if changes and manifest.get("link_hint"):
            common.out(f"  note: {manifest['link_hint']}")
        sys.stdout.flush()  # keep warnings next to their agent
        for message in dict.fromkeys(ctx.warnings):
            common.warn(f"{name}: {message}")
        failed = failed or bool(problems)
    _save_local(list(dict.fromkeys(local_agents() + selected)), generated)
    return 1 if failed else 0


def unlink(names: list[str] | None = None, force: bool = False) -> int:
    """Remove generated files and links of adapters; user files (settings.local.json, files
    changed outside tb, …) stay. force: move changed generated files to <file>.bak instead."""
    root = common.project_root()
    available = adapters.discover(root)
    if not names and not local_agents():
        common.out("No agents linked on this machine.")
        return 0
    selected = _resolve_names(names, available, "unlink")
    if selected is None:
        return 1
    generated = generated_hashes()
    failed = False
    for name in selected:
        manifest = available.get(name)
        common.out(f"{name} ({manifest.get('title', name) if manifest else 'adapter not found'})")
        if manifest is None:
            common.out("  ✓ removed from this machine's list")
            continue
        changes: list[str] = []
        problems: list[str] = []
        touched: list[str] = []
        section = manifest.get("skills", {})
        if section.get("mode") == "link":
            target_rel = str(section["target"])
            target = root / target_rel
            touched.append(target_rel)
            if _is_skills_dir_link(target):
                common.remove_link(target)
                changes.append(f"- remove {target_rel} (directory link)")
            elif target.is_dir() and not common.is_link(target):
                for entry in sorted(target.iterdir()):
                    if _is_skill_link(entry):
                        common.remove_link(entry)
                        changes.append(f"- remove {target_rel}/{entry.name}")
        # A fresh render recognises files generated before hashes were recorded.
        rendered = adapters.render(adapters.load_context(root, name, manifest))
        for path in adapters.owned_files(root, manifest, generated):
            state = _ownership(root, path, rendered.get(path), generated)
            if state in ("directory", "foreign"):
                continue
            if state == "modified" and not force:
                problems.append(f"{path}: {_modified('unlink')}")
                continue
            try:
                if state == "modified":
                    changes.append(f"- remove {path} (moved to {_backup(root, path)})")
                elif state == "ours":
                    (root / path).unlink()
                    changes.append(f"- remove {path}")
            except OSError as exc:
                problems.append(f"{path}: cannot remove: {exc}")
                continue
            generated.pop(path, None)
            touched.append(path)
        sub_target = manifest.get("subagents", {}).get("target")
        if sub_target:
            touched.append(str(sub_target))
        changes += _remove_empty_dirs(root, touched)
        for line in changes:
            common.out(f"  {line}")
        for line in problems:
            common.out(f"  ✗ {line}")
        if not changes and not problems:
            common.out("  ✓ nothing to remove")
        failed = failed or bool(problems)
    remaining = [n for n in local_agents() if n not in selected]
    _save_local(remaining, generated)
    return 1 if failed else 0


# --- doctor --------------------------------------------------------------------------------------

def _gitignore_block(root: Path) -> list[str] | None:
    path = root / ".gitignore"
    if not path.is_file():
        return None
    lines = common.normalize_newlines(common.read_text(path)).split("\n")
    start = next((i for i, line in enumerate(lines) if "agentic:begin" in line), None)
    if start is None:
        return lines
    end = next((i for i in range(start + 1, len(lines)) if "agentic:end" in lines[i]), len(lines))
    return lines[start + 1:end]


def _general_checks(root: Path, available: dict[str, dict], line) -> None:
    if (root / common.LOCK_PATH).is_file():
        line("✓", f"{common.LOCK_PATH} present")
    else:
        line("✗", f"{common.LOCK_PATH} missing — the project is not initialized from the template")

    top = common.git("rev-parse", "--show-toplevel")
    if top.returncode != 0:
        line("!", "not a git repository — git hooks are inactive")
    else:
        hooks_path = common.git("config", "--get", "core.hooksPath").stdout.strip()
        if hooks_path == ".agents/git-hooks":
            line("✓", "git core.hooksPath = .agents/git-hooks")
        else:
            line("✗", f"git core.hooksPath is {repr(hooks_path) if hooks_path else 'not set'}, "
                      "expected .agents/git-hooks — run Toolbox/tb setup")

    if not common.is_windows():
        tb = root / "Toolbox" / "tb"
        if not tb.is_file():
            line("✗", "Toolbox/tb missing")
        elif os.access(tb, os.X_OK):
            line("✓", "Toolbox/tb executable")
        else:
            line("✗", "Toolbox/tb not executable — run: sh Toolbox/tb setup")

    agents_md = root / "AGENTS.md"
    shadows = [name for name in SHADOW_FILES if (root / name).exists() or common.is_link(root / name)]
    for name in shadows:
        path = root / name
        if path.is_symlink() and agents_md.is_file() and path.resolve() == agents_md.resolve():
            line("✓", f"{name} is a link to AGENTS.md")
        else:
            line("!", f"{name} exists — Claude Code reads it instead of AGENTS.md "
                      "(delete it or make it a link to AGENTS.md)")
    if not shadows:
        line("✓", "no CLAUDE.md: Claude Code reads AGENTS.md")

    block = _gitignore_block(root)
    if block is None:
        line("✗", ".gitignore missing — generated agent files would be committed")
        return
    entries = {item.strip().strip("/") for item in block}
    missing = [f"{out} ({name})" for name, manifest in available.items()
               for out in manifest.get("outputs", []) if str(out).strip("/") not in entries]
    if missing:
        line("✗", f".gitignore managed block lacks: {', '.join(missing)}")
    else:
        line("✓", ".gitignore covers adapter outputs")


def cmd_doctor(_args: argparse.Namespace) -> int:
    root = common.project_root()
    available = adapters.discover(root)
    linked = local_agents()
    generated = generated_hashes()
    failures = 0

    def line(mark: str, message: str) -> None:
        nonlocal failures
        failures += mark == "✗"
        common.out(f"  {mark} {message}")

    if not linked:
        common.out("agents")
        line("!", f"no agents linked on this machine — run Toolbox/tb agents link <agent>… "
                  f"(available: {', '.join(available) or 'none'})")
    for name in linked:
        manifest = available.get(name)
        common.out(f"{name} ({manifest.get('title', name) if manifest else '?'})")
        if manifest is None:
            line("✗", f"{adapters.ADAPTERS_DIR}/{name}/adapter.toml not found — "
                      f"run Toolbox/tb agents unlink {name}")
            continue
        ctx = adapters.load_context(root, name, manifest)
        rendered = adapters.render(ctx)
        _, skill_problems, links_ok = _sync_skills(root, manifest, ctx.skills, apply=False)
        _, file_problems = _sync_files(root, manifest, rendered, generated, apply=False)
        if manifest.get("skills", {}).get("mode") == "link" and not skill_problems:
            line("✓", f"{links_ok} skill link(s) in {manifest['skills']['target']}")
        elif manifest.get("skills", {}).get("mode") == "native":
            line("✓", f"skills read natively from {adapters.SKILLS_DIR}")
        if not file_problems:
            line("✓", f"{len(rendered)} generated file(s) up to date")
        for problem in skill_problems + file_problems:
            line("✗", problem)
        for message in dict.fromkeys(ctx.warnings):
            line("!", message)

    common.out("project")
    _general_checks(root, available, line)
    return 1 if failures else 0
