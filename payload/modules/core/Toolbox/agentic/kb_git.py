"""tb kb commit / squash — commit Knowledge/ right after an edit, attributed to the agent session.

Parallel sessions share one working tree and one git index, so a commit takes only the given paths
(`git commit --only`): whatever another session has staged stays staged and out of this commit.
Every commit carries the trailer `Agent-Session: <agent>:<id> (<session title>)`; it tells which session
wrote what and which earlier commit `--amend` may correct. Only `<agent>:<id>` identifies the session:
the title (`tb kb session title`) is for people searching the history and may change.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import time
from pathlib import Path

import common

SESSION_TRAILER = "Agent-Session"
SESSION_ENV = (("claude", "CLAUDE_CODE_SESSION_ID"),)  # (agent, variable with the session id)
SESSION_OVERRIDE = "AGENTIC_SESSION"                  # "<agent>:<id>" for agents not listed above
SESSIONS_DIR = "Runtime/sessions"                     # Knowledge files edited per session (hooks)
SESSION_FILE_DAYS = 14
TITLE_MAX = 80
HOOKS_PATH = ".agents/git-hooks"
FIXUP = "fixup! "
SCOPE = "knowledge:"
HISTORY = 200        # how far back to look for this session's commits and fixup targets
LOCK_RETRIES = 10    # another session may hold .git/index.lock for a moment

_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")
_SEP, _END = "\x1f", "\x1e"


# --- sessions -----------------------------------------------------------------------------------

def current_session() -> str | None:
    """`<agent>:<id>` of the agent session running tb, from its environment."""
    if value := os.environ.get(SESSION_OVERRIDE, "").strip():
        return value
    for agent, var in SESSION_ENV:
        if value := os.environ.get(var, "").strip():
            return f"{agent}:{value}"
    return None


def session_file(session: str) -> Path:
    return common.project_root() / SESSIONS_DIR / (_SAFE_RE.sub("-", session).strip("-") + ".txt")


def title_file(session: str) -> Path:
    return session_file(session).with_suffix(".title")


def session_title(session: str) -> str:
    path = title_file(session)
    return common.read_text(path).strip() if path.is_file() else ""


def normalize_title(text: str) -> str:
    title = " ".join(text.split())
    return title if len(title) <= TITLE_MAX else title[:TITLE_MAX - 1].rstrip() + "…"


def trailer_value(session: str) -> str:
    """`<agent>:<id>`, followed by ` (<title>)` when the session has one."""
    title = session_title(session)
    return f"{session} ({title})" if title else session


def tracked(session: str) -> list[str]:
    path = session_file(session)
    if not path.is_file():
        return []
    return [line for line in common.read_text(path).splitlines() if line.strip()]


def track(session: str, paths: list[str]) -> None:
    """Remember Knowledge files edited by a session (after-tool hook); prune old session files."""
    path = session_file(session)
    known = tracked(session)
    new = [p for p in dict.fromkeys(paths) if p not in known]
    path.parent.mkdir(parents=True, exist_ok=True)
    if new:
        common.write_text(path, "".join(f"{p}\n" for p in known + new))
    cutoff = time.time() - SESSION_FILE_DAYS * 86400
    for old in path.parent.glob("*"):
        if old.is_file() and old.stat().st_mtime < cutoff:
            old.unlink(missing_ok=True)


def dirty(paths: list[str]) -> list[str]:
    """Paths among `paths` with changes not committed yet."""
    return sorted(status(paths)) if paths else []


def dirty_state(paths: list[str]) -> str:
    """Fingerprint of uncommitted paths and their mtimes: the stop hook nudges once per state."""
    root = common.project_root()
    parts = []
    for p in paths:
        try:
            parts.append(f"{p}:{(root / p).stat().st_mtime_ns}")
        except OSError:
            parts.append(f"{p}:deleted")
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


# --- git helpers --------------------------------------------------------------------------------

def _git(*args: str, env: dict | None = None):
    """git in the project root; retries while another session holds index.lock."""
    full_env = {**os.environ, **env} if env else None
    for attempt in range(LOCK_RETRIES):
        res = common.run(["git", *args], cwd=common.project_root(), env=full_env)
        if res.returncode == 0 or "index.lock" not in res.stderr or attempt == LOCK_RETRIES - 1:
            return res
        time.sleep(0.5)
    return res


def status(paths: list[str]) -> dict[str, str]:
    """{path: XY} of `git status --porcelain` for the paths (untracked files listed one by one)."""
    res = _git("status", "--porcelain=v1", "-z", "--untracked-files=all", "--", *paths)
    entries = res.stdout.split("\0")
    result: dict[str, str] = {}
    i = 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if len(entry) < 4:
            continue
        xy, path = entry[:2], entry[3:]
        result[path] = xy
        if xy[0] in "RC":  # the next entry is the rename source
            i += 1
    return result


def _commits(*args: str) -> list[dict[str, str]]:
    """Recent commits, newest first: sha, subject, session trailer."""
    fmt = f"%H{_SEP}%s{_SEP}%(trailers:key={SESSION_TRAILER},valueonly,separator=%x20){_END}"
    res = _git("log", f"-n{HISTORY}", f"--format={fmt}", *args)
    if res.returncode != 0:
        return []
    result = []
    for record in res.stdout.split(_END):
        fields = record.strip("\n").split(_SEP)
        if len(fields) == 3:
            value = fields[2].split()  # `<agent>:<id> (<title>)`: the first word is the session
            result.append({"sha": fields[0], "subject": fields[1], "session": value[0] if value else ""})
    return result


def pushed(sha: str) -> bool:
    """The commit is on a remote-tracking branch: never rewrite it."""
    res = _git("branch", "-r", "--contains", sha)
    return res.returncode == 0 and bool(res.stdout.strip())


def _hooks_problem() -> str | None:
    if _git("rev-parse", "--git-dir").returncode != 0:
        return "the project root is not a git repository"
    hooks = _git("config", "--get", "core.hooksPath").stdout.strip().rstrip("/")
    if hooks != HOOKS_PATH or not (common.project_root() / HOOKS_PATH / "pre-commit").is_file():
        return ("git hooks are not enabled (the pre-commit hook checks notes and secrets): "
                "run Toolbox/tb setup, then commit again")
    return None


# --- commit -------------------------------------------------------------------------------------

def knowledge_paths(raw_paths: list[str]) -> tuple[list[str], str | None]:
    """Normalize paths (absolute, from the cwd, the project root or Knowledge/) to root-relative ones."""
    root = common.project_root()
    kdir = root / common.KNOWLEDGE_DIR
    result = []
    for raw in raw_paths:
        p = Path(raw)
        cands = [p] if p.is_absolute() else [Path.cwd() / p, root / p, kdir / p]
        chosen = next((c for c in cands if c.exists()), None)
        if chosen is None:  # deleted: as written from the root, or from Knowledge/
            chosen = p if p.is_absolute() else (root / p if p.parts[:1] == (common.KNOWLEDGE_DIR,) else kdir / p)
        rel = Path(os.path.relpath(os.path.abspath(chosen), root)).as_posix()
        parts = rel.split("/")
        if parts[0] != common.KNOWLEDGE_DIR or ".obsidian" in parts:
            return [], f"not a Knowledge path: {raw} (tb kb commit commits only Knowledge/; " \
                       "commit other files separately when the human asks)"
        result.append(rel)
    return list(dict.fromkeys(result)), None


def compose(messages: list[str], session: str | None, fixup_of: str | None = None) -> str:
    lines = [m.strip() for m in messages if m.strip()]
    if fixup_of is not None:
        subject = FIXUP + fixup_of
    else:
        subject = lines[0] if lines else ""
        if not subject.lower().startswith(SCOPE):
            subject = f"{SCOPE} {subject}"
    body = lines[1:] if fixup_of is None else lines
    text = subject + ("\n\n" + "\n".join(body) if body else "")
    if session:
        text += f"\n\n{SESSION_TRAILER}: {trailer_value(session)}"
    return text + "\n"


def correction_target(paths: list[str], session: str | None) -> tuple[dict | None, str]:
    """This session's newest unpushed commit that touched the paths: (commit, why-not-found)."""
    if not session:
        return None, "no agent session id in the environment, so this session's commits are unknown"
    for c in _commits("--", *paths):
        if c["session"] != session or c["subject"].startswith(FIXUP):
            continue
        if pushed(c["sha"]):
            return None, f"this session's commit {c['sha'][:7]} is already pushed"
        return c, ""
    return None, "this session has no commit with these notes yet"


def cmd_commit(args: argparse.Namespace) -> int:
    if problem := _hooks_problem():
        return common.fail(problem)
    paths, problem = knowledge_paths(args.paths)
    if problem:
        return common.fail(problem, 2)
    if not args.amend and not args.message:
        return common.fail("give a message: -m \"<what changed>\" [-m \"- point\"]…", 2)
    changed = status(paths)
    if not changed:
        common.out("Nothing to commit: no changes in " + ", ".join(paths))
        return 0
    session = current_session()
    mode, target, note = "commit", None, ""
    if args.amend:
        target, note = correction_target(paths, session)
        if target is None:
            if not args.message:
                return common.fail(f"cannot amend: {note}; give -m to make a new commit", 2)
        else:
            head = _git("rev-parse", "HEAD").stdout.strip()
            mode = "amend" if target["sha"] == head else "fixup"
    untracked = [p for p, xy in changed.items() if xy == "??"]
    if untracked and (res := _git("add", "--", *untracked)).returncode != 0:
        return common.fail(res.stderr.strip() or "git add failed")

    cmd = ["commit", "--only"]
    if mode == "amend":
        cmd.append("--amend")
        if not args.message:
            cmd.append("--no-edit")
    message = None
    if mode == "fixup":
        message = compose(args.message or [], session, fixup_of=target["subject"])
    elif args.message:
        message = compose(args.message, session)
    msg_file = None
    if message is not None:
        msg_file = common.project_root() / "Runtime" / f"kb-commit-{os.getpid()}.txt"
        msg_file.parent.mkdir(parents=True, exist_ok=True)
        common.write_text(msg_file, message)
        cmd += ["-F", str(msg_file)]
    try:
        res = _git(*cmd, "--", *sorted(changed))
    finally:
        if msg_file is not None:
            msg_file.unlink(missing_ok=True)
    if res.returncode != 0:
        if untracked:  # leave the index as it was
            _git("reset", "-q", "--", *untracked)
        detail = "\n".join(x for x in (res.stdout.strip(), res.stderr.strip()) if x)
        return common.fail(f"git commit failed:\n{detail}")
    head = _git("log", "-1", "--format=%h %s").stdout.strip()
    verb = {"commit": "Committed", "amend": "Amended", "fixup": "Fixup committed"}[mode]
    common.out(f"{verb} {head}")
    for p in sorted(changed):
        common.out(f"  {p}")
    if mode == "fixup":
        common.out(f"Corrects {target['sha'][:7]} {target['subject']}; other commits came after it. "
                   "Squash later with Toolbox/tb kb squash (needs a clean working tree).")
    elif args.amend and target is None:
        common.out(f"New commit instead of a correction: {note}.")
    if not session:
        common.out(f"No {SESSION_TRAILER} trailer: the agent session id is unknown "
                   f"(set {SESSION_OVERRIDE}=<agent>:<id>).")
    elif not session_title(session):
        common.out('The session has no title: Toolbox/tb kb session title "<what this session does>" '
                   "adds it to the next commits.")
    return 0


# --- session ------------------------------------------------------------------------------------

def cmd_session(args: argparse.Namespace) -> int:
    session = current_session()
    if session is None:
        return common.fail(f"the agent session id is unknown (set {SESSION_OVERRIDE}=<agent>:<id>)")
    if getattr(args, "session_command", None) == "title":
        title = normalize_title(" ".join(args.text))
        if not title:
            return common.fail("give a title", 2)
        path = title_file(session)
        path.parent.mkdir(parents=True, exist_ok=True)
        common.write_text(path, title + "\n")
    common.out(f"{SESSION_TRAILER}: {trailer_value(session)}")
    return 0


# --- squash -------------------------------------------------------------------------------------

def fixup_plan() -> tuple[list[tuple[dict, dict]], str | None]:
    """[(fixup, target)] among recent commits, newest first; error when a target is missing."""
    commits = _commits()
    plan = []
    for i, c in enumerate(commits):
        if not c["subject"].startswith(FIXUP):
            continue
        subject = c["subject"]
        while subject.startswith(FIXUP):
            subject = subject[len(FIXUP):]
        target = next((t for t in commits[i + 1:] if t["subject"] == subject), None)
        if target is None:
            return [], f"target of '{c['subject']}' not found in the last {HISTORY} commits"
        plan.append((c, target))
    return plan, None


def cmd_squash(args: argparse.Namespace) -> int:
    plan, problem = fixup_plan()
    if problem:
        return common.fail(problem)
    if not plan:
        common.out("Nothing to squash: no fixup! commits.")
        return 0
    for fix, target in plan:
        common.out(f"{fix['sha'][:7]} {fix['subject']}  ->  {target['sha'][:7]}")
    if args.dry_run:
        return 0
    if _git("status", "--porcelain", "--untracked-files=no").stdout.strip():
        return common.fail("the working tree has uncommitted changes (maybe another session's work): "
                           "squash when they are committed")
    for marker in ("rebase-merge", "rebase-apply"):
        p = Path(_git("rev-parse", "--git-path", marker).stdout.strip())
        if (p if p.is_absolute() else common.project_root() / p).exists():
            return common.fail("a rebase is in progress: finish or abort it first")
    shas = [c["sha"] for c in _commits()]
    oldest = max((target for _f, target in plan), key=lambda t: shas.index(t["sha"]))
    if pushed(oldest["sha"]):
        return common.fail(f"{oldest['sha'][:7]} is already pushed: history is not rewritten")
    parent = _git("rev-parse", "-q", "--verify", f"{oldest['sha']}^").stdout.strip()
    base = [parent] if parent else ["--root"]
    env = {"GIT_SEQUENCE_EDITOR": ":", "GIT_EDITOR": ":"}
    res = _git("-c", "rebase.autoStash=false", "rebase", "-i", "--autosquash", *base, env=env)
    if res.returncode != 0:
        _git("rebase", "--abort")
        detail = "\n".join(x for x in (res.stdout.strip(), res.stderr.strip()) if x)
        return common.fail(f"rebase failed and was aborted; history is unchanged:\n{detail}")
    common.out(f"Squashed {len(plan)} fixup commit(s); HEAD is "
               + _git("log", "-1", "--format=%h %s").stdout.strip())
    return 0


def register(s) -> None:
    c = s.add_parser("commit", help="commit Knowledge/ paths now, attributed to the agent session")
    c.add_argument("paths", nargs="+", metavar="path", help="files or folders inside Knowledge/ (also deleted ones)")
    c.add_argument("-m", "--message", action="append",
                   help="first: the gist (knowledge: is prefixed); next ones: body lines ('- point')")
    c.add_argument("--amend", action="store_true",
                   help="correct this session's last commit of these notes: amend when it is HEAD, "
                        "else a fixup! commit (tb kb squash); pushed commits are never rewritten")
    c.set_defaults(func=cmd_commit)

    se = s.add_parser("session", help="this agent session as commits name it; set its title")
    se.set_defaults(func=cmd_session)
    ses = se.add_subparsers(dest="session_command", metavar="<subcommand>")
    st = ses.add_parser("title", help="set the session title shown in the Agent-Session trailer")
    st.add_argument("text", nargs="+", help="what this session does, e.g. the task title")
    st.set_defaults(func=cmd_session)

    sq = s.add_parser("squash", help="fold fixup! commits into their targets (clean working tree, unpushed)")
    sq.add_argument("--dry-run", action="store_true", help="only list fixups and their targets")
    sq.set_defaults(func=cmd_squash)
