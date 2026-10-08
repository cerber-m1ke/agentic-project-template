"""Shared helpers for tb commands."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tomllib
from datetime import date
from pathlib import Path
from typing import Any

import tomli_w
import yaml

LANGS = ("ru", "en")
LOCK_PATH = ".agents/agentic.lock"
LOCAL_PATH = ".agents/local.toml"
KNOWLEDGE_DIR = "Knowledge"

# Knowledge note types: folder and allowed statuses.
KNOWLEDGE_TYPES: dict[str, dict[str, Any]] = {
    "decision": {"folder": "Decisions", "statuses": ("proposed", "accepted", "superseded")},
    "entity": {"folder": "Entities", "statuses": ("active", "deprecated")},
    "example": {"folder": "Examples", "statuses": ("active", "outdated")},
    "gotcha": {"folder": "Gotchas", "statuses": ("active", "resolved")},
    "plan": {"folder": "Plans", "statuses": ("idea", "ready", "dropped")},
    "task": {"folder": "Tasks", "statuses": ("active", "blocked", "done")},
}
FOLDER_TO_TYPE = {spec["folder"]: name for name, spec in KNOWLEDGE_TYPES.items()}

_root: Path | None = None


# --- paths -------------------------------------------------------------------

def project_root() -> Path:
    """Project root: $AGENTIC_ROOT (set by Toolbox/tb), else two levels above this file."""
    global _root
    if _root is None:
        env = os.environ.get("AGENTIC_ROOT")
        _root = Path(env).resolve() if env else Path(__file__).resolve().parents[2]
    return _root


def rel(path: Path | str) -> str:
    """Path relative to the project root, with forward slashes."""
    p = Path(path)
    root = project_root()
    try:
        return Path(os.path.abspath(p)).relative_to(root).as_posix()
    except ValueError:
        pass
    try:  # e.g. /tmp vs /private/tmp on macOS
        return p.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return p.as_posix()


def is_windows() -> bool:
    return os.name == "nt"


# --- text and data files ---------------------------------------------------------

def read_text(path: Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n")


def sha256_text(text: str) -> str:
    return hashlib.sha256(normalize_newlines(text).encode("utf-8")).hexdigest()


def load_toml(path: Path) -> dict:
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def dump_toml(data: dict) -> str:
    return tomli_w.dumps(data)


def load_lock() -> dict | None:
    path = project_root() / LOCK_PATH
    return load_toml(path) if path.is_file() else None


def project_language() -> str:
    lock = load_lock() or {}
    return lock.get("project", {}).get("language", "ru")


def load_local() -> dict:
    path = project_root() / LOCAL_PATH
    return load_toml(path) if path.is_file() else {}


def save_local(data: dict) -> None:
    write_text(project_root() / LOCAL_PATH, dump_toml(data))


def today_iso() -> str:
    return date.today().isoformat()


# --- frontmatter -------------------------------------------------------------------

_FM_RE = re.compile(r"\A---[ \t]*\n(.*?)\n---[ \t]*(?:\n|\Z)", re.DOTALL)


def split_frontmatter(text: str) -> tuple[dict | None, str, str | None]:
    """Return (meta, body, error). meta is None when there is no frontmatter."""
    text = normalize_newlines(text)
    m = _FM_RE.match(text)
    if not m:
        return None, text, None
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except (yaml.YAMLError, ValueError) as exc:  # ValueError: impossible dates like 2026-13-45
        return None, text[m.end():], f"invalid YAML frontmatter: {exc}"
    if not isinstance(meta, dict):
        return None, text[m.end():], "frontmatter is not a mapping"
    return meta, text[m.end():], None


def read_note(path: Path) -> tuple[dict | None, str, str | None]:
    return split_frontmatter(read_text(path))


# --- output ----------------------------------------------------------------------

def out(msg: str = "") -> None:
    print(msg)


def warn(msg: str) -> None:
    print(f"warning: {msg}", file=sys.stderr)


def fail(msg: str, code: int = 1) -> int:
    print(f"error: {msg}", file=sys.stderr)
    return code


def print_json(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


# --- processes -------------------------------------------------------------------

def run(cmd: list[str], cwd: Path | None = None, check: bool = False,
        env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, check=check, env=env, text=True,
                          encoding="utf-8", errors="replace", capture_output=True)


def git(*args: str, cwd: Path | None = None, check: bool = False) -> subprocess.CompletedProcess:
    return run(["git", *args], cwd=cwd or project_root(), check=check)


_CMD_SPECIAL = set(' \t"&|<>^()')


def _cmd_quote(arg: str) -> str:
    """Quote one argument for a cmd.exe command line (MSVC argv rules + cmd metacharacters)."""
    if arg and not _CMD_SPECIAL.intersection(arg):
        return arg
    out, backslashes = ['"'], 0
    for ch in arg:
        if ch == "\\":
            backslashes += 1
            continue
        out.append("\\" * (backslashes * 2 + 1) + '"' if ch == '"' else "\\" * backslashes + ch)
        backslashes = 0
    out.append("\\" * (backslashes * 2) + '"')
    return "".join(out)


def run_tb(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Run this project's tb with arguments (output captured, never raises on failure).

    Windows: `cmd /d /s /c ""<tb.cmd>" <args>"` passed as ONE string, so paths with spaces,
    parentheses or `&` survive cmd's quote handling. POSIX: `sh Toolbox/tb <args>`.
    """
    root = project_root()
    if is_windows():
        tbcmd = root / "Toolbox" / "tb.cmd"
        line = 'cmd /d /s /c ""%s" %s"' % (tbcmd, " ".join(_cmd_quote(str(a)) for a in args))
        return subprocess.run(line, cwd=cwd, text=True, encoding="utf-8", errors="replace",
                              capture_output=True)
    return run(["sh", str(root / "Toolbox" / "tb"), *map(str, args)], cwd=cwd)


# --- directory links (symlink, or junction on Windows without symlink rights) ----

def is_link(path: Path) -> bool:
    path = Path(path)
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def link_points_to(link: Path, target: Path) -> bool:
    return is_link(link) and Path(link).resolve() == Path(target).resolve()


def make_dir_link(link: Path, target: Path) -> str:
    """Create a directory link. Returns "symlink" or "junction"."""
    link, target = Path(link), Path(target)
    link.parent.mkdir(parents=True, exist_ok=True)
    relative = os.path.relpath(target, link.parent)
    try:
        os.symlink(relative, link, target_is_directory=True)
        return "symlink"
    except OSError:
        if not is_windows():
            raise
    import _winapi  # Windows only; a junction needs no symlink privilege

    _winapi.CreateJunction(str(target.resolve()), str(link))
    return "junction"


def remove_link(link: Path) -> None:
    link = Path(link)
    if link.is_symlink():
        link.unlink()
    elif is_link(link):  # junction
        os.rmdir(link)


def _make_writable(path: str) -> None:
    """Add the write bit (clears the Windows read-only attribute); other bits are kept."""
    try:
        os.chmod(path, stat.S_IMODE(os.stat(path).st_mode) | stat.S_IWRITE)
    except OSError:
        pass


def rmtree(path: Path) -> None:
    """shutil.rmtree that also removes read-only files (git objects on Windows).
    A file or a link at `path` is removed itself (a link's target is never touched)."""
    path = Path(path)
    if is_link(path):
        remove_link(path)
        return
    if path.is_file():
        _make_writable(str(path))
        path.unlink()
        return
    if not path.exists():
        return

    def _onexc(func, p, exc):
        if getattr(func, "__name__", "") not in ("unlink", "remove", "rmdir"):
            raise exc  # e.g. scandir/open of an unreadable directory: chmod won't help
        _make_writable(p)
        _make_writable(os.path.dirname(p))  # POSIX: deleting needs a writable parent
        func(p)

    shutil.rmtree(path, onexc=_onexc)
