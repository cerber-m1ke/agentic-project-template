"""tb obsidian — per-machine Obsidian config of the Knowledge/ vault (.obsidian/ is not in git).

Only the keys below are set; everything else in the user's config is preserved.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

import common

VAULT_CONFIG = f"{common.KNOWLEDGE_DIR}/.obsidian"
SETTINGS: dict[str, dict[str, Any]] = {
    # Markdown links with relative paths: the same links agents and `tb kb` understand.
    "app.json": {"useMarkdownLinks": True, "newLinkFormat": "relative", "alwaysUpdateLinks": True},
    # Core "Templates" plugin: note templates shared with `tb kb new`.
    "templates.json": {"folder": "_templates"},
}


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("obsidian", help="Obsidian vault config for Knowledge/",
                            description="Configure Knowledge/ as an Obsidian vault on this machine.")
    actions = parser.add_subparsers(dest="obsidian_action", metavar="<action>")
    actions.add_parser("setup", help=f"write {VAULT_CONFIG}/app.json and templates.json") \
        .set_defaults(func=cmd_setup)
    parser.set_defaults(func=lambda _args: (parser.print_help(), 0)[1])


def cmd_setup(_args: argparse.Namespace) -> int:
    return setup()


def setup() -> int:
    root = common.project_root()
    if not (root / common.KNOWLEDGE_DIR).is_dir():
        return common.fail(f"{common.KNOWLEDGE_DIR}/ not found — nothing to configure")
    config_dir = root / VAULT_CONFIG
    for name, wanted in SETTINGS.items():
        path = config_dir / name
        shown = f"{VAULT_CONFIG}/{name}"
        data: dict[str, Any] = {}
        if path.is_file():
            try:
                data = json.loads(common.read_text(path) or "{}")
            except (OSError, ValueError) as exc:
                return common.fail(f"cannot read {shown}: {exc} — fix or delete it, then rerun")
            if not isinstance(data, dict):
                return common.fail(f"{shown} is not a JSON object — fix or delete it, then rerun")
        if all(data.get(key) == value for key, value in wanted.items()):
            common.out(f"  ✓ {shown} up to date")
            continue
        existed = path.is_file()
        data.update(wanted)
        common.write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        common.out(f"  ✓ {shown} {'updated' if existed else 'written'}")
    common.out(f"  hint: open {common.KNOWLEDGE_DIR}/ as a vault in Obsidian and enable the core "
               'plugin "Templates" (Settings → Core plugins) to insert notes from _templates/.')
    return 0
