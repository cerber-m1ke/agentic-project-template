"""Codex CLI renderer: .codex/config.toml, .codex/hooks.json, .codex/agents/<name>.toml.

Codex reads AGENTS.md and .agents/skills natively, so nothing is linked.
The project .codex/ is honoured only for trusted projects; new hooks are approved in /hooks.
"""

from __future__ import annotations

from typing import Any

from adapters import GENERATED_NOTE, Context, dump_json, dump_toml, hook_command, hooks_by_event, tier_value


def _config(ctx: Context) -> dict[str, dict[str, Any]]:
    """config.toml documents keyed by target path (memory and MCP normally share one file)."""
    docs: dict[str, dict[str, Any]] = {}

    memory = ctx.section("memory")
    if memory.get("disable"):
        docs.setdefault(memory["target"], {}).setdefault("features", {})["memories"] = False

    mcp_target = ctx.section("mcp").get("target")
    if mcp_target and ctx.mcp_servers:
        servers: dict[str, Any] = {}
        for server in ctx.mcp_servers:
            if server.transport == "stdio":
                entry: dict[str, Any] = {"command": server.command, "args": server.args}
                if server.env:
                    entry["env"] = server.env
            else:
                entry = {"url": server.url}
                if server.headers:
                    entry["http_headers"] = server.headers
            servers[server.name] = entry
        docs.setdefault(mcp_target, {})["mcp_servers"] = servers
    return {path: dict(sorted(doc.items())) for path, doc in docs.items()}


def _hooks(ctx: Context) -> dict[str, Any] | None:
    hooks = ctx.section("hooks")
    grouped = hooks_by_event(ctx)
    if not grouped:
        return None
    native: dict[str, list] = {}
    for event, items in grouped.items():
        handlers = []
        for hook in items:
            handler: dict[str, Any] = {"type": "command",
                                       "command": hook_command(hooks["command"], hook, ctx)}
            if hooks.get("command_windows"):
                handler["commandWindows"] = hook_command(hooks["command_windows"], hook, ctx)
            if hooks.get("timeout"):
                handler["timeout"] = int(hooks["timeout"])
            handlers.append(handler)
        native[event] = [{"hooks": handlers}]
    # `description` is optional metadata in Codex hooks.json: the only place for the note.
    return {"description": GENERATED_NOTE, "hooks": native}


def _subagent(ctx: Context, agent) -> str:
    doc: dict[str, Any] = {"name": agent.name, "description": agent.description}
    effort = tier_value(ctx, "subagents", "reasoning_effort", agent.model, "model tier")
    if effort:
        doc["model_reasoning_effort"] = effort
    sandbox = tier_value(ctx, "subagents", "sandbox", agent.tools, "tools tier")
    if sandbox:
        doc["sandbox_mode"] = sandbox
    doc["developer_instructions"] = agent.prompt
    return dump_toml(doc, multiline=True)


def render(ctx: Context) -> dict[str, str]:
    files: dict[str, str] = {}
    for path, doc in _config(ctx).items():
        files[path] = dump_toml(doc)
    hooks = _hooks(ctx)
    if hooks:
        files[ctx.section("hooks")["target"]] = dump_json(hooks)
    target = ctx.section("subagents").get("target")
    if target:
        for agent in ctx.subagents:
            files[f"{target}/{agent.name}.toml"] = _subagent(ctx, agent)
    return files
