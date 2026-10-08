"""tb secrets scan — look for high-confidence secret patterns (keys, tokens, private keys).

Only patterns with a very low false-positive rate are checked. A line that contains the marker
`agentic:allow-secret` is skipped. The patterns are assembled from parts so this file never
matches itself.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import common

ALLOW_MARKER = "agentic:allow-secret"
DEFAULT_PATHS = ("Knowledge", ".agents", "Toolbox")
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", ".mypy_cache", ".pytest_cache"}
MAX_FILE_BYTES = 10 * 1024 * 1024

_TAIL = r"(?![A-Za-z0-9_-])"  # token must not continue

# (kind, needles, regex). The regex runs only when one of the plain-text needles occurs in the text.
# Prefixes are split so the source does not contain a literal token start.
PATTERNS: list[tuple[str, tuple[str, ...], re.Pattern[str]]] = [
    ("private-key", ("PRIVATE KEY",),
     re.compile("-----" + "BEGIN" + r" (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----")),
    ("aws-access-key", ("AK" + "IA",),
     re.compile(r"(?<![A-Za-z0-9])" + "AK" + r"IA[0-9A-Z]{16}(?![A-Za-z0-9])")),
    ("github-token", tuple("gh" + c + "_" for c in "pousr"),
     re.compile(r"(?<![A-Za-z0-9_])" + "gh" + r"[pousr]_[A-Za-z0-9]{36,}" + _TAIL)),
    ("github-token", ("github" + "_pat_",),
     re.compile(r"(?<![A-Za-z0-9_])" + "github" + r"_pat_[A-Za-z0-9_]{50,}" + _TAIL)),
    ("slack-token", ("xo" + "x",),
     re.compile(r"(?<![A-Za-z0-9_])" + "xo" + r"x[abprs]-(?:[A-Za-z0-9]+-)+[A-Za-z0-9]+" + _TAIL)),
    ("api-key", ("s" + "k-",),
     re.compile(r"(?<![A-Za-z0-9_-])" + "s" + r"k-(?:ant-)?[A-Za-z0-9_-]{20,}" + _TAIL)),
    ("google-api-key", ("AI" + "za",),
     re.compile(r"(?<![A-Za-z0-9_])" + "AI" + r"za[0-9A-Za-z_-]{35}" + _TAIL)),
    ("stripe-live-key", ("_live_",),
     re.compile(r"(?<![A-Za-z0-9_])" + r"(?:s|r)k" + "_live_" + r"[0-9A-Za-z]{16,}" + _TAIL)),
]


@dataclass
class Finding:
    path: str
    line: int
    kind: str
    value: str

    @property
    def masked(self) -> str:
        return mask(self.value)

    def format(self) -> str:
        return f"{self.path}:{self.line}: {self.kind} {self.masked}"


def mask(value: str) -> str:
    if value.startswith("-----"):
        return value  # PEM header: the header itself is not secret
    if len(value) <= 10:
        return value[:2] + "…"
    return f"{value[:6]}…{value[-2:]} ({len(value)} chars)"


def _plausible(kind: str, value: str) -> bool:
    """Extra sanity checks for the generic `sk-…` pattern (kebab-case words are not keys)."""
    if kind == "api-key":
        body = value[3:]
        return any(c.isdigit() for c in body) and any(c.isalpha() for c in body)
    return True


def _kind_name(kind: str, value: str) -> str:
    if kind == "api-key":
        return "anthropic-api-key" if value.startswith("sk-ant-") else "openai-api-key"
    return kind


def scan_text(text: str, path: str = "") -> list[Finding]:
    """Scan text; return findings (line numbers are 1-based)."""
    findings: list[Finding] = []
    for kind, needles, rx in PATTERNS:  # whole-text passes; line numbers only for matches (fast)
        if not any(n in text for n in needles):
            continue
        for m in rx.finditer(text):
            value = m.group(0)
            if not _plausible(kind, value):
                continue
            start = text.rfind("\n", 0, m.start()) + 1
            end = text.find("\n", m.end())
            if ALLOW_MARKER in text[start:end if end != -1 else len(text)]:
                continue
            findings.append(Finding(path, text.count("\n", 0, m.start()) + 1, _kind_name(kind, value), value))
    findings.sort(key=lambda f: f.line)
    return findings


def decode_text(data: bytes) -> str | None:
    """Decode file content as UTF-8 text; None for binary content."""
    if b"\0" in data[:8192]:
        return None
    return data.decode("utf-8", errors="replace")


def scan_bytes(data: bytes, path: str) -> list[Finding]:
    text = decode_text(data)
    return scan_text(text, path) if text is not None else []


def iter_files(paths: list[Path], skip_dirs: set[str] = SKIP_DIRS):
    """Yield regular files under the given paths (directories are walked, links not followed)."""
    for base in paths:
        if base.is_file():
            yield base
            continue
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if d not in skip_dirs)
            for name in sorted(filenames):
                p = Path(dirpath) / name
                if p.is_file() and not p.is_symlink():
                    yield p


def _rel(path: Path, root: str) -> str:
    """Fast common.rel for paths under the root (common.rel resolves symlinks on every call)."""
    r = os.path.relpath(os.path.abspath(path), root)
    return common.rel(path) if r.startswith("..") else r.replace(os.sep, "/")


def scan_files(files) -> tuple[list[Finding], int]:
    findings: list[Finding] = []
    count = 0
    root = os.path.abspath(common.project_root())
    for path in files:
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
            data = path.read_bytes()
        except OSError:
            continue
        count += 1
        findings.extend(scan_bytes(data, _rel(path, root)))
    return findings, count


# --- staged files ----------------------------------------------------------------

def _staged_paths(root: Path) -> list[str]:
    res = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"],
                         cwd=root, capture_output=True)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.decode("utf-8", errors="replace").strip() or "git diff failed")
    return [p for p in res.stdout.decode("utf-8", errors="replace").split("\0") if p]


def _staged_blobs(root: Path, paths: list[str]) -> dict[str, bytes]:
    """Read staged contents of many files with one `git cat-file --batch` call."""
    if not paths:
        return {}
    request = "".join(f":{p}\n" for p in paths).encode("utf-8")
    res = subprocess.run(["git", "cat-file", "--batch"], cwd=root, input=request, capture_output=True)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.decode("utf-8", errors="replace").strip() or "git cat-file failed")
    data, pos, blobs = res.stdout, 0, {}
    for p in paths:
        eol = data.index(b"\n", pos)
        header = data[pos:eol].split()
        pos = eol + 1
        if len(header) == 3 and header[1] == b"blob":
            size = int(header[2])
            blobs[p] = data[pos:pos + size]
            pos += size + 1
        elif len(header) == 3:  # e.g. submodule commit: skip its content
            pos += int(header[2]) + 1
    return blobs


def _under(path: str, prefixes: list[str]) -> bool:
    return not prefixes or any(path == pre or path.startswith(pre.rstrip("/") + "/") for pre in prefixes)


def scan_staged(root: Path, filters: list[str]) -> tuple[list[Finding], int]:
    paths = [p for p in _staged_paths(root) if _under(p, filters)]
    blobs = _staged_blobs(root, paths)
    findings: list[Finding] = []
    for p in paths:
        if p in blobs and len(blobs[p]) <= MAX_FILE_BYTES:
            findings.extend(scan_bytes(blobs[p], p))
    return findings, len(blobs)


# --- command -----------------------------------------------------------------------

def _resolve(arg: str, root: Path) -> Path:
    p = Path(arg)
    if p.is_absolute() or p.exists():
        return p
    return root / p


def cmd_scan(args: argparse.Namespace) -> int:
    root = common.project_root()
    if args.staged:
        if common.git("rev-parse", "--git-dir", cwd=root).returncode != 0:
            return common.fail("--staged needs a git repository")
        filters = [common.rel(_resolve(a, root)) for a in args.paths]
        try:
            findings, count = scan_staged(root, filters)
        except RuntimeError as exc:
            return common.fail(str(exc))
        where = "staged files"
    else:
        targets = [_resolve(a, root) for a in args.paths] if args.paths else \
            [root / d for d in DEFAULT_PATHS]
        missing = [a for a, t in zip(args.paths, targets) if not t.exists()]
        for a in missing:
            common.warn(f"path not found: {a}")
        findings, count = scan_files(iter_files([t for t in targets if t.exists()]))
        where = "files"
    for f in findings:
        common.out(f.format())
    if findings:
        return common.fail(f"{len(findings)} possible secret(s) found. Remove them (rotate if real) "
                           f"or mark a false positive with the comment \"{ALLOW_MARKER}\".")
    common.out(f"No secrets found ({count} {where} scanned).")
    return 0


def register(sub) -> None:
    p = sub.add_parser("secrets", help="scan files for secrets")
    s = p.add_subparsers(dest="secrets_command", metavar="<subcommand>")
    scan = s.add_parser("scan", help="scan files (default: Knowledge/, .agents/, Toolbox/) for secrets")
    scan.add_argument("--staged", action="store_true", help="scan staged content (pre-commit)")
    scan.add_argument("paths", nargs="*", help="files or directories to scan")
    scan.set_defaults(func=cmd_scan)
    p.set_defaults(func=lambda _a: (p.print_help(), 0)[1])
