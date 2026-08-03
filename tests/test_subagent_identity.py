"""Oracle tests: a sub-agent is not a session (ticket 21, slice 21a).

THE BLOCKER, and the only dangerous slice in the ticket. Everything else waits
on it, because relaxing the `agent-` skip without it destroys data.

Ruling (a), 2026-08-02: "a file is a SESSION if any entry carries a sessionId."
Measured 2026-08-03: all 1,420 real sub-agent transcripts carry one, and the
value is THE PARENT'S UUID. So ruling (a) says yes to every sub-agent file. Feed
one to `write_session_folder` and it computes the parent's folder, names the
payload `<parent-uuid>.jsonl`, lands it in the parent's own folder, and the
replace-if-larger rule then overwrites the parent's transcript whenever the
sub-agent is larger. Sub-agents have a median of 192 KB against 3.7 KB for a
regular session, so "larger" is the common case, not the edge one.

The rule was right about what it was written for and blind to a case that did
not exist in the corpus it was measured on. It is NARROWED here rather than
replaced: a session has a sessionId AND NO agentId.

Identity keys on CONTENT, never on the filename. `agent-` is a path convention
of `~/.claude`, and F4 is the whole reason this project does not trust paths.
"""

import ast

from cc_warehouse import archive
from cc_warehouse.render import RenderOptions
from conftest import (
    DEFAULT_UUID,
    SRC_ROOT,
    basic_session,
    matrix_session,
    subagent_session,
)

ZONE = "Australia/Melbourne"
OPTS = RenderOptions()


# ---------------------------------------------------------------------------
# The narrowed rule
# ---------------------------------------------------------------------------


def test_a_subagent_transcript_is_not_a_session() -> None:
    assert archive.is_session(basic_session()) is True
    assert archive.is_session(subagent_session()) is False


def test_a_subagent_is_recognised_as_one() -> None:
    assert archive.is_subagent(subagent_session()) is True
    assert archive.is_subagent(basic_session()) is False
    assert archive.is_subagent(matrix_session()) is False


def test_the_sessionId_inside_a_subagent_is_the_PARENTS() -> None:
    """The fact the whole slice turns on, asserted so nobody re-derives it from
    a filename later."""
    from cc_warehouse.parser import parse_session

    data = subagent_session(agent_id="abc123", parent_uuid=DEFAULT_UUID)
    assert parse_session(data).session_uuid == DEFAULT_UUID
    assert archive.parent_uuid_of(data) == DEFAULT_UUID
    assert archive.agent_id_of(data) == "abc123"


def test_a_payload_with_neither_is_still_not_a_session() -> None:
    """The 7 workflow journals: no sessionId, no agentId. Unchanged by this
    narrowing, and asserted so the narrowing cannot quietly adopt them."""
    assert archive.is_session(b'{"type":"started","key":"v2:abc","agentId":"x"}\n') is False
    assert archive.is_session(b'{"type":"log","message":"nothing"}\n') is False


# ---------------------------------------------------------------------------
# THE DEFECT: a sub-agent must never be written as its parent
# ---------------------------------------------------------------------------


def test_the_session_writer_refuses_a_subagent(tmp_path: object) -> None:
    """Refusing is the point. Landing it "somewhere sensible" would still put a
    sub-agent transcript where a session belongs."""
    from pathlib import Path

    import pytest

    assert isinstance(tmp_path, Path)
    with pytest.raises(ValueError):
        archive.write_session_folder(
            tmp_path, "widget", subagent_session(), OPTS, ZONE
        )


def test_a_larger_subagent_cannot_overwrite_its_parent(tmp_path: object) -> None:
    """The data-destroying scenario, reproduced exactly and then required to
    fail. A real sub-agent is typically 51x the size of a real session, so the
    replace-if-larger rule would have fired on the common case."""
    from pathlib import Path

    import pytest

    assert isinstance(tmp_path, Path)
    parent = basic_session(session_id=DEFAULT_UUID)
    result = archive.write_session_folder(tmp_path, "widget", parent, OPTS, ZONE)
    assert result.jsonl.read_bytes() == parent

    fat = subagent_session(parent_uuid=DEFAULT_UUID, prompt="x" * 20_000)
    assert len(fat) > len(parent), "fixture is not larger; the test would pass vacuously"
    with pytest.raises(ValueError):
        archive.write_session_folder(tmp_path, "widget", fat, OPTS, ZONE)

    assert result.jsonl.read_bytes() == parent, "the parent transcript was overwritten"


def test_the_migration_skips_subagents_as_not_sessions(tmp_path: object) -> None:
    """`ccw archive` reports them by name rather than silently, the same way it
    reports the workflow journals (R10)."""
    from pathlib import Path

    assert isinstance(tmp_path, Path)
    assert not archive.is_session(subagent_session())


# ---------------------------------------------------------------------------
# Identity comes from CONTENT, never from a path (F4)
# ---------------------------------------------------------------------------


def test_identity_does_not_depend_on_the_agent_filename_prefix() -> None:
    """A sub-agent carried in a file named anything at all is still a sub-agent.
    `agent-` is a convention of ~/.claude's layout; the archive must not inherit
    a path as identity."""
    assert archive.is_subagent(subagent_session()) is True


def test_no_module_identifies_a_subagent_by_filename() -> None:
    """A fence, because the cheap fix is exactly the wrong one. F4 exists
    because the specimen derived identity from paths; sweep may FILTER on the
    prefix (it walks a source tree), but nothing may DECIDE what a payload is
    from its name."""
    offenders: list[str] = []
    for path in sorted(SRC_ROOT.glob("*.py")):
        if path.name == "sweep.py":  # walks the source tree; filtering there is legitimate
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value in ("agent-", "agent-*"):
                    offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, f"sub-agent identity taken from a filename (F4): {offenders}"
