"""tb update — fetch a newer template release into Runtime/update/<version>/.

The update logic itself lives in the fetched template (setup/update.py, setup/UPDATE.md), so the
update mechanism is always the newest one.
"""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

import common

TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
UPDATE_DIR = "Runtime/update"


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("update", help="fetch a newer template release (then follow its setup/UPDATE.md)")
    commands = parser.add_subparsers(dest="update_command", metavar="<subcommand>")
    fetch = commands.add_parser("fetch", help=f"clone the newest template release into {UPDATE_DIR}/<version>/")
    fetch.add_argument("--ref", help="tag, branch or commit to fetch instead of the newest vX.Y.Z release")
    fetch.add_argument("--source", help="template repository URL or path "
                                        "(default: [template] source in .agents/agentic.lock)")
    fetch.set_defaults(func=cmd_fetch)
    parser.set_defaults(func=lambda _args: _usage(parser))


def _usage(parser: argparse.ArgumentParser) -> int:
    parser.print_help()
    return 2


def _version(text: str) -> tuple[int, int, int] | None:
    m = VERSION_RE.match(text.strip())
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def _git(*args: str, cwd: Path | None = None):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")  # never hang on a credential prompt
    return common.run(["git", *args], cwd=cwd or common.project_root(), env=env)


def release_tags(source: str) -> tuple[dict[tuple[int, int, int], str] | None, str]:
    res = _git("ls-remote", "--tags", "--refs", source)
    if res.returncode != 0:
        return None, (res.stderr or res.stdout).strip()
    tags = {}
    for line in res.stdout.splitlines():
        parts = line.split()
        if len(parts) != 2 or not parts[1].startswith("refs/tags/"):
            continue
        tag = parts[1][len("refs/tags/"):]
        m = TAG_RE.match(tag)
        if m:
            tags[(int(m.group(1)), int(m.group(2)), int(m.group(3)))] = tag
    return tags, ""


def folder_name(ref: str) -> str:
    m = TAG_RE.match(ref)
    if m:
        return ref[1:]
    return re.sub(r"[^A-Za-z0-9._-]+", "-", ref).strip("-.") or "ref"


def clone(source: str, ref: str, dest: Path) -> str:
    """Clone `ref` of `source` into `dest`; returns an error message or ""."""
    res = _git("-c", "advice.detachedHead=false", "clone", "--quiet", "--depth", "1", "--branch", ref,
               source, str(dest))
    if res.returncode == 0:
        return ""
    common.rmtree(dest)
    # --branch accepts only branches and tags; fall back to a full clone for commits.
    res = _git("clone", "--quiet", source, str(dest))
    if res.returncode != 0:
        return (res.stderr or res.stdout).strip()
    res = _git("-c", "advice.detachedHead=false", "checkout", "--quiet", ref, cwd=dest)
    if res.returncode != 0:
        return (res.stderr or res.stdout).strip()
    return ""


def cmd_fetch(args: argparse.Namespace) -> int:
    lock = common.load_lock()
    if not lock:
        return common.fail(f"not an agentic project: {common.LOCK_PATH} not found")
    tpl = lock.get("template", {})
    locked_source = tpl.get("source", "")
    source = args.source or locked_source
    if not source:
        return common.fail(f"template source is unknown ([template] source in {common.LOCK_PATH} is empty); "
                           "pass --source <url>")
    if args.source and args.source != locked_source:
        common.warn(f"using --source {args.source}; {common.LOCK_PATH} records "
                    f"{locked_source or '(none)'}")
    current = tpl.get("version", "0.0.0")
    current_v = _version(current) or (0, 0, 0)

    if args.ref:
        ref = args.ref
    else:
        tags, error = release_tags(source)
        if tags is None:
            return common.fail(f"cannot list tags of {source}: {error}")
        if not tags:
            return common.fail(f"no release tags (vX.Y.Z) found at {source}")
        newest = max(tags)
        if newest <= current_v:
            common.out(f"Already up to date: v{current} (newest release at the source: {tags[newest]}).")
            return 0
        ref = tags[newest]

    root = common.project_root()
    dest = root / UPDATE_DIR / folder_name(ref)
    common.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    error = clone(source, ref, dest)
    if error:
        common.rmtree(dest)
        return common.fail(f"cannot fetch {ref} from {source}: {error}")
    if not (dest / "setup" / "update.py").is_file() or not (dest / "setup" / "VERSION").is_file():
        return common.fail(f"{common.rel(dest)}/ is not an agentic-project-template "
                           "(setup/update.py or setup/VERSION missing)")
    version = (dest / "setup" / "VERSION").read_text(encoding="utf-8").strip()
    head = _git("rev-parse", "HEAD", cwd=dest).stdout.strip()
    tag_match = TAG_RE.match(ref)
    if tag_match and ref[1:] != version:
        common.warn(f"tag {ref} contains setup/VERSION {version}")
    if (_version(version) or (0, 0, 0)) <= current_v:
        common.warn(f"fetched v{version} is not newer than the installed v{current}")
    where = common.rel(dest)
    common.out(f"Fetched template v{version} ({ref}, {head[:12]}) into {where}/")
    common.out(f"Next: follow {where}/setup/UPDATE.md")
    return 0
