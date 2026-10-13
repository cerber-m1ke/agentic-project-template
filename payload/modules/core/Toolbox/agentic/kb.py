"""tb kb — search and maintain the project Knowledge base (Knowledge/)."""

from __future__ import annotations

import argparse
import math
import os
import re
import urllib.parse
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

import common
import secret_scan

# The C loader is ~10x faster than common.split_frontmatter's pure-Python safe_load (matters for hooks).
_YAML_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)

KEBAB_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
NOTE_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
WINDOWS_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
                    *(f"lpt{i}" for i in range(1, 10))}
REQUIRED_KEYS = ("type", "title", "description", "created")  # + `status` for types that have statuses
LIST_KEYS = ("tags", "aliases", "resources", "applies_to")
TEMPLATES_DIR = "_templates"
AGENTS_TOKEN_BUDGET = 1500

# Search: BM25 over weighted fields (a simple BM25F).
FIELD_WEIGHTS = {"title": 3.0, "aliases": 3.0, "tags": 2.0, "description": 2.0, "body": 1.0}
K1, B = 1.2, 0.75
SNIPPET_WIDTH = 160

# Review thresholds in days since `verified` (else `created`); None = any status.
STALE_RULES: dict[str, tuple[int, tuple[str, ...] | None]] = {
    "gotcha": (90, None),
    "entity": (180, None),
    "example": (180, None),
    "plan": (60, ("idea", "ready")),
    "task": (30, ("active", "blocked")),
    "decision": (30, ("proposed",)),
}

_FM_RE = re.compile(r"\A---[ \t]*\n(.*?)\n---[ \t]*(?:\n|\Z)", re.DOTALL)
_WORD_RE = re.compile(r"\w+")
_CYRILLIC_RE = re.compile(r"[\u0400-\u04ff]")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_LINK_RE = re.compile(
    r"(!?)\[((?:[^\[\]\n]|\[[^\]\n]*\])*)\]\(\s*(<[^>\n]*>|[^)\s]+)"
    r"(?:\s+(?:\"[^\"\n]*\"|'[^'\n]*'|\([^)\n]*\)))?\s*\)")
_WIKILINK_RE = re.compile(r"(?<!!)\[\[[^\]\n]+\]\]")
_FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
_INLINE_CODE_RE = re.compile(r"(`+)[^`\n]*?\1")
_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")

STOPWORDS = frozenset("""
a an and are as at be been but by can could do does for from had has have how i if in into is it
its me my no not of on or our so than that the their them then there these they this those to too
us was we were what when where which who why will with would you your
а без более бы был была были было быть в вам вас весь во вот все всего всех вы где да даже для до
его ее если есть еще же за здесь и из или им их к как какая какой когда кто ли либо мне может мы
на над надо наш не него нее нет ни них но ну о об однако он она они оно от очень по под при про с
со так также такой там те тем то того тоже той только том ты у уже хотя чего чей чем что чтобы
чье чья эта эти это этого этой этом этот я
""".split())


# --- notes -----------------------------------------------------------------------------

@dataclass
class Link:
    line: int            # 1-based line in the file
    target: str          # raw target as written
    path: Path           # normalized absolute target path (fragment removed)
    exists: bool
    image: bool


@dataclass
class Note:
    path: Path
    rel: str
    parts: tuple[str, ...]          # path parts relative to Knowledge/
    text: str
    meta: dict[str, Any]
    body: str
    body_offset: int                 # number of lines before the body
    has_frontmatter: bool
    error: str | None
    _links: list[Link] | None = field(default=None, repr=False)
    _code_free: list[str] | None = field(default=None, repr=False)

    @property
    def folder(self) -> str:
        return self.parts[0] if len(self.parts) > 1 else ""

    @property
    def folder_type(self) -> str | None:
        return common.FOLDER_TO_TYPE.get(self.folder)

    @property
    def type(self) -> str:
        t = self.meta.get("type")
        return t if isinstance(t, str) and t else (self.folder_type or "?")

    @property
    def status(self) -> str:
        s = self.meta.get("status")
        return str(s) if s not in (None, "") else ""

    @property
    def label(self) -> str:
        """`type/status`, or just `type` for notes without a status."""
        return f"{self.type}/{self.status}" if self.status else self.type

    @property
    def slug(self) -> str:
        if self.path.name == "index.md" and len(self.parts) >= 3:
            return self.path.parent.name
        return self.path.stem

    @property
    def title(self) -> str:
        t = self.meta.get("title")
        return str(t).strip() if t not in (None, "") else self.slug

    @property
    def description(self) -> str:
        d = self.meta.get("description")
        return " ".join(str(d).split()) if d not in (None, "") else ""

    def list_field(self, key: str) -> list:
        v = self.meta.get(key)
        if v is None:
            return []
        return v if isinstance(v, list) else [v]

    def resource_names(self) -> list[str]:
        names = []
        for item in self.list_field("resources"):
            name = resource_name(item)
            if name:
                names.append(name)
        return names

    @property
    def code_free_lines(self) -> list[str]:
        """Body lines with code blanked out (links and wikilinks inside code are ignored)."""
        if self._code_free is None:
            self._code_free = strip_code(self.body)
        return self._code_free

    @property
    def links(self) -> list[Link]:
        if self._links is None:
            self._links = extract_links(self.code_free_lines, self.path, self.body_offset)
        return self._links


def resource_name(item: Any) -> str | None:
    """Resource reference in frontmatter: "name", "name@branch" or {name: …, branch: …}."""
    if isinstance(item, dict):
        item = item.get("name")
    if isinstance(item, str) and item.strip():
        return item.strip().split("@", 1)[0].strip()
    return None


def knowledge_dir() -> Path:
    return common.project_root() / common.KNOWLEDGE_DIR


def is_note_parts(parts: tuple[str, ...]) -> bool:
    """Whether a file (parts relative to Knowledge/) is a note: *.md except READMEs, templates,
    hidden folders and task artifacts inside Tasks/<slug>/."""
    name = parts[-1]
    if not name.endswith(".md") or name == "README.md":
        return False
    if any(part.startswith(".") for part in parts[:-1]) or (len(parts) > 1 and parts[0] == TEMPLATES_DIR):
        return False
    return not (parts[0] == "Tasks" and len(parts) >= 3 and not (len(parts) == 3 and name == "index.md"))


def note_files(kdir: Path) -> list[tuple[Path, tuple[str, ...]]]:
    """Note files (path, parts relative to Knowledge/), see is_note_parts."""
    result: list[tuple[Path, tuple[str, ...]]] = []
    for dirpath, dirnames, filenames in os.walk(kdir):
        d = Path(dirpath)
        rp = os.path.relpath(dirpath, kdir)
        relparts = () if rp == "." else tuple(rp.split(os.sep))
        dirnames[:] = sorted(n for n in dirnames if not n.startswith(".")
                             and not (not relparts and n == TEMPLATES_DIR))
        for name in sorted(filenames):
            parts = relparts + (name,)
            if is_note_parts(parts):
                result.append((d / name, parts))
    return result


def split_frontmatter(text: str) -> tuple[dict | None, str, str | None, bool]:
    """Like common.split_frontmatter (fast C loader, never raises); also returns has_frontmatter."""
    m = _FM_RE.match(text)
    if not m:
        return None, text, None, False
    body = text[m.end():]
    try:
        meta = yaml.load(m.group(1), Loader=_YAML_LOADER) or {}
    except Exception:
        try:  # canonical message from the shared helper
            _meta, _body, err = common.split_frontmatter(text)
        except Exception as exc:  # e.g. ValueError for an impossible date like 2026-13-45
            err = f"invalid YAML frontmatter: {exc}"
        return None, body, err or "invalid YAML frontmatter", True
    if not isinstance(meta, dict):
        return None, body, "frontmatter is not a mapping", True
    return meta, body, None, True


def parse_note(path: Path, kdir: Path, parts: tuple[str, ...] | None = None,
               data: bytes | None = None) -> Note:
    """Parse a note from disk, or from `data` (e.g. its staged content)."""
    parts = parts or path.relative_to(kdir).parts
    try:
        raw = common.read_text(path) if data is None else data.decode("utf-8")
        text = common.normalize_newlines(raw).removeprefix("\ufeff")
    except (OSError, UnicodeDecodeError) as exc:
        text, meta, body, err, has_fm = "", None, "", f"cannot read file: {exc}", False
    else:
        meta, body, err, has_fm = split_frontmatter(text)
    offset = text.count("\n") - body.count("\n") if has_fm else 0
    return Note(path=path, rel="/".join((common.KNOWLEDGE_DIR, *parts)), parts=parts, text=text,
                meta=meta or {}, body=body, body_offset=offset, has_frontmatter=has_fm, error=err)


def load_notes(warn_missing: bool = True) -> list[Note]:
    kdir = knowledge_dir()
    if not kdir.is_dir():
        if warn_missing:
            common.warn(f"no {common.KNOWLEDGE_DIR}/ directory in {common.project_root()}")
        return []
    return sorted((parse_note(p, kdir, parts) for p, parts in note_files(kdir)), key=lambda n: n.rel)


# --- links -------------------------------------------------------------------------------

class IndexSnapshot:
    """File existence as of the git index (what the next commit contains), for `lint --staged`.
    Paths outside the project or under Resources/ (not in the root repository) use the disk."""

    def __init__(self, root: Path, paths: set[str]) -> None:
        self.root = root
        self.files = paths
        self.dirs = {"/".join(p.split("/")[:i]) for p in paths for i in range(1, p.count("/") + 1)}

    def _rel(self, path: Path) -> str | None:
        rel = os.path.relpath(os.path.normpath(path), self.root).replace(os.sep, "/")
        if rel == "." or rel.startswith("../") or rel == ".." or rel.split("/")[0] == "Resources":
            return None
        return rel

    def exists(self, path: Path) -> bool:
        rel = self._rel(path)
        return path.exists() if rel is None else (rel in self.files or rel in self.dirs)

    def is_dir(self, path: Path) -> bool:
        rel = self._rel(path)
        return path.is_dir() if rel is None else rel in self.dirs


_snapshot: IndexSnapshot | None = None  # set by `lint --staged`


def _exists(path: Path) -> bool:
    return path.exists() if _snapshot is None else _snapshot.exists(path)


def _is_dir(path: Path) -> bool:
    return path.is_dir() if _snapshot is None else _snapshot.is_dir(path)

def strip_code(body: str) -> list[str]:
    """Body lines with fenced code blocks and inline code blanked out (line count preserved)."""
    lines, fence = [], None
    for line in body.split("\n"):
        m = _FENCE_RE.match(line)
        if fence:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
                fence = None
            lines.append("")
        elif m:
            fence = m.group(1)
            lines.append("")
        else:
            lines.append(_INLINE_CODE_RE.sub(lambda mm: " " * len(mm.group(0)), line))
    return lines


def resolve_target(target: str, base_dir: Path) -> Path | None:
    """Resolve a relative Markdown link target; None for external links and pure anchors."""
    target = target.strip()
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1].strip()
    if not target or target.startswith("#") or _SCHEME_RE.match(target):
        return None
    target = urllib.parse.unquote(re.split(r"[#?]", target, maxsplit=1)[0])
    if not target:
        return None
    if target.startswith("/"):
        p = common.project_root() / target.lstrip("/")
    else:
        p = base_dir / target
    p = Path(os.path.normpath(p))
    if _is_dir(p) and _exists(p / "index.md"):
        p = p / "index.md"
    return p


def extract_links(lines: list[str], path: Path, offset: int = 0) -> list[Link]:
    links: list[Link] = []
    for i, line in enumerate(lines, start=1):
        if "](" not in line:
            continue
        for m in _LINK_RE.finditer(line):
            resolved = resolve_target(m.group(3), path.parent)
            if resolved is not None:
                links.append(Link(line=offset + i, target=m.group(3), path=resolved,
                                  exists=_exists(resolved), image=bool(m.group(1))))
    return links


def _key(p: Path) -> str:
    return os.path.normcase(os.path.normpath(str(p)))


# --- search ----------------------------------------------------------------------------------

class Analyzer:
    """Lowercase \\w+ tokens, stop words removed, Snowball stems (Russian for Cyrillic, English for Latin)."""

    def __init__(self) -> None:
        import snowballstemmer

        self._ru = snowballstemmer.stemmer("russian")
        self._en = snowballstemmer.stemmer("english")
        self._cache: dict[str, str] = {}
        self._token_cache: dict[str, tuple[str, ...]] = {}

    def stem(self, token: str) -> str:
        s = self._cache.get(token)
        if s is None:
            if _CYRILLIC_RE.search(token):
                s = self._ru.stemWord(token.replace("ё", "е"))
            elif token.isascii() and not token.isdigit():
                s = self._en.stemWord(token)
            else:
                s = token
            self._cache[token] = s
        return s

    def _analyze(self, token: str) -> tuple[str, ...]:
        pieces = [token] + ([p for p in token.split("_") if p] if "_" in token else [])
        return tuple(self.stem(t) for t in pieces if len(t) >= 2 and t not in STOPWORDS)

    def terms(self, text: str) -> list[str]:
        cache, out = self._token_cache, []
        for tok in _WORD_RE.findall(text.lower()):
            stems = cache.get(tok)
            if stems is None:
                stems = cache[tok] = self._analyze(tok)
            out.extend(stems)
        return out


def note_fields(note: Note) -> dict[str, str]:
    def joined(key: str) -> str:
        return " ".join(str(x) for x in note.list_field(key) if not isinstance(x, (dict, list)))

    return {
        "title": str(note.meta.get("title") or ""),
        "aliases": joined("aliases") + " " + note.slug.replace("-", " "),
        "tags": joined("tags"),
        "description": note.description,
        "body": note.body,
    }


@dataclass
class Hit:
    note: Note
    score: float
    matched: set[str]
    strong: bool          # a query term matched title/aliases/tags/description
    snippet: str = ""


class SearchIndex:
    def __init__(self, notes: list[Note], analyzer: Analyzer | None = None) -> None:
        self.notes = notes
        self.analyzer = analyzer or Analyzer()
        self.postings: dict[str, list[tuple[int, float]]] = defaultdict(list)
        self.strong_terms: list[set[str]] = []
        self.lengths: list[float] = []
        for i, note in enumerate(notes):
            tf: dict[str, float] = defaultdict(float)
            length, strong = 0.0, set()
            for name, text in note_fields(note).items():
                if not text:
                    continue
                w = FIELD_WEIGHTS[name]
                counts = Counter(self.analyzer.terms(text))
                length += w * counts.total()
                for t, c in counts.items():
                    tf[t] += w * c
                if name != "body":
                    strong.update(counts)
            for t, v in tf.items():
                self.postings[t].append((i, v))
            self.strong_terms.append(strong)
            self.lengths.append(length)
        n = len(notes)
        self.avgdl = (sum(self.lengths) / n) if n and sum(self.lengths) else 1.0
        self.idf = {t: math.log(1 + (n - len(p) + 0.5) / (len(p) + 0.5)) for t, p in self.postings.items()}

    def query_terms(self, query: str) -> list[str]:
        return list(dict.fromkeys(self.analyzer.terms(query)))

    def search(self, query: str, accept=None) -> tuple[list[Hit], list[str]]:
        terms = self.query_terms(query)
        scores: dict[int, float] = defaultdict(float)
        matched: dict[int, set[str]] = defaultdict(set)
        for t in terms:
            idf = self.idf.get(t)
            if idf is None:
                continue
            for i, tf in self.postings[t]:
                norm = K1 * (1 - B + B * self.lengths[i] / self.avgdl)
                scores[i] += idf * tf * (K1 + 1) / (tf + norm)
                matched[i].add(t)
        hits = [Hit(self.notes[i], s, matched[i], bool(matched[i] & self.strong_terms[i]))
                for i, s in scores.items() if accept is None or accept(self.notes[i])]
        hits.sort(key=lambda h: (-h.score, h.note.rel))
        return hits, terms

    def snippet(self, note: Note, terms: list[str]) -> str:
        wanted = set(terms)
        best, best_score = "", 0.0
        for raw in note.body.split("\n"):
            line = " ".join(raw.split())
            if not line:
                continue
            found = wanted.intersection(self.analyzer.terms(line))
            score = sum(self.idf.get(t, 0.0) for t in found)
            if score > best_score:
                best, best_score = line, score
        return trim_line(best, wanted, self.analyzer) if best else ""


def trim_line(line: str, wanted: set[str], analyzer: Analyzer, width: int = SNIPPET_WIDTH) -> str:
    if len(line) <= width:
        return line
    pos = 0
    for m in _WORD_RE.finditer(line):
        if analyzer.stem(m.group(0).lower()) in wanted:
            pos = m.start()
            break
    start = max(0, min(pos - 40, len(line) - (width - 1)))
    prefix = "…" if start > 0 else ""
    room = width - len(prefix)
    chunk = line[start:start + room]
    if start + room < len(line):
        chunk = chunk[:room - 1] + "…"
    return prefix + chunk


def _split_values(value: str | None) -> set[str] | None:
    if not value:
        return None
    return {v.strip() for v in value.split(",") if v.strip()}


def run_search(query: str, notes: list[Note], *, types: set[str] | None = None,
               statuses: set[str] | None = None, resource: str | None = None,
               limit: int | None = 10, snippets: bool = True) -> list[Hit]:
    """BM25 search. An empty query lists all notes passing the filters, most recent first."""
    def accept(note: Note) -> bool:
        return ((types is None or note.type in types)
                and (statuses is None or note.status in statuses)
                and (resource is None or resource in note.resource_names()))

    if not query.strip():
        listed = sorted((n for n in notes if accept(n)), key=lambda n: n.rel)
        listed.sort(key=lambda n: note_date(n) or date.min, reverse=True)
        return [Hit(n, 0.0, set(), False) for n in listed][:None if limit is None else max(limit, 0)]
    index = SearchIndex(notes)
    hits, terms = index.search(query, accept)
    hits = hits[:10 if limit is None else max(limit, 0)]
    if snippets:
        for h in hits:
            h.snippet = index.snippet(h.note, terms)
    return hits


def cmd_search(args: argparse.Namespace) -> int:
    query = " ".join(args.query).strip()
    types = _split_values(args.type)
    if not query and not (types or args.status or args.resource):
        return common.fail("give a query, or filters (--type/--status/--resource) to list notes", 2)
    if types and (bad := types - set(common.KNOWLEDGE_TYPES)):
        return common.fail(f"unknown type: {', '.join(sorted(bad))} "
                           f"(expected one of: {', '.join(common.KNOWLEDGE_TYPES)})")
    notes = load_notes()
    hits = run_search(query, notes, types=types, statuses=_split_values(args.status),
                      resource=args.resource, limit=args.limit, snippets=not args.brief or args.json)
    if args.json:
        common.print_json([{"path": h.note.rel, "type": h.note.type, "status": h.note.status,
                            "title": h.note.title, "description": h.note.description,
                            "score": round(h.score, 4), "snippet": h.snippet} for h in hits])
        return 0
    if not hits:
        common.out(f'No matches for "{query}".' if query else "No notes match the filters.")
        return 0
    for h in hits:
        head = f"{h.note.rel}  [{h.note.label}]  {h.note.title}"
        common.out(f"{head} — {h.note.description}" if h.note.description else head)
        if not args.brief and h.snippet:
            common.out(f"    {h.snippet}")
    return 0


# --- show / related ----------------------------------------------------------------------------

def resolve_ref(ref: str, notes: list[Note]) -> tuple[Path | None, list[Note]]:
    """Return (path, []) when found, (None, candidates) when ambiguous, (None, []) when not found."""
    root, kdir = common.project_root(), knowledge_dir()
    p = Path(ref)
    bases = [None] if p.is_absolute() else [Path.cwd(), root, kdir]
    for base in bases:
        q = p if base is None else base / p
        for cand in (q, q.with_name(q.name + ".md"), q / "index.md"):
            if cand.is_file():
                return Path(os.path.normpath(cand.absolute())), []
    if "/" in ref or "\\" in ref:
        return None, []
    slug = ref[:-3] if ref.endswith(".md") else ref
    matches = [n for n in notes if n.slug == slug]
    if len(matches) == 1:
        return matches[0].path, []
    return None, matches


def _find_note(ref: str, notes: list[Note]) -> tuple[Path | None, int]:
    path, candidates = resolve_ref(ref, notes)
    if path is None:
        if candidates:
            common.out(f'"{ref}" is ambiguous:')
            for n in candidates:
                common.out(f"  {n.rel}  [{n.label}]  {n.title}")
            return None, common.fail("specify the path")
        return None, common.fail(f'note not found: {ref} (try: tb kb search {ref})')
    try:
        path.relative_to(knowledge_dir().absolute())
    except ValueError:
        return None, common.fail(f"not inside {common.KNOWLEDGE_DIR}/: {common.rel(path)}")
    return path, 0


def cmd_show(args: argparse.Namespace) -> int:
    path, code = _find_note(args.ref, load_notes())
    if path is None:
        return code
    text = common.read_text(path)
    common.out(text.rstrip("\n"))
    return 0


def cmd_related(args: argparse.Namespace) -> int:
    notes = load_notes()
    path, code = _find_note(args.ref, notes)
    if path is None:
        return code
    by_key = {_key(n.path): n for n in notes}
    note = by_key.get(_key(path)) or parse_note(path, knowledge_dir())
    key = _key(path)

    def describe(p: Path) -> str:
        other = by_key.get(_key(p))
        return f"{common.rel(p)} — {other.title}" if other else common.rel(p)

    outgoing, seen = [], set()
    for link in note.links:
        k = _key(link.path)
        if k in seen:
            continue
        seen.add(k)
        outgoing.append(describe(link.path) + ("" if link.exists else "  [broken]"))
    backlinks = sorted({n.rel: n for n in notes if n.path != note.path
                        and any(_key(l.path) == key for l in n.links)}.values(), key=lambda n: n.rel)

    common.out(f"{note.rel}  [{note.label}]  {note.title}")
    common.out(f"Links ({len(outgoing)}):" if outgoing else "Links: none")
    for line in outgoing:
        common.out(f"  {line}")
    common.out(f"Backlinks ({len(backlinks)}):" if backlinks else "Backlinks: none")
    for n in backlinks:
        common.out(f"  {n.rel} — {n.title}")
    return 0


# --- new ---------------------------------------------------------------------------------------------

def _yaml_dq(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def render_template(template: str, title: str, today: str) -> str:
    template = common.normalize_newlines(template)
    m = _FM_RE.match(template)
    head, body = (template[:m.end()], template[m.end():]) if m else ("", template)
    if head:
        head = head.replace('"{{title}}"', '"' + _yaml_dq(title) + '"')
        head = head.replace("'{{title}}'", "'" + title.replace("'", "''") + "'")
        head = head.replace("{{title}}", _yaml_dq(title))  # assume a double-quoted context
    text = head + body.replace("{{title}}", title)
    return text.replace("{{date}}", today)


def valid_slug(slug: str) -> bool:
    return bool(KEBAB_RE.match(slug)) and slug not in WINDOWS_RESERVED


def cmd_new(args: argparse.Namespace) -> int:
    ntype, slug = args.type, args.slug
    if slug.endswith(".md"):
        slug = slug[:-3]
    if ntype not in common.KNOWLEDGE_TYPES:
        return common.fail(f"unknown type: {ntype} (expected one of: {', '.join(common.KNOWLEDGE_TYPES)})")
    if not valid_slug(slug):
        return common.fail(f"invalid slug: {slug!r} (lowercase kebab-case like 'uv-proxy-timeout'; "
                           "Windows reserved names are not allowed)")
    if args.folder and ntype != "task":
        return common.fail("--folder is only supported for tasks")
    kdir = knowledge_dir()
    template = kdir / TEMPLATES_DIR / f"{ntype}.md"
    if not template.is_file():
        return common.fail(f"template not found: {common.rel(template)} "
                           "(is the knowledge module installed?)")
    folder = kdir / common.KNOWLEDGE_TYPES[ntype]["folder"]
    target = folder / slug / "index.md" if args.folder else folder / f"{slug}.md"
    for existing in (folder / f"{slug}.md", folder / slug / "index.md") if ntype == "task" else (target,):
        if existing.exists():
            return common.fail(f"already exists: {common.rel(existing)}")
    title = args.title.strip() if args.title and args.title.strip() else slug.replace("-", " ").capitalize()
    text = render_template(common.read_text(template), title, common.today_iso())
    if args.description and args.description.strip():
        line = 'description: "' + _yaml_dq(" ".join(args.description.split())) + '"'
        text, n = re.subn(r"(?m)^description:.*$", lambda _m: line, text, count=1)
        if not n:
            return common.fail(f"template {common.rel(template)} has no `description:` line")
    if _FM_RE.match(text):
        try:
            _meta, _body, err = common.split_frontmatter(text)
        except Exception as exc:
            err = str(exc)
        if err:
            return common.fail(f"template {common.rel(template)} produced invalid frontmatter "
                               f"(quote {{{{title}}}} in the template?): {' '.join(err.split())}")
    same = [n.rel for n in load_notes(warn_missing=False) if n.slug == slug]
    common.write_text(target, text)
    if same:
        common.warn(f"slug '{slug}' is also used by {', '.join(same)}")
    common.out(common.rel(target))
    if not (args.description and args.description.strip()):
        common.warn("fill `description` (one line; search ranks by it): `tb kb lint` requires it")
    return 0


# --- index -----------------------------------------------------------------------------------------------

def _md_link_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def cmd_index(args: argparse.Namespace) -> int:
    notes = load_notes()
    if args.json:
        common.print_json([{
            "path": n.rel, "type": n.type, "status": n.status, "title": n.title,
            "description": n.description, "created": n.meta.get("created"),
            "verified": n.meta.get("verified"), "tags": n.list_field("tags"),
            "resources": n.resource_names(),
        } for n in notes])
        return 0
    if not notes:
        common.out(f"No notes in {common.KNOWLEDGE_DIR}/.")
        return 0
    groups: dict[str, list[Note]] = defaultdict(list)
    for n in notes:
        groups[n.type if n.type in common.KNOWLEDGE_TYPES else "other"].append(n)
    common.out("# Knowledge index")
    for t in [*common.KNOWLEDGE_TYPES, "other"]:
        if t not in groups:
            continue
        heading = common.KNOWLEDGE_TYPES[t]["folder"] if t in common.KNOWLEDGE_TYPES else "Other"
        common.out(f"\n## {heading} ({len(groups[t])})\n")
        for n in groups[t]:
            target = n.rel
            if args.base is not None:
                target = Path(os.path.relpath(n.path, common.project_root() / args.base)).as_posix()
            target = f"<{target}>" if " " in target else target
            desc = f" — {n.description}" if n.description else ""
            status = f" ({n.status})" if n.status else ""
            common.out(f"- [{_md_link_text(n.title)}]({target}){desc}{status}")
    return 0


# --- lint ------------------------------------------------------------------------------------------------------

@dataclass
class Problem:
    path: str
    line: int | None
    level: str          # "error" | "warning"
    message: str

    def format(self) -> str:
        loc = f"{self.path}:{self.line}" if self.line else self.path
        return f"{loc}: {self.level}: {self.message}"


def note_date(note: Note) -> date | None:
    """Date of the last check: `verified`, else `created`."""
    return as_date(note.meta.get("verified")) or as_date(note.meta.get("created"))


def as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str) and _DATE_RE.match(value.strip()):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


def estimate_tokens(text: str) -> int:
    """Rough upper estimate: ~4 ASCII characters per token, ~2.5 for Cyrillic and other scripts."""
    ascii_chars = sum(1 for c in text if ord(c) < 128)
    return round(ascii_chars / 4 + (len(text) - ascii_chars) / 2.5)


def load_resource_names(problems: list[Problem], text: str | None = None) -> set[str] | None:
    """Resource names of the catalog (from disk, or from `text`, e.g. its staged content)."""
    import tomllib

    path = common.project_root() / "Resources" / "resources.toml"
    if text is None and not path.is_file():
        return None
    try:
        data = common.load_toml(path) if text is None else tomllib.loads(text)
    except Exception as exc:
        problems.append(Problem(common.rel(path), None, "error", f"invalid TOML: {exc}"))
        return None
    items = data.get("resource", [])
    return {str(r["name"]) for r in items if isinstance(r, dict) and r.get("name")} \
        if isinstance(items, list) else set()


def check_name(note: Note) -> list[str]:
    msgs = []
    for part in note.parts[1:-1]:
        if not KEBAB_RE.match(part):
            msgs.append(f"folder name '{part}' is not lowercase kebab-case")
        elif part in WINDOWS_RESERVED:
            msgs.append(f"folder name '{part}' is reserved on Windows")
    name = note.path.name
    if not NOTE_NAME_RE.match(name):
        msgs.append(f"file name '{name}' is not lowercase kebab-case (^[a-z0-9]+(-[a-z0-9]+)*\\.md$)")
    elif note.path.stem in WINDOWS_RESERVED:
        msgs.append(f"file name '{name}' is reserved on Windows")
    return msgs


def lint_note(note: Note, slugs: dict[str, list[Note]], resource_names: set[str] | None,
              today: date) -> list[Problem]:
    problems: list[Problem] = []

    def err(msg: str, line: int | None = None) -> None:
        problems.append(Problem(note.rel, line, "error", msg))

    def warn(msg: str, line: int | None = None) -> None:
        problems.append(Problem(note.rel, line, "warning", msg))

    for msg in check_name(note):
        err(msg)
    if note.folder_type is None:
        warn("note is outside the type folders (" + ", ".join(sorted(common.FOLDER_TO_TYPE)) + ")")
    if len(slugs.get(note.slug, [])) > 1:
        others = [n.rel for n in slugs[note.slug] if n is not note]
        warn(f"slug '{note.slug}' is also used by {', '.join(others)}")

    meta = note.meta
    if note.error:
        err(" ".join(note.error.split()))
    elif not note.has_frontmatter:
        err("missing YAML frontmatter (--- … --- at the top of the file)")
    else:
        for key in REQUIRED_KEYS:
            if meta.get(key) in (None, "", [], {}):
                err(f"missing required key '{key}'")
        ntype = meta.get("type")
        spec = common.KNOWLEDGE_TYPES.get(ntype) if isinstance(ntype, str) else None
        if ntype not in (None, "") and spec is None:
            err(f"unknown type '{ntype}' (expected one of: {', '.join(common.KNOWLEDGE_TYPES)})")
        if spec and note.folder_type and ntype != note.folder_type:
            err(f"type '{ntype}' does not match folder {note.folder}/ (expected '{note.folder_type}')")
        status = meta.get("status")
        if spec and spec["statuses"] and status in (None, ""):
            err("missing required key 'status'")
        elif spec and status not in (None, "") and status not in spec["statuses"]:
            if status in common.RETIRED_STATUSES.get(ntype, ()):
                warn(f"status '{status}' is retired: the note is obsolete, delete it (git history keeps it)")
            elif not spec["statuses"]:
                warn(f"{ntype} notes have no status: remove 'status'")
            else:
                err(f"status '{status}' is not allowed for {ntype} "
                    f"(allowed: {', '.join(spec['statuses'])})")
        for key in ("title", "description"):
            v = meta.get(key)
            if v not in (None, "") and not isinstance(v, str):
                err(f"'{key}' must be a string")
        if isinstance(meta.get("description"), str) and "\n" in meta["description"].strip():
            warn("'description' should be a single line")
        dates = {}
        for key in ("created", "verified"):
            v = meta.get(key)
            if v in (None, ""):
                continue
            d = as_date(v)
            if d is None:
                err(f"'{key}' is not a valid date (expected YYYY-MM-DD): '{v}'")
                continue
            dates[key] = d
            if d > today:
                warn(f"'{key}' is in the future: {d.isoformat()}")
        if "created" in dates and "verified" in dates and dates["verified"] < dates["created"]:
            warn("'verified' is earlier than 'created'")
        for key in LIST_KEYS:
            v = meta.get(key)
            if v is not None and not isinstance(v, list):
                err(f"'{key}' must be a list")
        if meta.get("applies_to") and ntype not in ("gotcha", "example"):
            warn("'applies_to' is meant for gotcha/example notes")
        if meta.get("superseded_by") not in (None, "", []):
            warn("'superseded_by' is retired: delete the superseded decision and explain the change "
                 "in the new one")
        if resource_names is not None:
            for item in note.list_field("resources"):
                name = resource_name(item)
                if name is None:
                    err(f"invalid 'resources' entry: {item!r}")
                elif name not in resource_names:
                    err(f"unknown resource '{name}' (not in Resources/resources.toml)")

    resources_dir = common.project_root() / "Resources"
    for link in note.links:
        if link.exists:
            continue
        try:
            inside = link.path.relative_to(resources_dir).parts
        except ValueError:
            inside = ()
        if inside:
            if (resources_dir / inside[0]).is_dir():
                warn(f"link to a missing file in resource '{inside[0]}': {link.target}", link.line)
            continue  # resource not cloned on this machine
        err(f"broken link: {link.target}", link.line)
    for i, line in enumerate(note.code_free_lines if "[[" in note.body else [], start=1):
        if _WIKILINK_RE.search(line):
            warn("wikilink found; use relative Markdown links [text](path.md)", note.body_offset + i)
    return problems


def staged_notes() -> tuple[list[Note], str | None]:
    """Notes as the next commit has them (the git index), and the staged resources.toml text.
    Sets the module's IndexSnapshot so links resolve against the index as well."""
    global _snapshot
    root, kdir = common.project_root(), knowledge_dir()
    res = common.run(["git", "ls-files", "-z"], cwd=root)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip() or "git ls-files failed")
    paths = {p for p in res.stdout.split("\0") if p}
    _snapshot = IndexSnapshot(root, paths)
    prefix = common.KNOWLEDGE_DIR + "/"
    wanted = sorted(p for p in paths if p.startswith(prefix) and is_note_parts(tuple(p[len(prefix):].split("/"))))
    catalog = "Resources/resources.toml"
    blobs = secret_scan._staged_blobs(root, wanted + ([catalog] if catalog in paths else []))
    notes = [parse_note(root / p, kdir, tuple(p[len(prefix):].split("/")), data=blobs.get(p, b""))
             for p in wanted]
    text = blobs[catalog].decode("utf-8", errors="replace") if catalog in blobs else None
    return notes, text


def run_lint(staged: bool = False) -> tuple[list[Problem], int]:
    """Lint the Knowledge base on disk, or (staged) exactly what the next commit contains:
    untracked or unstaged drafts neither block a commit nor hide a broken staged note."""
    root = common.project_root()
    kdir = knowledge_dir()
    problems: list[Problem] = []
    if staged:
        notes, catalog_text = staged_notes()
        resource_names = load_resource_names(problems, catalog_text) if catalog_text is not None else None
    else:
        notes = load_notes(warn_missing=False)
        if not kdir.is_dir():
            problems.append(Problem(common.KNOWLEDGE_DIR + "/", None, "warning", "directory not found"))
        resource_names = load_resource_names(problems)
    slugs: dict[str, list[Note]] = defaultdict(list)
    for n in notes:
        slugs[n.slug].append(n)
    today = date.today()
    for n in notes:
        problems.extend(lint_note(n, slugs, resource_names, today))
    if staged:  # secrets of staged files: `tb secrets scan --staged` (pre-commit runs both)
        problems.sort(key=lambda p: (p.path, p.line or 0))
        return problems, len(notes)
    if kdir.is_dir():
        skip = secret_scan.SKIP_DIRS | {".obsidian", ".trash"}
        findings, _ = secret_scan.scan_files(secret_scan.iter_files([kdir], skip))
        for f in findings:
            problems.append(Problem(f.path, f.line, "error", f"possible secret: {f.kind} {f.masked}"))
    agents = root / "AGENTS.md"
    if agents.is_file():
        tokens = estimate_tokens(common.read_text(agents))
        if tokens > AGENTS_TOKEN_BUDGET:
            problems.append(Problem("AGENTS.md", None, "warning",
                                    f"~{tokens} tokens, above the {AGENTS_TOKEN_BUDGET}-token budget "
                                    "(it is loaded into every session; move details to Knowledge/ or skills)"))
    problems.sort(key=lambda p: (p.path, p.line or 0))
    return problems, len(notes)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def cmd_lint(args: argparse.Namespace) -> int:
    if args.staged and common.git("rev-parse", "--git-dir").returncode != 0:
        return common.fail("--staged needs a git repository")
    try:
        problems, count = run_lint(staged=args.staged)
    except RuntimeError as exc:
        return common.fail(str(exc))
    for p in problems:
        common.out(p.format())
    errors = sum(1 for p in problems if p.level == "error")
    warnings = len(problems) - errors
    summary = f"{_plural(errors, 'error')}, {_plural(warnings, 'warning')}"
    if not args.quiet:
        common.out(f"{summary} ({_plural(count, 'note')} checked)")
    elif problems:
        common.out(summary)
    return 1 if errors else 0


# --- stale ----------------------------------------------------------------------------------------------------------

def stale_reason(note: Note, today: date, days_override: int | None) -> tuple[int, str] | None:
    """(sort key, reason) when the note is a review candidate."""
    if note.type == "task" and note.status == "done":
        return 10 ** 6, "harvest pending (task is done: move lasting results to Knowledge, then delete it)"
    if note.status and note.status in common.RETIRED_STATUSES.get(note.type, ()):
        return 10 ** 6, f"retired status '{note.status}' (the note is obsolete: delete it)"
    rule = STALE_RULES.get(note.type)
    if rule is None:
        return None
    threshold, statuses = rule
    if statuses is not None and note.status not in statuses:
        return None
    if days_override is not None:
        threshold = days_override
    verified, created = as_date(note.meta.get("verified")), as_date(note.meta.get("created"))
    ref = verified or created
    if ref is None:
        return 10 ** 5, "no valid 'verified' or 'created' date"
    age = (today - ref).days
    if age < threshold:
        return None
    if verified:
        return age, f"verified {age} days ago (threshold {threshold})"
    return age, f"created {age} days ago, never verified (threshold {threshold})"


def cmd_stale(args: argparse.Namespace) -> int:
    if args.days is not None and args.days < 0:
        return common.fail("--days must be >= 0")
    today = date.today()
    found = []
    for n in load_notes():
        r = stale_reason(n, today, args.days)
        if r:
            found.append((r[0], n, r[1]))
    if not found:
        common.out("No stale notes.")
        return 0
    found.sort(key=lambda x: (-x[0], x[1].rel))
    for _age, n, reason in found:
        common.out(f"{n.rel}  [{n.label}]  {reason}")
    return 0


# --- registration -------------------------------------------------------------------------------------------------------

def register(sub) -> None:
    p = sub.add_parser("kb", help="search and maintain Knowledge/")
    s = p.add_subparsers(dest="kb_command", metavar="<subcommand>")

    q = s.add_parser("search", help="full-text search (BM25, Russian/English stemming)")
    q.add_argument("query", nargs="*", help="search words (omit to list notes matching the filters)")
    q.add_argument("--type", help="filter by type (comma-separated)")
    q.add_argument("--status", help="filter by status (comma-separated)")
    q.add_argument("--resource", help="filter by resource name")
    q.add_argument("--limit", type=int, help="max results (default 10; all when listing by filters)")
    q.add_argument("--brief", action="store_true", help="no snippet lines")
    q.add_argument("--json", action="store_true", help="JSON output")
    q.set_defaults(func=cmd_search)

    sh = s.add_parser("show", help="print a note (path or slug)")
    sh.add_argument("ref", help="path (relative to the project root or Knowledge/) or slug")
    sh.set_defaults(func=cmd_show)

    r = s.add_parser("related", help="outgoing links and backlinks of a note")
    r.add_argument("ref", help="path or slug")
    r.set_defaults(func=cmd_related)

    n = s.add_parser("new", help="create a note from Knowledge/_templates/<type>.md")
    n.add_argument("type", help="|".join(common.KNOWLEDGE_TYPES))
    n.add_argument("slug", help="file name: lowercase kebab-case, without .md")
    n.add_argument("--title", help="note title (default: from the slug)")
    n.add_argument("--description", help="one-line description (required by lint; search ranks by it)")
    n.add_argument("--folder", action="store_true", help="task only: create Tasks/<slug>/index.md")
    n.set_defaults(func=cmd_new)

    i = s.add_parser("index", help="print an index of all notes grouped by type")
    i.add_argument("--json", action="store_true", help="JSON output")
    i.add_argument("--base", metavar="DIR",
                   help="make links relative to DIR (e.g. Knowledge when saving the index there); "
                        "default: the project root")
    i.set_defaults(func=cmd_index)

    li = s.add_parser("lint", help="validate notes (frontmatter, names, links, secrets, AGENTS.md size)")
    li.add_argument("--quiet", action="store_true", help="print only problems")
    li.add_argument("--staged", action="store_true",
                    help="lint the notes as staged in git (pre-commit): ignores unstaged and untracked edits")
    li.set_defaults(func=cmd_lint)

    st = s.add_parser("stale", help="notes due for review")
    st.add_argument("--days", type=int, help="use this threshold (days) for every type")
    st.set_defaults(func=cmd_stale)

    p.set_defaults(func=lambda _a: (p.print_help(), 0)[1])
