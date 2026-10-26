"""Claude Code renderer: CLAUDE.md (imports AGENTS.md), .claude/settings.json,
.claude/agents/<name>.md, .mcp.json.

Permissions: the template's [permissions].allow from adapter.toml plus the project's
.agents/permissions.toml — a [[command]] prefix becomes `Bash(<cmd>)` and `Bash(<cmd> *)`,
[claude] rules are copied as is.

Skills are linked per skill by agents.py ([skills] mode = "link" in adapter.toml).
JSON allows no comments, so only the subagent files carry the "generated" note.
"""

from __future__ import annotations

from typing import Any

import yaml

from adapters import (DECISIONS, GENERATED_NOTE, Context, dump_json, hook_command, hooks_by_event, matcher_groups,
                      tier_value)


def permission_rules(ctx: Context) -> dict[str, list[str]]:
    """`permissions` of settings.json: deny | ask | allow -> rules, without duplicates."""
    rules: dict[str, list[str]] = {d: [] for d in DECISIONS}
    rules["allow"] += [str(x) for x in ctx.section("permissions").get("allow", [])]
    for rule in ctx.permissions.commands:
        # Plain join: Claude matches the rule text literally, shell quoting would break it
        # (`rm -rf '~'`). The loader rejects tokens that need quoting or contain `*`.
        command = " ".join(rule.prefix)
        rules[rule.decision] += [f"Bash({command})", f"Bash({command} *)"]
    for decision, raw in ctx.permissions.claude.items():
        rules[decision] += raw
    return {d: list(dict.fromkeys(items)) for d, items in rules.items() if items}


def _settings(ctx: Context) -> dict[str, dict[str, Any]]:
    """Settings documents keyed by target path (sections may share one file)."""
    docs: dict[str, dict[str, Any]] = {}

    memory = ctx.section("memory")
    if memory.get("disable"):
        doc = docs.setdefault(memory["target"], {})
        doc["autoMemoryEnabled"] = False
        doc.setdefault("env", {})["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"

    permissions = ctx.section("permissions")
    rules = permission_rules(ctx)
    if rules and permissions.get("target"):
        docs.setdefault(permissions["target"], {})["permissions"] = rules
    elif rules and (ctx.permissions.commands or ctx.permissions.claude):
        ctx.warnings.append("adapter.toml has no [permissions] target; .agents/permissions.toml skipped")

    hooks = ctx.section("hooks")
    grouped = hooks_by_event(ctx)
    if grouped:
        template = hooks["command"]
        native: dict[str, list] = {}
        for event, items in grouped.items():
            native[event] = []
            for matcher, group in matcher_groups(ctx, items):
                handlers = []
                for hook in group:
                    handler: dict[str, Any] = {"type": "command",
                                               "command": hook_command(template, hook, ctx)}
                    if hooks.get("timeout"):
                        handler["timeout"] = int(hooks["timeout"])
                    handlers.append(handler)
                native[event].append({"matcher": matcher, "hooks": handlers} if matcher else {"hooks": handlers})
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


def _instructions(ctx: Context) -> tuple[str, str] | None:
    section = ctx.section("instructions")
    if not section.get("target") or not section.get("import"):
        return None
    return str(section["target"]), f"<!-- {GENERATED_NOTE} -->\n@{section['import']}\n"


def render(ctx: Context) -> dict[str, str]:
    files: dict[str, str] = {}
    instructions = _instructions(ctx)
    if instructions:
        files[instructions[0]] = instructions[1]
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
