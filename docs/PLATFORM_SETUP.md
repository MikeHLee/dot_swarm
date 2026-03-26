# SwarmCity Platform Setup

Copy-paste shim templates for each agent platform. Each shim is a thin one-liner
(or small config block) that points agents at `.swarm/BOOTSTRAP.md`. The protocol
itself lives in BOOTSTRAP.md — never in the shim.

---

## Claude Code — CLAUDE.md

Place in the root of any division repo or in oasis-x/ for org-level sessions.

```markdown
Before starting any work, read @.swarm/BOOTSTRAP.md and follow the protocol exactly.
Active context: @.swarm/context.md | State: @.swarm/state.md | Queue: @.swarm/queue.md
```

For the org root (oasis-x/) where CLAUDE.md may contain other content, append:

```markdown
## SwarmCity Protocol
See @.swarm/BOOTSTRAP.md — follow the On Start / During Work / On Stop protocol
before beginning any task.
```

---

## Windsurf — .windsurfrules

Place at repo root. Windsurf reads this file automatically.

```
Before starting any task, read the file .swarm/BOOTSTRAP.md and follow its protocol.
Do not begin work without:
1. Claiming an item in .swarm/queue.md
2. Updating .swarm/state.md with your current focus
Always update state.md and queue.md when finishing a session.
```

---

## Cursor — .cursorrules

Place at repo root.

```
Always begin every session by reading .swarm/BOOTSTRAP.md.
Follow the "On Start", "During Work", and "On Stop" sections exactly.
Do not start implementing without first claiming an item in .swarm/queue.md.
```

---

## Gemini CLI

Gemini CLI supports a `~/.gemini/system_prompt` file or per-project config.

Option A — Global (affects all Gemini CLI sessions):
Append to `~/.gemini/system_prompt`:
```
When working in any Oasis project directory, read .swarm/BOOTSTRAP.md before
starting work and follow its coordination protocol.
```

Option B — Per-project (if Gemini CLI supports project configs):
Create `.gemini/config.yaml` at repo root:
```yaml
system_prompt_append: |
  Read .swarm/BOOTSTRAP.md and follow the SwarmCity protocol before starting any task.
```

---

## OpenCode

OpenCode supports `.opencode/rules.md` at the project root.

```markdown
# SwarmCity Protocol

Read `.swarm/BOOTSTRAP.md` before starting any task in this repository.
Follow the On Start → During Work → On Stop protocol. Update state.md when
starting and finishing. Claim items from queue.md before implementing.
```

---

## SwarmCity MCP (Claude Code / Windsurf / Cursor)

Install the MCP server once, configure per-project.

### Installation

```bash
cd oasis-x/swarm-city
pip install -e mcp/
```

### Claude Code configuration

Add to `~/.claude/settings.json` (global) or `.claude/settings.json` (project):

```json
{
  "mcpServers": {
    "swarm-city": {
      "command": "python",
      "args": ["-m", "swarm_city_mcp"],
      "env": {
        "SWARM_ROOT": "/Users/yourname/Documents/Runes/oasis-x"
      }
    }
  }
}
```

### Windsurf / Cursor MCP

Configure via the platform's MCP settings panel. Use:
- **Command**: `python -m swarm_city_mcp`
- **Env**: `SWARM_ROOT=/path/to/oasis-x`

---

## Verification

After setting up any platform, test with:

```
"Read .swarm/BOOTSTRAP.md and tell me what the current state is"
```

The agent should:
1. Read BOOTSTRAP.md (or call `swarm_bootstrap` via MCP)
2. Read state.md and report the current focus
3. Read queue.md and identify the next available item
4. Claim the item before starting work
