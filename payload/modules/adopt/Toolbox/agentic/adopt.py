"""tb adopt — moving a large existing project into this one (module `adopt`, skill `adopt`).

The move is a task `Knowledge/Tasks/<task>/` with `adopt.toml` (old roots, archive dir, knowledge
sources), `plan.md`, `rules.md` and ledgers `ledger/<source>/`: a manifest of the source's files and
batch files with one row per file (source | verdict | target | reason | audit). The commands keep the
mechanics exact — coverage, verdicts, links, the gate before a commit — while the decisions stay with
the agent and the human (`.agents/skills/adopt/SKILL.md`).

Old places are only read. Writes go to the task folder and Runtime/adopt/; `archive` writes archives,
`links --write` rewrites notes.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import os
import re
import tarfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import common
import kb

TASKS_DIR = "Knowledge/Tasks"
CONFIG = "adopt.toml"
TEMPLATES = ".agents/skills/adopt/templates"
RUNTIME = "Runtime/adopt"
SECRETS_DIR = "Resources/secrets"

KINDS = ("vault", "docs", "claude-memory", "codex-memory", "agent-files", "loose-docs", "transcripts",
         "instructions")
VERDICTS = ("migrated", "merged", "task", "secret", "foreign", "obsolete", "derivable", "duplicate",
            "duplicate-candidate", "junk")
NEED_TARGET = {"migrated", "merged", "task", "secret"}
NEED_REASON = {"foreign", "obsolete", "derivable", "duplicate", "junk"}
LIVE = {"migrated", "merged", "task"}  # verdicts whose target a link may point to
OTHER_TARGETS = (".agents/", "Toolbox/", "AGENTS.md")  # `migrated` outside Knowledge/
REASON_LIMIT = 600
SKIP_NAMES = {".git", ".obsidian", ".trash", ".idea", ".DS_Store", "Thumbs.db"}

# Batch file sections (headings in the project language; matched case-insensitively).
SECTIONS = {"handoff": ("передача", "handoff"), "questions": ("вопросы", "questions"),
            "secrets": ("секреты", "secrets")}
ITEM_RE = re.compile(r"^\s*[-*]\s+#(\d+)\b[:.]?\s*(.*)$")
RECEIVER_RE = re.compile(r"^(?:→|->)\s*([a-z0-9][a-z0-9-]*)\s*:?\s*(.*)$")
ACCEPT_RE = re.compile(r"(?:принято|accepted)\s*:\s*([a-z0-9][a-z0-9-]*/[a-z0-9][a-z0-9-]*#\d+)"
                       r"\s*(?:→|->)\s*([^;)\n]+)", re.I)
ANSWER_RE = re.compile(r"(?:ответ|answer)\s*:", re.I)
SEPARATOR_RE = re.compile(r"^\|[\s|:-]+\|?$")
WIKILINK_RE = re.compile(r"(!?)\[\[([^\]\n|#]*)(#[^\]\n|]*)?(?:\|([^\]\n]*))?\]\]")
MDLINK_RE = re.compile(r"(!?)\[((?:[^\[\]\n]|\[[^\]\n]*\])*)\]\(\s*(<[^>\n]*>|[^)\s]+)"
                       r"(?:\s+(\"[^\"\n]*\"|'[^'\n]*'|\([^)\n]*\)))?\s*\)")
INLINE_CODE_RE = re.compile(r"(`+)[^`\n]*?\1")
FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
DATE_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-(?=.)")

TRANSLIT = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
                    ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p",
                     "r", "s", "t", "u", "f", "kh", "ts", "ch", "sh", "shch", "", "y", "", "e", "yu", "ya"]))


# --- paths outside the project --------------------------------------------------------------------------

def home() -> Path:
    """The user's home, read at call time (tests point HOME/USERPROFILE elsewhere)."""
    return Path(os.path.expanduser("~"))


def tilde(path: Path) -> str:
    """`~/…` for paths under home, else the absolute path; always with `/`."""
    p = Path(os.path.abspath(path))
    try:
        return "~/" + p.relative_to(home()).as_posix()
    except ValueError:
        return p.as_posix()


def untilde(text: str) -> Path:
    text = text.strip()
    if text == "~":
        return home()
    if text.startswith(("~/", "~\\")):
        return home() / text[2:]
    return Path(text)


def expand(pattern: str) -> list[Path]:
    """A configured path: `~` expanded, glob characters expanded (sorted); a missing plain path is kept."""
    p = untilde(pattern)
    if not any(ch in str(p) for ch in "*?["):
        return [p]
    anchor = Path(p.anchor) if p.is_absolute() else Path(".")
    rest = p.relative_to(anchor).as_posix() if p.is_absolute() else p.as_posix()
    return sorted(anchor.glob(rest))


def show(path: Path) -> str:
    """A path for output: relative to the project root inside it, `~/…` or absolute outside."""
    p = Path(os.path.abspath(path))
    try:
        return p.relative_to(common.project_root()).as_posix()
    except ValueError:
        return tilde(p)


def to_slug(stem: str) -> str:
    """Note slug from a file name: Russian transliterated, kebab-case, a `YYYY-MM-DD-` prefix dropped
    (the date goes to `created`)."""
    s = "".join(TRANSLIT.get(ch, ch) for ch in stem.lower())
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    s = DATE_PREFIX_RE.sub("", s)
    if not s:
        return "note"
    return s if kb.valid_slug(s) else f"{s}-note"


# --- task and configuration ------------------------------------------------------------------------------

@dataclass
class Source:
    name: str
    kind: str
    paths: list[str]
    folder: str = ""                 # default note folder (slugmap), e.g. "Decisions"
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    codex_cwd: list[str] = field(default_factory=list)  # transcripts: Codex sessions by working dir


@dataclass
class Task:
    slug: str
    dir: Path
    old_roots: list[str]
    archive_dir: str
    secrets_dir: str
    sources: list[Source]

    @property
    def ledger(self) -> Path:
        return self.dir / "ledger"

    @property
    def slugmap(self) -> Path:
        return self.dir / "slugmap.md"

    def source(self, name: str) -> Source:
        for s in self.sources:
            if s.name == name:
                return s
        raise AdoptError(f"unknown source: {name} (in {show(self.dir / CONFIG)}: "
                         f"{', '.join(s.name for s in self.sources) or 'none'})")

    def roots(self) -> list[Path]:
        return [p for r in self.old_roots for p in expand(r)]


class AdoptError(Exception):
    pass


def _str_list(value, where: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise AdoptError(f"{where}: expected a list of strings")
    return value


def parse_config(path: Path, slug: str) -> Task:
    try:
        data = common.load_toml(path)
    except (OSError, ValueError) as exc:
        raise AdoptError(f"{show(path)}: {exc}") from exc
    where = show(path)
    sources, names = [], set()
    for i, raw in enumerate(data.get("source", []), start=1):
        at = f"{where}: [[source]] #{i}"
        if not isinstance(raw, dict):
            raise AdoptError(f"{at}: expected a table")
        name, kind = raw.get("name"), raw.get("kind")
        if not isinstance(name, str) or not kb.KEBAB_RE.match(name):
            raise AdoptError(f"{at}: name must be kebab-case, got {name!r}")
        if name in names:
            raise AdoptError(f"{at}: duplicate source name {name}")
        if kind not in KINDS:
            raise AdoptError(f"{at} ({name}): kind must be one of {', '.join(KINDS)}, got {kind!r}")
        folder = raw.get("folder", "")
        if folder and folder not in common.FOLDER_TO_TYPE:
            raise AdoptError(f"{at} ({name}): folder must be one of {', '.join(sorted(common.FOLDER_TO_TYPE))}")
        names.add(name)
        sources.append(Source(name=name, kind=kind, paths=_str_list(raw.get("paths"), f"{at}: paths"),
                              folder=folder, include=_str_list(raw.get("include"), f"{at}: include"),
                              exclude=_str_list(raw.get("exclude"), f"{at}: exclude"),
                              codex_cwd=_str_list(raw.get("codex_cwd"), f"{at}: codex_cwd")))
    secrets_dir = str(data.get("secrets_dir") or SECRETS_DIR).strip("/")
    return Task(slug=slug, dir=path.parent, old_roots=_str_list(data.get("old_roots"), f"{where}: old_roots"),
                archive_dir=str(data.get("archive_dir") or ""), secrets_dir=secrets_dir, sources=sources)


def find_task(slug: str | None) -> Task:
    tasks = common.project_root() / TASKS_DIR
    if slug:
        path = tasks / slug / CONFIG
        if not path.is_file():
            raise AdoptError(f"no {show(path)} (create the task with: tb adopt start {slug})")
        return parse_config(path, slug)
    found = sorted(tasks.glob(f"*/{CONFIG}")) if tasks.is_dir() else []
    if not found:
        raise AdoptError(f"no adopt task in {TASKS_DIR}/ (start one: tb adopt start <slug>)")
    if len(found) > 1:
        raise AdoptError("several adopt tasks: pass --task " + "|".join(p.parent.name for p in found))
    return parse_config(found[0], found[0].parent.name)


# --- manifests ------------------------------------------------------------------------------------------------

def manifest_path(task: Task, source: str) -> Path:
    return task.ledger / source / "manifest.txt"


def write_manifest(task: Task, source: Source) -> int:
    import adopt_sources

    entries = sorted({tilde(p) for p in adopt_sources.collect(task, source) if p.is_file()})
    head = [f"# source: {source.name} ({source.kind})",
            f"# generated: {common.today_iso()} by tb adopt manifest", f"# files: {len(entries)}"]
    common.write_text(manifest_path(task, source.name), "\n".join(head + entries) + "\n")
    return len(entries)


def read_manifest(task: Task, source: str) -> list[str]:
    path = manifest_path(task, source)
    if not path.is_file():
        raise AdoptError(f"manifest not found: {show(path)} (run: tb adopt manifest --source {source})")
    return [line.strip() for line in common.read_text(path).splitlines()
            if line.strip() and not line.startswith("#")]


# --- ledger ------------------------------------------------------------------------------------------------------

@dataclass
class Row:
    batch: str
    line: int
    source: str          # manifest entry
    verdict: str
    targets: list[str]
    reason: str
    audit: str

    @property
    def loc(self) -> str:
        return f"{self.batch}.md:{self.line}"


@dataclass
class Item:
    """A numbered line of a batch section: handoff, question or secret pointer."""
    id: str              # <source>/<batch>#<n>, or questions#<n> in the task's questions.md
    kind: str
    file: Path
    line: int
    text: str
    receiver: str = ""   # handoff: the receiving source


@dataclass
class Batch:
    source: str
    name: str
    path: Path
    rows: list[Row]
    items: list[Item]
    problems: list[str]
    accepted: dict[str, tuple[str, int]]  # handoff id -> (target, line)


def split_cells(line: str) -> list[str]:
    s = line.strip()
    s = s[1:-1] if s.endswith("|") and not s.endswith("\\|") else s[1:]
    cells = [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", s)]
    return [c[1:-1] if len(c) > 1 and c[0] == c[-1] == "`" else c for c in cells]


def split_targets(cell: str) -> list[str]:
    parts = re.split(r"[,;]|<br\s*/?>", cell)
    return [t for t in (p.strip().strip("`").strip() for p in parts) if t not in ("", "—", "-")]


def section_kind(heading: str) -> str:
    h = heading.strip().lower()
    for kind, names in SECTIONS.items():
        if any(h.startswith(n) for n in names):
            return kind
    return "other"


def parse_batch(path: Path, source: str) -> Batch:
    batch = Batch(source=source, name=path.stem, path=path, rows=[], items=[], problems=[], accepted={})
    section, header_seen = None, False
    for n, line in enumerate(common.normalize_newlines(common.read_text(path)).split("\n"), start=1):
        for m in ACCEPT_RE.finditer(line):
            batch.accepted[m.group(1)] = (m.group(2).strip().strip("`"), n)
        heading = re.match(r"^##\s+(.+?)\s*$", line)
        if heading:
            section = section_kind(heading.group(1))
            continue
        stripped = line.strip()
        if section is None and stripped.startswith("|"):
            if SEPARATOR_RE.match(stripped):
                continue
            if not header_seen:
                header_seen = True
                continue
            cells = split_cells(stripped)
            if len(cells) != 5:
                batch.problems.append(f"{path.stem}.md:{n}: expected 5 columns "
                                      f"(source | verdict | target | reason | audit), got {len(cells)}")
                continue
            batch.rows.append(Row(path.stem, n, cells[0], cells[1].strip().lower(), split_targets(cells[2]),
                                  cells[3], cells[4]))
        elif section in SECTIONS and (m := ITEM_RE.match(line)):
            item = Item(id=f"{source}/{path.stem}#{m.group(1)}", kind=section, file=path, line=n,
                        text=m.group(2).strip())
            if section == "handoff":
                r = RECEIVER_RE.match(item.text)
                if r:
                    item.receiver, item.text = r.group(1), r.group(2).strip()
                else:
                    batch.problems.append(f"{path.stem}.md:{n}: handoff #{m.group(1)} needs a receiving "
                                          "source: `- #N → <source>: <fact and proof>`")
            batch.items.append(item)
    return batch


def read_batches(task: Task, source: str) -> list[Batch]:
    d = task.ledger / source
    if not d.is_dir():
        return []
    return [parse_batch(p, source) for p in sorted(d.glob("*.md")) if p.name != "README.md"]


def task_questions(task: Task) -> list[Item]:
    path = task.dir / "questions.md"
    if not path.is_file():
        return []
    items = []
    for n, line in enumerate(common.read_text(path).splitlines(), start=1):
        if m := ITEM_RE.match(line):
            items.append(Item(id=f"questions#{m.group(1)}", kind="questions", file=path, line=n,
                              text=m.group(2).strip()))
    return items


@dataclass
class Ledger:
    batches: dict[str, list[Batch]]      # source name -> batches

    def rows(self, source: str | None = None) -> list[Row]:
        names = [source] if source else list(self.batches)
        return [r for s in names for b in self.batches.get(s, []) for r in b.rows]

    def items(self, kind: str) -> list[Item]:
        return [i for bs in self.batches.values() for b in bs for i in b.items if i.kind == kind]

    def accepted(self) -> dict[str, tuple[Batch, str, int]]:
        return {hid: (b, target, line) for bs in self.batches.values() for b in bs
                for hid, (target, line) in b.accepted.items()}

    def open_handoffs(self, receiver: str | None = None) -> list[Item]:
        done = self.accepted()
        return [i for i in self.items("handoff") if i.id not in done and (receiver is None or i.receiver == receiver)]


def read_ledger(task: Task) -> Ledger:
    return Ledger({s.name: read_batches(task, s.name) for s in task.sources})


# --- slugmap -----------------------------------------------------------------------------------------------------

def read_slugmap(task: Task) -> dict[str, tuple[str, str, str]]:
    """lower(link key) -> (source name, manifest entry, planned target or "")."""
    out: dict[str, tuple[str, str, str]] = {}
    if not task.slugmap.is_file():
        return out
    rows, header = [], False
    for line in common.read_text(task.slugmap).splitlines():
        s = line.strip()
        if not s.startswith("|") or SEPARATOR_RE.match(s):
            continue
        if not header:
            header = True
            continue
        rows.append(split_cells(s))
    for cells in rows:
        if len(cells) >= 4:
            target = cells[3] if cells[3].startswith("Knowledge/") else ""
            out.setdefault(cells[2].lower(), (cells[0], cells[1], target))
    return out


def build_slugmap(task: Task) -> tuple[list[tuple[str, str, str, str]], int, list[str]]:
    rows: list[tuple[str, str, str, str]] = []
    used: dict[str, list[int]] = defaultdict(list)
    keys: dict[str, list[str]] = defaultdict(list)
    for source in task.sources:
        if not source.folder:
            continue
        for entry in read_manifest(task, source.name):
            p = untilde(entry)
            keys[p.stem.lower()].append(entry)
            if p.suffix.lower() != ".md":
                rows.append((source.name, entry, p.stem, "—"))
                continue
            slug = to_slug(p.stem)
            used[f"{source.folder}/{slug}"].append(len(rows))
            rows.append((source.name, entry, p.stem, f"Knowledge/{source.folder}/{slug}.md"))
    by_slug: dict[str, list[int]] = defaultdict(list)
    for key, idx in used.items():
        by_slug[key.split("/", 1)[1]].extend(idx)
    conflicts = 0
    for slug, idx in by_slug.items():  # one slug for several files: suffix the later ones
        for k, i in enumerate(sorted(idx)[1:], start=2):
            src, entry, key, target = rows[i]
            rows[i] = (src, entry, key, target[:-3] + f"-{k}.md")
            conflicts += 1
    ambiguous = [f"{k}: {', '.join(v)}" for k, v in sorted(keys.items()) if len(v) > 1]
    return rows, conflicts, ambiguous


# --- links ---------------------------------------------------------------------------------------------------------

def code_mask(lines: list[str]) -> list[bool]:
    """Per line: True inside a fenced code block (fence lines included)."""
    mask, fence = [], None
    for line in lines:
        m = FENCE_RE.match(line)
        if fence:
            mask.append(True)
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
                fence = None
        elif m:
            fence = m.group(1)
            mask.append(True)
        else:
            mask.append(False)
    return mask


def note_title(path: Path) -> str | None:
    try:
        meta, body, _err = common.split_frontmatter(common.read_text(path))
    except (OSError, UnicodeDecodeError):
        return None
    if meta and meta.get("title"):
        return str(meta["title"]).strip()
    m = re.search(r"^#\s+(.+)$", body, re.M)
    return m.group(1).strip() if m else None


class Resolver:
    """Resolves an old link key (file name without .md) to a note by the slugmap and the ledgers."""

    def __init__(self, task: Task, ledger: Ledger):
        self.root = common.project_root()
        self.slugmap = read_slugmap(task)
        self.rows: dict[str, Row] = {}
        self.by_stem: dict[str, list[Row]] = defaultdict(list)
        for r in ledger.rows():
            self.rows.setdefault(r.source, r)
        for entry, r in self.rows.items():
            self.by_stem[untilde(entry).stem.lower()].append(r)

    def resolve(self, key: str) -> tuple[str, str | None, str | None]:
        """(state, target relative to the root, manifest entry): live | planned | dead | unknown."""
        k = key.strip().replace("\\", "/").split("/")[-1]
        k = k[:-3] if k.lower().endswith(".md") else k
        hit = self.slugmap.get(k.lower())
        if hit:
            _source, entry, planned = hit
            row = self.rows.get(entry)
        else:
            rows = self.by_stem.get(k.lower(), [])
            if len(rows) != 1:
                return "unknown", None, None
            row, entry, planned = rows[0], rows[0].source, ""
        if row and row.verdict in LIVE and row.targets:
            target = row.targets[0]
            return ("live" if (self.root / target).exists() else "planned"), target, entry
        if row and row.verdict != "duplicate-candidate":
            return "dead", None, entry
        if planned:
            return ("live" if (self.root / planned).exists() else "planned"), planned, entry
        return ("dead" if row else "unknown"), None, entry


def convert_note(path: Path, res: Resolver) -> tuple[str, list[str]]:
    """Rewrite old links of one note. Returns (new text, report lines)."""
    root = common.project_root()
    text = common.normalize_newlines(common.read_text(path))
    lines = text.split("\n")
    masked = code_mask(lines)
    report: list[str] = []
    in_front = bool(lines) and lines[0].strip() == "---"
    out_lines = []

    def rel_to(target: str) -> str:
        return os.path.relpath(root / target, path.parent).replace(os.sep, "/")

    def make(embed: str, label: str, target: str, state: str) -> str:
        link = f"{embed}[{label}]({rel_to(target)}"
        return link + (")" if state == "live" else ' "pending")')

    for i, line in enumerate(lines):
        n = i + 1
        if in_front:
            out_lines.append(line)
            if i > 0 and line.strip() == "---":
                in_front = False
            continue
        if masked[i]:
            out_lines.append(line)
            continue

        def spans() -> list[tuple[int, int]]:
            return [(m.start(), m.end()) for m in INLINE_CODE_RE.finditer(line)]

        def in_code(pos: int, code: list[tuple[int, int]]) -> bool:
            return any(a <= pos < b for a, b in code)

        code = spans()

        def wiki(m: re.Match) -> str:
            if in_code(m.start(), code):
                return m.group(0)
            embed, key, anchor, alias = m.groups()
            state, target, entry = res.resolve(key)
            label = (alias or "").strip()
            if not label:
                label = (note_title(root / target) if target and (root / target).is_file() else None) \
                    or (note_title(untilde(entry)) if entry else None) or key.strip()
            if state in ("live", "planned"):
                report.append(f"{n}: [[{key}]] -> {target}" + (" (pending)" if state == "planned" else ""))
                return make(embed, label, target, state)  # Obsidian heading anchors do not carry over
            if state == "dead":
                report.append(f"{n}: [[{key}]] -> plain text (source not migrated)")
                return label
            report.append(f"{n}: [[{key}]] UNKNOWN key, left as is")
            return m.group(0)

        line = WIKILINK_RE.sub(wiki, line)
        code = spans()

        def md(m: re.Match) -> str:
            if in_code(m.start(), code):
                return m.group(0)
            embed, label, raw, title = m.groups()
            target = raw[1:-1].strip() if raw.startswith("<") else raw
            if re.match(r"^[a-z][a-z0-9+.-]*:|^#", target, re.I):
                return m.group(0)
            plain = target.split("#")[0]
            resolved = Path(os.path.normpath(path.parent / plain))
            pending = bool(title) and title[1:-1].strip().lower() == kb.PENDING_TITLE
            if resolved.exists():
                if pending:
                    report.append(f"{n}: pending link resolved -> {show(resolved)}")
                    return f"{embed}[{label}]({raw})"
                return m.group(0)
            if pending:
                return m.group(0)
            state, tgt, _entry = res.resolve(Path(plain).name)
            if state in ("live", "planned"):
                report.append(f"{n}: ({target}) -> {tgt}" + (" (pending)" if state == "planned" else ""))
                return make(embed, label, tgt, state)
            return m.group(0)

        line = MDLINK_RE.sub(md, line)
        out_lines.append(line)
    return "\n".join(out_lines), report


def knowledge_notes() -> list[Path]:
    return [p for p, _parts in kb.note_files(kb.knowledge_dir())]


# --- check and gate ------------------------------------------------------------------------------------------------

@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warns: list[str] = field(default_factory=list)


def check_source(task: Task, ledger: Ledger, source: str, batch: str | None, pre_audit: bool,
                 rep: Report) -> tuple[int, int, int, set[str]]:
    """Check one source's ledger. Returns (rows checked, covered, manifest size, live targets)."""
    root = common.project_root()
    manifest = read_manifest(task, source)
    mset = set(manifest)
    batches = ledger.batches.get(source, [])
    if batch and not any(b.name == batch for b in batches):
        raise AdoptError(f"batch not found: {show(task.ledger / source / (batch + '.md'))}")
    rows = [r for b in batches for r in b.rows]
    for b in batches:
        if not batch or b.name == batch:
            rep.errors += [f"{source}/{p}" for p in b.problems]
    seen: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
        seen[r.source].append(r)
    for s, rs in seen.items():
        if len(rs) > 1 and (not batch or any(r.batch == batch for r in rs)):
            rep.errors.append(f"{s}: covered {len(rs)} times ({', '.join(f'{source}/{r.loc}' for r in rs)})")
    planned = {entry: t for _src, entry, t in read_slugmap(task).values()}
    secrets_prefix = task.secrets_dir + "/"
    check_rows = [r for r in rows if not batch or r.batch == batch]
    targets: set[str] = set()
    for r in check_rows:
        at = f"{source}/{r.loc}: {r.source}"
        if r.source not in mset:
            rep.errors.append(f"{at}: not in the manifest")
        if r.verdict not in VERDICTS:
            rep.errors.append(f"{at}: unknown verdict '{r.verdict}' (one of: {', '.join(VERDICTS)})")
            continue
        if r.verdict == "duplicate-candidate" and not pre_audit:
            rep.errors.append(f"{at}: duplicate-candidate is not resolved")
        audit = r.audit.strip().lower()
        if pre_audit:
            if audit.startswith("fix"):
                rep.errors.append(f"{at}: audit says '{r.audit}' (rework, then clear the audit cell)")
        elif audit != "ok":
            rep.errors.append(f"{at}: audit is '{r.audit or '(empty)'}', expected ok")
        if r.verdict in NEED_TARGET and not r.targets:
            rep.errors.append(f"{at}: verdict {r.verdict} needs a target")
        if r.verdict in NEED_REASON and not r.reason.strip(" —-"):
            rep.errors.append(f"{at}: verdict {r.verdict} needs a reason")
        if len(r.reason) > REASON_LIMIT:
            rep.warns.append(f"{at}: reason is {len(r.reason)} chars; keep it under ~400")
        for t in r.targets:
            p = root / t
            if r.verdict == "secret":
                if not t.startswith(secrets_prefix):
                    rep.errors.append(f"{at}: secret target must be under {secrets_prefix}: {t}")
                elif not p.exists():
                    rep.errors.append(f"{at}: target does not exist: {t}")
                continue
            if r.verdict == "migrated" and t.startswith(OTHER_TARGETS):
                if not p.exists():
                    rep.errors.append(f"{at}: target does not exist: {t}")
                continue
            if not t.startswith("Knowledge/") or not t.endswith(".md"):
                if r.verdict in NEED_TARGET or r.verdict.startswith("duplicate"):
                    rep.errors.append(f"{at}: target must be a note Knowledge/…/*.md: {t}")
                continue
            if not p.is_file():
                rep.errors.append(f"{at}: target does not exist: {t}")
                continue
            if r.verdict == "task" and not t.startswith(TASKS_DIR + "/"):
                rep.errors.append(f"{at}: task target must be under {TASKS_DIR}/: {t}")
            if r.verdict in LIVE:
                targets.add(t)
        if r.verdict == "migrated" and planned.get(r.source) and planned[r.source] not in r.targets:
            rep.warns.append(f"{at}: target differs from the slugmap ({planned[r.source]}): explain in the reason")
    if not batch:
        for s in manifest:
            if s not in seen:
                rep.errors.append(f"{source}: {s}: not covered by any batch")
            elif not untilde(s).exists():
                rep.warns.append(f"{source}: {s}: source file no longer exists (refresh the manifest?)")
    for item in ledger.open_handoffs(receiver=source):
        if batch:
            continue
        msg = f"{show(item.file)}:{item.line}: handoff {item.id} → {source} is not accepted yet"
        (rep.warns if pre_audit else rep.errors).append(msg)
    for t in sorted(targets):
        lines = common.normalize_newlines(common.read_text(root / t)).split("\n")
        mask = code_mask(lines)
        body = "\n".join(INLINE_CODE_RE.sub("", ln) for ln, c in zip(lines, mask) if not c)
        if WIKILINK_RE.search(body):
            rep.errors.append(f"{t}: wikilinks left (run: tb adopt links {t} --write)")
    covered = len(set(seen) & mset)
    return len(check_rows), covered, len(manifest), targets


def lint_into(rep: Report, targets: set[str] | None) -> None:
    """`tb kb lint`: errors in `targets` (all when None) fail the check, others are one warning."""
    problems, _count = kb.run_lint()
    mine = [p for p in problems if p.level == "error" and (targets is None or p.path in targets)]
    other = [p for p in problems if p.level == "error" and p not in mine]
    rep.errors += [f"lint: {p.format()}" for p in mine]
    if other:
        rep.warns.append(f"lint: {len(other)} error(s) outside this batch (first: {other[0].format()})")
    rep.warns += [f"lint: {p.format()}" for p in problems
                  if p.level == "warning" and (targets is not None and p.path in targets)]


def print_report(rep: Report, summary: str) -> int:
    for w in rep.warns:
        common.out(f"warning: {w}")
    for e in rep.errors:
        common.out(f"error: {e}")
    common.out(f"{summary}, {len(rep.errors)} errors, {len(rep.warns)} warnings — "
               f"{'GREEN' if not rep.errors else 'RED'}")
    return 1 if rep.errors else 0


# --- archives ---------------------------------------------------------------------------------------------------

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _private(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:  # Windows: POSIX modes are not supported
        pass


def make_archive(dest: Path, paths: list[Path]) -> tuple[int, int]:
    """tar.gz of `paths` (links stored as links), mode 600, then verified: every regular file is in the
    archive with the same sha256. Returns (files, bytes of the archive)."""
    expected: dict[str, str] = {}
    dest.parent.mkdir(parents=True, exist_ok=True)
    _private(dest.parent, 0o700)
    tmp = dest.with_name(dest.name + ".part")
    try:
        with tarfile.open(tmp, "w:gz") as tar:
            for src in paths:
                tar.add(src, arcname=src.name, recursive=True)  # links are stored as links
                if src.is_symlink():
                    continue
                if src.is_file():
                    expected[src.name] = _sha256(src)
                    continue
                for dirpath, _dirnames, filenames in os.walk(src):
                    for f in filenames:
                        p = Path(dirpath) / f
                        if p.is_file() and not p.is_symlink():
                            expected[(Path(src.name) / p.relative_to(src)).as_posix()] = _sha256(p)
        _private(tmp, 0o600)
        found: dict[str, str] = {}
        with tarfile.open(tmp, "r:gz") as tar:
            for member in tar:
                if member.isfile():
                    fh = tar.extractfile(member)
                    assert fh is not None
                    h = hashlib.sha256()
                    for chunk in iter(lambda: fh.read(1 << 20), b""):
                        h.update(chunk)
                    found[member.name] = h.hexdigest()
        missing = sorted(set(expected) - set(found))
        changed = sorted(k for k in expected if k in found and found[k] != expected[k])
        if missing or changed:
            raise AdoptError(f"archive verification failed: {len(missing)} missing, {len(changed)} changed "
                             f"(first: {(missing + changed)[0]}); the source may be changing — retry")
        os.replace(tmp, dest)
    finally:
        if tmp.exists():
            tmp.unlink()
    return len(expected), dest.stat().st_size


# --- commands -------------------------------------------------------------------------------------------------

def _with_task(func):
    def run(args: argparse.Namespace) -> int:
        try:
            return func(args, find_task(getattr(args, "task", None)))
        except AdoptError as exc:
            return common.fail(str(exc))
    return run


def cmd_start(args: argparse.Namespace) -> int:
    slug = args.slug
    if not kb.valid_slug(slug):
        return common.fail(f"invalid slug: {slug!r} (lowercase kebab-case)")
    root = common.project_root()
    templates = root / TEMPLATES
    if not templates.is_dir():
        return common.fail(f"templates not found: {TEMPLATES} (is the adopt module installed?)")
    tdir = root / TASKS_DIR / slug
    for existing in (tdir, root / TASKS_DIR / f"{slug}.md"):
        if existing.exists():
            return common.fail(f"already exists: {show(existing)}")
    title = args.title.strip() if args.title and args.title.strip() else f"Adopt: {slug}"
    today = common.today_iso()
    written = []
    for src in sorted(p for p in templates.rglob("*") if p.is_file()):
        relpath = src.relative_to(templates)
        text = common.read_text(src)
        if relpath.as_posix() == CONFIG:
            roots = [tilde(Path(os.path.abspath(untilde(r)))) for r in args.old_root]
            text = re.sub(r"(?m)^old_roots = \[\]$", lambda _m: "old_roots = " + _toml_list(roots), text, count=1)
            if args.archive_dir:
                arch = tilde(Path(os.path.abspath(untilde(args.archive_dir))))
                text = re.sub(r'(?m)^archive_dir = ""$', lambda _m: f'archive_dir = "{_toml_str(arch)}"', text,
                              count=1)
        else:
            text = kb.render_template(text, title, today).replace("{{slug}}", slug)
        common.write_text(tdir / relpath, text)
        written.append(show(tdir / relpath))
    if not (tdir / "index.md").is_file():
        return common.fail(f"{TEMPLATES}/index.md is missing: the task has no note")
    for w in written:
        common.out(w)
    if not args.old_root:
        common.warn(f"no --old-root: fill old_roots in {show(tdir / CONFIG)}")
    common.out(f"next: fill {show(tdir / 'plan.md')}, then tb adopt inventory (stage 1 of the adopt skill)")
    return 0


def _toml_str(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _toml_list(items: list[str]) -> str:
    return "[" + ", ".join(f'"{_toml_str(i)}"' for i in items) + "]"


@_with_task
def cmd_manifest(args: argparse.Namespace, task: Task) -> int:
    sources = [task.source(args.source)] if args.source else task.sources
    if not sources:
        return common.fail(f"no [[source]] in {show(task.dir / CONFIG)} (see: tb adopt sources)")
    for s in sources:
        n = write_manifest(task, s)
        common.out(f"{s.name}: {n} files -> {show(manifest_path(task, s.name))}")
    entries: dict[str, list[str]] = defaultdict(list)
    for s in task.sources:
        path = manifest_path(task, s.name)
        if path.is_file():
            for e in read_manifest(task, s.name):
                entries[e].append(s.name)
    dups = {e: names for e, names in entries.items() if len(names) > 1}
    for e, names in sorted(dups.items())[:20]:
        common.warn(f"{e}: in several manifests ({', '.join(names)}); narrow the sources (exclude = …)")
    return 0


@_with_task
def cmd_slugmap(args: argparse.Namespace, task: Task) -> int:
    if task.slugmap.exists() and not args.force:
        return common.fail(f"{show(task.slugmap)} exists; --force regenerates it (manual rows are lost)")
    rows, conflicts, ambiguous = build_slugmap(task)
    lines = ["# Slugmap", "",
             "<!-- Generated by `tb adopt slugmap`: source file -> planned note. The link key is the file name",
             "     without .md, as in [[wikilinks]] (case-insensitive). The actual target is in the ledger. -->", "",
             "| Source | File | Link key | Planned note |", "|---|---|---|---|"]
    lines += [f"| {s} | {e.replace('|', chr(92) + '|')} | {k.replace('|', chr(92) + '|')} | {t} |"
              for s, e, k, t in rows]
    common.write_text(task.slugmap, "\n".join(lines) + "\n")
    common.out(f"{len(rows)} rows -> {show(task.slugmap)}; slug conflicts resolved: {conflicts}")
    for a in ambiguous[:20]:
        common.warn(f"link key used by several files, [[wikilinks]] to it resolve to the first: {a}")
    return 0


@_with_task
def cmd_next(args: argparse.Namespace, task: Task) -> int:
    task.source(args.source)
    covered = {r.source for b in read_batches(task, args.source) for r in b.rows}
    manifest = read_manifest(task, args.source)
    left = [e for e in manifest if e not in covered]
    for e in left[: args.limit]:
        p = untilde(e)
        common.out(f"{p.stat().st_size / 1024:8.1f} KB  {e}" if p.is_file() else f"  missing   {e}")
    common.out(f"{len(left)} of {len(manifest)} not covered")
    return 0


@_with_task
def cmd_links(args: argparse.Namespace, task: Task) -> int:
    res = Resolver(task, read_ledger(task))
    paths = [Path(os.path.abspath(p)) for p in args.notes] if args.notes else knowledge_notes()
    unknown = changed = 0
    for p in paths:
        if not p.is_file():
            return common.fail(f"not a file: {show(p)}")
        new, report = convert_note(p, res)
        if not report:
            continue
        unknown += sum("UNKNOWN" in r for r in report)
        common.out(f"{show(p)}:")
        for r in report:
            common.out(f"  {r}")
        if new != common.normalize_newlines(common.read_text(p)):
            changed += 1
            if args.write:
                common.write_text(p, new)
    common.out(f"{changed} note(s) {'rewritten' if args.write else 'to rewrite (dry run; add --write)'}"
               + (f"; {unknown} unknown key(s)" if unknown else ""))
    return 1 if unknown else 0


@_with_task
def cmd_check(args: argparse.Namespace, task: Task) -> int:
    task.source(args.source)
    rep = Report()
    ledger = read_ledger(task)
    n, covered, total, targets = check_source(task, ledger, args.source, args.batch, args.pre_audit, rep)
    lint_into(rep, targets if args.batch else None)
    scope = f"{args.source}/{args.batch}" if args.batch else args.source
    return print_report(rep, f"{scope}: {n} rows, manifest {covered}/{total} covered"
                              + (" (pre-audit)" if args.pre_audit else ""))


@_with_task
def cmd_gate(_args: argparse.Namespace, task: Task) -> int:
    rep = Report()
    ledger = read_ledger(task)
    if not task.sources:
        rep.errors.append(f"no [[source]] in {show(task.dir / CONFIG)}")
    entries: dict[str, list[str]] = defaultdict(list)
    total_rows = 0
    for s in task.sources:
        try:
            n, covered, size, _targets = check_source(task, ledger, s.name, None, False, rep)
        except AdoptError as exc:
            rep.errors.append(str(exc))
            continue
        total_rows += n
        for e in read_manifest(task, s.name):
            entries[e].append(s.name)
        common.out(f"{s.name}: manifest {covered}/{size} covered, {n} rows")
    for e, names in sorted(entries.items()):
        if len(names) > 1:
            rep.errors.append(f"{e}: in several manifests ({', '.join(names)})")
    known = {s.name for s in task.sources}
    for item in ledger.items("handoff"):
        if item.receiver and item.receiver not in known:
            rep.errors.append(f"{show(item.file)}:{item.line}: handoff {item.id} → unknown source {item.receiver}")
    for hid, (b, target, line) in ledger.accepted().items():
        if target not in ("—", "-") and target.startswith("Knowledge/") \
                and not (common.project_root() / target).exists():
            rep.errors.append(f"{show(b.path)}:{line}: accepted {hid} → {target}: target does not exist")
    open_q = [q for q in ledger.items("questions") + task_questions(task) if not ANSWER_RE.search(q.text)]
    for q in open_q:
        rep.warns.append(f"open question {q.id} ({show(q.file)}:{q.line}): {q.text[:120]}")
    lint_into(rep, None)
    return print_report(rep, f"gate: {len(task.sources)} sources, {total_rows} rows, "
                             f"{len(open_q)} open questions")


@_with_task
def cmd_status(_args: argparse.Namespace, task: Task) -> int:
    common.out(f"task: {show(task.dir)}")
    plan = task.dir / "plan.md"
    if plan.is_file():
        rows = [ln for ln in common.read_text(plan).splitlines() if ln.strip().startswith("|")]
        if rows:
            common.out("plan.md:")
            for ln in rows[:40]:
                common.out(f"  {ln.strip()}")
    ledger = read_ledger(task)
    common.out("sources:")
    for s in task.sources:
        path = manifest_path(task, s.name)
        if not path.is_file():
            common.out(f"  {s.name} ({s.kind}): no manifest")
            continue
        manifest = read_manifest(task, s.name)
        rows = ledger.rows(s.name)
        covered = {r.source for r in rows}
        audited = sum(1 for r in rows if r.audit.strip().lower() == "ok")
        first = next((e for e in manifest if e not in covered), None)
        common.out(f"  {s.name} ({s.kind}): {len(covered & set(manifest))}/{len(manifest)} covered, "
                   f"{audited}/{len(rows)} audited ok" + (f"; next: {first}" if first else ""))
    for title, items in (("open handoffs", ledger.open_handoffs()),
                         ("open questions", [q for q in ledger.items("questions") + task_questions(task)
                                             if not ANSWER_RE.search(q.text)]),
                         ("secret pointers", ledger.items("secrets"))):
        common.out(f"{title}: {len(items)}")
        for i in items[:30]:
            to = f" → {i.receiver}" if i.receiver else ""
            common.out(f"  {i.id}{to}: {i.text[:110]}")
        if len(items) > 30:
            common.out(f"  … {len(items) - 30} more")
    return 0


@_with_task
def cmd_archive(args: argparse.Namespace, task: Task) -> int:
    if not kb.KEBAB_RE.match(args.name):
        return common.fail(f"archive name must be kebab-case: {args.name!r}")
    base = args.dir or task.archive_dir
    if not base:
        return common.fail(f"no archive dir: set archive_dir in {show(task.dir / CONFIG)} or pass --dir")
    dest = untilde(base) / f"{args.name}.tgz"
    if dest.exists():
        return common.fail(f"already exists: {tilde(dest)} (archives are never overwritten)")
    sources = [untilde(p) for p in args.paths]
    for p in sources:
        if not p.exists() and not p.is_symlink():
            return common.fail(f"not found: {tilde(p)}")
    names = [p.name for p in sources]
    if len(set(names)) != len(names):
        return common.fail("paths with the same name would collide in the archive: archive them separately")
    root, parent = common.project_root().resolve(), dest.parent.resolve()
    if parent == root or root in parent.parents:
        return common.fail("the archive dir must be outside the project (archives are not for git)")
    try:
        files, size = make_archive(dest, sources)
    except AdoptError as exc:
        return common.fail(str(exc))
    common.out(f"{tilde(dest)}: {files} files verified (sha256), {size / 1024 / 1024:.1f} MB, mode 600")
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("adopt", help="move a large existing project in (module adopt; skill adopt)",
                            description="Ledgers, checks and archives of an adopt task "
                                        f"({TASKS_DIR}/<task>/{CONFIG}). Procedure: the adopt skill.")
    actions = parser.add_subparsers(dest="adopt_action", metavar="<action>")

    def add(name: str, help_: str, func, task: bool = True) -> argparse.ArgumentParser:
        p = actions.add_parser(name, help=help_, description=help_)
        if task:
            p.add_argument("--task", metavar="SLUG", help="the adopt task (default: the only one)")
        p.set_defaults(func=func)
        return p

    p = add("start", f"create the task {TASKS_DIR}/<slug>/ from the adopt templates", cmd_start, task=False)
    p.add_argument("slug")
    p.add_argument("--title", help='task title (default: "Adopt: <slug>")')
    p.add_argument("--old-root", action="append", default=[], metavar="PATH",
                   help="old copy of the project (repeatable); read-only until cleanup")
    p.add_argument("--archive-dir", metavar="PATH", help="where tb adopt archive puts archives (outside the project)")

    import adopt_sources

    adopt_sources.register(add)

    p = add("manifest", "rebuild ledger/<source>/manifest.txt (all sources or one)", cmd_manifest)
    p.add_argument("--source")
    p = add("slugmap", "slugmap.md: planned note for every file of sources with a folder", cmd_slugmap)
    p.add_argument("--force", action="store_true", help="overwrite (manual rows are lost)")
    p = add("next", "files of a source not covered by a batch yet, with sizes", cmd_next)
    p.add_argument("source")
    p.add_argument("--limit", type=int, default=1000)
    p = add("links", "old [[wikilinks]] and links -> relative links by the slugmap and ledgers "
                     '(not yet moved -> "pending"); drop "pending" from links whose target exists', cmd_links)
    p.add_argument("notes", nargs="*", help="notes (default: every note in Knowledge/)")
    p.add_argument("--write", action="store_true", help="rewrite the notes (default: dry run)")
    p = add("check", "check a source's ledger (coverage, verdicts, targets, audit), then tb kb lint", cmd_check)
    p.add_argument("source")
    p.add_argument("batch", nargs="?")
    p.add_argument("--pre-audit", action="store_true",
                   help="after the worker, before the auditor: empty audit and duplicate-candidate allowed")
    add("gate", "before a shared commit or closing a stage: every source checked, handoffs accepted, "
                "open questions listed", cmd_gate)
    add("status", "where the move stands: plan rows, coverage per source, open handoffs and questions", cmd_status)
    p = add("archive", "tar.gz of old paths into the archive dir, mode 600, verified by sha256", cmd_archive)
    p.add_argument("name", help="archive name (kebab-case), e.g. old-vault")
    p.add_argument("paths", nargs="+")
    p.add_argument("--dir", metavar="PATH", help="archive dir (default: archive_dir of adopt.toml)")
    parser.set_defaults(func=lambda _args: (parser.print_help(), 0)[1])
