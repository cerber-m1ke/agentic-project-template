"""Codex CLI renderer: .codex/config.toml, .codex/hooks.json, .codex/agents/<name>.toml,
.codex/rules/project.rules.

Codex reads AGENTS.md and .agents/skills natively, so nothing is linked.
The project .codex/ is honoured only for trusted projects; new hooks are approved in /hooks.
Command rules of .agents/permissions.toml become Starlark `prefix_rule(...)` calls; its [claude]
section is Claude Code only and is skipped with a warning.
"""

from __future__ import annotations

import json
from typing import Any

from adapters import (GENERATED_NOTE, PERMISSIONS_FILE, Context, dump_json, dump_toml, hook_command,
                      hooks_by_event, tier_value)


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


# Canonical decision -> Codex execpolicy decision.
RULE_DECISIONS = {"deny": "forbidden", "ask": "prompt", "allow": "allow"}


def _starlark(value: str) -> str:
    """A Starlark string literal (JSON escapes are valid Starlark)."""
    return json.dumps(value, ensure_ascii=False)


def rules(ctx: Context) -> str | None:
    """.codex/rules/project.rules: one prefix_rule per [[command]]; None if there are none."""
    skipped = sum(len(items) for items in ctx.permissions.claude.values())
    if skipped:
        ctx.notes.append(f"{PERMISSIONS_FILE}: [claude] has {skipped} Claude Code-only rule(s), not "
                         "applied by codex (use [[command]] for rules every agent applies)")
    if not ctx.permissions.commands:
        return None
    blocks = []
    for rule in ctx.permissions.commands:
        lines = ["prefix_rule(",
                 f"    pattern = [{', '.join(_starlark(x) for x in rule.prefix)}],",
                 f"    decision = {_starlark(RULE_DECISIONS[rule.decision])},"]
        if rule.reason:
            lines.append(f"    justification = {_starlark(rule.reason)},")
        blocks.append("\n".join(lines + [")"]))
    return (f"# {GENERATED_NOTE}\n# Source: {PERMISSIONS_FILE}. Check: codex execpolicy check "
            "--rules <this file> -- <command>\n\n" + "\n\n".join(blocks) + "\n")


def render(ctx: Context) -> dict[str, str]:
    files: dict[str, str] = {}
    target = ctx.section("permissions").get("target")
    if target:
        content = rules(ctx)
        if content:
            files[str(target)] = content
    elif ctx.permissions.commands:
        ctx.warnings.append("adapter.toml has no [permissions] target; .agents/permissions.toml skipped")
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
