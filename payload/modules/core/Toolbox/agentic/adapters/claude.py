"""Claude Code renderer: .claude/settings.json, .claude/agents/<name>.md, .mcp.json.

Skills are linked per skill by agents.py ([skills] mode = "link" in adapter.toml).
JSON allows no comments, so only the subagent files carry the "generated" note.
"""

from __future__ import annotations

from typing import Any

import yaml

from adapters import GENERATED_NOTE, Context, dump_json, hook_command, hooks_by_event, tier_value


def _settings(ctx: Context) -> dict[str, dict[str, Any]]:
    """Settings documents keyed by target path (sections may share one file)."""
    docs: dict[str, dict[str, Any]] = {}

    memory = ctx.section("memory")
    if memory.get("disable"):
        doc = docs.setdefault(memory["target"], {})
        doc["autoMemoryEnabled"] = False
        doc.setdefault("env", {})["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"

    permissions = ctx.section("permissions")
    if permissions.get("allow"):
        doc = docs.setdefault(permissions["target"], {})
        doc.setdefault("permissions", {})["allow"] = [str(x) for x in permissions["allow"]]

    hooks = ctx.section("hooks")
    grouped = hooks_by_event(ctx)
    if grouped:
        template = hooks["command"]
        native: dict[str, list] = {}
        for event, items in grouped.items():
            handlers = []
            for hook in items:
                handler: dict[str, Any] = {"type": "command",
                                           "command": hook_command(template, hook, ctx)}
                if hooks.get("timeout"):
                    handler["timeout"] = int(hooks["timeout"])
                handlers.append(handler)
            native[event] = [{"hooks": handlers}]
        docs.setdefault(hooks["target"], {})["hooks"] = native
    return docs


def _mcp(ctx: Context) -> dict[str, Any]:
    servers: dict[str, Any] = {}
    for server in ctx.mcp_servers:
        if server.transport == "stdio":
            entry: dict[str, Any] = {"type": "stdio", "command": server.command, "args": server.args}
            if server.env:
                entry["env"] = server.env
        else:
            entry = {"type": "http", "url": server.url}
            if server.headers:
                entry["headers"] = server.headers
        servers[server.name] = entry
    return {"mcpServers": servers}


def _subagent(ctx: Context, agent) -> str:
    meta: dict[str, Any] = {"name": agent.name, "description": agent.description}
    tools = tier_value(ctx, "subagents", "tools", agent.tools, "tools tier")
    if tools:
        meta["tools"] = tools
    model = tier_value(ctx, "subagents", "models", agent.model, "model tier")
    if model:
        meta["model"] = model
    front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, width=1_000_000)
    return f"---\n# {GENERATED_NOTE}\n{front}---\n\n{agent.prompt}"


def render(ctx: Context) -> dict[str, str]:
    files: dict[str, str] = {}
    for path, doc in _settings(ctx).items():
        files[path] = dump_json(doc)
    mcp_target = ctx.section("mcp").get("target")
    if mcp_target and ctx.mcp_servers:
        files[mcp_target] = dump_json(_mcp(ctx))
    target = ctx.section("subagents").get("target")
    if target:
        for agent in ctx.subagents:
            files[f"{target}/{agent.name}.md"] = _subagent(ctx, agent)
    return files
