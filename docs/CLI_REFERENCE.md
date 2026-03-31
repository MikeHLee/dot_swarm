# CLI Reference

`swarm` is installed as a standalone command via `pip install swarm-city`.

```bash
pip install swarm-city          # base CLI
pip install 'swarm-city[ai]'    # + AWS Bedrock support (boto3)
```

---

## Global Options

| Flag | Default | Description |
|------|---------|-------------|
| `--path PATH` | `.` (cwd) | Root path to search for `.swarm/` directory |
| `--version` | — | Print version and exit |
| `--help` | — | Show help |

All commands inherit `--path`. Example: `swarm --path ../oasis-cloud status`

---

## Initialization

### `swarm init`

Initialize a `.swarm/` directory in the current repo.

```bash
swarm init                   # auto-detect org vs division level
swarm init --level org       # force org level (ORG- item IDs)
swarm init --level division  # force division level
swarm init --code CLD        # set division code (default: derived from folder name)
```

Creates: `BOOTSTRAP.md`, `context.md`, `state.md`, `queue.md`, `memory.md`

---

## Situational Awareness

### `swarm status`

Print current state and active/pending queue items for this division.

```bash
swarm status          # active + pending items only
swarm status --all    # include done items
```

### `swarm ls`

List queue items with filtering.

```bash
swarm ls                            # all items
swarm ls --section active           # active only
swarm ls --section pending          # pending only
swarm ls --priority high            # filter by priority
swarm ls --project cloud-stability  # filter by project tag
```

### `swarm explore`

Show the heartbeat of all divisions in the colony. Recursively discovers `.swarm/` directories.

```bash
swarm explore                       # from current directory, depth 2
swarm explore --depth 3             # search deeper
swarm --path ~/org explore          # from org root
```

### `swarm report`

Generate a full markdown report of all divisions. Unlike `explore`, outputs a complete
document suitable for sharing, filing as a GitHub issue, or posting to a wiki.

```bash
swarm report                        # print to stdout
swarm report --out REPORT.md        # write to file
swarm report --only active          # active items only
swarm report --no-done              # skip done sections
```

---

## Work Item Lifecycle

### `swarm add`

Add a new work item to the Pending queue.

```bash
swarm add "Add request ID tracing to all services"
swarm add "Fix Redis timeout" --priority high --project infra
swarm add "OAuth2 discovery" --notes "See RFC 8414 for discovery spec"
```

Options: `--priority [low|medium|high|critical]`, `--project TEXT`, `--notes TEXT`

### `swarm claim`

Claim an item (move Active, stamp with agent ID + timestamp).

```bash
swarm claim CLD-042
swarm claim CLD-042 --agent my-agent-id
```

### `swarm done`

Mark a claimed item as done.

```bash
swarm done CLD-042
swarm done CLD-042 --note "Used converse API instead of invoke-model"
```

### `swarm partial`

Checkpoint progress on a claimed item without marking it done. Updates the item's
in-progress note and refreshes the claim timestamp.

```bash
swarm partial CLD-042 "Auth header parsing done, token validation next"
```

### `swarm block`

Mark a claimed item as blocked.

```bash
swarm block CLD-042 "Waiting for staging DB credentials from ops"
```

### `swarm unblock`

Clear a blocked item back to Open (or back to Claimed if an agent is specified).

```bash
swarm unblock CLD-042                  # → OPEN
swarm unblock CLD-042 --reclaim        # → re-CLAIMED by current agent
```

---

## Memory & Audit

### `swarm audit`

List stale claimed items (default: claimed > 48 hours without update).

```bash
swarm audit
swarm audit --since 24    # flag items stale after 24 hours
```

### `swarm handoff`

Print a structured handoff note for the current session — what was done, what's in
flight, what's next. Useful at the end of a work session.

```bash
swarm handoff
swarm handoff --format json    # machine-readable output
```

---

## AI Interface

### `swarm ai`

Translate a natural-language instruction into `.swarm/` operations using an LLM backend.
Previews proposed changes before executing (unless `--yes`).

```bash
swarm ai "mark CLD-042 as done, merged the OAuth PR"
swarm ai "what should I work on next?"
swarm ai "add three items for rate limiting: design, implement, test"
swarm ai "write a memory entry: chose NATS over Kafka for lower latency"
swarm ai "update focus to markets ASGI fix" --yes

# With a specific backend:
swarm ai "summarise the queue" --via claude
swarm ai "what needs doing?" --via gemini
swarm ai "mark done" --via bedrock      # explicit Bedrock (default)
```

Options: `--yes / -y`, `--agent TEXT`, `--limit INT` (context token budget), `--via [bedrock|claude|gemini|opencode]`

### `swarm session`

Launch an interactive LLM session in the division root, seeded with `.swarm/` context.

```bash
swarm session                          # interactive, auto-detect CLI
swarm session --with claude            # prefer Claude Code
swarm session --with gemini            # prefer Gemini CLI
swarm session "what should I pick up?" # single non-interactive turn
```

For **Claude Code**: CLAUDE.md already loads `.swarm/` context automatically.
For **gemini / opencode**: writes `.swarm/CURRENT_SESSION.md` context file first.

### `swarm configure`

Interactive wizard to set your default LLM interface and (if Bedrock) model + region.

```bash
swarm configure
```

Config stored at `~/.config/swarm/config.toml`. Credentials are never stored here —
use `aws configure` or env vars for Bedrock; the respective CLI handles auth for others.

---

## Setup & CI

### `swarm setup-drift-check`

Install the `swarm-drift-check.yml` GitHub Actions workflow into the current repo.
Uses the `gh` CLI to set secrets if needed.

```bash
swarm setup-drift-check           # install workflow file only
swarm setup-drift-check --commit  # also commit + push
```

See [Drift Check Setup](DRIFT_CHECK_SETUP.md) for AWS Bedrock prerequisites.

---

## Item ID Convention

```
<DIVISION-CODE>-<3-digit-number>
```

| Division | Code |
|----------|------|
| Org level | `ORG` |
| oasis-cloud | `CLD` |
| oasis-cloud-admin | `ADM` |
| oasis-weather | `WTH` |
| oasis-firmware | `FW` |
| oasis-home | `HM` |
| oasis-ui | `UI` |
| oasis-forms | `FRM` |
| oasis-hardware | `HW` |
| oasis-welcome | `WEB` |
| oasis-cloud-wiki | `WIKI` |
| oasis-records | `REC` |
| swarm-city | `SWC` |

IDs are assigned sequentially and never reused.
