"""Oracle tests: sub-agent folders inside their session (ticket 21, 21b + 21c).

    <root>/<label>/<stamp>_<parent-uuid>/
        <parent-uuid>.jsonl        transcript.md  ...  manifest.json
        subagents/
            <stamp>_<agentId>/     <- a FOLDER, holding one file today
                <agentId>.jsonl
                meta.json

A FOLDER per sub-agent, not a loose file, and the reason is the day markdown and
HTML arrive for them (the principal's stated future). Loose files mean that day
restructures every session folder in a 13,829-folder archive; folders mean the
new files simply appear inside containers that already exist. The container
costs nothing now and buys a non-event later.

Contract: DESIGN 15 2026-08-02 (archive-first naming, start-keyed, zone pinned in
config); R2 (atomic writes); R4 as amended (a JSONL is never deletable, and this
module has no deletion primitive at all); R5 (conservative branch); F6.
"""

import ast
import json
from pathlib import Path

from cc_warehouse import archive, build, store
from cc_warehouse.render import RenderOptions
from conftest import (
    DEFAULT_UUID,
    SRC_ROOT,
    basic_session,
    subagent_meta,
    subagent_session,
)

ZONE = "Australia/Melbourne"
OPTS = RenderOptions()
LABEL = "widget"
AGENT = "a94d30c1d877f964d"
# The sub-agent fixture's own first entry is at 04:00:00Z -> 14:00:00 +1000.
AGENT_STAMP = "20260507-140000+1000"


def parent_folder(root: Path) -> Path:
    """Write the parent session and return its folder."""
    return archive.write_session_folder(
        root, LABEL, basic_session(session_id=DEFAULT_UUID), OPTS, ZONE
    ).directory


# ---------------------------------------------------------------------------
# 21b: the name
# ---------------------------------------------------------------------------


def test_the_subagent_folder_name_is_stamp_then_agent_id() -> None:
    assert build.subagent_folder_name(
        "2026-05-07T04:00:00.000Z", AGENT, ZONE
    ) == f"{AGENT_STAMP}_{AGENT}"


def test_the_zone_comes_from_config_not_the_machine() -> None:
    """Same determinism the session names rest on: a sub-agent must not be
    renamed by moving house."""
    assert build.subagent_folder_name("2026-05-07T04:00:00.000Z", AGENT, "UTC").startswith(
        "20260507-040000+0000_"
    )


def test_subagent_folders_sort_chronologically_by_plain_string_sort() -> None:
    """`ls subagents/` then reads in the order the agents actually ran, with no
    tooling at all - which is the whole reason the archive is start-keyed."""
    stamps = [
        "2026-05-07T04:00:00.000Z",
        "2026-05-07T04:00:01.000Z",
        "2026-05-07T09:30:00.000Z",
        "2026-05-08T01:00:00.000Z",
    ]
    names = [build.subagent_folder_name(s, AGENT, ZONE) for s in stamps]
    assert sorted(names) == names


def test_two_agents_in_the_same_second_do_not_collide() -> None:
    a = build.subagent_folder_name("2026-05-07T04:00:00.000Z", "agent-one", ZONE)
    b = build.subagent_folder_name("2026-05-07T04:00:00.000Z", "agent-two", ZONE)
    assert a != b


def test_an_undated_subagent_still_gets_a_stable_name() -> None:
    assert build.subagent_folder_name(None, AGENT, ZONE) == f"undated_{AGENT}"


def test_the_orphan_area_is_a_reserved_label() -> None:
    """A project called `_orphaned-subagents` would collide with the holding
    area, exactly as one called `locks` would collide with the lock dir."""
    assert archive.ORPHAN_LABEL in build.RESERVED_LABELS


# ---------------------------------------------------------------------------
# 21c: writing one
# ---------------------------------------------------------------------------


def test_a_subagent_lands_inside_its_parents_folder(tmp_path: Path) -> None:
    parent = parent_folder(tmp_path)
    result = archive.write_subagent(
        tmp_path, LABEL, subagent_session(agent_id=AGENT), ZONE, meta=subagent_meta()
    )
    assert result.directory.parent == parent / "subagents"
    assert result.directory.name == f"{AGENT_STAMP}_{AGENT}"
    assert not result.orphaned


def test_the_payload_is_byte_identical(tmp_path: Path) -> None:
    parent_folder(tmp_path)
    data = subagent_session(agent_id=AGENT)
    result = archive.write_subagent(tmp_path, LABEL, data, ZONE, meta=subagent_meta())
    assert result.jsonl.read_bytes() == data
    assert result.jsonl.name == f"{AGENT}.jsonl"


def test_the_meta_json_travels_with_it(tmp_path: Path) -> None:
    """It is the ONLY record of what the agent WAS. Without it you have 1,420
    folders and no way to tell a code reviewer from a researcher."""
    parent_folder(tmp_path)
    result = archive.write_subagent(
        tmp_path, LABEL, subagent_session(agent_id=AGENT), ZONE,
        meta=subagent_meta(agent_type="Explore", description="Inspect verify hook"),
    )
    meta = json.loads((result.directory / "meta.json").read_text(encoding="utf-8"))
    assert meta["agentType"] == "Explore"
    assert meta["description"] == "Inspect verify hook"


def test_no_markdown_or_html_is_generated(tmp_path: Path) -> None:
    """The principal's default: sub-agents are archived, not rendered. A flag to
    render them is recorded as future work, so the ABSENCE is asserted rather
    than left to be noticed."""
    parent_folder(tmp_path)
    result = archive.write_subagent(
        tmp_path, LABEL, subagent_session(agent_id=AGENT), ZONE, meta=subagent_meta()
    )
    names = {p.name for p in result.directory.iterdir()}
    assert names == {f"{AGENT}.jsonl", "meta.json"}


def test_a_missing_meta_is_not_fatal(tmp_path: Path) -> None:
    """R5. Claude Code writes the companion, but a source that lost it must not
    cost us the transcript."""
    parent_folder(tmp_path)
    result = archive.write_subagent(
        tmp_path, LABEL, subagent_session(agent_id=AGENT), ZONE, meta=None
    )
    assert result.jsonl.is_file()
    assert not (result.directory / "meta.json").exists()


def test_writing_twice_is_idempotent(tmp_path: Path) -> None:
    parent_folder(tmp_path)
    data = subagent_session(agent_id=AGENT)
    first = archive.write_subagent(tmp_path, LABEL, data, ZONE, meta=subagent_meta())
    before = first.jsonl.stat().st_mtime_ns
    archive.write_subagent(tmp_path, LABEL, data, ZONE, meta=subagent_meta())
    assert first.jsonl.stat().st_mtime_ns == before


def test_a_larger_payload_replaces_and_a_smaller_is_refused(tmp_path: Path) -> None:
    parent_folder(tmp_path)
    big = subagent_session(agent_id=AGENT, prompt="x" * 5_000)
    archive.write_subagent(tmp_path, LABEL, big, ZONE, meta=subagent_meta())
    small = subagent_session(agent_id=AGENT)
    result = archive.write_subagent(tmp_path, LABEL, small, ZONE, meta=subagent_meta())
    assert result.refused_smaller
    assert result.jsonl.read_bytes() == big


def test_an_equal_size_content_mismatch_is_refused_not_silently_dropped(
    tmp_path: Path,
) -> None:
    """The write_session_folder twin (ticket 30, closed 2026-08-23) had the same
    bug: equal SIZE was treated as proof of equal CONTENT (F1), with neither
    `replaced` nor `refused_smaller` set, so a genuinely different sub-agent
    payload of the same length was silently discarded - no error, no flag, no
    trace. Found by the 2026-08-23 architecture re-review (the fix that closed
    ticket 30 was applied only to write_session_folder, not its two siblings)
    and fixed here the same way: compare bytes, not just size, when they match."""
    parent_folder(tmp_path)
    archived = subagent_session(agent_id=AGENT, prompt="x" * 100)
    offered = subagent_session(agent_id=AGENT, prompt="y" * 100)
    assert len(offered) == len(archived), "fixture precondition: equal length"
    assert offered != archived, "fixture precondition: different content"

    archive.write_subagent(tmp_path, LABEL, archived, ZONE, meta=subagent_meta())
    result = archive.write_subagent(tmp_path, LABEL, offered, ZONE, meta=subagent_meta())

    assert result.refused_equal_size
    assert not result.replaced
    assert not result.refused_smaller
    assert result.jsonl.read_bytes() == archived, "the archived payload must survive"


def test_a_session_payload_is_refused_by_the_subagent_writer(tmp_path: Path) -> None:
    """The mirror of 21a's refusal, so neither writer can be handed the other's
    payload and quietly do something reasonable-looking with it."""
    import pytest

    with pytest.raises(ValueError):
        archive.write_subagent(tmp_path, LABEL, basic_session(), ZONE, meta=None)


# ---------------------------------------------------------------------------
# Orphans: no parent folder to nest under
# ---------------------------------------------------------------------------


def test_an_orphan_lands_in_the_reserved_area_under_its_project(
    tmp_path: Path,
) -> None:
    """Measured 2026-08-03: ZERO of the 1,420 real sub-agents are orphaned
    against the warehouse. This is a safety net for a case that does not exist
    today, which is exactly when it is cheap to build."""
    result = archive.write_subagent(
        tmp_path, LABEL, subagent_session(agent_id=AGENT), ZONE, meta=subagent_meta()
    )
    assert result.orphaned
    assert result.directory.parent.parent.name == archive.ORPHAN_LABEL
    assert result.jsonl.read_bytes() == subagent_session(agent_id=AGENT)


def test_an_orphan_records_the_parent_it_is_waiting_for(tmp_path: Path) -> None:
    """So a later sweep that finds the parent can re-home it. Re-homing itself
    is NOT built: moving a JSONL means deleting one, which R4 as amended forbids
    outright, so it would need to join R4's closed list of sanctioned
    external-world writers. Recorded with the constraint rather than left for
    someone to implement casually."""
    result = archive.write_subagent(
        tmp_path, LABEL, subagent_session(agent_id=AGENT, parent_uuid=DEFAULT_UUID),
        ZONE, meta=subagent_meta(),
    )
    waiting = json.loads((result.directory / "orphan.json").read_text(encoding="utf-8"))
    assert waiting["parent_session_uuid"] == DEFAULT_UUID
    assert waiting["agent_id"] == AGENT


def test_a_parent_arriving_later_does_not_duplicate_the_orphan(
    tmp_path: Path,
) -> None:
    """The orphan stays where it is. Writing a second copy under the parent
    would leave the archive holding the same transcript twice with no way to
    tell which is canonical."""
    data = subagent_session(agent_id=AGENT)
    orphan = archive.write_subagent(tmp_path, LABEL, data, ZONE, meta=subagent_meta())
    parent_folder(tmp_path)
    again = archive.write_subagent(tmp_path, LABEL, data, ZONE, meta=subagent_meta())
    assert again.directory != orphan.directory, "it should now nest under the parent"
    assert orphan.jsonl.is_file(), "the orphan copy must not be deleted (R4)"


# ---------------------------------------------------------------------------
# R4: still no deletion primitive anywhere in this module
# ---------------------------------------------------------------------------


def test_the_archive_module_still_has_no_deletion_primitive() -> None:
    """Re-asserted because this slice added a writer. R4 as amended is the
    load-bearing rule of the whole redesign: the module that maintains the tree
    must not be able to remove the only copy."""
    tree = ast.parse((SRC_ROOT / "archive.py").read_text(encoding="utf-8"))
    offenders = [
        f"archive.py:{node.lineno} .{node.func.attr}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"unlink", "rmdir", "rmtree", "remove", "removedirs"}
    ]
    assert not offenders, f"deletion primitives in the archive module (R4): {offenders}"


def test_the_subagent_jsonl_survives_repeated_writes(tmp_path: Path) -> None:
    parent_folder(tmp_path)
    data = subagent_session(agent_id=AGENT)
    result = archive.write_subagent(tmp_path, LABEL, data, ZONE, meta=subagent_meta())
    for _ in range(3):
        archive.write_subagent(tmp_path, LABEL, data, ZONE, meta=subagent_meta())
    assert result.jsonl.read_bytes() == data
    assert store.sha256_hex(result.jsonl.read_bytes()) == store.sha256_hex(data)


# ---------------------------------------------------------------------------
# Ticket 37 part A: meta.json is compared before it is written. Measured on the
# live archive 2026-09-06: the daily sweep rewrote 2,501 of 2,505 meta.json
# files because this function wrote the meta unconditionally, so every
# sub-agent folder's mtime said "today" whatever day its content arrived.
# ---------------------------------------------------------------------------


def test_identical_meta_written_twice_is_not_rewritten(tmp_path: Path) -> None:
    parent_folder(tmp_path)
    data = subagent_session(agent_id=AGENT)
    first = archive.write_subagent(tmp_path, LABEL, data, ZONE, meta=subagent_meta())
    meta_path = first.directory / "meta.json"
    before = meta_path.stat().st_mtime_ns
    dir_before = first.directory.stat().st_mtime_ns
    again = archive.write_subagent(tmp_path, LABEL, data, ZONE, meta=subagent_meta())
    assert meta_path.stat().st_mtime_ns == before
    assert first.directory.stat().st_mtime_ns == dir_before
    assert first.meta_written is True
    assert again.meta_written is False


def test_changed_meta_is_written(tmp_path: Path) -> None:
    parent_folder(tmp_path)
    data = subagent_session(agent_id=AGENT)
    archive.write_subagent(tmp_path, LABEL, data, ZONE, meta=subagent_meta())
    changed = subagent_meta(description="a different description")
    result = archive.write_subagent(tmp_path, LABEL, data, ZONE, meta=changed)
    assert result.meta_written is True
    assert (result.directory / "meta.json").read_bytes() == changed


def test_unchanged_reports_nothing_written(tmp_path: Path) -> None:
    """The flag the sweep leans on: neither the JSONL nor the meta moved."""
    parent_folder(tmp_path)
    data = subagent_session(agent_id=AGENT)
    archive.write_subagent(tmp_path, LABEL, data, ZONE, meta=subagent_meta())
    again = archive.write_subagent(tmp_path, LABEL, data, ZONE, meta=subagent_meta())
    assert again.unchanged is True
    assert again.replaced is False
    assert again.meta_written is False
