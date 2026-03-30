"""SwarmCity CLI — `swarm` command."""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

import click

from .models import ItemState, Priority, SwarmPaths
from .operations import (
    add_item, append_memory, audit, block_item, claim_item, done_item,
    next_item_id, partial_item, read_queue, read_state, write_state,
    _division_code_from_paths,
)


def _get_paths(path: str) -> SwarmPaths:
    paths = SwarmPaths.find(path)
    if paths is None:
        click.echo(
            "Error: No .swarm/ directory found. Run 'swarm init' first.", err=True
        )
        sys.exit(1)
    return paths


def _default_agent() -> str:
    return os.environ.get("SWARM_AGENT_ID") or f"human-{os.environ.get('USER', 'unknown')}"


# ---------------------------------------------------------------------------
# CLI root
# ---------------------------------------------------------------------------

@click.group()
@click.option("--path", default=".", help="Path to operate on (default: cwd)")
@click.version_option("0.2.0")
@click.pass_context
def cli(ctx: click.Context, path: str) -> None:
    """SwarmCity — markdown-native agent orchestration.

    Reads and writes .swarm/ directories in the current working directory (or
    specified --path). All state lives in plain markdown files — git is the
    audit trail.

    Quick start:
      swarm init        Initialize .swarm/ here
      swarm status      Show current state
      swarm claim ID    Claim a work item
      swarm done ID     Mark item complete
    """
    ctx.ensure_object(dict)
    ctx.obj["path"] = path


# ---------------------------------------------------------------------------
# swarm init
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--level", type=click.Choice(["org", "div"]), default=None,
              help="Override level detection (org|div)")
@click.option("--division-code", default=None, help="Division code e.g. CLD, FW")
@click.option("--division-name", default=None, help="Human-readable division name")
@click.pass_context
def init(ctx: click.Context, level: str | None, division_code: str | None,
         division_name: str | None) -> None:
    """Initialize .swarm/ in the current directory.

    Creates BOOTSTRAP.md, context.md, state.md, queue.md, memory.md
    with appropriate templates. At org level, also creates workflows/.

    At division level, also creates platform shims (CLAUDE.md, .windsurfrules,
    .cursorrules) if they don't already exist.
    """
    p = Path(ctx.obj["path"]).resolve()
    swarm_dir = p / ".swarm"

    # Detect level
    is_div = (p / ".git").exists()
    if level == "org":
        is_div = False
    elif level == "div":
        is_div = True

    level_str = "division" if is_div else "org"
    click.echo(f"Initializing .swarm/ at {level_str} level in {p}")

    swarm_dir.mkdir(exist_ok=True)
    code = division_code or _division_code_from_paths(SwarmPaths(
        root=swarm_dir, bootstrap=swarm_dir/"BOOTSTRAP.md",
        context=swarm_dir/"context.md", state=swarm_dir/"state.md",
        queue=swarm_dir/"queue.md", memory=swarm_dir/"memory.md",
        workflows=swarm_dir/"workflows",
    ))
    name = division_name or p.name

    # BOOTSTRAP.md
    _create_if_missing(swarm_dir / "BOOTSTRAP.md",
        f"# SwarmCity Bootstrap — {name}\n\n"
        "See `oasis-x/.swarm/BOOTSTRAP.md` for the full protocol.\n\n"
        "Quick reference:\n"
        "1. Read context.md → state.md → queue.md\n"
        "2. Claim an OPEN item\n"
        "3. Update state.md on start and finish\n"
    )

    # context.md
    _create_if_missing(swarm_dir / "context.md",
        f"# Context — {name}\n\n"
        f"**Level**: {'Organization' if not is_div else 'Division'}\n"
        f"**Division code**: {code}\n"
        f"**Last updated**: {datetime.utcnow().strftime('%Y-%m-%d')}\n\n"
        "## What This Division Is\n\n"
        "(fill in)\n\n"
        "## Architecture Constraints\n\n"
        "1. (fill in)\n\n"
        "## Current Focus Areas\n\n"
        "1. (fill in)\n"
    )

    # state.md
    _create_if_missing(swarm_dir / "state.md",
        f"# State — {name}\n\n"
        f"**Last touched**: {datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ')} by unknown\n"
        "**Current focus**: (not set)\n"
        "**Active items**: (none)\n"
        "**Blockers**: None\n"
        "**Ready for pickup**: (none)\n\n"
        "---\n\n"
        "## Handoff Note\n\n"
        "(no handoff note yet)\n"
    )

    # queue.md
    _create_if_missing(swarm_dir / "queue.md",
        f"# Queue — {name} ({'Organization' if not is_div else 'Division'} Level)\n\n"
        "Items are listed in priority order within each section.\n"
        f"Item IDs: `{code}-<3-digit-number>` — assigned sequentially, never reused.\n\n"
        "---\n\n"
        "## Active\n\n"
        "(no active items)\n\n"
        "## Pending\n\n"
        f"- [ ] [{code}-001] [OPEN] First work item (replace this)\n"
        "      priority: medium | project: misc\n\n"
        "## Done\n\n"
        "(none yet)\n"
    )

    # memory.md
    _create_if_missing(swarm_dir / "memory.md",
        f"# Memory — {name}\n\n"
        "Append-only. Non-obvious decisions, constraints, and rationale.\n"
        "Format: `## <ISO8601-date> — <topic> (<agent-id>)`\n\n"
        "---\n\n"
        "(no entries yet)\n"
    )

    if not is_div:
        (swarm_dir / "workflows").mkdir(exist_ok=True)

    click.echo(f"Created .swarm/ with {len(list(swarm_dir.iterdir()))} files/dirs.")

    if is_div:
        _create_platform_shims(p)
        _install_drift_check_workflow(p)

    click.echo("\nNext steps:")
    click.echo(f"  1. Edit .swarm/context.md — describe what {name} is")
    click.echo("  2. Run 'swarm status' to verify")
    click.echo("  3. Run 'swarm add \"first task\"' to add a work item")
    if is_div:
        click.echo("  4. Add GEMINI_API_KEY to GitHub secrets to enable drift checks")


# ---------------------------------------------------------------------------
# swarm status
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--all", "show_all", is_flag=True, help="Show full queue")
@click.pass_context
def status(ctx: click.Context, show_all: bool) -> None:
    """Show current state and next available work items."""
    paths = _get_paths(ctx.obj["path"])
    state = read_state(paths)
    active, pending, done = read_queue(paths)

    name = paths.root.parent.name
    click.echo(f"\n{'─' * 60}")
    click.echo(f"  {name}")
    click.echo(f"{'─' * 60}")

    for key in ["Last touched", "Current focus", "Active items", "Blockers"]:
        val = state.get(key, "(not set)")
        click.echo(f"  {key}: {val}")

    if state.get("Handoff note"):
        click.echo(f"\n  Handoff: {state['Handoff note'][:120]}")

    click.echo(f"\n  Active ({len(active)}):")
    for item in active[:5]:
        click.echo(f"    [{item.id}] {item.description[:60]}  [{item.state.value}]")

    click.echo(f"\n  Pending ({len(pending)}):")
    for item in (pending if show_all else pending[:5]):
        click.echo(f"    [{item.id}] [{item.priority.value.upper()}] {item.description[:60]}")
    if not show_all and len(pending) > 5:
        click.echo(f"    ... and {len(pending) - 5} more (use --all)")

    click.echo(f"\n  Done: {len(done)} items\n")


# ---------------------------------------------------------------------------
# swarm claim
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("item_id")
@click.option("--agent", default=None, help="Agent ID (default: $SWARM_AGENT_ID or human-$USER)")
@click.pass_context
def claim(ctx: click.Context, item_id: str, agent: str | None) -> None:
    """Claim a work item. Updates queue.md and state.md."""
    paths = _get_paths(ctx.obj["path"])
    agent_id = agent or _default_agent()
    try:
        item = claim_item(paths, item_id, agent_id)
        write_state(paths, {
            "Current focus": item.description[:100],
            "Active items": item_id,
            "last_agent": agent_id,
        })
        click.echo(f"Claimed [{item_id}] for {agent_id}: {item.description}")
        click.echo("Remember to update state.md and run 'swarm done' when complete.")
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


# ---------------------------------------------------------------------------
# swarm done
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("item_id")
@click.option("--agent", default=None)
@click.option("--note", default="", help="Brief completion note")
@click.option("--next", "next_focus", default=None, help="Set state.md next focus")
@click.pass_context
def done(ctx: click.Context, item_id: str, agent: str | None,
         note: str, next_focus: str | None) -> None:
    """Mark a work item as done."""
    paths = _get_paths(ctx.obj["path"])
    agent_id = agent or _default_agent()
    try:
        item = done_item(paths, item_id, agent_id, note)
        updates: dict = {"last_agent": agent_id}
        if next_focus:
            updates["Current focus"] = next_focus
            updates["Handoff note"] = next_focus
        write_state(paths, updates)
        click.echo(f"Done: [{item_id}] {item.description}")
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


# ---------------------------------------------------------------------------
# swarm add
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("description")
@click.option("--priority", type=click.Choice(["critical", "high", "medium", "low"]),
              default="medium")
@click.option("--project", default="misc")
@click.option("--notes", default="")
@click.option("--refs", default="", help="Comma-separated refs e.g. 'oasis-x/.swarm/queue.md#ORG-001'")
@click.option("--depends", default="", help="Comma-separated item IDs")
@click.option("--code", default=None, help="Division code override")
@click.pass_context
def add(ctx: click.Context, description: str, priority: str, project: str,
        notes: str, refs: str, depends: str, code: str | None) -> None:
    """Add a new work item to the queue."""
    paths = _get_paths(ctx.obj["path"])
    division_code = code or _division_code_from_paths(paths)
    item = add_item(
        paths=paths,
        description=description,
        division_code=division_code,
        priority=Priority(priority),
        project=project,
        notes=notes,
        refs=[r.strip() for r in refs.split(",") if r.strip()],
        depends=[d.strip() for d in depends.split(",") if d.strip()],
    )
    click.echo(f"Added [{item.id}] ({priority}) {description}")


# ---------------------------------------------------------------------------
# swarm audit
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--since", default=48, help="Stale threshold in hours (default: 48)")
@click.pass_context
def audit_cmd(ctx: click.Context, since: int) -> None:
    """Check for drift: stale claims, blocked items, state.md staleness."""
    paths = _get_paths(ctx.obj["path"])
    findings = audit(paths, stale_hours=since)
    if not findings:
        click.echo("No drift detected.")
        return
    for f in findings:
        icon = "⚠️ " if f["severity"] == "WARN" else "🚨"
        id_str = f"[{f['item_id']}] " if f["item_id"] else ""
        click.echo(f"{icon} {id_str}{f['message']}")
        click.echo(f"   → {f['suggested_action']}")


# ---------------------------------------------------------------------------
# swarm handoff
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--format", "fmt", type=click.Choice(["md", "text"]), default="md")
@click.pass_context
def handoff(ctx: click.Context, fmt: str) -> None:
    """Generate a handoff summary for the next agent or developer."""
    paths = _get_paths(ctx.obj["path"])
    state = read_state(paths)
    active, pending, done = read_queue(paths)
    name = paths.root.parent.name
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ")

    lines = [
        f"# SwarmCity Handoff — {name} — {now}",
        "",
        "## Current State",
        f"Focus: {state.get('Current focus', '(not set)')}",
        f"Agent: {state.get('Last touched', 'unknown').split(' by ')[-1]}",
    ]
    if active:
        lines.append(f"Active: {', '.join(i.id for i in active)}")
    if state.get("Blockers") and state["Blockers"] != "None":
        lines.append(f"Blockers: {state['Blockers']}")
    if state.get("Handoff note"):
        lines.append(f"\n{state['Handoff note']}")

    lines += ["", "## Ready for Pickup"]
    for item in pending[:5]:
        lines.append(f"- {item.id}: {item.description} [{item.priority.value.upper()}]")

    lines += [
        "",
        "## Context Files to Load",
        f"- @{paths.root}/BOOTSTRAP.md",
        f"- @{paths.root}/context.md",
        f"- @{paths.root}/queue.md",
    ]

    click.echo("\n".join(lines))


# ---------------------------------------------------------------------------
# swarm ls
# ---------------------------------------------------------------------------

@cli.command(name="ls")
@click.option("--section", type=click.Choice(["active", "pending", "done", "all"]),
              default="all", help="Section to show (default: all)")
@click.option("--priority", default=None,
              type=click.Choice(["critical", "high", "medium", "low"]),
              help="Filter by priority")
@click.option("--project", default=None, help="Filter by project")
@click.pass_context
def ls_cmd(ctx: click.Context, section: str, priority: str | None, project: str | None) -> None:
    """List work items from the queue."""
    paths = _get_paths(ctx.obj["path"])
    active, pending, done = read_queue(paths)

    sections: list[tuple[str, list]] = []
    if section in ("active", "all"):
        sections.append(("Active", active))
    if section in ("pending", "all"):
        sections.append(("Pending", pending))
    if section in ("done", "all"):
        sections.append(("Done", done))

    STATE_ICON = {
        "OPEN": "[ ]", "CLAIMED": "[>]", "PARTIAL": "[~]",
        "BLOCKED": "[!]", "DONE": "[x]", "CANCELLED": "[-]",
    }

    for label, items in sections:
        filtered = items
        if priority:
            filtered = [i for i in filtered if i.priority.value == priority]
        if project:
            filtered = [i for i in filtered if i.project == project]
        if filtered:
            click.echo(f"\n## {label}")
            for item in filtered:
                icon = STATE_ICON.get(item.state.value, "[ ]")
                pri = f"[{item.priority.value.upper()}]"
                claim = f" ← {item.claimed_by}" if item.claimed_by else ""
                click.echo(f"  {icon} [{item.id}] {pri} {item.description}{claim}")


# ---------------------------------------------------------------------------
# swarm partial
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("item_id")
@click.option("--note", default="", help="Checkpoint note")
@click.option("--agent", "agent_id", default=None, help="Agent ID override")
@click.pass_context
def partial(ctx: click.Context, item_id: str, note: str, agent_id: str | None) -> None:
    """Mark a claimed item as partially done (checkpoint)."""
    paths = _get_paths(ctx.obj["path"])
    agent = agent_id or _default_agent()
    try:
        item = partial_item(paths, item_id, agent, note)
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)
    click.echo(f"Partial [{item.id}]: {item.description} (re-claimed by {agent})")


# ---------------------------------------------------------------------------
# swarm block
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("item_id")
@click.argument("reason")
@click.pass_context
def block(ctx: click.Context, item_id: str, reason: str) -> None:
    """Mark a work item as blocked with a reason."""
    paths = _get_paths(ctx.obj["path"])
    try:
        item = block_item(paths, item_id, reason)
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)
    click.echo(f"Blocked [{item.id}]: {item.description}")
    click.echo(f"  Reason: {reason}")


# ---------------------------------------------------------------------------
# swarm configure
# ---------------------------------------------------------------------------

@cli.command()
def configure() -> None:
    """Interactive wizard: set Bedrock model + region, test connectivity.

    Credentials are NEVER stored here. boto3 reads them from the standard
    AWS credential chain: env vars → ~/.aws/credentials → IAM role.

    Run 'aws configure' or set AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY
    in your environment before running this.
    """
    try:
        import boto3  # noqa: F401  (just checking it's available)
    except ImportError:
        click.echo("Error: boto3 not installed. Run: pip install 'swarm-city[ai]'", err=True)
        raise SystemExit(1)

    from . import bedrock as _bedrock

    cfg = _bedrock.load_config()

    click.echo("SwarmCity Bedrock configuration\n")
    click.echo("Credentials: boto3 credential chain")
    click.echo("  (env vars → ~/.aws/credentials → IAM role — never stored here)\n")

    model  = click.prompt("  Bedrock model",  default=cfg["model"])
    region = click.prompt("  AWS region",     default=cfg["region"])

    if click.confirm("\n  Test connectivity now?", default=True):
        click.echo("  Connecting...", nl=False)
        try:
            client = _bedrock.get_bedrock_client(region)
            ok, msg = _bedrock.test_connectivity(client, model)
        except Exception as e:
            ok, msg = False, str(e)

        if ok:
            click.echo(" ✓ OK")
        else:
            click.echo(f" ✗\n")
            if "NoCredentialsError" in msg or "CredentialRetrievalError" in msg:
                click.echo("  No AWS credentials found. Options:")
                click.echo("    aws configure                          (interactive)")
                click.echo("    export AWS_ACCESS_KEY_ID=...           (env var)")
                click.echo("    export AWS_SECRET_ACCESS_KEY=...")
            elif "AccessDeniedException" in msg or "AuthorizationError" in msg:
                click.echo("  Access denied. Check two things:")
                click.echo("    1. IAM policy: add bedrock:InvokeModel on the model ARN")
                click.echo("    2. Bedrock model access: AWS Console → Bedrock → Model access")
            elif "EndpointResolution" in msg or "Connection" in msg:
                click.echo(f"  Connection failed — is region '{region}' correct?")
            else:
                click.echo(f"  Error: {msg[:200]}")

    _bedrock.save_config(model, region)
    click.echo(f"\n  Config saved to {_bedrock.CONFIG_PATH}")
    click.echo("  Run 'swarm ai \"what should I work on next?\"' to try it out.")


# ---------------------------------------------------------------------------
# swarm ai
# ---------------------------------------------------------------------------

@cli.command(name="ai")
@click.argument("instruction")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation and execute immediately")
@click.option("--agent", "agent_id", default=None, help="Agent ID override")
@click.pass_context
def ai_cmd(ctx: click.Context, instruction: str, yes: bool, agent_id: str | None) -> None:
    """Translate a natural language instruction into .swarm/ operations.

    Examples:
      swarm ai "mark ORG-009 as done, blog service is fixed"
      swarm ai "add three items for OAuth2: discovery, token exchange, refresh"
      swarm ai "what should I work on next?"
      swarm ai "write a memory entry: chose NATS over Kafka for native async"
      swarm ai "update my focus to the markets ASGI fix" --yes
    """
    try:
        import boto3  # noqa: F401
    except ImportError:
        click.echo("Error: boto3 not installed. Run: pip install 'swarm-city[ai]'", err=True)
        raise SystemExit(1)

    from . import bedrock as _bedrock
    from . import ai_ops as _ai

    paths  = _get_paths(ctx.obj["path"])
    agent  = agent_id or _default_agent()
    cfg    = _bedrock.load_config()

    # Build context and prompt
    context  = _ai.build_context_bundle(paths)
    user_msg = f"Instruction: {instruction}\n\n{context}"

    # Call Bedrock
    try:
        client = _bedrock.get_bedrock_client(cfg["region"])
        result = _ai.invoke_ai(client, cfg["model"], user_msg)
    except ImportError:
        click.echo("Error: boto3 not installed. Run: pip install 'swarm-city[ai]'", err=True)
        raise SystemExit(1)
    except Exception as e:
        kind = type(e).__name__
        if "NoCredentials" in kind or "CredentialRetrieval" in kind:
            click.echo("Error: No AWS credentials. Run 'swarm configure' or set AWS_* env vars.", err=True)
        elif "AccessDenied" in str(e) or "Authorization" in str(e):
            click.echo("Error: Bedrock access denied. Run 'swarm configure' to troubleshoot.", err=True)
        else:
            click.echo(f"Error: {kind}: {e}", err=True)
        raise SystemExit(1)

    commentary = result.get("commentary", "")
    ops        = result.get("operations", [])

    if not ops:
        click.echo(f"\n{commentary}")
        return

    # Separate respond ops (informational) from file-write ops
    respond_ops = [o for o in ops if o.get("op") == "respond"]
    write_ops   = [o for o in ops if o.get("op") != "respond"]

    # Always print respond messages immediately
    for op in respond_ops:
        click.echo(f"\n{op['message']}")

    if not write_ops:
        return

    # Preview write ops and confirm
    click.echo("\n" + _ai.format_preview(commentary, write_ops))

    if not yes:
        click.echo()
        if not click.confirm("  Execute these operations?", default=False):
            click.echo("  Aborted.")
            return

    click.echo()
    results = _ai.execute_operations(paths, write_ops, agent)
    for r in results:
        click.echo(r)


# ---------------------------------------------------------------------------
# swarm setup-drift-check
# ---------------------------------------------------------------------------

@cli.command(name="setup-drift-check")
@click.option("--repo", default=None, metavar="OWNER/REPO",
              help="GitHub repo (default: detected from git remote)")
@click.option("--region", default=None, metavar="REGION",
              help="AWS region for Bedrock (default: us-east-1)")
@click.option("--commit", is_flag=True,
              help="Commit and push the workflow file after creating it")
@click.option("--model", default=None, metavar="MODEL_ID",
              help="Override Bedrock model ID (sets repo variable SWARM_BEDROCK_MODEL)")
@click.pass_context
def setup_drift_check(
    ctx: click.Context,
    repo: str | None,
    region: str | None,
    commit: bool,
    model: str | None,
) -> None:
    """Install the SwarmCity drift-check GitHub Actions workflow.

    Copies swarm-drift-check.yml to .github/workflows/, verifies AWS secrets
    exist via gh CLI, and optionally commits + pushes.

    Requires: gh CLI authenticated (run `gh auth login` if needed).
    """
    import shutil, subprocess

    repo_root = _find_git_root()
    if repo_root is None:
        click.echo("Error: not inside a git repository.", err=True)
        raise SystemExit(1)

    # --- Check gh CLI -------------------------------------------------------
    if not shutil.which("gh"):
        click.echo("Error: gh CLI not found. Install from https://cli.github.com/", err=True)
        raise SystemExit(1)

    # --- Detect repo if not provided ----------------------------------------
    if not repo:
        result = subprocess.run(
            ["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"],
            capture_output=True, text=True, cwd=repo_root,
        )
        if result.returncode != 0:
            click.echo("Error: could not detect repo. Pass --repo OWNER/REPO.", err=True)
            raise SystemExit(1)
        repo = result.stdout.strip()

    click.echo(f"Setting up drift check for: {repo}")

    # --- Check / set AWS secrets --------------------------------------------
    secrets_result = subprocess.run(
        ["gh", "secret", "list", "--repo", repo],
        capture_output=True, text=True,
    )
    existing_secrets = secrets_result.stdout

    needed = {
        "AWS_ACCESS_KEY_ID": "AWS access key ID",
        "AWS_SECRET_ACCESS_KEY": "AWS secret access key",
        "AWS_DEFAULT_REGION": f"AWS region (e.g. {region or 'us-east-1'})",
    }
    for secret_name, description in needed.items():
        if secret_name in existing_secrets:
            click.echo(f"  ✓ {secret_name} already set")
        else:
            value = click.prompt(f"  Enter {description} (or press Enter to skip)", default="", show_default=False)
            if value:
                subprocess.run(
                    ["gh", "secret", "set", secret_name, "--repo", repo, "--body", value],
                    check=True,
                )
                click.echo(f"  ✓ {secret_name} set")
            else:
                click.echo(f"  ⚠ {secret_name} skipped — add manually if needed")

    # --- Set model variable if requested ------------------------------------
    if model:
        subprocess.run(
            ["gh", "variable", "set", "SWARM_BEDROCK_MODEL", "--repo", repo, "--body", model],
            check=True,
        )
        click.echo(f"  ✓ SWARM_BEDROCK_MODEL set to {model}")

    # --- Copy workflow file -------------------------------------------------
    workflow_dest = repo_root / ".github" / "workflows" / "swarm-drift-check.yml"
    if workflow_dest.exists():
        click.echo(f"\n  ✓ {workflow_dest.relative_to(repo_root)} already exists")
    else:
        _install_drift_check_workflow(repo_root)

    # --- Commit and push if requested ---------------------------------------
    if commit:
        wf_rel = str(workflow_dest.relative_to(repo_root))
        subprocess.run(["git", "add", wf_rel], cwd=repo_root, check=True)
        subprocess.run(
            ["git", "commit", "-m", "chore: add SwarmCity drift-check workflow\n\nAuto-installed via `swarm setup-drift-check`"],
            cwd=repo_root, check=True,
        )
        subprocess.run(["git", "push"], cwd=repo_root, check=True)
        click.echo("  ✓ Committed and pushed")
    else:
        click.echo(f"\n  Workflow written. To activate:\n")
        click.echo(f"    git add .github/workflows/swarm-drift-check.yml")
        click.echo(f"    git commit -m 'chore: add SwarmCity drift-check workflow'")
        click.echo(f"    git push")

    click.echo(f"\nDone. The drift check will run on every merge to dev/prod in {repo}.")
    click.echo("See docs/DRIFT_CHECK_SETUP.md for Bedrock model access setup.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _install_drift_check_workflow(repo_root: Path) -> None:
    """Install swarm-drift-check.yml into .github/workflows/ if not already present."""
    import importlib.resources

    dest = repo_root / ".github" / "workflows" / "swarm-drift-check.yml"
    if dest.exists():
        return

    # Try to load the bundled template
    try:
        template_path = (
            Path(__file__).parent.parent.parent.parent.parent  # swarm-city root
            / ".github" / "workflows" / "swarm-drift-check.yml"
        )
        if template_path.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(template_path.read_text())
            click.echo("  Created .github/workflows/swarm-drift-check.yml")
            return
    except Exception:
        pass

    click.echo(
        "  Note: drift-check workflow not found at package root. "
        "Copy swarm-city/.github/workflows/swarm-drift-check.yml manually."
    )


def _find_git_root() -> Path | None:
    """Walk up from cwd to find the nearest .git/ directory."""
    p = Path.cwd()
    for _ in range(8):
        if (p / ".git").is_dir():
            return p
        if p.parent == p:
            break
        p = p.parent
    return None


def _create_if_missing(path: Path, content: str) -> None:
    if not path.exists():
        path.write_text(content)
        click.echo(f"  Created {path.name}")
    else:
        click.echo(f"  Skipped {path.name} (already exists)")


def _create_platform_shims(repo_root: Path) -> None:
    """Create CLAUDE.md, .windsurfrules, .cursorrules if they don't exist."""
    shims = {
        "CLAUDE.md": (
            "Before starting any work, read @.swarm/BOOTSTRAP.md and follow the protocol exactly.\n"
            "Active context: @.swarm/context.md | State: @.swarm/state.md | Queue: @.swarm/queue.md\n"
        ),
        ".windsurfrules": (
            "Before starting any task, read the file .swarm/BOOTSTRAP.md and follow its protocol.\n"
            "Do not begin work without claiming an item in .swarm/queue.md.\n"
        ),
        ".cursorrules": (
            "Always begin every session by reading .swarm/BOOTSTRAP.md.\n"
            "Follow the On Start, During Work, and On Stop sections exactly.\n"
        ),
    }
    for filename, content in shims.items():
        path = repo_root / filename
        _create_if_missing(path, content)
