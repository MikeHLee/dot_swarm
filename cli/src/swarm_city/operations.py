"""SwarmCity core file operations.

All reads and writes go through these functions. Write operations are atomic
(write to temp file, then rename). File locking is used for concurrent safety.
"""

from __future__ import annotations

import fcntl
import os
import re
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator

from .models import (
    ItemState, Priority, SwarmPaths, SwarmState, WorkItem,
    _now_ts, _parse_ts, PRIORITY_ORDER,
)


# ---------------------------------------------------------------------------
# Queue operations
# ---------------------------------------------------------------------------

SECTION_RE = re.compile(r"^## (Active|Pending|Done)$", re.MULTILINE)
FIELD_RE = re.compile(r"^\s{6}(?P<key>priority|project|notes|depends|refs): (?P<value>.+)$")


def read_queue(paths: SwarmPaths) -> tuple[list[WorkItem], list[WorkItem], list[WorkItem]]:
    """Parse queue.md into (active, pending, done) lists."""
    if not paths.queue.exists():
        return [], [], []

    text = paths.queue.read_text()
    sections = _split_sections(text)
    active = _parse_items(sections.get("Active", ""))
    pending = _parse_items(sections.get("Pending", ""))
    done = _parse_items(sections.get("Done", ""))
    return active, pending, done


def _split_sections(text: str) -> dict[str, str]:
    """Split queue.md text into section name → content."""
    result: dict[str, str] = {}
    current: str | None = None
    lines: list[str] = []
    for line in text.splitlines():
        m = re.match(r"^## (Active|Pending|Done)$", line)
        if m:
            if current is not None:
                result[current] = "\n".join(lines)
            current = m.group(1)
            lines = []
        else:
            if current is not None:
                lines.append(line)
    if current:
        result[current] = "\n".join(lines)
    return result


def _parse_items(section_text: str) -> list[WorkItem]:
    """Parse a section of queue.md into WorkItems, attaching continuation fields."""
    items: list[WorkItem] = []
    current_item: WorkItem | None = None
    for line in section_text.splitlines():
        item = WorkItem.parse_line(line)
        if item:
            current_item = item
            items.append(item)
        elif current_item and (fm := FIELD_RE.match(line)):
            key, value = fm.group("key"), fm.group("value").strip()
            if key == "priority":
                # priority: high | project: cloud-stability
                for part in value.split("|"):
                    part = part.strip()
                    if part.startswith("priority:"):
                        try:
                            current_item.priority = Priority(part.split(":", 1)[1].strip())
                        except ValueError:
                            pass
                    elif part.startswith("project:"):
                        current_item.project = part.split(":", 1)[1].strip()
            elif key == "notes":
                current_item.notes = value
            elif key == "depends":
                current_item.depends = [d.strip() for d in value.split(",")]
            elif key == "refs":
                current_item.refs = [r.strip() for r in value.split(",")]
    return items


def write_queue(
    paths: SwarmPaths,
    active: list[WorkItem],
    pending: list[WorkItem],
    done: list[WorkItem],
) -> None:
    """Write queue.md atomically from three lists."""
    lines = [
        f"# Queue — {_division_name(paths)} ({_level_label(paths)})",
        "",
        "Items are listed in priority order within each section.",
        "Item IDs: `<DIVISION-CODE>-<3-digit-number>` — assigned sequentially, never reused.",
        "",
        "---",
        "",
        "## Active",
        "",
    ]
    for item in active:
        lines.append(item.to_line())
        lines.append("")

    lines += ["## Pending", ""]
    # Sort pending by priority
    pending_sorted = sorted(pending, key=lambda i: PRIORITY_ORDER.get(i.priority, 99))
    for item in pending_sorted:
        lines.append(item.to_line())
        lines.append("")

    lines += ["## Done", ""]
    for item in done:
        lines.append(item.to_line())
        lines.append("")

    _atomic_write(paths.queue, "\n".join(lines))


def next_item_id(paths: SwarmPaths, division_code: str) -> str:
    """Compute the next available item ID for a division code."""
    active, pending, done = read_queue(paths)
    all_items = active + pending + done
    id_re = re.compile(rf"^{re.escape(division_code)}-(\d+)$")
    max_num = 0
    for item in all_items:
        if m := id_re.match(item.id):
            max_num = max(max_num, int(m.group(1)))
    return f"{division_code}-{max_num + 1:03d}"


def claim_item(paths: SwarmPaths, item_id: str, agent_id: str) -> WorkItem:
    """Claim an OPEN work item. Raises ValueError if not found or already claimed."""
    active, pending, done = read_queue(paths)
    target = _find_item(pending + active, item_id)
    if target is None:
        raise ValueError(f"Item {item_id} not found in active or pending queue.")
    if target.state == ItemState.CLAIMED:
        raise ValueError(
            f"Item {item_id} is already claimed by {target.claimed_by} since "
            f"{target.claimed_at}. Use 'swarm partial {item_id}' to re-claim."
        )

    target.state = ItemState.CLAIMED
    target.claimed_by = agent_id
    target.claimed_at = datetime.utcnow()

    # Move from pending to active
    pending = [i for i in pending if i.id != item_id]
    if target not in active:
        active.append(target)

    write_queue(paths, active, pending, done)
    return target


def done_item(paths: SwarmPaths, item_id: str, agent_id: str, note: str = "") -> WorkItem:
    """Mark a claimed item as done."""
    active, pending, done = read_queue(paths)
    target = _find_item(active + pending, item_id)
    if target is None:
        raise ValueError(f"Item {item_id} not found in active or pending queue.")

    target.state = ItemState.DONE
    target.done_at = datetime.utcnow()
    if note:
        target.notes = (target.notes + " | " + note).strip(" | ")

    active = [i for i in active if i.id != item_id]
    pending = [i for i in pending if i.id != item_id]
    done.append(target)

    write_queue(paths, active, pending, done)
    return target


def add_item(
    paths: SwarmPaths,
    description: str,
    division_code: str,
    priority: Priority = Priority.MEDIUM,
    project: str = "misc",
    notes: str = "",
    refs: list[str] | None = None,
    depends: list[str] | None = None,
) -> WorkItem:
    """Add a new OPEN work item with an auto-assigned ID."""
    item_id = next_item_id(paths, division_code)
    item = WorkItem(
        id=item_id,
        state=ItemState.OPEN,
        description=description,
        priority=priority,
        project=project,
        notes=notes,
        refs=refs or [],
        depends=depends or [],
    )
    active, pending, done = read_queue(paths)
    pending.append(item)
    write_queue(paths, active, pending, done)
    return item


# ---------------------------------------------------------------------------
# State operations
# ---------------------------------------------------------------------------

STATE_FIELD_RE = re.compile(r"^\*\*(?P<key>[^*]+)\*\*: (?P<value>.+)$")


def read_state(paths: SwarmPaths) -> dict[str, str]:
    """Parse state.md into a dict of field → value."""
    if not paths.state.exists():
        return {}
    result: dict[str, str] = {}
    handoff_lines: list[str] = []
    in_handoff = False
    for line in paths.state.read_text().splitlines():
        if line.strip() == "## Handoff Note":
            in_handoff = True
            continue
        if in_handoff:
            if line.startswith("## "):
                in_handoff = False
            else:
                handoff_lines.append(line)
            continue
        if m := STATE_FIELD_RE.match(line):
            result[m.group("key")] = m.group("value").strip()
    result["Handoff note"] = "\n".join(handoff_lines).strip()
    return result


def write_state(paths: SwarmPaths, updates: dict[str, str]) -> None:
    """Update specific fields in state.md, preserving all other content."""
    if not paths.state.exists():
        _create_state_template(paths)

    lines = paths.state.read_text().splitlines()
    now = _now_ts()
    updates.setdefault("Last touched", now)

    new_lines: list[str] = []
    in_handoff = False
    handoff_written = False

    for line in lines:
        if line.strip() == "## Handoff Note":
            in_handoff = True
            new_lines.append(line)
            if "Handoff note" in updates:
                new_lines.append("")
                new_lines.append(updates["Handoff note"])
                handoff_written = True
            continue
        if in_handoff:
            if line.startswith("## ") and not line.strip() == "## Handoff Note":
                in_handoff = False
                new_lines.append(line)
            elif not handoff_written:
                new_lines.append(line)
            continue

        if m := STATE_FIELD_RE.match(line):
            key = m.group("key")
            if key in updates:
                # Reconstruct the "last touched" line which includes "by <agent>"
                if key == "Last touched" and "last_agent" in updates:
                    new_lines.append(f"**Last touched**: {updates[key]} by {updates['last_agent']}")
                else:
                    new_lines.append(f"**{key}**: {updates[key]}")
                continue
        new_lines.append(line)

    _atomic_write(paths.state, "\n".join(new_lines) + "\n")


# ---------------------------------------------------------------------------
# Memory operations
# ---------------------------------------------------------------------------

def append_memory(
    paths: SwarmPaths,
    topic: str,
    decision: str,
    why: str,
    tradeoff: str = "",
    agent_id: str = "unknown",
) -> str:
    """Append a formatted entry to memory.md."""
    date = datetime.utcnow().strftime("%Y-%m-%d")
    entry = f"\n## {date} — {topic} ({agent_id})\n\n"
    entry += f"**Decision**: {decision}\n\n"
    entry += f"**Why**: {why}\n"
    if tradeoff:
        entry += f"\n**Trade-off accepted**: {tradeoff}\n"

    if paths.memory.exists():
        existing = paths.memory.read_text()
        _atomic_write(paths.memory, existing.rstrip() + "\n" + entry)
    else:
        _atomic_write(paths.memory, f"# Memory — {_division_name(paths)}\n\nAppend-only.\n" + entry)
    return entry


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

def audit(paths: SwarmPaths, stale_hours: int = 48) -> list[dict]:
    """Return list of drift findings."""
    findings: list[dict] = []
    active, pending, done = read_queue(paths)
    now = datetime.utcnow()
    threshold = timedelta(hours=stale_hours)

    for item in active:
        if item.state == ItemState.CLAIMED and item.claimed_at:
            age = now - item.claimed_at
            if age > threshold:
                findings.append({
                    "severity": "WARN",
                    "type": "stale_claim",
                    "item_id": item.id,
                    "message": f"Claimed {int(age.total_seconds() / 3600)}h ago by {item.claimed_by}",
                    "suggested_action": "Re-evaluate or mark PARTIAL if still in progress.",
                })
        if item.state == ItemState.BLOCKED:
            findings.append({
                "severity": "WARN",
                "type": "blocked_item",
                "item_id": item.id,
                "message": f"Item is BLOCKED: {item.notes}",
                "suggested_action": "Escalate to org level or resolve blocker.",
            })

    # Check state.md freshness
    state = read_state(paths)
    if lt := state.get("Last touched"):
        ts_part = lt.split(" by ")[0].strip()
        if ts := _parse_ts(ts_part):
            age = now - ts
            if age > timedelta(hours=stale_hours * 1.5):
                findings.append({
                    "severity": "WARN",
                    "type": "stale_state",
                    "item_id": None,
                    "message": f"state.md not updated in {int(age.total_seconds() / 3600)}h",
                    "suggested_action": "Run 'swarm status' and update state.md.",
                })

    return findings


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_item(items: list[WorkItem], item_id: str) -> WorkItem | None:
    for item in items:
        if item.id == item_id:
            return item
    return None


def _atomic_write(path: Path, content: str) -> None:
    """Write content to path atomically using temp file + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.write(content)
            fcntl.flock(f, fcntl.LOCK_UN)
        os.replace(tmp_path, path)
    except Exception:
        os.unlink(tmp_path)
        raise


def _division_name(paths: SwarmPaths) -> str:
    return paths.root.parent.name


def _level_label(paths: SwarmPaths) -> str:
    return "Organization Level" if paths.is_org_level() else "Division Level"


def _create_state_template(paths: SwarmPaths) -> None:
    name = _division_name(paths)
    content = f"""# State — {name}

**Last touched**: {_now_ts()} by unknown
**Current focus**: (not set)
**Active items**: (none)
**Blockers**: None
**Ready for pickup**: (none)

---

## Handoff Note

(no handoff note yet)
"""
    _atomic_write(paths.state, content)
