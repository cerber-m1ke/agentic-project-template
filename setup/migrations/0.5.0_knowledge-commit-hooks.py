"""0.5.0: hooks of the Knowledge commit guard in the project-owned .agents/hooks/hooks.toml.

kb-track (after-tool, edit tools) remembers the Knowledge files a session edits; kb-uncommitted (stop)
asks the agent once to commit what it left uncommitted. A hook the file already names is left alone;
a project without hooks.toml chose to have no hooks and is not touched.
"""

from __future__ import annotations

import re
from pathlib import Path

HOOKS = {
    "kb-track": '''[[hook]]
name = "kb-track"
event = "after-tool"
tools = "edit"
description = "Remember the Knowledge files this session edits (Runtime/sessions/)."
''',
    "kb-uncommitted": '''[[hook]]
name = "kb-uncommitted"
event = "stop"
description = "Ask the agent once to commit Knowledge files it edited and left uncommitted."
''',
}


def migrate(root: Path) -> None:
    path = root / ".agents" / "hooks" / "hooks.toml"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    missing = [block for name, block in HOOKS.items()
               if not re.search(rf'^\s*name\s*=\s*["\']{re.escape(name)}["\']', text, re.MULTILINE)]
    if not missing:
        return
    text = text.rstrip("\n") + "\n" if text.strip() else ""
    for block in missing:
        text += ("\n" if text else "") + block
    path.write_text(text, encoding="utf-8", newline="\n")
