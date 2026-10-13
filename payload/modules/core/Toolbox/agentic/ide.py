"""tb ide — keep IDEs from indexing Resources/ and Runtime/ (per machine; .idea/ and .vscode/ are not in git).

Resources/ holds whole repositories of their own, and Runtime/ holds uv, Python and caches: indexing
them slows the IDE down and floods search with duplicates. The folders stay visible and editable.

- JetBrains: `excludeFolder` in the module (.iml) whose content root is the project root; without
  .idea/ a minimal project (modules.xml + <name>.iml) is written.
- VS Code: `search.exclude` and `files.watcherExclude` in .vscode/settings.json. VS Code search also
  reads .ignore, where agents need Resources/ visible, so the exclusion has to be explicit.

Only these entries are added; everything else in the user's config is preserved.
"""

from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import common

EXCLUDED = ("Resources", "Runtime")
IDEA_DIR = ".idea"
VSCODE_SETTINGS = ".vscode/settings.json"
VSCODE_KEYS = ("search.exclude", "files.watcherExclude")
ROOT_URLS = ("file://$PROJECT_DIR$", "file://$MODULE_DIR$")

MODULES_XML = """<?xml version="1.0" encoding="UTF-8"?>
<project version="4">
  <component name="ProjectModuleManager">
    <modules>
      <module fileurl="file://$PROJECT_DIR$/.idea/{name}.iml" filepath="$PROJECT_DIR$/.idea/{name}.iml" />
    </modules>
  </component>
</project>
"""
MODULE_IML = """<?xml version="1.0" encoding="UTF-8"?>
<module type="WEB_MODULE" version="4">
  <component name="NewModuleRootManager">
    <content url="file://$MODULE_DIR$">
{excludes}    </content>
    <orderEntry type="inheritedJdk" />
    <orderEntry type="sourceFolder" forTests="false" />
  </component>
</module>
"""


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("ide", help="IDE settings: do not index Resources/ and Runtime/",
                            description="Exclude Resources/ and Runtime/ from IDE indexing on this machine.")
    actions = parser.add_subparsers(dest="ide_action", metavar="<action>")
    actions.add_parser("setup", help=f"JetBrains ({IDEA_DIR}/*.iml) and VS Code ({VSCODE_SETTINGS})") \
        .set_defaults(func=lambda _args: setup())
    parser.set_defaults(func=lambda _args: (parser.print_help(), 0)[1])


def setup() -> int:
    root = common.project_root()
    ok = _jetbrains(root)
    ok = _vscode(root) and ok
    return 0 if ok else 1


# --- JetBrains --------------------------------------------------------------------------------------------

def _exclude_lines(base: str, indent: str) -> str:
    return "".join(f'{indent}<excludeFolder url="{base}/{name}" />\n' for name in EXCLUDED)


def _module_files(root: Path) -> list[Path]:
    """Module files from .idea/modules.xml, existing ones only."""
    tree = ET.parse(root / IDEA_DIR / "modules.xml")
    paths = []
    for module in tree.iter("module"):
        raw = module.get("filepath") or ""
        path = Path(raw.replace("$PROJECT_DIR$", str(root)))
        if raw and path.is_file():
            paths.append(path)
    return paths


def _root_content_url(iml: Path, root: Path) -> str | None:
    """URL of the <content> entry that is the project root, as written in the file."""
    module_dir = iml.parent
    for content in ET.parse(iml).iter("content"):
        url = (content.get("url") or "").rstrip("/")
        if url == "file://$PROJECT_DIR$":
            return url
        if url == "file://$MODULE_DIR$" and module_dir.resolve() in (root.resolve(), (root / IDEA_DIR).resolve()):
            return url
    return None


def _exclude_in_iml(iml: Path, root: Path) -> str:
    """Add missing excludeFolder entries; returns 'updated', 'up to date' or 'no root content'."""
    url = _root_content_url(iml, root)
    if url is None:
        return "no root content"
    text = common.read_text(iml)
    content_re = re.compile(r'(?P<indent>[ \t]*)<content\s+url="' + re.escape(url) + r'/?"\s*(?P<close>/?)>')
    m = content_re.search(text)
    if m is None:
        return "no root content"
    indent = m.group("indent") or "    "
    inner = indent + "  "
    if m.group("close"):  # <content url="…" />
        block = f'{indent}<content url="{url}">\n{_exclude_lines(url, inner)}{indent}</content>'
        text = text[:m.start()] + block + text[m.end():]
    else:
        end = text.find("</content>", m.end())
        if end < 0:
            return "no root content"
        body = text[m.end():end]
        missing = [n for n in EXCLUDED if f'url="{url}/{n}"' not in body and f'url="{url}/{n}/"' not in body]
        if not missing:
            return "up to date"
        line_start = text.rfind("\n", 0, end) + 1
        if text[line_start:end].strip():  # `</content>` shares a line with other markup
            line_start = end
        insert = "".join(f'{inner}<excludeFolder url="{url}/{n}" />\n' for n in missing)
        if line_start == end:
            insert = "\n" + insert + indent
        text = text[:line_start] + insert + text[line_start:]
    common.write_text(iml, text)
    return "updated"


def _jetbrains(root: Path) -> bool:
    idea = root / IDEA_DIR
    if not (idea / "modules.xml").is_file():
        if idea.is_dir() and any(idea.glob("*.iml")):
            common.out(f"  ! {IDEA_DIR}/modules.xml missing: open the project in the IDE once, then rerun")
            return True
        name = re.sub(r"[^A-Za-z0-9._-]+", "-", root.name).strip("-.") or "project"
        common.write_text(idea / "modules.xml", MODULES_XML.format(name=name))
        common.write_text(idea / f"{name}.iml",
                          MODULE_IML.format(excludes=_exclude_lines("file://$MODULE_DIR$", " " * 6)))
        common.out(f"  ✓ {IDEA_DIR}/{name}.iml written (JetBrains: {', '.join(EXCLUDED)} excluded)")
        return True
    try:
        modules = _module_files(root)
    except (OSError, ET.ParseError) as exc:
        common.fail(f"cannot read {IDEA_DIR}/modules.xml: {exc}")
        return False
    found = False
    for iml in modules:
        shown = common.rel(iml)
        try:
            result = _exclude_in_iml(iml, root)
        except (OSError, ET.ParseError) as exc:
            common.fail(f"cannot update {shown}: {exc}")
            return False
        if result == "no root content":
            continue
        found = True
        common.out(f"  ✓ {shown} {result}")
    if not found:
        common.out(f"  ! no JetBrains module has the project root as content root — exclude "
                   f"{', '.join(EXCLUDED)} by hand (right-click → Mark Directory as → Excluded)")
    return True


# --- VS Code ----------------------------------------------------------------------------------------------

def _vscode(root: Path) -> bool:
    path = root / VSCODE_SETTINGS
    data: dict[str, Any] = {}
    if path.is_file():
        try:
            data = json.loads(common.read_text(path) or "{}")
        except (OSError, ValueError) as exc:
            # settings.json may be JSONC (comments, trailing commas): do not rewrite it blindly.
            globs = ", ".join(f'"{name}/**": true' for name in EXCLUDED)
            common.out(f"  ! cannot parse {VSCODE_SETTINGS} ({exc}); add by hand: "
                       + ", ".join(f'"{key}": {{{globs}}}' for key in VSCODE_KEYS))
            return True
        if not isinstance(data, dict):
            return not common.fail(f"{VSCODE_SETTINGS} is not a JSON object — fix or delete it, then rerun")
    wanted = {f"{name}/**": True for name in EXCLUDED}
    changed = False
    for key in VSCODE_KEYS:
        current = data.get(key)
        if not isinstance(current, dict):
            current = {}
        if all(current.get(glob) is True for glob in wanted):
            continue
        data[key] = {**current, **wanted}
        changed = True
    if not changed:
        common.out(f"  ✓ {VSCODE_SETTINGS} up to date")
        return True
    existed = path.is_file()
    common.write_text(path, json.dumps(data, ensure_ascii=False, indent=4) + "\n")
    common.out(f"  ✓ {VSCODE_SETTINGS} {'updated' if existed else 'written'} (VS Code: search and watcher exclude)")
    return True
