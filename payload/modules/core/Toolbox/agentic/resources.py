"""tb resources — catalog of the project's resources (Resources/resources.toml) and their clones.

Each `[[resource]]` has `name` (directory in Resources/), `kind` (git | folder), `url`,
optional `branch`, `description`, `entity`, `agent_settings_reviewed`. Git resources are cloned
into Resources/<name>/, which the root repository ignores.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import common

RESOURCES_DIR = "Resources"
CATALOG = f"{RESOURCES_DIR}/resources.toml"
RESERVED = {"readme.md", "resources.toml"}
KINDS = ("git", "folder")
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SCP_RE = re.compile(r"^[^/\\]+:")          # user@host:path / host:path (not C:\...)
_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")
# Agent settings a resource may carry. An agent started in the project root does not load them
# (only the resource's AGENTS.md/CLAUDE.md are read, by the rule in AGENTS.md).
AGENT_CONFIGS = (".claude/settings.json", ".claude/settings.local.json", ".claude/skills",
                 ".claude/commands", ".claude/agents", ".mcp.json", ".codex/config.toml",
                 ".codex/hooks.json", ".codex/agents", ".agents/skills")
# Catalog fields `tb resources set` may change (`name` is the key and stays).
FIELDS = ("kind", "url", "branch", "description", "entity", "agent_settings_reviewed")
REVIEWED = "agent_settings_reviewed"   # AGENT_CONFIGS paths the human has reviewed
_HEADER_RE = re.compile(r"^\s*\[\[?\s*[^\[\]=]+?\s*\]\]?\s*(?:#.*)?$")
_RESOURCE_HEADER_RE = re.compile(r"^\s*\[\[\s*resource\s*\]\]\s*(?:#.*)?$")


# --- CLI --------------------------------------------------------------------------------

def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("resources", help="project resources: status | clone | add | set",
                            description=f"Resources catalogued in {CATALOG}.")
    actions = parser.add_subparsers(dest="resources_action", metavar="<action>")
    actions.add_parser("status", help="catalog entries: cloned?, branch, changes") \
        .set_defaults(func=cmd_status)
    p = actions.add_parser("clone", help="clone catalogued git resources into Resources/")
    p.add_argument("names", nargs="*", metavar="name")
    p.add_argument("--all", action="store_true", help="clone every git resource not cloned yet")
    p.add_argument("--from", dest="from_path", metavar="PATH",
                   help="clone from a local copy (e.g. while the upstream is unreachable); origin is then "
                        "set to the catalog url")
    p.set_defaults(func=cmd_clone)
    p = actions.add_parser("add", help=f"add a resource to {CATALOG}")
    p.add_argument("url", help="repository URL (git) or source location (folder)")
    p.add_argument("--name", help="directory name in Resources/ (default: from the URL)")
    p.add_argument("--branch", help="branch to clone")
    p.add_argument("--kind", choices=KINDS, default="git", help="git (default) or folder")
    p.add_argument("--description", help="what the resource is")
    p.add_argument("--entity", help="the resource's card in Knowledge, e.g. Knowledge/Entities/api.md")
    p.add_argument("--clone", action="store_true", help="clone it right away (git only)")
    p.set_defaults(func=cmd_add)
    p = actions.add_parser("set", help=f"change fields of a resource in {CATALOG}",
                           description=f"Set or remove fields of a [[resource]] in {CATALOG}, keeping "
                                       "the rest of the file (comments included) as is. "
                                       f"Fields: {', '.join(FIELDS)}. `field=` (empty) removes the "
                                       f"field; {REVIEWED} takes a comma-separated list.")
    p.add_argument("name", help="resource name (not changed by this command)")
    p.add_argument("assignments", nargs="+", metavar="field=value")
    p.set_defaults(func=cmd_set)
    parser.set_defaults(func=lambda _args: (parser.print_help(), 0)[1])


def cmd_status(_args: argparse.Namespace) -> int:
    _missing, ok = print_status()
    return 0 if ok else 1


def cmd_clone(args: argparse.Namespace) -> int:
    if not args.names and not args.all:
        return common.fail("name the resources to clone, or use --all")
    if args.from_path and (args.all or len(args.names) != 1):
        return common.fail("--from clones exactly one resource: tb resources clone <name> --from <path>")
    return clone(args.names, all_missing=args.all, from_path=args.from_path)


def cmd_add(args: argparse.Namespace) -> int:
    return add(args.url, name=args.name, branch=args.branch, kind=args.kind,
               description=args.description, entity=args.entity, do_clone=args.clone)


def cmd_set(args: argparse.Namespace) -> int:
    return set_fields(args.name, args.assignments)


# --- catalog ---------------------------------------------------------------------------------

def load_catalog() -> tuple[list[dict[str, Any]], str | None]:
    """Valid catalog entries and an error message (None if the catalog is readable or absent)."""
    path = common.project_root() / CATALOG
    if not path.is_file():
        return [], None
    try:
        data = common.load_toml(path)
    except (OSError, ValueError) as exc:
        return [], f"{CATALOG}: {exc}"
    entries: list[dict[str, Any]] = []
    for i, item in enumerate(data.get("resource", []), 1):
        name = item.get("name") if isinstance(item, dict) else None
        if not isinstance(name, str) or not _NAME_RE.match(name):
            common.warn(f"{CATALOG}: resource #{i} has no valid `name`; skipped")
            continue
        if item.get("kind", "git") not in KINDS:
            common.warn(f"{CATALOG}: {name}: unknown kind {item.get('kind')!r} (git | folder)")
        reviewed = item.get(REVIEWED, [])
        if not (isinstance(reviewed, list) and all(isinstance(x, str) for x in reviewed)):
            common.warn(f"{CATALOG}: {name}: `{REVIEWED}` must be a list of paths; ignored")
            item = {k: v for k, v in item.items() if k != REVIEWED}
        entries.append(item)
    return entries, None


def _resource_dir(name: str) -> Path:
    return common.project_root() / RESOURCES_DIR / name


def _git_state(path: Path) -> tuple[str, str]:
    """(branch, changes) of a cloned resource."""
    branch = common.git("rev-parse", "--abbrev-ref", "HEAD", cwd=path).stdout.strip()
    if branch == "HEAD":
        sha = common.git("rev-parse", "--short", "HEAD", cwd=path).stdout.strip()
        branch = f"detached@{sha}"
    status = common.git("status", "--porcelain", cwd=path)
    if status.returncode != 0:
        return branch or "?", "git status failed"
    count = len([line for line in status.stdout.splitlines() if line.strip()])
    return branch or "?", f"dirty ({count} change{'s' if count != 1 else ''})" if count else "clean"


def is_local_path(url: str) -> bool:
    """A filesystem path rather than a URL: such a catalog entry only works on this machine."""
    url = url.strip()
    if "://" in url:
        return url.lower().startswith("file://")
    if _DRIVE_RE.match(url) or url.startswith(("/", "./", "../", "~", "\\")):
        return True
    return not _SCP_RE.match(url) and Path(url).expanduser().exists()


def agent_configs(path: Path) -> list[str]:
    """Agent settings inside a resource that an agent started in the project root ignores."""
    return [name for name in AGENT_CONFIGS if (path / name).exists()]


def _norm_config(path: str) -> str:
    return path.replace("\\", "/").strip().strip("/")


def reviewed_configs(entry: dict[str, Any] | None) -> list[str]:
    """`agent_settings_reviewed` of a catalog entry, normalized."""
    value = (entry or {}).get(REVIEWED, [])
    return [_norm_config(x) for x in value if isinstance(x, str)] if isinstance(value, list) else []


def unreviewed_agent_configs(entries: list[dict[str, Any]]) -> list[tuple[str, list[str], str]]:
    """Resource folders whose agent settings are not all marked as reviewed in the catalog:
    (folder name, unreviewed paths, hint to mark the present ones as reviewed — "" if the folder
    is not in the catalog)."""
    base = common.project_root() / RESOURCES_DIR
    if not base.is_dir():
        return []
    by_name = {entry["name"].lower(): entry for entry in entries}
    result: list[tuple[str, list[str], str]] = []
    for path in sorted(base.iterdir()):
        if not path.is_dir() or path.name.startswith("."):
            continue
        found = agent_configs(path)
        entry = by_name.get(path.name.lower())
        reviewed = reviewed_configs(entry)
        new = [name for name in found if name not in reviewed]
        if not new:
            continue
        hint = ""
        if entry is not None:
            marked = list(dict.fromkeys(reviewed + found))
            hint = f"Toolbox/tb resources set {entry['name']} {REVIEWED}={','.join(marked)}"
        result.append((path.name, new, hint))
    return result


def agent_settings_lines(entries: list[dict[str, Any]]) -> list[str]:
    """Report lines about unreviewed agent settings inside resources (empty: nothing to report)."""
    found = unreviewed_agent_configs(entries)
    if not found:
        return []
    lines = ["Agent settings inside resources are NOT loaded by an agent started in the project root "
             "(hooks, permissions, MCP, skills): "
             + "; ".join(f"{RESOURCES_DIR}/{name}/ ({', '.join(new)})" for name, new, _ in found),
             "  Move what the project needs into .agents/ (permissions.toml, mcp.toml, skills/, "
             "hooks/hooks.toml), or start the agent inside the resource for resource-only work.",
             "  Reviewed? Mark them so that only new ones are reported:"]
    lines += [f"    {hint}" for _, _, hint in found if hint]
    return lines


def print_status() -> tuple[list[str], bool]:
    """Print the status table. Returns (missing git resources, catalog readable)."""
    entries, error = load_catalog()
    if error:
        common.fail(error)
        return [], False
    root = common.project_root()
    missing: list[str] = []
    rows: list[tuple[str, ...]] = []
    local_urls: list[str] = []
    for entry in entries:
        name, kind = entry["name"], entry.get("kind", "git")
        path = _resource_dir(name)
        if not path.is_dir():
            if kind == "git":
                missing.append(name)
                rows.append((name, kind, "missing", "", f"Toolbox/tb resources clone {name}"))
            else:
                rows.append((name, kind, "missing", "", f"copy it into {RESOURCES_DIR}/{name}/"))
        elif kind == "git" and not (path / ".git").exists():
            rows.append((name, kind, "present", "", "not a git repository"))
        elif kind == "git":
            branch, changes = _git_state(path)
            expected = entry.get("branch")
            if expected and branch != expected:
                changes += f", catalog branch: {expected}"
            rows.append((name, kind, "cloned", branch, changes))
        else:
            rows.append((name, kind, "present", "", ""))
        if kind == "git" and is_local_path(str(entry.get("url") or "")):
            local_urls.append(name)

    if not (root / CATALOG).is_file():
        common.out(f"No catalog: {CATALOG} not found.")
    elif not rows:
        common.out(f"No resources in {CATALOG}.")
    else:
        common.out(f"{CATALOG}: {len(rows)} resource(s)")
        widths = [max(len(row[i]) for row in rows) for i in range(4)]
        for row in rows:
            cells = [cell.ljust(widths[i]) for i, cell in enumerate(row[:4])] + [row[4]]
            common.out("  " + "  ".join(cells).rstrip())

    known = {entry["name"].lower() for entry in entries}
    base = root / RESOURCES_DIR
    extra = sorted(p.name for p in base.iterdir()
                   if p.is_dir() and not p.name.startswith(".") and p.name.lower() not in known) \
        if base.is_dir() else []
    if extra:
        common.out(f"Not in the catalog: {', '.join(n + '/' for n in extra)} "
                   f"— add with Toolbox/tb resources add <url> --name <name>")
    if missing:
        common.out(f"Not cloned: {len(missing)} — Toolbox/tb resources clone --all")
    if local_urls:
        common.out(f"Local-path url (works only on this machine; use the upstream URL): "
                   f"{', '.join(local_urls)}")
    for line in agent_settings_lines(entries):
        common.out(line)
    return missing, True


# --- clone / add ----------------------------------------------------------------------------

def _clone_from_local(name: str, entry: dict[str, Any], source: Path, dest: Path) -> int:
    """Fresh clone from a local copy, then point origin at the catalog url (a fresh clone in a new
    folder, so nothing bound to the old path moves; local-only branches arrive as origin/*)."""
    url, shown = str(entry.get("url") or ""), f"{RESOURCES_DIR}/{name}/"
    source = source.expanduser()
    if not source.is_dir() or common.git("rev-parse", "--git-dir", cwd=source).returncode != 0:
        return common.fail(f"{name}: {source} is not a git repository")
    common.out(f"{name}: cloning the local copy {source} into {shown}")
    sys.stdout.flush()
    result = subprocess.run(["git", "clone", "--", str(source), str(dest)], cwd=common.project_root())
    if result.returncode != 0:
        return common.fail(f"{name}: git clone failed (exit {result.returncode})")
    if url and common.git("remote", "set-url", "origin", url, cwd=dest).returncode != 0:
        return common.fail(f"{name}: cloned, but `git remote set-url origin {url}` failed")
    branch = entry.get("branch")
    if branch and common.git("checkout", "--quiet", str(branch), cwd=dest).returncode != 0:
        common.warn(f"{name}: branch {branch!r} is not in the local copy; left on "
                    f"{common.git('branch', '--show-current', cwd=dest).stdout.strip() or 'HEAD'}")
    common.out(f"  ✓ cloned {shown} from the local copy; origin = {url or '(unchanged)'}")
    common.out(f"  When the upstream is reachable: git -C {shown} fetch --prune origin")
    return 0


def clone(names: list[str], all_missing: bool = False, from_path: str | None = None) -> int:
    entries, error = load_catalog()
    if error:
        return common.fail(error)
    by_name = {entry["name"]: entry for entry in entries}
    if all_missing:
        names = list(dict.fromkeys(names + [
            e["name"] for e in entries
            if e.get("kind", "git") == "git" and not _resource_dir(e["name"]).exists()]))
        if not names:
            common.out("All git resources are cloned.")
            return 0
    code = 0
    for name in names:
        entry = by_name.get(name)
        if entry is None:
            code = common.fail(f"unknown resource {name!r} (catalog: {', '.join(by_name) or 'empty'})")
            continue
        dest = _resource_dir(name)
        shown = f"{RESOURCES_DIR}/{name}/"
        if entry.get("kind", "git") != "git":
            common.warn(f"{name}: folder resource — copy it into {shown} by hand")
            continue
        if dest.exists():
            common.out(f"{name}: already present in {shown}, skipped")
            continue
        if from_path:
            code = _clone_from_local(name, entry, Path(from_path), dest) or code
            continue
        url = str(entry.get("url") or "")
        if not url:
            code = common.fail(f"{name}: no `url` in {CATALOG}")
            continue
        branch = entry.get("branch")
        cmd = ["git", "clone", *(["--branch", str(branch)] if branch else []), "--", url, str(dest)]
        common.out(f"{name}: cloning {url}{f' ({branch})' if branch else ''} into {shown}")
        sys.stdout.flush()
        # Not captured: the user sees progress and credential prompts.
        result = subprocess.run(cmd, cwd=common.project_root())
        if result.returncode != 0:
            code = common.fail(f"{name}: git clone failed (exit {result.returncode})")
        else:
            common.out(f"  ✓ cloned {shown}")
    return code


def name_from_url(url: str) -> str:
    tail = re.split(r"[/\\:]", url.strip().rstrip("/\\"))[-1]
    return tail[:-4] if tail.lower().endswith(".git") else tail


def _toml_line(key: str, value: str) -> str:
    return common.dump_toml({key: value}).strip()


def _upstream_of_local(path: Path) -> tuple[str | None, str]:
    """For a local repository given as a resource source: (URL to record, error).

    A bare repository is a remote itself and is kept (machine-specific). A working copy is replaced
    by its `origin`: the catalog must name the shared upstream, and a fresh clone is made from it
    (DESIGN §6.2) — so work that exists only in the old copy is reported here."""
    path = path.expanduser()
    if not path.is_dir():
        return None, f"{path} is not a directory"
    if common.git("rev-parse", "--git-dir", cwd=path).returncode != 0:
        return None, f"{path} is not a git repository (use --kind folder for a plain folder)"
    if common.git("rev-parse", "--is-bare-repository", cwd=path).stdout.strip() == "true":
        common.warn(f"{path} is a local bare repository: the catalog entry works only on this machine")
        return str(path), ""
    origin = common.git("remote", "get-url", "origin", cwd=path)
    if origin.returncode != 0 or not origin.stdout.strip():
        return None, (f"{path} is a local working copy without `origin`; pass the upstream URL "
                      "(the catalog is shared, a local path works only on this machine)")
    upstream = origin.stdout.strip()
    common.out(f"{path} is a local working copy: recording its origin {upstream} (the old copy is "
               "left as is; a fresh clone is made from origin)")
    dirty = [l for l in common.git("status", "--porcelain", cwd=path).stdout.splitlines() if l.strip()]
    unpushed = [l for l in common.git("log", "--branches", "--not", "--remotes", "--oneline",
                                      cwd=path).stdout.splitlines() if l.strip()]
    stashes = [l for l in common.git("stash", "list", cwd=path).stdout.splitlines() if l.strip()]
    for what, items in (("uncommitted change(s)", dirty), ("unpushed commit(s)", unpushed),
                        ("stash(es)", stashes)):
        if items:
            common.warn(f"{path}: {len(items)} {what} will NOT be in the fresh clone — push or move "
                        "them first (the old copy keeps them)")
    return upstream, ""


def _check_entity(entity: str) -> None:
    if not (common.project_root() / entity).is_file():
        common.warn(f"entity {entity!r} does not exist yet — create the card, e.g. "
                    "Toolbox/tb kb new entity <slug> --title \"…\"")


def add(url: str, name: str | None = None, branch: str | None = None, kind: str = "git",
        description: str | None = None, entity: str | None = None, do_clone: bool = False) -> int:
    local_copy: Path | None = None
    if kind == "git" and is_local_path(url):
        local = Path(url.removeprefix("file://"))
        upstream, error = _upstream_of_local(local)
        if upstream is None:
            return common.fail(error)
        name = name or name_from_url(url)
        if upstream != str(local):  # a working copy (a bare repository is kept as the url itself)
            local_copy = local
        url = upstream
    name = name or name_from_url(url)
    if not _NAME_RE.match(name) or name.lower() in RESERVED:
        return common.fail(f"invalid resource name {name!r} — pass --name "
                           "(letters, digits, '.', '_', '-')")
    entries, error = load_catalog()
    if error:
        return common.fail(error)
    for entry in entries:
        if entry["name"].lower() == name.lower():
            return common.fail(f"resource {entry['name']!r} is already in {CATALOG}")
        if entry.get("url") == url:
            return common.fail(f"{url} is already in {CATALOG} as {entry['name']!r}")

    lines = ["[[resource]]", _toml_line("name", name), _toml_line("kind", kind), _toml_line("url", url)]
    if branch:
        lines.append(_toml_line("branch", branch))
    if description:
        lines.append(_toml_line("description", description))
    if entity:
        lines.append(_toml_line("entity", entity))

    path = common.project_root() / CATALOG
    existed = path.is_file()
    original = common.read_text(path) if existed else ""
    text = original
    if text and not text.endswith("\n"):
        text += "\n"
    if text.strip():
        text += "\n"
    common.write_text(path, text + "\n".join(lines) + "\n")
    try:
        common.load_toml(path)
    except ValueError as exc:
        if existed:
            common.write_text(path, original)
        else:
            path.unlink()
        return common.fail(f"{CATALOG} would become invalid ({exc}); left unchanged")
    common.out(f"Added {name!r} to {CATALOG}.")
    if entity:
        _check_entity(entity)
    if kind == "folder":
        common.out(f"Note: folder resources are not versioned by the project: {RESOURCES_DIR}/{name}/ "
                   "exists only on this machine and `tb resources clone` cannot restore it. Record "
                   "where the content comes from in `url` or in the entity note.")
    if do_clone:
        if kind != "git":
            common.warn(f"{name}: --clone works for git resources only")
            return 0
        code = clone([name])
        if code and local_copy is not None and not _resource_dir(name).exists():
            common.warn(f"{name}: the upstream is unreachable; cloning the local copy instead "
                        "(its origin is set to the upstream url)")
            code = clone([name], from_path=str(local_copy))
        return code
    if kind == "git":
        common.out(f"Clone it: Toolbox/tb resources clone {name}")
    return 0


# --- set ------------------------------------------------------------------------------------

def _value_extent(lines: list[str], start: int) -> int:
    """Index after the last line of the key/value pair starting at `start` (multi-line arrays and
    strings included); -1 if it never parses."""
    for end in range(start + 1, len(lines) + 1):
        try:
            tomllib.loads("\n".join(lines[start:end]))
            return end
        except tomllib.TOMLDecodeError:
            continue
    return -1


def _resource_blocks(lines: list[str]) -> list[tuple[int, int, dict[str, tuple[int, int]]]] | None:
    """Every [[resource]] table in the text: (header line, end of its last pair, top-level key ->
    (first line, end)). None if a pair cannot be delimited."""
    blocks: list[tuple[int, int, dict[str, tuple[int, int]]]] = []
    i = 0
    while i < len(lines):
        if not _RESOURCE_HEADER_RE.match(lines[i]):
            i += 1
            continue
        header, keys, last = i, {}, i + 1
        i += 1
        while i < len(lines):
            stripped = lines[i].strip()
            if not stripped or stripped.startswith("#"):
                i += 1
                continue
            if _HEADER_RE.match(lines[i]):
                break
            end = _value_extent(lines, i)
            if end < 0:
                return None
            key = next(iter(tomllib.loads("\n".join(lines[i:end]))), None)
            if key is not None:
                keys.setdefault(key, (i, end))
            i, last = end, end
        blocks.append((header, last, keys))
    return blocks


def _trailing_comment(line: str) -> str:
    """The `# comment` that ends a one-line pair (with the spaces before it), or ""."""
    for pos in [m.start() for m in re.finditer("#", line)]:
        try:
            tomllib.loads(line[:pos])
        except tomllib.TOMLDecodeError:
            continue
        head = line[:pos]
        return line[len(head.rstrip()):]
    return ""


def _toml_kv(key: str, value: Any) -> str:
    """One-line `key = value` (a list of strings stays on one line)."""
    if isinstance(value, list):
        items = (common.dump_toml({"v": str(x)}).strip()[len("v = "):] for x in value)
        return f"{key} = [{', '.join(items)}]"
    return common.dump_toml({key: value}).strip()


def _field_value(key: str, raw: str) -> tuple[Any, str]:
    """Parsed value of `key=raw` and an error ("" if fine). An empty raw value removes the field."""
    if raw == "":
        return None, ""
    if key == REVIEWED:
        items = [_norm_config(x) for x in raw.split(",") if x.strip()]
        unknown = [x for x in items if x not in AGENT_CONFIGS]
        if unknown:
            common.warn(f"{REVIEWED}: {', '.join(unknown)} — not among the reported paths "
                        f"({', '.join(AGENT_CONFIGS)})")
        return list(dict.fromkeys(items)), ""
    if key == "kind" and raw not in KINDS:
        return None, f"kind must be one of: {', '.join(KINDS)}"
    return raw, ""


def set_fields(name: str, assignments: list[str]) -> int:
    """Set (or, with an empty value, remove) fields of one catalog entry, editing only its lines."""
    changes: dict[str, Any] = {}
    for item in assignments:
        key, sep, raw = item.partition("=")
        key = key.strip()
        if not sep:
            return common.fail(f"{item!r}: expected field=value (an empty value removes the field)")
        if key == "name":
            return common.fail("`name` is the resource's key and cannot be changed with set")
        if key not in FIELDS:
            return common.fail(f"unknown field {key!r} (fields: {', '.join(FIELDS)})")
        if key in changes:
            return common.fail(f"field {key!r} given twice")
        value, error = _field_value(key, raw.strip())
        if error:
            return common.fail(error)
        changes[key] = value

    path = common.project_root() / CATALOG
    if not path.is_file():
        return common.fail(f"{CATALOG} not found")
    original = common.read_text(path)
    try:
        data = tomllib.loads(original)
    except tomllib.TOMLDecodeError as exc:
        return common.fail(f"{CATALOG}: {exc}")
    raw_entries = data.get("resource", [])
    index = next((i for i, e in enumerate(raw_entries) if isinstance(e, dict) and e.get("name") == name),
                 None)
    if index is None:
        names = [str(e.get("name")) for e in raw_entries if isinstance(e, dict)]
        return common.fail(f"unknown resource {name!r} (catalog: {', '.join(names) or 'empty'})")

    lines = common.normalize_newlines(original).split("\n")
    blocks = _resource_blocks(lines)
    if blocks is None or len(blocks) != len(raw_entries):
        return common.fail(f"{CATALOG}: cannot locate the [[resource]] tables in the text; edit it by hand")
    header, last, keys = blocks[index]
    edits: list[tuple[int, int, list[str]]] = []   # (start, end, replacement lines)
    appended: list[str] = []
    for key, value in changes.items():
        new_line = None if value is None else _toml_kv(key, value)
        if key in keys:
            start, end = keys[key]
            comment = _trailing_comment(lines[start]) if end - start == 1 else ""
            edits.append((start, end, [] if new_line is None else [new_line + comment]))
        elif new_line is not None:
            appended.append(new_line)
    if appended:
        edits.append((last, last, appended))
    for start, end, replacement in sorted(edits, key=lambda e: e[0], reverse=True):
        lines[start:end] = replacement
    text = "\n".join(lines)

    expected = {k: v for k, v in raw_entries[index].items() if k not in changes}
    expected.update({k: v for k, v in changes.items() if v is not None})
    try:
        result = tomllib.loads(text).get("resource", [])
        ok = (len(result) == len(raw_entries) and result[index] == expected
              and all(result[i] == raw_entries[i] for i in range(len(raw_entries)) if i != index))
        error = "the edit changed more than the requested fields"
    except tomllib.TOMLDecodeError as exc:
        ok, error = False, str(exc)
    if not ok:
        return common.fail(f"{CATALOG} would become invalid ({error}); left unchanged")
    if text == common.normalize_newlines(original):
        common.out(f"{name}: nothing to change in {CATALOG}.")
        return 0
    common.write_text(path, text)
    for key, value in changes.items():
        common.out(f"{name}: {'removed ' + key if value is None else _toml_kv(key, value)}")
    if changes.get("entity"):
        _check_entity(changes["entity"])
    return 0
