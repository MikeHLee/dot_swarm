"""SwarmCity MCP Server.

Exposes .swarm/ directory operations as MCP tools. Agents on any MCP-compatible
platform (Claude Code, Windsurf, Cursor, etc.) can call these tools to read and
write coordination state without manually editing markdown files.

Transport: stdio (default) — suitable for local MCP server configs.

Configure in Claude Code (~/.claude/settings.json):
    {
      "mcpServers": {
        "swarm-city": {
          "command": "python",
          "args": ["-m", "swarm_city_mcp"],
          "env": { "SWARM_ROOT": "/path/to/oasis-x" }
        }
      }
    }
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import mcp.server.stdio
import mcp.types as types
from mcp.server import Server

from swarm_city.models import Priority, SwarmPaths
from swarm_city.operations import (
    add_item,
    append_memory,
    audit,
    claim_item,
    done_item,
    read_queue,
    read_state,
    write_state,
)

server = Server("swarm-city")

# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def _resolve_paths(path: str = ".") -> SwarmPaths:
    """Find .swarm/ starting from the given path or SWARM_ROOT env var."""
    root = os.environ.get("SWARM_ROOT", ".")
    start = path if path != "." else root
    paths = SwarmPaths.find(start)
    if paths is None:
        raise ValueError(
            f"No .swarm/ directory found starting from {start}. "
            "Run 'swarm init' to initialize."
        )
    return paths


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="swarm_bootstrap",
            description=(
                "Read BOOTSTRAP.md — the universal agent protocol. Call this first "
                "in any session to get the current coordination protocol."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Working directory (default: SWARM_ROOT)"}
                },
            },
        ),
        types.Tool(
            name="swarm_context",
            description="Read context.md — the stable charter for this division or org.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Working directory"}
                },
            },
        ),
        types.Tool(
            name="swarm_state",
            description=(
                "Read or update state.md — the pheromone trail. "
                "Pass write=true with fields dict to update specific fields."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "write": {"type": "boolean", "description": "True to update state"},
                    "fields": {
                        "type": "object",
                        "description": (
                            "Fields to update. Keys: current_focus, active_items, "
                            "blockers, ready_for_pickup, handoff_note"
                        ),
                    },
                },
            },
        ),
        types.Tool(
            name="swarm_queue",
            description="Read work items from queue.md with optional filters.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "section": {
                        "type": "string",
                        "enum": ["active", "pending", "done", "all"],
                        "description": "Which section to read (default: all)",
                    },
                    "priority": {"type": "string", "description": "Filter by priority"},
                    "project": {"type": "string", "description": "Filter by project name"},
                },
            },
        ),
        types.Tool(
            name="swarm_claim",
            description="Atomically claim an OPEN work item. Updates queue.md and state.md.",
            inputSchema={
                "type": "object",
                "required": ["id", "agent_id"],
                "properties": {
                    "id": {"type": "string", "description": "Item ID e.g. ORG-002"},
                    "agent_id": {"type": "string", "description": "Your agent ID e.g. claude-code"},
                    "path": {"type": "string"},
                },
            },
        ),
        types.Tool(
            name="swarm_done",
            description="Mark a claimed work item as done. Updates queue.md and state.md.",
            inputSchema={
                "type": "object",
                "required": ["id", "agent_id"],
                "properties": {
                    "id": {"type": "string"},
                    "agent_id": {"type": "string"},
                    "note": {"type": "string", "description": "Brief completion note"},
                    "next_focus": {"type": "string", "description": "What to set as next focus in state.md"},
                    "path": {"type": "string"},
                },
            },
        ),
        types.Tool(
            name="swarm_add",
            description="Add a new OPEN work item to queue.md with an auto-assigned ID.",
            inputSchema={
                "type": "object",
                "required": ["description"],
                "properties": {
                    "description": {"type": "string"},
                    "priority": {
                        "type": "string",
                        "enum": ["critical", "high", "medium", "low"],
                        "default": "medium",
                    },
                    "project": {"type": "string", "default": "misc"},
                    "notes": {"type": "string"},
                    "refs": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Reference pointers e.g. ['oasis-x/.swarm/queue.md#ORG-001']",
                    },
                    "depends": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Item IDs this depends on",
                    },
                    "division_code": {"type": "string", "description": "Override division code for ID"},
                    "path": {"type": "string"},
                },
            },
        ),
        types.Tool(
            name="swarm_append_memory",
            description="Append a decision entry to memory.md. Use for non-obvious decisions.",
            inputSchema={
                "type": "object",
                "required": ["topic", "decision", "why"],
                "properties": {
                    "topic": {"type": "string", "description": "Short topic label"},
                    "decision": {"type": "string"},
                    "why": {"type": "string"},
                    "tradeoff": {"type": "string", "description": "Trade-off accepted (optional)"},
                    "agent_id": {"type": "string"},
                    "path": {"type": "string"},
                },
            },
        ),
        types.Tool(
            name="swarm_audit",
            description="Check for drift: stale claims, blocked items, state.md staleness.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "since_hours": {
                        "type": "integer",
                        "description": "Stale threshold in hours (default: 48)",
                        "default": 48,
                    },
                },
            },
        ),
        types.Tool(
            name="swarm_handoff",
            description="Generate a handoff document for the next agent or developer.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                },
            },
        ),
    ]


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    path = arguments.get("path", ".")

    try:
        if name == "swarm_bootstrap":
            paths = _resolve_paths(path)
            content = paths.bootstrap.read_text() if paths.bootstrap.exists() else "(no BOOTSTRAP.md found)"
            return [types.TextContent(type="text", text=content)]

        elif name == "swarm_context":
            paths = _resolve_paths(path)
            content = paths.context.read_text() if paths.context.exists() else "(no context.md found)"
            return [types.TextContent(type="text", text=content)]

        elif name == "swarm_state":
            paths = _resolve_paths(path)
            if arguments.get("write") and arguments.get("fields"):
                fields = arguments["fields"]
                # Map camelCase / snake_case keys to display keys
                key_map = {
                    "current_focus": "Current focus",
                    "active_items": "Active items",
                    "blockers": "Blockers",
                    "ready_for_pickup": "Ready for pickup",
                    "handoff_note": "Handoff note",
                    "last_agent": "last_agent",
                }
                mapped = {key_map.get(k, k): v for k, v in fields.items()}
                write_state(paths, mapped)
            content = paths.state.read_text() if paths.state.exists() else "(no state.md found)"
            return [types.TextContent(type="text", text=content)]

        elif name == "swarm_queue":
            paths = _resolve_paths(path)
            active, pending, done = read_queue(paths)
            section = arguments.get("section", "all")
            items = []
            if section in ("active", "all"):
                items.extend(active)
            if section in ("pending", "all"):
                items.extend(pending)
            if section in ("done", "all"):
                items.extend(done)
            # Apply filters
            if prio := arguments.get("priority"):
                items = [i for i in items if i.priority.value == prio]
            if proj := arguments.get("project"):
                items = [i for i in items if i.project == proj]
            result = [
                {
                    "id": i.id,
                    "state": i.state.value,
                    "description": i.description,
                    "priority": i.priority.value,
                    "project": i.project,
                    "claimed_by": i.claimed_by,
                    "claimed_at": i.claimed_at.isoformat() if i.claimed_at else None,
                    "refs": i.refs,
                    "depends": i.depends,
                }
                for i in items
            ]
            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "swarm_claim":
            paths = _resolve_paths(path)
            item = claim_item(paths, arguments["id"], arguments["agent_id"])
            write_state(paths, {
                "Current focus": item.description[:100],
                "Active items": item.id,
                "last_agent": arguments["agent_id"],
            })
            return [types.TextContent(type="text", text=f"Claimed [{item.id}]: {item.description}")]

        elif name == "swarm_done":
            paths = _resolve_paths(path)
            item = done_item(
                paths, arguments["id"], arguments["agent_id"],
                arguments.get("note", "")
            )
            updates: dict = {"last_agent": arguments["agent_id"]}
            if nf := arguments.get("next_focus"):
                updates["Current focus"] = nf
                updates["Handoff note"] = nf
            write_state(paths, updates)
            return [types.TextContent(type="text", text=f"Done [{item.id}]: {item.description}")]

        elif name == "swarm_add":
            paths = _resolve_paths(path)
            from swarm_city.operations import _division_code_from_paths  # local import
            code = arguments.get("division_code") or _division_code_from_paths(paths)  # type: ignore
            item = add_item(
                paths=paths,
                description=arguments["description"],
                division_code=code,
                priority=Priority(arguments.get("priority", "medium")),
                project=arguments.get("project", "misc"),
                notes=arguments.get("notes", ""),
                refs=arguments.get("refs"),
                depends=arguments.get("depends"),
            )
            return [types.TextContent(
                type="text",
                text=f"Added [{item.id}] ({item.priority.value}): {item.description}"
            )]

        elif name == "swarm_append_memory":
            paths = _resolve_paths(path)
            entry = append_memory(
                paths=paths,
                topic=arguments["topic"],
                decision=arguments["decision"],
                why=arguments["why"],
                tradeoff=arguments.get("tradeoff", ""),
                agent_id=arguments.get("agent_id", "unknown"),
            )
            return [types.TextContent(type="text", text=f"Appended to memory.md:\n{entry}")]

        elif name == "swarm_audit":
            paths = _resolve_paths(path)
            findings = audit(paths, stale_hours=arguments.get("since_hours", 48))
            if not findings:
                return [types.TextContent(type="text", text="No drift detected.")]
            return [types.TextContent(type="text", text=json.dumps(findings, indent=2))]

        elif name == "swarm_handoff":
            paths = _resolve_paths(path)
            state = read_state(paths)
            active, pending, _ = read_queue(paths)
            from datetime import datetime
            name_str = paths.root.parent.name
            now = datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ")
            lines = [
                f"# SwarmCity Handoff — {name_str} — {now}", "",
                "## Current State",
                f"Focus: {state.get('Current focus', '(not set)')}",
            ]
            if active:
                lines.append(f"Active: {', '.join(i.id for i in active)}")
            if state.get("Handoff note"):
                lines.append(f"\n{state['Handoff note']}")
            lines += ["", "## Ready for Pickup"]
            for item in pending[:5]:
                lines.append(f"- {item.id}: {item.description} [{item.priority.value.upper()}]")
            lines += [
                "", "## Context",
                f"@{paths.root}/BOOTSTRAP.md",
                f"@{paths.root}/context.md",
            ]
            return [types.TextContent(type="text", text="\n".join(lines))]

        else:
            return [types.TextContent(type="text", text=f"Unknown tool: {name}")]

    except Exception as e:
        return [types.TextContent(type="text", text=f"Error: {e}")]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    import asyncio
    asyncio.run(mcp.server.stdio.run(server))


if __name__ == "__main__":
    main()
