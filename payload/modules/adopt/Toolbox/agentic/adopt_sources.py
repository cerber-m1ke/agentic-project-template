"""tb adopt — what is read from the old places: source collectors (manifests), candidate sources,
inventory of old repositories, references to old paths in the environment, transcript digests.

Everything here only reads the old places. Git runs with GIT_OPTIONAL_LOCKS=0, so even `git status`
does not refresh an old index; only `inventory --fetch` updates remote-tracking refs.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import fnmatch
import json
import os
import re
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import common
import secret_scan
from adopt import (AdoptError, Source, Task, _with_task, expand, home, read_manifest, show, tilde, untilde,
                   SKIP_NAMES, RUNTIME)

WALK_SKIP = SKIP_NAMES | {"node_modules", "vendor", ".venv", "venv", "__pycache__", "var", "storage",
                          "build", "dist", "target", ".gradle", ".next", ".nuxt"}
AGENT_NAMES = ("AGENTS.md", "CLAUDE.md", "CLAUDE.local.md", "GEMINI.md", ".mcp.json", ".cursorrules")
AGENT_DIRS = (".claude", ".codex", ".cursor", ".gemini")
GLOBAL_INSTRUCTIONS = ("~/.claude/CLAUDE.md", "~/.codex/AGENTS.md")
REPO_DEPTH = 3
# inventory: untracked/ignored paths worth a look, and the usual junk
VALUABLE = re.compile(r"(^|/)(\.env[^/]*|[^/]*override[^/]*\.ya?ml|CLAUDE\.md|AGENTS\.md|\.claude|\.mcp\.json|"
                      r"\.codex|\.cursor|config\.ini|[^/]*\.local\.[^/]+|[^/]*\.(pem|key|ovpn|p12|pfx|crt|kdbx)|"
                      r"secrets?[^/]*|[^/]*\.(md|txt|sql|ipynb))(/|$)", re.I)
JUNK = re.compile(r"(^|/)(vendor|node_modules|var|cache|\.cache|logs?|tmp|build|dist|coverage|storage|"
                  r"\.idea|\.vscode|\.DS_Store|__pycache__|\.pytest_cache|\.venv|venv|bin|obj|\.gradle|"
                  r"\.next|\.nuxt|target)(/|$)|\.log$")
FOLDER_GUESS = {"decision": "Decisions", "gotcha": "Gotchas", "plan": "Plans", "project": "Entities",
                "entit": "Entities", "example": "Examples", "task": "Tasks"}
REMINDER_RE = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
CODEX_SKIP = ("<environment_context>", "<user_instructions>", "# AGENTS.md", "<permissions", "<INSTRUCTIONS>")
PEM_RE = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)", re.S)
UUID_RE = re.compile(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")
DIGEST_FIRST, DIGEST_LAST_HUMAN, DIGEST_ANSWER, DIGEST_TITLE = 900, 350, 550, 200


def git_env() -> dict:
    return {**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"}


def git(repo: Path, *args: str, timeout: int = 600) -> tuple[int, str]:
    try:
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, env=git_env())
    except subprocess.TimeoutExpired:
        return 124, ""
    return r.returncode, r.stdout


def claude_dir_name(path: Path) -> str:
    """Claude Code's directory for a project path: every char except ASCII letters and digits -> '-'."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(Path(os.path.abspath(path))))


# --- collectors ---------------------------------------------------------------------------------------------

def walk_files(base: Path, skip: set[str] = SKIP_NAMES) -> list[Path]:
    if base.is_file():
        return [base]
    found = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if d not in skip)
        found += [Path(dirpath) / f for f in sorted(filenames) if f not in skip]
    return found


def git_repos(base: Path, depth: int = REPO_DEPTH) -> list[Path]:
    """Git working copies under `base` (itself included), nested ones too, down to `depth` levels."""
    repos = []
    for dirpath, dirnames, _files in os.walk(base):
        d = Path(dirpath)
        if (d / ".git").exists():
            repos.append(d)
        if len(d.relative_to(base).parts) >= depth:
            dirnames[:] = []
        dirnames[:] = sorted(x for x in dirnames if x not in WALK_SKIP and not x.startswith("."))
    return repos


def untracked(repo: Path) -> list[str]:
    files: set[str] = set()
    for extra in ([], ["--ignored", "--exclude-standard"]):
        _rc, out = git(repo, "ls-files", "--others", "-z", *extra)
        files |= {f for f in out.split("\0") if f}
    return sorted(files)


def is_agent_file(relpath: str) -> bool:
    parts = relpath.split("/")
    if parts[-1] in SKIP_NAMES or WALK_SKIP & set(parts[:-1]):
        return False
    return parts[-1] in AGENT_NAMES or any(d in parts[:-1] for d in AGENT_DIRS)


def _filtered(source: Source, files: list[Path]) -> list[Path]:
    def match(p: Path, patterns: list[str]) -> bool:
        s = tilde(p)
        return any(fnmatch.fnmatch(s, pat) or fnmatch.fnmatch(p.name, pat) for pat in patterns)

    if source.include:
        files = [p for p in files if match(p, source.include)]
    return [p for p in files if not match(p, source.exclude)]


def _other_source_paths(task: Task, source: Source) -> list[Path]:
    return [Path(os.path.abspath(p)) for s in task.sources if s is not source
            for raw in s.paths for p in expand(raw)]


def _covered_elsewhere(path: Path, others: list[Path]) -> bool:
    p = Path(os.path.abspath(path))
    return any(p == o or o in p.parents for o in others)


def codex_sessions() -> list[Path]:
    base = home() / ".codex"
    found = []
    for d in ("sessions", "archived_sessions"):
        if (base / d).is_dir():
            found += sorted((base / d).rglob("rollout-*.jsonl"))
    return found


def codex_cwd(path: Path) -> str:
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            meta = json.loads(fh.readline())
    except (OSError, ValueError):
        return ""
    payload = meta.get("payload") if isinstance(meta, dict) else None
    return str((payload or {}).get("cwd", "")) if isinstance(payload, dict) else ""


def _under(cwd: str, prefixes: list[Path]) -> bool:
    if not cwd:
        return False
    p = Path(cwd)
    return any(p == pre or pre in p.parents for pre in prefixes)


def collect(task: Task, source: Source) -> list[Path]:
    """Files of one source (the manifest). Paths default to the task's old roots where it makes sense."""
    kind = source.kind
    paths = [p for raw in source.paths for p in expand(raw)]
    if kind in ("agent-files", "loose-docs") and not source.paths:
        paths = task.roots()
    if kind == "instructions" and not source.paths:
        paths = [untilde(p) for p in GLOBAL_INSTRUCTIONS]
    files: list[Path] = []
    if kind in ("vault", "docs", "claude-memory", "codex-memory", "instructions"):
        for p in paths:
            if p.exists():
                files += walk_files(p)
    elif kind == "loose-docs":
        others = _other_source_paths(task, source)
        for base in paths:
            if base.is_dir():
                files += [p for p in sorted(base.glob("*.md")) if p.name not in AGENT_NAMES
                          and not _covered_elsewhere(p, others)]
    elif kind == "agent-files":
        others = _other_source_paths(task, source)
        for base in paths:
            if not base.is_dir():
                continue
            files += [base / n for n in AGENT_NAMES if (base / n).is_file()]
            for repo in git_repos(base):
                if _covered_elsewhere(repo, others) and repo != base:
                    continue
                excl = repo / ".git" / "info" / "exclude"
                if excl.is_file() and any(n in common.read_text(excl) for n in (*AGENT_NAMES, *AGENT_DIRS)):
                    files.append(excl)
                files += [repo / f for f in untracked(repo) if is_agent_file(f)]
            files = [p for p in files if not _covered_elsewhere(p, others)]
    elif kind == "transcripts":
        for d in paths:
            if d.is_dir():
                files += sorted(d.glob("*.jsonl"))
        prefixes = [Path(os.path.abspath(untilde(c))) for c in source.codex_cwd]
        if prefixes:
            files += [p for p in codex_sessions() if _under(codex_cwd(p), prefixes)]
    else:  # parse_config validates kinds
        raise AdoptError(f"unknown kind: {kind}")
    return _filtered(source, sorted(dict.fromkeys(files)))


# --- sources: candidates ------------------------------------------------------------------------------------

def _toml_block(name: str, kind: str, paths: list[str], folder: str = "", comment: str = "",
                commented: bool = False, extra: dict[str, list[str]] | None = None) -> list[str]:
    lines = [f"# {comment}"] if comment else []
    body = ["[[source]]", f'name = "{name}"', f'kind = "{kind}"',
            "paths = [" + ", ".join(json.dumps(p, ensure_ascii=False) for p in paths) + "]"]
    if folder:
        body.append(f'folder = "{folder}"')
    for key, values in (extra or {}).items():
        body.append(f"{key} = [" + ", ".join(json.dumps(v, ensure_ascii=False) for v in values) + "]")
    lines += [("# " if commented else "") + b for b in body]
    return lines + [""]


def _kebab(text: str) -> str:
    from adopt import to_slug

    return to_slug(text)


def find_vaults(roots: list[Path], extra: list[Path]) -> list[Path]:
    vaults = [v for v in extra if v.is_dir()]
    for root in roots:
        for dirpath, dirnames, _files in os.walk(root):
            d = Path(dirpath)
            if (d / ".obsidian").is_dir():
                vaults.append(d)
                dirnames[:] = []
                continue
            if len(d.relative_to(root).parts) >= REPO_DEPTH:
                dirnames[:] = []
            dirnames[:] = sorted(x for x in dirnames if x not in WALK_SKIP and not x.startswith("."))
    return list(dict.fromkeys(vaults))


def candidate_sources(task: Task, vault_args: list[str]) -> list[str]:
    roots = [r for r in task.roots() if r.is_dir()]
    lines = ["# Candidate [[source]] blocks for adopt.toml (tb adopt sources): review, rename, cut.", ""]
    projects = home() / ".claude" / "projects"
    for root in roots:
        tag = _kebab(root.name)
        dirs = sorted(projects.glob(claude_dir_name(root) + "*")) if projects.is_dir() else []
        mem = [d / "memory" for d in dirs if (d / "memory").is_dir()]
        if mem:
            lines += _toml_block(f"{tag}-claude-memory", "claude-memory", [tilde(m) for m in mem],
                                 comment="Claude Code memory of the old copy (cut by topic)")
        jsonl = [d for d in dirs if any(d.glob("*.jsonl"))]
        codex = [p for p in codex_sessions() if _under(codex_cwd(p), [Path(os.path.abspath(root))])]
        if jsonl or codex:
            n = sum(len(list(d.glob("*.jsonl"))) for d in jsonl) + len(codex)
            lines += _toml_block(f"{tag}-transcripts", "transcripts", [tilde(d) for d in jsonl], commented=True,
                                 extra={"codex_cwd": [tilde(root)]} if codex else None,
                                 comment=f"agent transcripts ({n} sessions): on request only, via tb adopt digest")
    vaults = find_vaults(roots, [untilde(v) for v in vault_args])
    for v in vaults:
        vtag = _kebab(v.name)
        subdirs = sorted(d for d in v.iterdir() if d.is_dir() and not d.name.startswith((".", "_")))
        for d in subdirs:
            folder = next((f for k, f in FOLDER_GUESS.items() if d.name.lower().startswith(k)), "")
            n = sum(1 for _ in d.rglob("*.md"))
            lines += _toml_block(f"{vtag}-{_kebab(d.name)}", "vault", [tilde(d)], folder=folder,
                                 comment=f"vault folder ({n} .md)" + ("" if folder else "; set folder if it is a type"))
        loose = sorted(p for p in v.glob("*.md"))
        if loose:
            lines += _toml_block(f"{vtag}-root", "vault", [tilde(p) for p in loose],
                                 comment="vault root files (index, glossary): usually derivable or aliases")
    if (home() / ".codex" / "memories").is_dir():
        lines += _toml_block("codex-memory", "codex-memory", ["~/.codex/memories"],
                             comment="global Codex memory: only what concerns this project (the rest — foreign)")
    for root in roots:
        tag = _kebab(root.name)
        for d in sorted(x for x in root.iterdir() if x.is_dir() and not x.name.startswith(".")):
            if (d / ".git").exists() or d in vaults:
                continue
            if d.name.lower().lstrip("_") in ("docs", "doc", "notes", "research") or any(d.glob("*.md")):
                lines += _toml_block(f"{tag}-{_kebab(d.name)}", "docs", [tilde(d)],
                                     comment="working documents outside repositories")
        lines += _toml_block(f"{tag}-agent-files", "agent-files", [tilde(root)],
                             comment="untracked agent files (CLAUDE.md, .claude/, …) in the old copy and its repos")
        if any(p.name not in AGENT_NAMES for p in root.glob("*.md")):
            lines += _toml_block(f"{tag}-loose-docs", "loose-docs", [tilde(root)], comment="*.md in the old root")
    present = [p for p in GLOBAL_INSTRUCTIONS if untilde(p).is_file()]
    if present:
        lines += _toml_block("instructions", "instructions", present,
                             comment="global agent instructions: rules about working with the human -> AGENTS.md")
    return lines


@_with_task
def cmd_sources(args: argparse.Namespace, task: Task) -> int:
    if not task.old_roots:
        common.warn("old_roots is empty in adopt.toml: only global sources are listed")
    for line in candidate_sources(task, args.vault):
        common.out(line)
    return 0


# --- inventory ------------------------------------------------------------------------------------------------

@dataclass
class RepoInfo:
    path: Path
    remote: str = ""
    branch: str = ""
    last: str = ""
    fetch: str = "-"
    lsremote: str = "-"
    unknown_heads: int = 0
    branches: list[tuple[str, int, str]] = field(default_factory=list)   # (branch, commits, on-server|local-only)
    stale: list[tuple[str, int]] = field(default_factory=list)           # origin/* gone from the server
    stash: list[str] = field(default_factory=list)
    dirty: list[str] = field(default_factory=list)
    keep: list[str] = field(default_factory=list)
    other: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)

    @property
    def flagged(self) -> bool:
        return bool(self.branches or self.stale or self.stash or self.dirty or self.keep or not self.remote)


def inspect_repo(repo: Path, fetch: bool, offline: bool) -> RepoInfo:
    d = RepoInfo(path=repo)
    _rc, url = git(repo, "remote", "get-url", "origin")
    d.remote = url.strip()
    if fetch and d.remote:
        rc, _ = git(repo, "fetch", "origin", "--no-prune", "--quiet")
        d.fetch = "ok" if rc == 0 else "FAIL"
    _rc, br = git(repo, "branch", "--show-current")
    d.branch = br.strip() or "(detached)"
    _rc, last = git(repo, "log", "-1", "--format=%cs")
    d.last = last.strip()
    live: dict[str, str] = {}
    if d.remote and not offline:
        rc, out = git(repo, "ls-remote", "--heads", "origin", timeout=120)
        if rc == 0:
            d.lsremote = "ok"
            for line in out.splitlines():
                sha, _, ref = line.partition("\t")
                live[ref.removeprefix("refs/heads/")] = sha
        else:
            d.lsremote = "FAIL"
    if d.lsremote != "ok":  # offline or unreachable: what the remote-tracking refs say
        _rc, out = git(repo, "for-each-ref", "--format=%(refname:short) %(objectname)", "refs/remotes/origin")
        for line in out.splitlines():
            ref, _, sha = line.partition(" ")
            if ref not in ("origin/HEAD", "origin"):
                live[ref.removeprefix("origin/")] = sha
    known = [s for s in set(live.values()) if git(repo, "cat-file", "-e", s + "^{commit}")[0] == 0]
    d.unknown_heads = len(set(live.values())) - len(known)

    def unique(ref: str) -> int:
        rc, out = git(repo, "rev-list", "--count", ref, "--not", *known) if known else \
            git(repo, "rev-list", "--count", ref)
        return int(out.strip() or 0) if rc == 0 else -1

    _rc, heads = git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads")
    for b in heads.split():
        if n := unique(b):
            d.branches.append((b, n, "on-server" if b in live else "local-only"))
    if d.lsremote == "ok":
        _rc, rrefs = git(repo, "for-each-ref", "--format=%(refname:short)", "refs/remotes/origin")
        for r in rrefs.split():
            name = r.removeprefix("origin/")
            if name in ("HEAD", "origin") or name in live:
                continue
            if n := unique(r):
                d.stale.append((r, n))
    _rc, st = git(repo, "stash", "list")
    d.stash = [line[:100] for line in st.splitlines()]
    _rc, por = git(repo, "status", "--porcelain", "--ignored", "--untracked-files=normal")
    nested = {p.name for p in repo.iterdir() if p.is_dir() and (p / ".git").exists()}
    for line in por.splitlines():
        code, path = line[:2], line[3:].strip('"').rstrip("/")
        if path.split("/")[0] in nested:
            continue
        if code not in ("??", "!!"):
            d.dirty.append(f"{code} {path}")
        elif VALUABLE.search(path) and not JUNK.search(path):
            d.keep.append(f"{code} {path}")
        elif not JUNK.search(path):
            d.other.append(f"{code} {path}")
    excl = repo / ".git" / "info" / "exclude"
    if excl.is_file():
        d.exclude = [line for line in common.read_text(excl).splitlines() if line.strip() and not line.startswith("#")]
    return d


def tree_size(path: Path) -> tuple[int, int]:
    if path.is_file():
        return 1, path.stat().st_size
    files = size = 0
    for dirpath, _dirnames, filenames in os.walk(path):
        for f in filenames:
            p = Path(dirpath) / f
            try:
                if not p.is_symlink():
                    size += p.stat().st_size
                    files += 1
            except OSError:
                pass
    return files, size


def _rel_to(path: Path, roots: list[Path]) -> str:
    for r in roots:
        try:
            return (Path(r.name) / path.relative_to(r)).as_posix()
        except ValueError:
            continue
    return tilde(path)


@_with_task
def cmd_inventory(args: argparse.Namespace, task: Task) -> int:
    roots = [untilde(r) for r in args.roots] if args.roots else task.roots()
    roots = [Path(os.path.abspath(r)) for r in roots]
    if not roots:
        return common.fail("no roots: pass them or fill old_roots in adopt.toml")
    for r in roots:
        if not r.is_dir():
            return common.fail(f"not a directory: {tilde(r)}")
    out = Path(args.out) if args.out else common.project_root() / RUNTIME / "inventory" / common.today_iso()
    if out.exists() and any(out.iterdir()) and not args.force:
        return common.fail(f"{show(out)} exists; pass --out DIR or --force")
    repos: list[Path] = []
    nongit: list[Path] = []
    for root in roots:
        found = git_repos(root, args.depth)
        repos += found
        for entry in sorted(root.iterdir()):
            if entry.name in SKIP_NAMES or (entry / ".git").exists() or entry in found:
                continue
            if not any(r == entry or entry in r.parents for r in found):
                nongit.append(entry)
    with cf.ThreadPoolExecutor(8) as ex:
        infos = list(ex.map(lambda r: inspect_repo(r, args.fetch, args.offline), repos))
    head = ["path", "remote", "branch", "last", "local_only", "unpushed", "stale_unique", "stash", "dirty",
            "keep", "other", "exclude", "unknown_heads", "ls_remote", "fetch"]
    rows = ["\t".join(head)]
    table = ["| Repository | Remote | Branch | Local work | Decision | Note |", "|---|---|---|---|---|---|"]
    for d in infos:
        name = _rel_to(d.path, roots)
        lo = [b for b in d.branches if b[2] == "local-only"]
        unp = sum(b[1] for b in d.branches)
        stale = sum(n for _, n in d.stale)
        rows.append("\t".join(map(str, [name, d.remote or "-", d.branch, d.last, len(lo), unp, stale, len(d.stash),
                                        len(d.dirty), len(d.keep), len(d.other), len(d.exclude), d.unknown_heads,
                                        d.lsremote, d.fetch])))
        det = [f"# {name}", f"path: {tilde(d.path)}", f"remote: {d.remote or '-'}",
               f"branch: {d.branch}  last: {d.last}  ls-remote: {d.lsremote}  fetch: {d.fetch}"]
        for title, items in (("branches with commits the server lacks", [f"{b} +{n} ({k})" for b, n, k in d.branches]),
                             ("stale origin/* refs with commits the server lacks", [f"{r} +{n}" for r, n in d.stale]),
                             ("stash", d.stash), ("dirty", d.dirty), ("keep (valuable untracked/ignored)", d.keep),
                             ("other untracked/ignored", d.other[:40]), (".git/info/exclude", d.exclude)):
            if items:
                det += [f"## {title}", *[f"- {i}" for i in items]]
        common.write_text(out / "details" / (re.sub(r"[^A-Za-z0-9._-]+", "__", name) + ".txt"), "\n".join(det) + "\n")
        work = []
        if unp:
            work.append(f"{unp} commits not on server" + (f" ({len(lo)} local-only branches)" if lo else ""))
        if stale:
            work.append(f"{stale} commits only in stale origin/*")
        for label, items in (("stash", d.stash), ("dirty", d.dirty), ("valuable untracked", d.keep)):
            if items:
                work.append(f"{len(items)} {label}")
        if not d.remote:
            work.append("no origin")
        table.append(f"| {name} | {d.remote or '—'} | {d.branch} | {'; '.join(work) or '—'} |  |  |")
    common.write_text(out / "git.tsv", "\n".join(rows) + "\n")
    ng = ["path\tfiles\tsize_mb\tnotable"]
    for p in nongit:
        files, size = tree_size(p)
        notable = sorted({f.name for f in (walk_files(p, WALK_SKIP) if p.is_dir() else [p])
                          if VALUABLE.search(f.name) and not f.name.endswith((".md", ".txt"))})[:10]
        ng.append(f"{_rel_to(p, roots)}\t{files}\t{size / 1024 / 1024:.1f}\t{','.join(notable)}")
        table.append(f"| {_rel_to(p, roots)} (not git) | — | — | {files} files, {size / 1024 / 1024:.1f} MB |  |  |")
    common.write_text(out / "nongit.tsv", "\n".join(ng) + "\n")
    common.write_text(out / "resources.md", "\n".join(table) + "\n")
    flagged = [d for d in infos if d.flagged]
    common.out(f"repos: {len(infos)}, non-git: {len(nongit)}, with local work: {len(flagged)} -> {show(out)}")
    for d in flagged:
        common.out(f"  {_rel_to(d.path, roots)}")
    if args.compare:
        return compare_inventory(Path(args.compare), out)
    return 0


def _tsv(path: Path) -> dict[str, dict[str, str]]:
    lines = common.read_text(path).splitlines()
    head = lines[0].split("\t")
    return {cells[0]: dict(zip(head, cells)) for cells in (line.split("\t") for line in lines[1:] if line)}


def compare_inventory(before_dir: Path, after_dir: Path) -> int:
    """Final audit: what changed in the old places since the snapshot (new work = a blocker)."""
    if not (before_dir / "git.tsv").is_file():
        return common.fail(f"no git.tsv in {show(before_dir)}")
    before, after = _tsv(before_dir / "git.tsv"), _tsv(after_dir / "git.tsv")
    keys = ("unpushed", "stale_unique", "stash", "dirty", "keep", "last")
    changes = 0
    for name in sorted(set(before) | set(after)):
        b, a = before.get(name), after.get(name)
        if b is None or a is None:
            common.out(f"{'new' if b is None else 'gone'}: {name}")
            changes += 1
            continue
        diff = [f"{k} {b.get(k)} -> {a.get(k)}" for k in keys if b.get(k) != a.get(k)]
        if diff:
            common.out(f"changed: {name}: {', '.join(diff)}")
            changes += 1
    common.out(f"{changes} change(s) since {show(before_dir)}")
    return 1 if changes else 0


# --- refs: old paths in the environment ---------------------------------------------------------------------

def env_files() -> list[Path]:
    h = home()
    appdata = Path(os.environ.get("APPDATA") or h / "AppData" / "Roaming")
    support = h / "Library" / "Application Support"
    config = Path(os.environ.get("XDG_CONFIG_HOME") or h / ".config")
    files = [h / ".gitconfig", config / "git" / "config", h / ".claude.json", h / ".claude" / "settings.json",
             h / ".codex" / "config.toml", h / ".zshrc", h / ".zprofile", h / ".bashrc", h / ".bash_profile",
             h / ".profile", config / "fish" / "config.fish"]
    files += [h / name for name in os.listdir(h) if name.startswith(".gitconfig-")] if h.is_dir() else []
    for base in (support, config, appdata):
        files += [base / "obsidian" / "obsidian.json", base / "Code" / "User" / "globalStorage" / "storage.json"]
        files += sorted(base.glob("JetBrains/*/options/recentProjects.xml"))
        files += sorted(base.glob("JetBrains/*/options/trusted-paths.xml"))
    files += sorted((h / "Library" / "LaunchAgents").glob("*.plist"))
    return [f for f in dict.fromkeys(files) if f.is_file()]


def _json_hits(data, needles: list[str], at: str = "") -> list[str]:
    hits = []
    if isinstance(data, dict):
        for k, v in data.items():
            key = f"{at}/{k}"
            if any(n in str(k) for n in needles):
                hits.append(key)
            hits += _json_hits(v, needles, key)
    elif isinstance(data, list):
        for i, v in enumerate(data):
            hits += _json_hits(v, needles, f"{at}/{i}")
    elif isinstance(data, str) and any(n in data for n in needles):
        hits.append(at or "/")
    return hits


def scan_refs(old: list[Path]) -> list[str]:
    needles = sorted({s for p in old for s in (str(p), tilde(p))}, key=len, reverse=True)
    found: list[str] = []
    for f in env_files():
        try:
            text = common.read_text(f)
        except (OSError, UnicodeDecodeError):
            continue
        if not any(n in text for n in needles):
            continue
        if f.suffix == ".json":
            try:
                found += [f"{tilde(f)}: {hit}" for hit in _json_hits(json.loads(text), needles)[:50]]
                continue
            except ValueError:
                pass
        for n, line in enumerate(text.splitlines(), start=1):
            hit = next((x for x in needles if x in line), None)
            if hit:
                found.append(f"{tilde(f)}:{n}: {hit}")
    for cmd, label in ((["crontab", "-l"], "crontab"),):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            continue
        for n, line in enumerate(r.stdout.splitlines(), start=1):
            hit = next((x for x in needles if x in line), None)
            if hit:
                found.append(f"{label}:{n}: {hit}")
    found += docker_refs(needles)
    return found


def docker_refs(needles: list[str]) -> list[str]:
    try:
        ids = subprocess.run(["docker", "ps", "-aq"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if ids.returncode != 0 or not ids.stdout.split():
        return []
    try:
        r = subprocess.run(["docker", "inspect", *ids.stdout.split()], capture_output=True, text=True, timeout=60)
        items = json.loads(r.stdout or "[]")
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return []
    found = []
    for c in items:
        name = str(c.get("Name", "?")).lstrip("/")
        labels = (c.get("Config") or {}).get("Labels") or {}
        for key in ("com.docker.compose.project.working_dir", "com.docker.compose.project.config_files"):
            if any(n in str(labels.get(key, "")) for n in needles):
                found.append(f"docker {name}: label {key} (compose project {labels.get('com.docker.compose.project', '?')})")
        for m in c.get("Mounts") or []:
            if any(n in str(m.get("Source", "")) for n in needles):
                found.append(f"docker {name}: mount {m.get('Source')} -> {m.get('Destination')}")
    return found


@_with_task
def cmd_refs(args: argparse.Namespace, task: Task) -> int:
    old = [Path(os.path.abspath(untilde(p))) for p in args.paths] if args.paths else task.roots()
    if not old:
        return common.fail("no paths: pass them or fill old_roots in adopt.toml")
    found = scan_refs(old)
    for line in found:
        common.out(line)
    common.out(f"{len(found)} reference(s) to {', '.join(tilde(p) for p in old)} "
               "(locations only; values are not printed)")
    return 0


# --- digest: transcripts -------------------------------------------------------------------------------------

def clip(text: str, n: int) -> str:
    text = re.sub(r"\n{3,}", "\n\n", text.strip())
    return text if len(text) <= n else text[:n].rstrip() + " […]"


def redact(text: str) -> str:
    """Replace every secret the scanner finds with its kind; values never leave the transcript.
    A private key is masked as a whole block: the scanner reports only its header line."""
    text = PEM_RE.sub("[secret: private key]", text)
    for f in sorted(secret_scan.scan_text(text), key=lambda f: -len(f.value)):
        text = text.replace(f.value, f"[secret: {f.kind}]")
    return text


def _texts(content, kinds: str) -> list[str]:
    if isinstance(content, str):
        return [content]
    return [b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") in kinds.split(",")]


def _new_session() -> dict:
    return {"cwd": set(), "ts": [], "human": [], "first": None, "answers": [], "title": None, "branch": set()}


def parse_claude(path: Path) -> dict:
    s = _new_session()
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if not isinstance(d, dict):
                continue
            t = d.get("type")
            if d.get("timestamp"):
                s["ts"].append(str(d["timestamp"]))
            if d.get("cwd"):
                s["cwd"].add(str(d["cwd"]))
            if d.get("gitBranch") and d["gitBranch"] != "HEAD":
                s["branch"].add(str(d["gitBranch"]))
            if t in ("custom-title", "summary"):
                s["title"] = d.get("customTitle") or d.get("summary") or s["title"]
            if d.get("isSidechain") or not isinstance(d.get("message"), dict):
                continue
            if t == "user" and not d.get("toolUseResult") and not d.get("isMeta"):
                body = REMINDER_RE.sub("", "\n".join(_texts(d["message"].get("content"), "text"))).strip()
                if not body or body.startswith(("[Request interrupted", "<local-command", "<command-")):
                    continue
                s["first"] = s["first"] or body
                s["human"].append(body)
            elif t == "assistant":
                s["answers"] += [x for x in _texts(d["message"].get("content"), "text") if x.strip()]
    return s


def parse_codex(path: Path) -> dict:
    s = _new_session()
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if not isinstance(d, dict):
                continue
            p = d.get("payload") if isinstance(d.get("payload"), dict) else {}
            if d.get("timestamp"):
                s["ts"].append(str(d["timestamp"]))
            if p.get("cwd"):
                s["cwd"].add(str(p["cwd"]))
            if d.get("type") == "response_item" and p.get("type") == "message":
                body = "\n".join(_texts(p.get("content"), "input_text,output_text")).strip()
                if p.get("role") == "user" and body and not body.startswith(CODEX_SKIP):
                    s["first"] = s["first"] or body
                    s["human"].append(body)
                elif p.get("role") == "assistant" and body:
                    s["answers"].append(body)
    return s


def digest(path: Path, entry: str) -> tuple[str, str, dict]:
    codex = "/.codex/" in entry or path.name.startswith("rollout-")
    s = parse_codex(path) if codex else parse_claude(path)
    m = UUID_RE.search(path.name)
    sid = m.group(1) if m else path.stem
    ts = sorted(s["ts"])
    start, end = (ts[0][:16].replace("T", " "), ts[-1][:16].replace("T", " ")) if ts else ("?", "?")
    parts = [f"# {sid}", "", f"- source: `{entry}`",
             f"- period (UTC): {start} → {end}; {path.stat().st_size // 1024} KB; human messages: {len(s['human'])}",
             f"- cwd: {', '.join(sorted(s['cwd'])) or '?'}"]
    if s["branch"]:
        parts.append(f"- branches: {', '.join(sorted(s['branch']))[:200]}")
    if s["title"]:
        parts.append(f"- title: {clip(str(s['title']), DIGEST_TITLE)}")
    parts += ["", "## First request", "", clip(s["first"] or "(none)", DIGEST_FIRST)]
    if len(s["human"]) > 1 and s["human"][-1] != s["first"]:
        parts += ["", "## Last human request", "", clip(s["human"][-1], DIGEST_LAST_HUMAN)]
    parts += ["", "## Last agent answers"]
    for i, a in enumerate(s["answers"][-3:], start=1):
        parts += ["", f"### {i}", "", clip(a, DIGEST_ANSWER)]
    meta = {"start": start, "end": end, "human": len(s["human"]), "codex": codex,
            "title": redact(str(s["title"] or "").replace("\t", " "))[:80]}
    return sid, redact("\n".join(parts)) + "\n", meta


@_with_task
def cmd_digest(args: argparse.Namespace, task: Task) -> int:
    source = task.source(args.source)
    if source.kind != "transcripts":
        return common.fail(f"{source.name} is a {source.kind} source; digests are for transcripts")
    out = common.project_root() / RUNTIME / "digests" / source.name
    entries = read_manifest(task, source.name)
    index = ["id\tstart\tend\tsize_kb\thuman_msgs\ttitle\tmanifest"]
    secrets = ["id\tkinds"]
    for entry in entries:
        path = untilde(entry)
        if not path.is_file():
            common.warn(f"missing: {entry}")
            continue
        sid, text, meta = digest(path, entry)
        kinds = Counter(f.kind for f in secret_scan.scan_text(path.read_text(encoding="utf-8", errors="replace")))
        if kinds:
            secrets.append(f"{sid}\t" + ", ".join(f"{k}×{n}" for k, n in sorted(kinds.items())))
        common.write_text(out / f"{sid}.md", text)
        index.append(f"{sid}\t{meta['start']}\t{meta['end']}\t{path.stat().st_size // 1024}\t{meta['human']}\t"
                     f"{meta['title']}\t{entry}")
    common.write_text(out / "_index.tsv", "\n".join(index) + "\n")
    common.write_text(out / "_secrets.tsv", "\n".join(secrets) + "\n")
    common.out(f"digests: {len(index) - 1} -> {show(out)}; sessions with secret findings: {len(secrets) - 1} "
               "(kinds only in _secrets.tsv; the transcripts are sensitive: archive them mode 600)")
    return 0


def register(add) -> None:
    p = add("sources", "candidate [[source]] blocks for adopt.toml found by the old roots and agent data",
            cmd_sources)
    p.add_argument("--vault", action="append", default=[], metavar="PATH",
                   help="an Obsidian vault or external memory outside the old roots (repeatable)")
    p = add("inventory", "old roots: git repos (nested too), local work against the live server, stash, "
                         "dirty and valuable untracked files, non-git entries -> Runtime/adopt/inventory/",
            cmd_inventory)
    p.add_argument("roots", nargs="*", help="default: old_roots of adopt.toml")
    p.add_argument("--fetch", action="store_true",
                   help="git fetch origin --no-prune first (updates refs of the old copies; stale refs are kept)")
    p.add_argument("--offline", action="store_true", help="no git ls-remote: compare against origin/* refs only")
    p.add_argument("--depth", type=int, default=REPO_DEPTH, help=f"levels to look for nested repos (default {REPO_DEPTH})")
    p.add_argument("--out", metavar="DIR", help="output dir (default: Runtime/adopt/inventory/<date>/)")
    p.add_argument("--force", action="store_true", help="write into a non-empty output dir")
    p.add_argument("--compare", metavar="DIR", help="an earlier inventory dir: report what changed (exit 1 if any)")
    p = add("refs", "references to old paths in the environment: git config, agents, shell rc, Obsidian, IDE, "
                    "LaunchAgents, crontab, Docker", cmd_refs)
    p.add_argument("paths", nargs="*", help="default: old_roots of adopt.toml")
    p = add("digest", "transcript digests (~3 KB, secrets masked) -> Runtime/adopt/digests/<source>/", cmd_digest)
    p.add_argument("source")
