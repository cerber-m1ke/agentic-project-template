"""0.2.0: gotcha and example notes have no `status` any more.

Removes the line `status: active` from the frontmatter of notes in Knowledge/Gotchas/ and
Knowledge/Examples/ and from the note templates `Knowledge/_templates/gotcha.md` and `example.md`.
Retired statuses (`resolved`, `outdated`, and `superseded`, `dropped` of other types) are left as is:
such notes are obsolete, and only the human decides to delete them (`tb kb lint` and `tb kb stale`
list them).
"""

from __future__ import annotations

import re
from pathlib import Path

FOLDERS = ("Gotchas", "Examples")
TEMPLATES = ("gotcha.md", "example.md")
STATUS_RE = re.compile(r"""^status:[ \t]*(?:active|"active"|'active')[ \t]*(?:#.*)?$""")


def _strip_status(path: Path) -> None:
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    lines = text.split("\n")
    if not lines or lines[0].rstrip() != "---":
        return
    for end in range(1, len(lines)):
        if lines[end].rstrip() == "---":
            break
    else:
        return
    kept = [line for i, line in enumerate(lines) if not (0 < i < end and STATUS_RE.match(line))]
    if len(kept) != len(lines):
        path.write_text("\n".join(kept), encoding="utf-8", newline="\n")


def migrate(root: Path) -> None:
    knowledge = root / "Knowledge"
    if not knowledge.is_dir():
        return
    for folder in FOLDERS:
        base = knowledge / folder
        if base.is_dir():
            for path in sorted(base.rglob("*.md")):
                if path.name != "README.md":
                    _strip_status(path)
    for name in TEMPLATES:
        path = knowledge / "_templates" / name
        if path.is_file():
            _strip_status(path)
