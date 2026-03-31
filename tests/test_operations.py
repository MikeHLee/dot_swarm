"""Tests for swarm_city.operations — core read/write/lifecycle logic."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from swarm_city.models import Priority, SwarmPaths, WorkItem
from swarm_city.operations import (
    add_item,
    append_memory,
    audit,
    block_item,
    claim_item,
    done_item,
    next_item_id,
    partial_item,
    read_queue,
    read_state,
    write_state,
    _division_code_from_paths,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def swarm_dir(tmp_path: Path) -> SwarmPaths:
    """Create a minimal .swarm/ directory in a temp folder."""
    div_root = tmp_path / "oasis-cloud"
    div_root.mkdir()
    swarm = div_root / ".swarm"
    swarm.mkdir()

    (swarm / "queue.md").write_text(
        "# Queue\n\n## Active\n\n(none)\n\n## Pending\n\n(none)\n\n## Done\n\n(none)\n"
    )
    (swarm / "state.md").write_text(
        "# State\n\n**Last touched**: 2026-01-01T00:00Z by test\n"
        "**Current focus**: testing\n**Active items**: (none)\n**Blockers**: (none)\n"
    )
    (swarm / "memory.md").write_text("# Memory\n\n(empty)\n")
    (swarm / "context.md").write_text("# Context\n\n## What This Division Is\n\nTest.\n")
    (swarm / "BOOTSTRAP.md").write_text("# Bootstrap\n\nTest bootstrap.\n")

    return SwarmPaths.find(div_root)


# ---------------------------------------------------------------------------
# Division code
# ---------------------------------------------------------------------------

def test_division_code_from_known_name(swarm_dir: SwarmPaths) -> None:
    assert _division_code_from_paths(swarm_dir) == "CLD"


def test_division_code_fallback(tmp_path: Path) -> None:
    mystery = tmp_path / "mystery-service" / ".swarm"
    mystery.mkdir(parents=True)
    paths = SwarmPaths.from_swarm_dir(mystery)
    code = _division_code_from_paths(paths)
    assert len(code) <= 4
    assert code == code.upper()


# ---------------------------------------------------------------------------
# Queue: add / read
# ---------------------------------------------------------------------------

def test_add_item_creates_pending(swarm_dir: SwarmPaths) -> None:
    add_item(swarm_dir, "Fix Redis timeout", priority=Priority.HIGH, project="infra")
    _, pending, _ = read_queue(swarm_dir)
    assert len(pending) == 1
    assert pending[0].description == "Fix Redis timeout"
    assert pending[0].priority == Priority.HIGH
    assert pending[0].project == "infra"


def test_item_id_sequential(swarm_dir: SwarmPaths) -> None:
    add_item(swarm_dir, "Task one")
    add_item(swarm_dir, "Task two")
    _, pending, _ = read_queue(swarm_dir)
    ids = [i.id for i in pending]
    assert ids[0].endswith("-001")
    assert ids[1].endswith("-002")


def test_ids_never_reused(swarm_dir: SwarmPaths) -> None:
    add_item(swarm_dir, "Task one")
    _, pending, _ = read_queue(swarm_dir)
    claim_item(swarm_dir, pending[0].id, "test-agent")
    done_item(swarm_dir, pending[0].id, "test-agent")
    add_item(swarm_dir, "Task two")
    _, pending2, done = read_queue(swarm_dir)
    assert len(pending2) == 1
    assert pending2[0].id != done[0].id


# ---------------------------------------------------------------------------
# Lifecycle: claim → done
# ---------------------------------------------------------------------------

def test_claim_moves_to_active(swarm_dir: SwarmPaths) -> None:
    add_item(swarm_dir, "Do a thing")
    _, pending, _ = read_queue(swarm_dir)
    item_id = pending[0].id
    claim_item(swarm_dir, item_id, "agent-x")
    active, pending2, _ = read_queue(swarm_dir)
    assert len(active) == 1
    assert len(pending2) == 0
    assert active[0].claimed_by == "agent-x"


def test_done_moves_to_done(swarm_dir: SwarmPaths) -> None:
    add_item(swarm_dir, "Do a thing")
    _, pending, _ = read_queue(swarm_dir)
    item_id = pending[0].id
    claim_item(swarm_dir, item_id, "agent-x")
    done_item(swarm_dir, item_id, "agent-x", note="all good")
    active, pending2, done = read_queue(swarm_dir)
    assert len(active) == 0
    assert len(done) == 1
    assert "all good" in (done[0].notes or "")


def test_claim_nonexistent_raises(swarm_dir: SwarmPaths) -> None:
    with pytest.raises(ValueError, match="not found"):
        claim_item(swarm_dir, "CLD-999", "agent-x")


# ---------------------------------------------------------------------------
# Lifecycle: partial / block
# ---------------------------------------------------------------------------

def test_partial_keeps_in_active(swarm_dir: SwarmPaths) -> None:
    add_item(swarm_dir, "Long task")
    _, pending, _ = read_queue(swarm_dir)
    item_id = pending[0].id
    claim_item(swarm_dir, item_id, "agent-x")
    partial_item(swarm_dir, item_id, "agent-x", note="halfway done")
    active, _, _ = read_queue(swarm_dir)
    assert len(active) == 1
    assert "halfway done" in (active[0].notes or active[0].description)


def test_block_marks_item(swarm_dir: SwarmPaths) -> None:
    add_item(swarm_dir, "Blocked task")
    _, pending, _ = read_queue(swarm_dir)
    item_id = pending[0].id
    claim_item(swarm_dir, item_id, "agent-x")
    block_item(swarm_dir, item_id, "Waiting for staging creds")
    active, _, _ = read_queue(swarm_dir)
    assert len(active) == 1
    assert active[0].state.value == "BLOCKED"


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

def test_write_and_read_state(swarm_dir: SwarmPaths) -> None:
    write_state(swarm_dir, {"Current focus": "new focus", "Blockers": "(none)"})
    state = read_state(swarm_dir)
    assert state.get("Current focus") == "new focus"


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------

def test_append_memory(swarm_dir: SwarmPaths) -> None:
    append_memory(swarm_dir, "messaging", "Chose NATS over Kafka", "lower latency")
    content = swarm_dir.memory.read_text()
    assert "NATS" in content
    assert "Kafka" in content


def test_memory_is_append_only(swarm_dir: SwarmPaths) -> None:
    append_memory(swarm_dir, "t1", "First entry", "reason one")
    append_memory(swarm_dir, "t2", "Second entry", "reason two")
    content = swarm_dir.memory.read_text()
    assert "First entry" in content
    assert "Second entry" in content


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

def test_audit_flags_stale_items(swarm_dir: SwarmPaths) -> None:
    add_item(swarm_dir, "Stale task")
    _, pending, _ = read_queue(swarm_dir)
    # Manually backdate the claim stamp by rewriting queue
    item_id = pending[0].id
    claim_item(swarm_dir, item_id, "agent-x")
    # Backdate the queue file's mtime to simulate staleness
    raw = swarm_dir.queue.read_text()
    backdated = raw.replace("2026", "2024")  # crude backdating
    swarm_dir.queue.write_text(backdated)
    stale = audit(swarm_dir, stale_hours=1)
    assert len(stale) >= 1
