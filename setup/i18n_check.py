# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml>=6"]
# [tool.uv]
# exclude-newer = "2026-10-01T00:00:00Z"
# ///
"""Check that every translatable file has a structurally identical ru/en pair.

Pairs: `<name>.ru.<ext>` <-> `<name>.en.<ext>` under payload/ and setup/profiles/, plus the root
README.md (ru) <-> README.en.md.

Markdown pairs must have: the same heading level sequence; the same number of fenced code blocks
with the same info strings (content may differ: comments get translated); the same number of
inline code spans, and every ru span without Cyrillic must occur in the en file at least as often
(commands and paths stay identical, placeholder words may be translated); the same agentic block
markers and {{agentic.*}} placeholders; the same frontmatter keys and values except
description/title. TOML pairs must parse to identical data. Exit code 1 if any problem is found.
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import yaml

LANG_RE = re.compile(r"^(?P<base>.+)\.(?P<lang>ru|en)(?P<ext>\.[A-Za-z0-9]+)?$")
SCAN_DIRS = ("payload", "setup/profiles")
SKIP_DIRS = {"__pycache__", ".git"}
FM_TRANSLATED = {"description", "title"}

FENCE_OPEN_RE = re.compile(r"^\s*(?P<fence>`{3,}|~{3,})(?P<info>.*)$")
HEADING_RE = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]|$)")
INLINE_RE = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)")
MARKER_RE = re.compile(r"agentic:(?:begin|end)")
PLACEHOLDER_RE = re.compile(r"\{\{agentic\.[A-Za-z0-9_]+\}\}")
FM_RE = re.compile(r"\A---[ \t]*\n(.*?)\n---[ \t]*(?:\n|\Z)", re.DOTALL)
CYRILLIC_RE = re.compile(r"[Ѐ-ӿ]")


@dataclass
class MdInfo:
    headings: list[int] = field(default_factory=list)
    fences: list[str] = field(default_factory=list)
    inline: list[str] = field(default_factory=list)
    markers: list[str] = field(default_factory=list)
    placeholders: Counter = field(default_factory=Counter)
    frontmatter: dict | None = None
    fm_error: str | None = None


def parse_frontmatter(block: str) -> tuple[dict | None, str | None]:
    try:
        data = yaml.safe_load(block)
        if isinstance(data, dict):
            return data, None
        return None, "frontmatter is not a mapping"
    except yaml.YAMLError:
        pass
    # Fallback for templates with Obsidian placeholders ({{title}}) that are not valid YAML:
    # top-level `key: raw value` lines, continuation lines appended to the previous key.
    data: dict = {}
    key = None
    for line in block.splitlines():
        m = re.match(r"^([A-Za-z_][\w-]*):(.*)$", line)
        if m:
            key = m.group(1)
            data[key] = m.group(2).strip()
        elif key is not None:
            data[key] += "\n" + line.rstrip()
    return data, None


def analyze_markdown(text: str) -> MdInfo:
    info = MdInfo()
    text = text.replace("\r\n", "\n")
    m = FM_RE.match(text)
    if m:
        info.frontmatter, info.fm_error = parse_frontmatter(m.group(1))
        text = text[m.end():]
    fence: tuple[str, int] | None = None
    for line in text.split("\n"):
        info.markers.extend(MARKER_RE.findall(line))
        info.placeholders.update(PLACEHOLDER_RE.findall(line))
        if fence is not None:
            stripped = line.strip()
            char, length = fence
            if stripped and set(stripped) == {char} and len(stripped) >= length:
                fence = None
            continue
        fm = FENCE_OPEN_RE.match(line)
        if fm and not (fm.group("fence")[0] == "`" and "`" in fm.group("info")):
            fence = (fm.group("fence")[0], len(fm.group("fence")))
            info.fences.append(fm.group("info").strip())
            continue
        hm = HEADING_RE.match(line)
        if hm:
            info.headings.append(len(hm.group(1)))
        info.inline.extend(m.group(2) for m in INLINE_RE.finditer(line))
    return info


def short(items, limit: int = 8) -> str:
    items = list(items)
    shown = ", ".join(repr(i) for i in items[:limit])
    return shown + (f", … (+{len(items) - limit})" if len(items) > limit else "")


def compare_markdown(ru_text: str, en_text: str) -> list[str]:
    ru, en = analyze_markdown(ru_text), analyze_markdown(en_text)
    problems = []
    if ru.headings != en.headings:
        idx = next((i for i, (a, b) in enumerate(zip(ru.headings, en.headings)) if a != b),
                   min(len(ru.headings), len(en.headings)))
        problems.append(f"heading levels differ: ru {len(ru.headings)} headings, en {len(en.headings)}; "
                        f"first difference at heading #{idx + 1} "
                        f"(ru {ru.headings[idx:idx + 1] or '-'} vs en {en.headings[idx:idx + 1] or '-'})")
    if ru.fences != en.fences:
        problems.append(f"fenced code blocks differ: ru {len(ru.fences)} [{short(ru.fences)}] vs "
                        f"en {len(en.fences)} [{short(en.fences)}]")
    if len(ru.inline) != len(en.inline):
        problems.append(f"number of inline code spans differs: ru {len(ru.inline)} vs en {len(en.inline)}")
    literal = Counter(s for s in ru.inline if not CYRILLIC_RE.search(s))
    missing = literal - Counter(en.inline)
    if missing:
        problems.append(f"inline code missing in en: {short(sorted(missing.elements()))}")
    if ru.markers != en.markers:
        problems.append(f"agentic markers differ: ru {ru.markers} vs en {en.markers}")
    if ru.placeholders != en.placeholders:
        problems.append(f"{{{{agentic.*}}}} placeholders differ: ru {dict(ru.placeholders)} vs "
                        f"en {dict(en.placeholders)}")
    for lang, info in (("ru", ru), ("en", en)):
        if info.fm_error:
            problems.append(f"{lang}: {info.fm_error}")
    if (ru.frontmatter is None) != (en.frontmatter is None):
        problems.append("frontmatter present in only one language")
    elif ru.frontmatter is not None and en.frontmatter is not None:
        rk, ek = set(ru.frontmatter), set(en.frontmatter)
        if rk != ek:
            problems.append(f"frontmatter keys differ: only ru {sorted(rk - ek)}, only en {sorted(ek - rk)}")
        for key in sorted(rk & ek - FM_TRANSLATED):
            if ru.frontmatter[key] != en.frontmatter[key]:
                problems.append(f"frontmatter value differs for '{key}': ru {ru.frontmatter[key]!r} "
                                f"vs en {en.frontmatter[key]!r}")
    return problems


def toml_diff(a, b, prefix: str = "") -> list[str]:
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for key in sorted(set(a) | set(b)):
            path = f"{prefix}.{key}" if prefix else key
            if key not in a or key not in b:
                out.append(f"{path} only in {'en' if key not in a else 'ru'}")
            else:
                out.extend(toml_diff(a[key], b[key], path))
        return out
    return [] if a == b else [f"{prefix or '<root>'}: ru {a!r} vs en {b!r}"]


def compare_toml(ru_text: str, en_text: str) -> list[str]:
    try:
        ru, en = tomllib.loads(ru_text), tomllib.loads(en_text)
    except tomllib.TOMLDecodeError as exc:
        return [f"invalid TOML: {exc}"]
    diffs = toml_diff(ru, en)
    return [f"TOML data differs: {'; '.join(diffs[:5])}" + (" …" if len(diffs) > 5 else "")] if diffs else []


def find_pairs(root: Path) -> tuple[list[tuple[Path, Path]], list[str]]:
    pairs: list[tuple[Path, Path]] = []
    problems: list[str] = []
    seen: set[Path] = set()

    def rel(p: Path) -> str:
        return p.relative_to(root).as_posix()

    for top in SCAN_DIRS:
        base = root / top
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or SKIP_DIRS & set(path.relative_to(root).parts):
                continue
            m = LANG_RE.match(path.name)
            if not m:
                continue
            ext = m.group("ext") or ""
            ru = path.with_name(f"{m.group('base')}.ru{ext}")
            en = path.with_name(f"{m.group('base')}.en{ext}")
            if ru in seen:
                continue
            seen.add(ru)
            if not ru.is_file():
                problems.append(f"{rel(en)}: missing Russian original {rel(ru)}")
            elif not en.is_file():
                problems.append(f"{rel(ru)}: missing translation {rel(en)}")
            else:
                pairs.append((ru, en))
    ru, en = root / "README.md", root / "README.en.md"
    if ru.is_file() and en.is_file():
        pairs.append((ru, en))
    else:
        for p in (ru, en):
            if not p.is_file():
                problems.append(f"{rel(p)}: missing (root README pair)")
    return pairs, problems


def check(root: Path) -> tuple[int, list[str]]:
    pairs, problems = find_pairs(root)
    for ru, en in pairs:
        label = f"{ru.relative_to(root).as_posix()} <-> {en.name}"
        try:
            ru_text, en_text = ru.read_text(encoding="utf-8"), en.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            problems.append(f"{label}: not UTF-8 text ({exc})")
            continue
        suffix = en.suffix.lower()
        if suffix == ".md":
            found = compare_markdown(ru_text, en_text)
        elif suffix == ".toml":
            found = compare_toml(ru_text, en_text)
        else:
            found = []
        problems.extend(f"{label}: {msg}" for msg in found)
    return len(pairs), problems


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="i18n_check", description="Check ru/en translation pairs.")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]),
                        help="template root (default: this template)")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    count, problems = check(root)
    for msg in problems:
        print(msg)
    print(f"i18n check: {count} pair(s) checked, {len(problems)} problem(s).")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
