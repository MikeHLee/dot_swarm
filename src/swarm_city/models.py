"""SwarmCity data models.

All models are plain dataclasses — no ORM, no database. State lives on disk as markdown.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path


class ItemState(str, Enum):
    OPEN = "OPEN"
    CLAIMED = "CLAIMED"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class Priority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


PRIORITY_ORDER = {Priority.CRITICAL: 0, Priority.HIGH: 1, Priority.MEDIUM: 2, Priority.LOW: 3}


@dataclass
class WorkItem:
    """A single entry in a queue.md file."""

    id: str                              # e.g. "ORG-002", "CLD-042"
    state: ItemState = ItemState.OPEN
    description: str = ""
    priority: Priority = Priority.MEDIUM
    project: str = "misc"
    notes: str = ""
    claimed_by: str | None = None
    claimed_at: datetime | None = None
    done_at: datetime | None = None
    refs: list[str] = field(default_factory=list)
    depends: list[str] = field(default_factory=list)

    # Regex patterns for parsing queue.md lines
    # Matches: - [>] [ORG-002] [CLAIMED · claude-code · 2026-03-26T14:30Z] description
    #      or: - [ ] [ORG-002] [OPEN] description
    #      or: - [x] [ORG-002] [DONE · 2026-03-26T16:45Z] description
    ITEM_RE = re.compile(
        r"^- \[(?P<checkbox>[x> ])\] "
        r"\[(?P<id>[A-Z]+-\d+)\] "
        r"\[(?P<stamp>[^\]]+)\] "
        r"(?P<description>.+)$"
    )
    CLAIM_STAMP_RE = re.compile(
        r"CLAIMED · (?P<agent>[^ ·]+) · (?P<ts>[0-9T:Z-]+)"
        r"(?: · (?P<modifier>PARTIAL))?"
    )
    DONE_STAMP_RE = re.compile(r"DONE · (?P<ts>[0-9T:Z-]+)")
    BLOCKED_STAMP_RE = re.compile(r"BLOCKED · (?P<reason>.+)")

    FIELD_RE = re.compile(
        r"^\s+(?P<key>priority|project|notes|depends|refs): (?P<value>.+)$"
    )

    @classmethod
    def parse_line(cls, line: str) -> "WorkItem | None":
        """Parse a single queue.md item line into a WorkItem. Returns None if not an item."""
        m = cls.ITEM_RE.match(line.rstrip())
        if not m:
            return None

        item = cls(id=m.group("id"), description=m.group("description").strip())
        stamp = m.group("stamp").strip()

        if stamp == "OPEN":
            item.state = ItemState.OPEN
        elif cm := cls.CLAIM_STAMP_RE.match(stamp):
            item.claimed_by = cm.group("agent")
            item.claimed_at = _parse_ts(cm.group("ts"))
            item.state = ItemState.PARTIAL if cm.group("modifier") == "PARTIAL" else ItemState.CLAIMED
        elif dm := cls.DONE_STAMP_RE.match(stamp):
            item.done_at = _parse_ts(dm.group("ts"))
            item.state = ItemState.DONE
        elif bm := cls.BLOCKED_STAMP_RE.match(stamp):
            item.state = ItemState.BLOCKED
            item.notes = f"BLOCKED: {bm.group('reason')}"
        elif stamp == "CANCELLED":
            item.state = ItemState.CANCELLED

        return item

    def to_line(self) -> str:
        """Render item back to queue.md line format."""
        checkbox = {"OPEN": " ", "CLAIMED": ">", "PARTIAL": ">",
                    "BLOCKED": " ", "DONE": "x", "CANCELLED": "x"}[self.state.value]
        stamp = self._render_stamp()
        line = f"- [{checkbox}] [{self.id}] [{stamp}] {self.description}"
        fields = []
        fields.append(f"priority: {self.priority.value} | project: {self.project}")
        if self.notes:
            fields.append(f"notes: {self.notes}")
        if self.depends:
            fields.append(f"depends: {', '.join(self.depends)}")
        if self.refs:
            fields.append(f"refs: {', '.join(self.refs)}")
        if fields:
            line += "\n      " + "\n      ".join(fields)
        return line

    def _render_stamp(self) -> str:
        now = _now_ts()
        if self.state == ItemState.OPEN:
            return "OPEN"
        elif self.state == ItemState.CLAIMED:
            return f"CLAIMED · {self.claimed_by} · {_fmt_ts(self.claimed_at)}"
        elif self.state == ItemState.PARTIAL:
            return f"CLAIMED · {self.claimed_by} · {_fmt_ts(self.claimed_at)} · PARTIAL"
        elif self.state == ItemState.BLOCKED:
            reason = self.notes.removeprefix("BLOCKED: ") if self.notes else "unknown"
            return f"BLOCKED · {reason}"
        elif self.state == ItemState.DONE:
            return f"DONE · {_fmt_ts(self.done_at or datetime.utcnow())}"
        elif self.state == ItemState.CANCELLED:
            return "CANCELLED"
        return "OPEN"


@dataclass
class SwarmState:
    """Parsed representation of state.md."""

    last_touched: datetime | None = None
    last_agent: str = "unknown"
    current_focus: str = ""
    active_items: list[str] = field(default_factory=list)
    blockers: str = "None"
    ready_for_pickup: list[str] = field(default_factory=list)
    handoff_note: str = ""

    STATE_FIELDS = {
        "Last touched": "last_touched_raw",
        "Current focus": "current_focus",
        "Active items": "active_items_raw",
        "Blockers": "blockers",
        "Ready for pickup": "ready_for_pickup_raw",
    }


@dataclass
class SwarmPaths:
    """Resolved paths for a .swarm/ directory."""

    root: Path           # the .swarm/ directory
    bootstrap: Path
    context: Path
    state: Path
    queue: Path
    memory: Path
    workflows: Path

    @classmethod
    def from_swarm_dir(cls, swarm: Path) -> "SwarmPaths":
        """Construct SwarmPaths directly from a .swarm/ directory path."""
        return cls(
            root=swarm,
            bootstrap=swarm / "BOOTSTRAP.md",
            context=swarm / "context.md",
            state=swarm / "state.md",
            queue=swarm / "queue.md",
            memory=swarm / "memory.md",
            workflows=swarm / "workflows",
        )

    @classmethod
    def find(cls, start: Path | str = ".") -> "SwarmPaths | None":
        """Walk up from start until .swarm/ is found (max 5 levels)."""
        p = Path(start).resolve()
        for _ in range(5):
            swarm = p / ".swarm"
            if swarm.is_dir():
                return cls(
                    root=swarm,
                    bootstrap=swarm / "BOOTSTRAP.md",
                    context=swarm / "context.md",
                    state=swarm / "state.md",
                    queue=swarm / "queue.md",
                    memory=swarm / "memory.md",
                    workflows=swarm / "workflows",
                )
            parent = p.parent
            if parent == p:
                break
            p = parent
        return None

    def is_org_level(self) -> bool:
        """True if this .swarm/ is at org level (no .git/ in parent)."""
        return not (self.root.parent / ".git").exists()


# --- Helpers ---

def _parse_ts(s: str) -> datetime | None:
    try:
        return datetime.strptime(s.rstrip("Z"), "%Y-%m-%dT%H:%M")
    except ValueError:
        return None


def _fmt_ts(dt: datetime | None) -> str:
    if dt is None:
        return _now_ts()
    return dt.strftime("%Y-%m-%dT%H:%MZ")


def _now_ts() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ")
