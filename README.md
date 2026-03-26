# SwarmCity

**Minimal, git-native, markdown-first agent orchestration for multi-repo organizations.**

SwarmCity lets human developers and AI agents (Claude Code, Windsurf, Cursor, Gemini CLI,
OpenCode, and others) coordinate work across multiple repositories without any external
services, databases, or daemons. All coordination state lives in `.swarm/` directories
as plain markdown files. Git is the only database.

---

## The Problem

Modern software teams use multiple AI coding agents simultaneously across different
platforms. Without coordination:
- Two agents work on the same task simultaneously
- Context is lost when chat history is compacted
- Non-obvious decisions (why approach A over B) disappear forever
- No agent knows what the previous agent did or decided

Existing solutions (Jira, Linear, GitHub Issues) require web UIs and API credentials.
Database-backed tools add binary files and server processes to your repo.

**SwarmCity takes a different approach: everything is a markdown file any agent on any
platform can read and write directly.**

---

## How It Works

### The `.swarm/` Directory

Every repository gets a `.swarm/` directory with five files:

| File | Role |
|------|------|
| `BOOTSTRAP.md` | Universal agent protocol — every agent reads this first |
| `context.md` | What this project is, its constraints, its architecture |
| `state.md` | Current focus, active items, blockers, handoff note |
| `queue.md` | Work items with claim stamps |
| `memory.md` | Non-obvious decisions and rationale (append-only) |

### The Pheromone Trail

Inspired by stigmergy in swarm robotics: agents leave state traces (`state.md` updates)
that guide successor agents without direct communication. The next agent reads `state.md`
first — it tells you exactly where things stand in one glance.

### The Claim Pattern

Work items use inline stamps for optimistic concurrency — no lock server needed:

```markdown
## Active
- [>] [CLD-042] [CLAIMED · claude-code · 2026-03-26T14:30Z] Fix Redis timeout
      priority: high | project: cloud-stability

## Pending
- [ ] [CLD-043] [OPEN] Add request ID tracing to all services
      priority: medium | project: observability

## Done
- [x] [CLD-041] [DONE · 2026-03-25T16:00Z] Update auth health check path
      project: cloud-stability
```

### Hierarchical Coordination

```
Organization (your-company/)       ← cross-repo initiatives
  .swarm/
├── Division (service-a/)          ← single-repo work
│     .swarm/
└── Division (service-b/)
      .swarm/
```

Work items use level-prefixed IDs: `ORG-001`, `CLD-042`, `FW-017`. Cross-division items
live at org level with `refs:` pointers in each affected division's queue.

---

## Quick Start

```bash
# Install the CLI
pip install -e cli/

# Initialize in your repo
cd your-repo
swarm init

# See current state
swarm status

# Claim a work item before starting
swarm claim CLD-001

# Work... then mark done
swarm done CLD-001 --note "Implemented JWT refresh via rotating secret"

# Generate a handoff for the next session
swarm handoff
```

---

## CLI Reference

```
swarm init          Initialize .swarm/ in current directory
swarm status        Show state and next available items
swarm claim <id>    Claim a work item (updates queue.md + state.md atomically)
swarm done <id>     Mark item done (updates queue.md + state.md)
swarm add "<desc>"  Add a new work item (auto-assigns ID)
swarm partial <id>  Mark partially done — safe for re-claim by next agent
swarm block <id>    Mark blocked with reason
swarm audit         Check for drift: stale claims, stale state.md
swarm handoff       Generate a handoff doc for the next session
swarm sync          Refresh org state snapshot from all division state files
```

---

## Platform Setup

`swarm init` creates shim files automatically. Each shim is a one-liner that points
the platform at `.swarm/BOOTSTRAP.md`. When the protocol changes, only `BOOTSTRAP.md`
needs updating — all platforms update automatically.

**Claude Code** (`CLAUDE.md`):
```markdown
Before starting any work, read @.swarm/BOOTSTRAP.md and follow the protocol exactly.
Active context: @.swarm/context.md | State: @.swarm/state.md | Queue: @.swarm/queue.md
```

**Windsurf** (`.windsurfrules`):
```
Before starting any task, read .swarm/BOOTSTRAP.md and follow its protocol.
Do not begin work without claiming an item in .swarm/queue.md.
```

**Cursor** (`.cursorrules`):
```
Always begin every session by reading .swarm/BOOTSTRAP.md.
Follow the On Start, During Work, and On Stop sections exactly.
```

**Gemini CLI / OpenCode**: append to system prompt or rules file:
```
Read .swarm/BOOTSTRAP.md before starting any task and follow the SwarmCity protocol.
```

Full templates in [`docs/PLATFORM_SETUP.md`](docs/PLATFORM_SETUP.md).

---

## MCP Server

The MCP server exposes all coordination operations as structured tools for agent
platforms that support the Model Context Protocol.

```bash
pip install -e mcp/
```

Configure in Claude Code (`~/.claude/settings.json`):

```json
{
  "mcpServers": {
    "swarm-city": {
      "command": "python",
      "args": ["-m", "swarm_city_mcp"],
      "env": { "SWARM_ROOT": "/path/to/your/org-folder" }
    }
  }
}
```

Available tools: `swarm_bootstrap`, `swarm_context`, `swarm_state`, `swarm_queue`,
`swarm_claim`, `swarm_done`, `swarm_add`, `swarm_append_memory`, `swarm_audit`,
`swarm_handoff`.

---

## Git Topology

Make your organization folder a thin git repo tracking only `.swarm/`:

```bash
cd your-org-folder/
git init
cat > .gitignore << 'EOF'
*
!.swarm/
!.swarm/**
!.gitignore
EOF
git add . && git commit -m "chore: initialize SwarmCity coordination layer"
```

Division repos stay independent — no submodules needed.

---

## CI/CD Drift Check

A GitHub Actions workflow calls an LLM (Bedrock, OpenAI, or Anthropic API) to verify
that `.swarm/state.md` and `queue.md` accurately reflect recent code changes, posting
a PR comment if drift is detected.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) section 10 for the full workflow spec.

---

## Project Structure

```
swarm-city/
├── README.md                        # This file
├── cli/                             # The `swarm` CLI
│   ├── pyproject.toml
│   └── src/swarm_city/
│       ├── models.py                # Data models (WorkItem, SwarmPaths, etc.)
│       ├── operations.py            # File read/write operations
│       └── cli.py                   # Click CLI commands
├── mcp/                             # The SwarmCity MCP server
│   ├── pyproject.toml
│   └── src/swarm_city_mcp/
│       └── server.py                # MCP server (swarm_* tools)
└── docs/
    ├── ARCHITECTURE.md              # Full architecture + implementation phases
    └── PLATFORM_SETUP.md            # Agent platform shim templates
```

---

## Relationship to Gastown

Gastown is the conceptual architecture for multi-agent orchestration — the vision of
multiple AI agents and human developers working asynchronously with stigmergic
coordination. SwarmCity is the minimal reference implementation: no servers, no
binaries, no proprietary sync, just markdown and git.

---

## License

MIT
