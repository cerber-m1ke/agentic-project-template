# /// script
# requires-python = ">=3.12"
# dependencies = ["tomli-w>=1", "pyyaml>=6"]
# [tool.uv]
# exclude-newer = "2026-10-01T00:00:00Z"
# ///
"""Update an Agentic Project from this (freshly fetched) template copy.

Runs from <project>/Runtime/update/<v>/ (see `tb update fetch` and setup/UPDATE.md):
    Toolbox/tb run Runtime/update/<v>/setup/update.py plan  --project . [--json]
    Toolbox/tb run Runtime/update/<v>/setup/update.py diff  --project . <path>…
    Toolbox/tb run Runtime/update/<v>/setup/update.py apply --project . --yes
        [--take-template PATH]… [--keep-local PATH]… [--no-branch]

The project composition can change in the same run (plan, diff and apply take the same options):
    --language ru|en  --profile NAME  --add-module NAME…  --remove-module NAME…
To change it without a new release, fetch the installed one: Toolbox/tb update fetch --ref v<installed>.

Three-way comparison per file: base = hash in .agents/agentic.lock, local = project file,
theirs = this template rendered for the project's language/profile/modules.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import argparse
import difflib
import json
import os
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import installer_lib as il  # noqa: E402

TEMPLATE_ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = "Runtime/update/plan.json"
STATUS_ORDER = ("conflict", "update", "add", "remove", "local-modified", "seeded-changed",
                "already-current", "unchanged")


@dataclass
class Item:
    path: str
    status: str
    cls: str
    module: str
    detail: str
    entry: il.Entry | None        # new template version (None: removed from template)
    lock_entry: dict | None       # record in the current lock (None: new in template)
    local: str | None             # local hash / sentinel
    frozen: bool = False          # cannot be updated by this template (profile rules missing)

    def as_json(self) -> dict:
        return {"path": self.path, "status": self.status, "class": self.cls, "module": self.module,
                "detail": self.detail}


@dataclass
class State:
    project: Path
    lock: dict
    old_version: str
    new_version: str
    source: str
    commit: str
    language: str
    profile: str
    modules: list[str]
    missing_modules: list[str]
    new_modules: list[str]
    changes: list[str]            # composition changes requested on the command line
    entries: dict[str, il.Entry]
    items: list[Item]
    migrations: list[tuple[str, Path]]
    notes: list[str]


# --- analysis ---------------------------------------------------------------------------------

def classify(project: Path, path: str, lock_entry: dict | None, entry: il.Entry | None) -> Item:
    base = lock_entry.get("sha256") if lock_entry else None
    old_cls = lock_entry.get("class", "managed") if lock_entry else None

    def item(status: str, detail: str, cls: str | None = None, local: str | None = None) -> Item:
        cls = cls or (entry.cls if entry else old_cls or "managed")
        module = entry.module if entry else (lock_entry or {}).get("module", "")
        return Item(path, status, cls, module, detail, entry, lock_entry, local)

    if entry is None:  # removed from the template
        local = il.local_hash(project / path, old_cls)
        if old_cls == "seeded":
            return item("seeded-changed", "removed from template; file kept (now project-owned)", local=local)
        if old_cls == "block":
            return item("remove", "managed block no longer provided; file kept as project-owned", local=local)
        if local is None:
            return item("already-current", "already absent", local=local)
        if local == base:
            return item("remove", "removed from template", local=local)
        return item("conflict", "changed locally, removed from template", local=local)

    cls, theirs = entry.cls, entry.sha256
    local = il.local_hash(project / path, cls)
    if cls == "seeded":
        if lock_entry is None:
            if local is None:
                return item("add", "new seeded file", local=local)
            return item("seeded-changed", "new seeded file already exists locally; not overwritten", local=local)
        if old_cls == "seeded" and theirs == base:
            return item("unchanged", "", local=local)
        if old_cls != "seeded":
            return item("seeded-changed", f"now project-owned (class {old_cls} -> seeded); file kept",
                        local=local)
        absent = " (file absent locally)" if local is None else ""
        return item("seeded-changed", f"template version changed; review with diff{absent}", local=local)

    if lock_entry is None:  # new managed/block file in the template
        if local is None:
            return item("add", "new in template", local=local)
        if local == theirs:
            return item("already-current", "already matches template", local=local)
        if local == il.NO_MARKERS:
            return item("conflict", "exists locally without agentic:begin/end markers", local=local)
        return item("conflict", "exists locally but is new in template", local=local)
    if old_cls != cls:
        if local == theirs:
            return item("already-current", f"class {old_cls} -> {cls}; content already matches", local=local)
        return item("conflict", f"ownership class changed {old_cls} -> {cls}; review", local=local)
    if local == theirs:
        if base == theirs:
            return item("unchanged", "", local=local)
        return item("already-current", "local already matches template", local=local)
    if base == theirs:
        if local is None:
            return item("local-modified", "deleted locally; template unchanged", local=local)
        if local == il.NO_MARKERS:
            return item("local-modified", "block markers removed locally; template unchanged", local=local)
        return item("local-modified", "changed locally; template unchanged", local=local)
    if local == base:
        return item("update", "managed block changed in template" if cls == "block" else "changed in template",
                    local=local)
    if local is None:
        return item("conflict", "deleted locally, changed in template", local=local)
    if local == il.NO_MARKERS:
        return item("conflict", "block markers missing locally, block changed in template", local=local)
    return item("conflict", "changed locally and in template", local=local)


def composition_args(args: argparse.Namespace) -> list[str]:
    """The composition options as command-line words (repeated in printed hints)."""
    words: list[str] = []
    if args.language:
        words += ["--language", args.language]
    if args.profile:
        words += ["--profile", args.profile]
    for name in args.add_module:
        words += ["--add-module", name]
    for name in args.remove_module:
        words += ["--remove-module", name]
    return words


def load_state(args: argparse.Namespace) -> State:
    project = Path(args.project).resolve()
    lock = il.read_lock(project)
    if lock is None:
        raise il.InstallerError(f"{project / il.LOCK_PATH} not found: not an agentic project")
    if lock.get("schema") != il.LOCK_SCHEMA:
        raise il.InstallerError(f"unsupported lock schema {lock.get('schema')!r} (expected {il.LOCK_SCHEMA})")
    tpl, prj = lock.get("template", {}), lock.get("project", {})
    old_version = tpl.get("version", "0.0.0")
    il.parse_version(old_version)
    new_version = il.read_version(TEMPLATE_ROOT)
    old_language, old_profile = prj.get("language", "ru"), prj.get("profile", "software")
    language, profile = args.language or old_language, args.profile or old_profile
    if language not in il.LANGS:
        raise il.InstallerError(f"unsupported language '{language}' (available: {', '.join(il.LANGS)})")
    if args.profile and args.profile not in il.list_profiles(TEMPLATE_ROOT):
        raise il.InstallerError(f"unknown profile '{args.profile}' "
                                f"(available: {', '.join(il.list_profiles(TEMPLATE_ROOT))})")
    all_modules = il.load_modules(TEMPLATE_ROOT)
    installed = list(prj.get("modules", []))
    changes: list[str] = []
    if language != old_language:
        changes.append(f"language {old_language} -> {language}")
    if profile != old_profile:
        changes.append(f"profile {old_profile} -> {profile}")
    for name in args.add_module:
        if name not in all_modules:
            raise il.InstallerError(f"unknown module '{name}' (available: {', '.join(all_modules)})")
        if name in installed:
            raise il.InstallerError(f"module '{name}' is already installed")
        changes.append(f"add module {name}")
    for name in args.remove_module:
        if name not in installed:
            raise il.InstallerError(f"module '{name}' is not installed")
        if name in all_modules and all_modules[name].required:
            raise il.InstallerError(f"module '{name}' is required and cannot be removed")
        changes.append(f"remove module {name}")
    modules = [m for m in installed if m not in args.remove_module] + list(dict.fromkeys(args.add_module))
    present = [m for m in modules if m in all_modules]
    missing = [m for m in modules if m not in all_modules]
    notes: list[str] = []
    new_modules: list[str] = []
    rules_file = f"{il.PROFILES_DIR}/{profile}.{language}.md"
    rules_missing = not (TEMPLATE_ROOT / rules_file).is_file()
    if profile in il.list_profiles(TEMPLATE_ROOT):
        prof = il.load_profile(TEMPLATE_ROOT, profile)
        new_modules = [m for m in il.available_profile_modules(prof, all_modules)
                       if m not in modules and m not in args.remove_module]
    else:
        notes.append(f"profile '{profile}' no longer exists in the template")
    if missing:
        notes.append(f"module(s) no longer in the template: {', '.join(missing)} (their files are removed)")
    # Without the profile rules {{agentic.profile_rules}} renders empty; files using it are frozen below.
    ctx = il.Context(project_name=prj.get("name", project.name), language=language, profile=profile,
                     date=prj.get("created", ""), template_root=TEMPLATE_ROOT,
                     _rules="" if rules_missing else None)
    entries = il.materialize(TEMPLATE_ROOT, present, all_modules, ctx)
    source, commit = il.template_git_info(TEMPLATE_ROOT)
    lock_files: dict[str, dict] = lock.get("files", {})
    items = [classify(project, path, lock_files.get(path), entries.get(path))
             for path in sorted(set(lock_files) | set(entries))]
    if rules_missing:
        frozen = []
        for item in items:
            if (item.entry is not None and item.entry.uses_rules
                    and item.status not in ("unchanged", "already-current", "seeded-changed")):
                item.status, item.frozen = "conflict", True
                item.detail = (f"{rules_file} is missing in the template; kept as-is "
                               "(update the managed block by hand)")
                frozen.append(item.path)
        if frozen:
            notes.append(f"{rules_file} is missing in the template: {{{{agentic.profile_rules}}}} cannot be "
                         f"rendered; kept as-is: {', '.join(frozen)}")
    migrations = il.list_migrations(TEMPLATE_ROOT, old_version, new_version)
    if il.parse_version(new_version) < il.parse_version(old_version):
        notes.append(f"template v{new_version} is OLDER than the project (v{old_version})")
    return State(project, lock, old_version, new_version, tpl.get("source", "") or source, commit,
                 language, profile, present, missing, new_modules, changes, entries, items, migrations, notes)


def plan_json(state: State) -> dict:
    summary = {s: sum(1 for i in state.items if i.status == s) for s in STATUS_ORDER}
    return {
        "project": str(state.project),
        "template": str(TEMPLATE_ROOT),
        "from_version": state.old_version,
        "to_version": state.new_version,
        "template_commit": state.commit,
        "language": state.language,
        "profile": state.profile,
        "modules": state.modules,
        "changes": state.changes,
        "summary": summary,
        "files": [i.as_json() for i in state.items],
        "migrations": [p.relative_to(TEMPLATE_ROOT).as_posix() for _v, p in state.migrations],
        "new_modules": state.new_modules,
        "notes": state.notes,
    }


def save_plan(state: State, data: dict) -> None:
    il.write_file(state.project, PLAN_PATH,
                  (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"), text=True)


def script_hint(state: State) -> str:
    script = Path(__file__).resolve()
    try:
        return script.relative_to(state.project).as_posix()
    except ValueError:
        return str(script)


# --- commands ------------------------------------------------------------------------------------

def cmd_plan(args: argparse.Namespace) -> int:
    state = load_state(args)
    data = plan_json(state)
    save_plan(state, data)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    commit = f", template commit {state.commit[:12]}" if state.commit else ""
    print(f"Update plan: v{state.old_version} -> v{state.new_version}{commit}")
    for change in state.changes:
        print(f"composition: {change}")
    for status in STATUS_ORDER[:-1]:
        items = [i for i in state.items if i.status == status]
        if not items:
            continue
        print(f"{status} ({len(items)}):")
        for i in items:
            tag = f" [{i.cls}]" if i.cls != "managed" else ""
            detail = f" — {i.detail}" if i.detail and status not in ("update", "add") else ""
            print(f"  {i.path}{tag}{detail}")
    print(f"unchanged: {data['summary']['unchanged']} file(s)")
    if state.migrations:
        print("Migrations: " + ", ".join(p.name for _v, p in state.migrations))
    else:
        print("Migrations: none")
    if state.new_modules:
        print(f"Not installed modules of profile '{state.profile}': {', '.join(state.new_modules)} "
              "(add with --add-module NAME)")
    for note in state.notes:
        print(f"note: {note}")
    script = script_hint(state)
    extra = "".join(f" {w}" for w in composition_args(args))
    print(f"Saved {PLAN_PATH}")
    if any(i.status in ("conflict", "seeded-changed") for i in state.items):
        print(f"Review: Toolbox/tb run {script} diff --project .{extra} <path>")
    print(f"Apply:  Toolbox/tb run {script} apply --project .{extra} --yes "
          "[--take-template PATH]… [--keep-local PATH]…")
    return 0


def file_text(path: Path) -> str | None:
    if not path.is_file():
        return None
    data = path.read_bytes()
    return il.normalize_newlines(data.decode("utf-8")) if il.is_text(data) else "\0binary"


def target_text(item: Item, local: str | None) -> str | None:
    """Full file content the project would get from the template (block files: merged)."""
    entry = item.entry
    if entry is None:
        return local if item.cls in ("block", "seeded") else None
    if not entry.text:
        return "\0binary"
    if entry.cls == "block" and local is not None and local != "\0binary":
        merged = il.replace_block(local, entry.block)
        return merged if merged is not None else il.append_block(local, entry.content)
    return entry.content


def cmd_diff(args: argparse.Namespace) -> int:
    state = load_state(args)
    by_path = {i.path: i for i in state.items}
    rc = 0
    for raw in args.paths:
        path = il.posix(raw)
        item = by_path.get(path)
        if item is None:
            print(f"error: {path} is neither in {il.LOCK_PATH} nor in the template", file=sys.stderr)
            rc = 1
            continue
        local = file_text(state.project / path)
        theirs = target_text(item, local)
        if "\0binary" in (local, theirs):
            same = item.local == (item.entry.sha256 if item.entry else None)
            print(f"{'No differences for' if same else 'Binary files differ:'} {path} ({item.status})")
            continue
        if local == theirs:
            print(f"No differences for {path} ({item.status}).")
            continue
        diff = difflib.unified_diff(
            (local or "").splitlines(keepends=True), (theirs or "").splitlines(keepends=True),
            fromfile=f"a/{path} (local)" if local is not None else "/dev/null",
            tofile=f"b/{path} (template v{state.new_version})" if theirs is not None else "/dev/null")
        for line in diff:
            sys.stdout.write(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n")
    return rc


def write_template_version(project: Path, item: Item) -> None:
    """Make the project file equal to the template version (block files: only the block)."""
    entry = item.entry
    if entry is None:
        il.remove_file_and_empty_parents(project, item.path)
        return
    path = project / item.path
    if entry.cls == "block" and path.is_file():
        local = file_text(path)
        if local is not None and local != "\0binary":
            merged = il.replace_block(local, entry.block)
            merged = merged if merged is not None else il.append_block(local, entry.content)
            il.write_file(project, item.path, merged.encode("utf-8"), text=True, executable=entry.executable)
            return
    il.write_entry(project, entry)


def cmd_apply(args: argparse.Namespace) -> int:
    if not args.yes:
        print("error: apply changes the project; review the plan, then re-run with --yes", file=sys.stderr)
        return 2
    state = load_state(args)
    project = state.project
    by_path = {i.path: i for i in state.items}
    take = [il.posix(p) for p in args.take_template]
    keep = [il.posix(p) for p in args.keep_local]
    problems = []
    for p in sorted(set(take) & set(keep)):
        problems.append(f"{p}: both --take-template and --keep-local given")
    for p in sorted(set(take) | set(keep)):
        if p in by_path and by_path[p].frozen:
            problems.append(f"{p}: cannot be resolved by update ({by_path[p].detail})")
    for p in take:
        if p not in by_path or by_path[p].status not in ("conflict", "local-modified"):
            status = by_path[p].status if p in by_path else "not in plan"
            problems.append(f"--take-template {p}: only for conflict/local-modified files (status: {status})")
        elif by_path[p].local == il.NO_MARKERS and by_path[p].lock_entry is not None:
            # The old block text is still in the file, just unmarked: appending the new block would
            # duplicate it. Only a person can tell which lines were the template's.
            problems.append(f"--take-template {p}: the file lost its agentic:begin/end markers; put the "
                            "marker lines back around the template part (or delete that part), commit, "
                            "and re-run the plan")
    for p in keep:
        if p not in by_path or by_path[p].status != "conflict":
            status = by_path[p].status if p in by_path else "not in plan"
            problems.append(f"--keep-local {p}: only for conflict files (status: {status})")
    if problems:
        for msg in problems:
            print(f"error: {msg}", file=sys.stderr)
        return 1

    if not il.has_own_git(project):
        return fail(f"{project} is not a git repository")
    status = il.git("status", "--porcelain", cwd=project)
    if status.returncode != 0:
        return fail(f"git status failed: {status.stderr.strip()}")
    if status.stdout.strip():
        return fail("the project has uncommitted changes; commit or stash them first:\n  "
                    + "\n  ".join(status.stdout.splitlines()[:20]))
    branch = None
    if not args.no_branch:
        branch = f"agentic/update-{state.new_version}"
        if il.git("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", cwd=project).returncode == 0:
            return fail(f"branch {branch} already exists; delete it or pass --no-branch")
        res = il.git("checkout", "-q", "-b", branch, cwd=project)
        if res.returncode != 0:
            return fail(f"cannot create branch {branch}: {res.stderr.strip()}")

    take_set, keep_set = set(take), set(keep)
    files: dict[str, dict] = {}
    done: dict[str, list[str]] = {k: [] for k in ("updated", "added", "removed", "took-template", "kept-local")}
    skipped: list[Item] = []
    seeded: list[Item] = []
    executables: list[str] = []  # written executables: +x is staged in the index (Windows has no +x)
    for item in state.items:
        entry, old = item.entry, item.lock_entry
        if entry is not None and entry.executable and (
                item.status in ("update", "add") or item.path in take_set):
            executables.append(item.path)
        if item.status in ("update", "add"):
            write_template_version(project, item)
            done["updated" if item.status == "update" else "added"].append(item.path)
        elif item.status == "remove":
            if item.cls != "block":
                il.remove_file_and_empty_parents(project, item.path)
            done["removed"].append(item.path)
        elif item.path in take_set:
            write_template_version(project, item)
            done["took-template"].append(item.path)
        elif item.path in keep_set:
            done["kept-local"].append(item.path)
        elif item.status == "conflict":
            skipped.append(item)
        elif item.status == "seeded-changed":
            seeded.append(item)

        # Lock record after apply.
        if item.status == "local-modified" and item.path not in take_set:
            files[item.path] = {**entry.lock_record(), "sha256": old["sha256"]}
        elif item.status == "conflict" and item.path not in take_set | keep_set:
            if old is not None:
                files[item.path] = dict(old)
        elif entry is not None and item.status != "remove":
            files[item.path] = entry.lock_record()

    ran = []
    for version, path in state.migrations:
        print(f"Running migration {path.name}", flush=True)
        try:
            il.run_migration(path, project)
        except Exception as exc:  # noqa: BLE001 — report any migration failure
            print(f"error: migration {path.name} failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            print("The lock was not updated; files are partially changed. Revert with "
                  "`git reset --hard && git clean -fd` (on the update branch) and report the problem.",
                  file=sys.stderr)
            return 1
        ran.append(path.name)

    tpl = state.lock.get("template", {})
    source = tpl.get("source") or state.source
    project_record = {**state.lock.get("project", {}), "language": state.language,
                      "profile": state.profile, "modules": state.modules}
    il.write_lock(project, il.make_lock(source, state.new_version, state.commit, project_record, files))

    staged: list[str] = []
    existing = [p for p in executables if (project / p).is_file()]
    if existing and il.has_own_git(project):
        res = il.git("update-index", "--add", "--chmod=+x", "--", *existing, cwd=project)
        if res.returncode == 0:
            staged = existing
        else:
            print(f"warning: git update-index --chmod=+x failed: {(res.stderr or res.stdout).strip()}; "
                  f"run it for: {', '.join(existing)}", file=sys.stderr)

    where = f"on branch {branch}" if branch else "in the current branch"
    print(f"Applied update v{state.old_version} -> v{state.new_version} {where} (not committed).")
    for change in state.changes:
        print(f"composition: {change}")
    for key, paths in done.items():
        if paths:
            print(f"{key} ({len(paths)}): {', '.join(paths)}")
    print(f"migrations: {', '.join(ran) if ran else 'none'}")
    if skipped:
        print("Skipped conflicts (local version kept; resolve by hand or re-run with "
              "--take-template/--keep-local after committing):")
        for i in skipped:
            print(f"  {i.path} — {i.detail}")
    if seeded:
        print("Seeded files with template changes (suggestions only; review with diff):")
        for i in seeded:
            print(f"  {i.path} — {i.detail}")
    if state.new_modules:
        print(f"Not installed modules of profile '{state.profile}': {', '.join(state.new_modules)}")
    tb = "Toolbox\\tb.cmd" if os.name == "nt" else "Toolbox/tb"
    print("Next steps:")
    print(f"  {tb} kb lint")
    if any(c.startswith(("add module", "remove module")) for c in state.changes):
        print(f"  {tb} setup")
    print(f"  {tb} agents link")
    print(f"  {tb} agents doctor")
    if staged:
        print(f"  already staged with the executable bit (git update-index --chmod=+x): {', '.join(staged)}")
    print(f"  review git status / git diff, then commit explicit paths: "
          f"git commit -m \"agentic: update to v{state.new_version}\"")
    print("  after merging: delete Runtime/update/")
    return 0


def fail(msg: str) -> int:
    print(f"error: {msg}", file=sys.stderr)
    return 1


def add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--project", required=True, help="project root")
    p.add_argument("--language", choices=il.LANGS, help="switch the project language (managed files)")
    p.add_argument("--profile", help="switch the profile (its rules in the AGENTS.md block)")
    p.add_argument("--add-module", action="append", default=[], metavar="NAME", help="install a module")
    p.add_argument("--remove-module", action="append", default=[], metavar="NAME",
                   help="remove a non-required module (its unchanged files are deleted)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="update.py", description="Update an agentic project from this template.")
    sub = parser.add_subparsers(dest="command", metavar="<command>", required=True)
    p = sub.add_parser("plan", help="classify every template file; saves Runtime/update/plan.json")
    add_common(p)
    p.add_argument("--json", action="store_true", help="print the plan as JSON")
    p.set_defaults(func=cmd_plan)
    d = sub.add_parser("diff", help="unified diff: local file vs new template version (block-aware)")
    add_common(d)
    d.add_argument("paths", nargs="+", metavar="path", help="file path relative to the project root")
    d.set_defaults(func=cmd_diff)
    a = sub.add_parser("apply", help="apply the plan on a new branch (does not commit)")
    add_common(a)
    a.add_argument("--yes", action="store_true", help="required: confirm applying")
    a.add_argument("--take-template", action="append", default=[], metavar="PATH",
                   help="resolve a conflict (or reset a local-modified file) with the template version")
    a.add_argument("--keep-local", action="append", default=[], metavar="PATH",
                   help="resolve a conflict by keeping the local version")
    a.add_argument("--no-branch", action="store_true", help="apply in the current branch")
    a.set_defaults(func=cmd_apply)
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except il.InstallerError as exc:
        return fail(str(exc))


if __name__ == "__main__":
    sys.exit(main())
