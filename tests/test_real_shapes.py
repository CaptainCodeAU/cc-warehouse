"""Oracle tests: the shapes a written suite never invents (ticket 18).

Every fixture below is derived from a MEASURED property of a real 13,836-session
corpus (census 2026-08-02), never from brainstorming. The suite is written from
the contract, and the contract describes what the product SHOULD do; neither
contains a 15 KB file-history snapshot or a message whose only content is a
base64 PDF, because nobody invents one.

Contract: DESIGN section 6 entry-type coverage ("the model now surfaces the
rest"); FINDINGS F6 (loss is never silent); DESIGN R9 (one implementation per
behaviour, so the dispatch is extended in place); principal ruling 2026-08-02
(option 4: classified markers plus a top-level `unrecognised` manifest key that
sits OUTSIDE the frozen `loss` set, because a rendered entry is not a lost one).
"""

import ast
import json
import tracemalloc
from pathlib import Path
from typing import cast

from cc_warehouse import parser
from cc_warehouse.parser import build_conversation, parse_session
from cc_warehouse.render import RenderOptions, build_manifest, render_html, render_markdown
from conftest import (
    SRC_ROOT,
    entry,
    hook_payload,
    jsonl,
    matrix_session,
    run_ccw,
    run_cli,
    session_count,
    warehouse_root,
    write_transcript,
)

# Every entry `type` observed across all 13,836 stored objects on 2026-08-02,
# with its count. This is the CENSUS, pinned: the fence below asserts the parser
# names every one of them, so a type cannot be added to the parser without
# appearing here and cannot appear here without the parser naming it.
CENSUS_ENTRY_TYPES = {
    "assistant": 154_763,
    "attachment": 144_157,
    "user": 103_601,
    "ai-title": 44_479,
    "last-prompt": 39_857,
    "queue-operation": 28_404,
    "permission-mode": 26_154,
    "mode": 19_165,
    "system": 16_600,
    "bridge-session": 16_459,
    "file-history-snapshot": 14_315,
    "agent-name": 8_476,
    "file-history-delta": 1_682,
    "custom-title": 910,
    "started": 173,
    "result": 173,
    "frame-link": 5,
}

# Content-block `type` values observed inside message.content in the same census.
CENSUS_BLOCK_TYPES = {
    "tool_use": 72_989,
    "tool_result": 72_988,
    "thinking": 43_060,
    "text": 38_768 + 2_723,
    "image": 87,
    "document": 2,
    "fallback": 1,
}

# `summary` carries zero occurrences in the corpus but parse_session reads it
# (SPEC 8 summary priority), so it is named-and-consumed like ai-title.
CONSUMED_BY_PARSE_SESSION = {"summary", "ai-title", "custom-title"}

UUID_MARKERS = "b1111111-2222-3333-4444-555555555551"
UUID_BLOCKS = "b1111111-2222-3333-4444-555555555552"
UUID_UNKNOWN = "b1111111-2222-3333-4444-555555555553"
UUID_HUGE = "b1111111-2222-3333-4444-555555555554"
UUID_NOSTAMP = "b1111111-2222-3333-4444-555555555555"
UUID_LONGLINE = "b1111111-2222-3333-4444-555555555556"
UUID_BARESTR = "b1111111-2222-3333-4444-555555555557"

CWD = "/home/alice/projects/widget"

# A distinctive value per unhandled entry type. Asserting on the VALUE rather
# than on the type name proves the entry was READ, not merely recognised.
MARKERS = {
    "permission-mode": "MARKERPERMMODE",
    "mode": "MARKERMODE",
    "file-history-delta": "MARKERDELTAPATH",
    "started": "MARKERAGENTID",
    "result": "MARKERRESULTPROSE",
    "frame-link": "MARKERFRAMETITLE",
    "custom-title": "MARKERCUSTOMTITLE",
}


def raw(kind: str, ts: str | None = None, **extra: object) -> dict[str, object]:
    """One JSONL entry with no `message` envelope. Several real machinery types
    carry no timestamp at all (permission-mode, mode, custom-title, ai-title),
    which is why `ts` is optional here."""
    record: dict[str, object] = {"type": kind, "sessionId": UUID_MARKERS}
    if ts is not None:
        record["timestamp"] = ts
    record.update(extra)
    return record


def unhandled_types_session(session_id: str = UUID_MARKERS) -> bytes:
    """A session carrying one instance of every entry type the v1 dispatch drops.

    Field shapes copied from the real corpus: permission-mode/mode/custom-title
    carry a single value and no timestamp; file-history-snapshot nests a
    `snapshot` object that reaches 15 KB in the wild; file-history-delta names a
    tracked path; started/result pair on an agentId and `result` carries a
    sub-agent's whole returned prose (mean 2,234 bytes, max 6,908).
    """
    return jsonl(
        entry(
            "user",
            "Audit the widget normalizer",
            "2026-01-05T10:00:00.000Z",
            session_id=session_id,
            cwd=CWD,
            gitBranch="main",
            version="2.0.0",
        ),
        raw("permission-mode", permissionMode=MARKERS["permission-mode"]),
        raw("mode", mode=MARKERS["mode"]),
        raw("ai-title", aiTitle="Model generated title"),
        raw("custom-title", customTitle=MARKERS["custom-title"]),
        entry(
            "assistant",
            [{"type": "text", "text": "Dispatching a reviewer."}],
            "2026-01-05T10:00:05.000Z",
            session_id=session_id,
            cwd=CWD,
        ),
        raw("started", key="v2:abc", agentId=MARKERS["started"]),
        raw(
            "result",
            key="v2:abc",
            agentId=MARKERS["started"],
            result={"summary": f"{MARKERS['result']} the branch is a strict ancestor."},
        ),
        raw(
            "file-history-snapshot",
            "2026-01-05T10:00:06.000Z",
            messageId="e56acf9f",
            snapshot={"messageId": "e56acf9f", "trackedFileBackups": {}},
            isSnapshotUpdate=False,
        ),
        raw(
            "file-history-delta",
            "2026-01-05T10:00:07.000Z",
            messageId="456bde03",
            trackingPath=f"/home/alice/projects/widget/{MARKERS['file-history-delta']}.py",
            backup={"backupFileName": None, "version": 1},
        ),
        raw(
            "frame-link",
            "2026-01-05T10:00:08.000Z",
            path="/home/alice/projects/widget/map.html",
            frameUrl="https://claude.ai/code/artifact/548733",
            title=MARKERS["frame-link"],
        ),
        entry(
            "assistant",
            [{"type": "text", "text": "Audit complete."}],
            "2026-01-05T10:00:09.000Z",
            session_id=session_id,
            cwd=CWD,
        ),
    )


def unhandled_blocks_session(session_id: str = UUID_BLOCKS) -> bytes:
    """A session whose message.content carries the three block types v1 drops.

    Real shapes: `image` and `document` wrap a base64 `source` (87 and 2 real
    cases; the corpus' largest single payload is 114 MB and 97% of it is block
    content), `fallback` records a model swap mid-reply (1 real case).
    """
    return jsonl(
        entry(
            "user",
            "Look at this",
            "2026-01-05T10:00:00.000Z",
            session_id=session_id,
            cwd=CWD,
            gitBranch="main",
        ),
        entry(
            "assistant",
            [
                {"type": "text", "text": "Reading it."},
                {
                    "type": "fallback",
                    "from": {"model": "claude-fable-5"},
                    "to": {"model": "claude-opus-5"},
                },
            ],
            "2026-01-05T10:00:01.000Z",
            session_id=session_id,
            cwd=CWD,
        ),
        entry(
            "user",
            [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": "iVBORw0KGgo" + "A" * 4000,
                    },
                },
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": "JVBERi0xLjQK" + "B" * 8000,
                    },
                },
            ],
            "2026-01-05T10:00:02.000Z",
            session_id=session_id,
            cwd=CWD,
        ),
        entry(
            "assistant",
            [{"type": "text", "text": "Seen."}],
            "2026-01-05T10:00:03.000Z",
            session_id=session_id,
            cwd=CWD,
        ),
    )


def full_markdown(data: bytes) -> str:
    full, _compact = render_markdown(data, RenderOptions())
    return full


def compact_markdown(data: bytes) -> str:
    _full, compact = render_markdown(data, RenderOptions())
    return compact


def full_html(data: bytes) -> str:
    page, _compact = render_html(data, RenderOptions())
    return page


# ---------------------------------------------------------------------------
# 1. Every entry type renders something OR increments a counter
# ---------------------------------------------------------------------------


def test_every_unhandled_entry_type_reaches_the_full_transcript() -> None:
    """DESIGN 6 promises the model "surfaces the rest"; F6 forbids a silent drop.

    Asserting on each type's own VALUE, not on its type name, proves the entry
    was read rather than merely matched.
    """
    text = full_markdown(unhandled_types_session())
    missing = [
        f"{kind} ({value})" for kind, value in MARKERS.items() if value not in text
    ]
    assert not missing, f"entry types dropped from transcript.md: {missing}"


def test_file_history_snapshot_is_marked_without_dumping_its_body() -> None:
    """14,315 real cases, up to 15,507 bytes each. The marker must name the
    entry without inlining the snapshot object."""
    text = full_markdown(unhandled_types_session())
    assert "file-history-snapshot" in text
    assert "trackedFileBackups" not in text


def test_result_keeps_the_whole_sub_agent_prose() -> None:
    """The 173 real `result` entries carry a sub-agent's full returned summary
    (mean 2,234 bytes, max 6,908). A one-line marker would bury a deliverable,
    which is the silent-loss class this ticket exists to close."""
    data = unhandled_types_session()
    text = full_markdown(data)
    assert "the branch is a strict ancestor." in text
    kinds = {b.kind for t in build_conversation(data).turns for b in t.blocks}
    assert "agent_result" in kinds


def test_a_structured_result_survives_without_a_summary_key() -> None:
    """Only 12 of the 173 real `result` entries carry `summary`. The other 161
    return a schema of their own (verdict/evidence 71, candidates 41, verdicts
    45, files/decisions/notes), so reading `summary` alone drops 93% of the
    sub-agent work this ticket exists to preserve. Measured 2026-08-02, after a
    first implementation here did exactly that."""
    data = jsonl(
        entry(
            "user",
            "Review it",
            "2026-01-05T10:00:00.000Z",
            session_id=UUID_MARKERS,
            cwd=CWD,
            gitBranch="main",
        ),
        {
            "type": "result",
            "sessionId": UUID_MARKERS,
            "agentId": "reviewer",
            "result": {
                "verdict": "STRUCTUREDVERDICT",
                "evidence": ["STRUCTUREDEVIDENCE one", "STRUCTUREDEVIDENCE two"],
            },
        },
    )
    text = full_markdown(data)
    assert "STRUCTUREDVERDICT" in text
    assert "STRUCTUREDEVIDENCE one" in text
    assert "STRUCTUREDEVIDENCE two" in text
    assert "STRUCTUREDVERDICT" in full_html(data)


def test_operator_custom_title_beats_the_model_ai_title() -> None:
    """`custom-title` is operator-set, `ai-title` is model-generated. 910 real
    sessions carry a custom title (principal ruling 2026-08-02)."""
    meta = parse_session(unhandled_types_session())
    assert meta.custom_title == MARKERS["custom-title"]
    assert meta.ai_title == "Model generated title"
    assert MARKERS["custom-title"] in full_markdown(unhandled_types_session())


def test_machinery_markers_stay_out_of_the_compact_variant() -> None:
    """The compact variant is prose-only by contract (DESIGN 6). Surfacing
    machinery must not leak into it, which is what keeps the ruling's blast
    radius to the full variants."""
    full = full_markdown(unhandled_types_session())
    compact = compact_markdown(unhandled_types_session())
    for kind in ("permission-mode", "mode", "file-history-snapshot"):
        needle = MARKERS.get(kind, kind)
        # Assert PRESENCE in full first: without this the test passes vacuously
        # while the markers do not exist at all, which is the green-for-the-
        # wrong-reason failure this suite's standing lessons warn about.
        assert needle in full, f"{kind} missing from the full variant"
        assert needle not in compact, f"{kind} leaked into compact"


def test_both_emitters_surface_the_same_entry_types() -> None:
    """The standing lesson from slice 14: a fix applied to one emitter and not
    the other passes a green suite. Assert the shared behaviour by construction."""
    data = unhandled_types_session()
    page = full_html(data)
    missing = [f"{k} ({v})" for k, v in MARKERS.items() if v not in page]
    assert not missing, f"entry types dropped from conversation.html: {missing}"


# ---------------------------------------------------------------------------
# 2. Every message.content block type likewise
# ---------------------------------------------------------------------------


def test_image_and_document_blocks_are_named_without_their_base64() -> None:
    """87 image and 2 document blocks in the corpus. The media type must
    survive; the base64 payload must never reach a projection."""
    data = unhandled_blocks_session()
    text = full_markdown(data)
    assert "image/png" in text
    assert "application/pdf" in text
    assert "iVBORw0KGgo" not in text
    assert "JVBERi0xLjQK" not in text


def test_fallback_block_records_the_model_swap() -> None:
    """1 real case: the assistant fell back from one model to another mid-reply."""
    text = full_markdown(unhandled_blocks_session())
    assert "claude-fable-5" in text
    assert "claude-opus-5" in text


def test_a_user_message_of_only_unhandled_blocks_still_produces_blocks() -> None:
    """v1 dropped the WHOLE message when its content list held no tool_result
    and no text, so an image-only message vanished with `loss: 0` beside it."""
    conv = build_conversation(unhandled_blocks_session())
    kinds = [b.kind for t in conv.turns for b in t.blocks]
    assert kinds.count("attachment") >= 2, kinds


def test_both_emitters_surface_the_same_block_types() -> None:
    page = full_html(unhandled_blocks_session())
    assert "image/png" in page
    assert "application/pdf" in page
    assert "claude-opus-5" in page


# ---------------------------------------------------------------------------
# 3. THE FENCE: an unrecognised type fails, by construction rather than by list
# ---------------------------------------------------------------------------


def _frozenset_type_literals() -> set[str]:
    """Every string constant in a module-level `*_TYPES` frozenset in parser.py.

    Modelled on test_fences.py's AST fences: it reads the SOURCE rather than
    trusting a hand-maintained list, so the fence cannot rot separately from the
    thing it fences.
    """
    tree = ast.parse((SRC_ROOT / "parser.py").read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if not any(
            n.endswith("_ENTRY_TYPES") and n != "KNOWN_ENTRY_TYPES" for n in names
        ):
            continue
        for sub in ast.walk(node.value):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                found.add(sub.value)
    return found


def test_known_entry_types_is_derived_from_the_named_sets() -> None:
    """KNOWN_ENTRY_TYPES must be the union of the parser's own dispatch sets, so
    naming a type in one place and forgetting the other is impossible."""
    assert _frozenset_type_literals() == set(parser.KNOWN_ENTRY_TYPES)


def test_the_parser_names_every_type_the_corpus_carries() -> None:
    """The 2026-08-02 census, pinned. A type measured in real data that the
    parser does not name is exactly the gap this ticket closes."""
    unnamed = sorted(set(CENSUS_ENTRY_TYPES) - set(parser.KNOWN_ENTRY_TYPES))
    assert not unnamed, f"real entry types the parser does not name: {unnamed}"


def test_the_census_pins_every_type_the_parser_names() -> None:
    """The other direction: a type named in the parser but absent from the
    census means the census was not re-run when the parser grew. `summary` is
    the sanctioned exception (SPEC 8 reads it; the corpus carries none)."""
    extra = sorted(set(parser.KNOWN_ENTRY_TYPES) - set(CENSUS_ENTRY_TYPES) - {"summary"})
    assert not extra, f"parser names types absent from the census: {extra}"


def test_an_unnamed_entry_type_is_rendered_and_counted() -> None:
    """The TRIPWIRE, and the durable half of this ticket. A one-time census of a
    living format goes stale by construction: `frame-link` first appeared
    2026-07-03 and `file-history-delta` 2026-07-14. When Claude Code ships the
    next one, the projection must show it AND the manifest must name it."""
    data = jsonl(
        entry(
            "user",
            "Hello",
            "2026-01-05T10:00:00.000Z",
            session_id=UUID_UNKNOWN,
            cwd=CWD,
            gitBranch="main",
        ),
        {"type": "some-future-type", "sessionId": UUID_UNKNOWN, "novelField": "NOVELMARKER"},
        entry(
            "assistant",
            [{"type": "text", "text": "Hi."}],
            "2026-01-05T10:00:01.000Z",
            session_id=UUID_UNKNOWN,
            cwd=CWD,
        ),
    )
    assert "some-future-type" in full_markdown(data)
    unrecognised = cast(
        "dict[str, object]", build_manifest(data, RenderOptions())["unrecognised"]
    )
    assert unrecognised["count"] == 1
    # The manifest name matches the marker text in the transcript EXACTLY, so a
    # reader who sees `entry:some-future-type` in the manifest can grep the
    # projection for the identical string, and an entry type is never confused
    # with a content-block type of the same name.
    assert unrecognised["types"] == ["entry:some-future-type"]


def test_an_unnamed_content_block_type_is_rendered_and_counted() -> None:
    """Same tripwire one level down: message.content grew `fallback` too."""
    data = jsonl(
        entry(
            "user",
            "Hello",
            "2026-01-05T10:00:00.000Z",
            session_id=UUID_UNKNOWN,
            cwd=CWD,
            gitBranch="main",
        ),
        entry(
            "assistant",
            [{"type": "some-future-block", "payload": "NOVELBLOCK"}],
            "2026-01-05T10:00:01.000Z",
            session_id=UUID_UNKNOWN,
            cwd=CWD,
        ),
    )
    assert "some-future-block" in full_markdown(data)
    unrecognised = cast(
        "dict[str, object]", build_manifest(data, RenderOptions())["unrecognised"]
    )
    assert unrecognised["count"] == 1
    assert unrecognised["types"] == ["block:some-future-block"]


def test_a_fully_known_session_reports_zero_unrecognised() -> None:
    """`unrecognised` sits OUTSIDE the frozen `loss` key set on purpose: a
    rendered entry is not a lost one, and calling it loss would be F6 pointing
    the other way. It reads zero for every session in today's corpus."""
    manifest = build_manifest(matrix_session(), RenderOptions())
    assert "unrecognised" not in cast("dict[str, object]", manifest["loss"])
    unrecognised = cast("dict[str, object]", manifest["unrecognised"])
    assert unrecognised == {"count": 0, "types": []}


# ---------------------------------------------------------------------------
# 4. Scale: a 100 MB payload renders without exhausting memory
# ---------------------------------------------------------------------------

# Measured ceiling, as a multiple of the payload size. The real corpus' largest
# object is 114,154,804 bytes across 1,673 lines: 291 user entries carry 111 MB
# of it, so the shape that matters is a FEW very large entries, not many small
# ones. MEASURED 2026-08-02: a 104,868,489-byte payload peaks at 943,779,996
# bytes of traced heap, a ratio of 9.00x, and emits 104,859,578 characters of
# markdown. The ceiling is pinned at 12x, a third above the observation, so it
# catches a step change in cost without failing on ordinary variance. It is not
# a target: if a future change makes rendering cheaper, LOWER it.
HUGE_PEAK_MULTIPLE = 12.0


def huge_session() -> bytes:
    """~100 MB in the shape the real 114 MB object has: a handful of entries
    carrying enormous tool_result payloads."""
    chunk = "x" * (5 * 1024 * 1024)
    lines: list[dict[str, object] | str] = [
        entry(
            "user",
            "Run the big job",
            "2026-01-05T10:00:00.000Z",
            session_id=UUID_HUGE,
            cwd=CWD,
            gitBranch="main",
        )
    ]
    for i in range(20):
        lines.append(
            entry(
                "assistant",
                [{"type": "tool_use", "id": f"t{i}", "name": "Bash", "input": {"command": "run"}}],
                "2026-01-05T10:00:01.000Z",
                session_id=UUID_HUGE,
                cwd=CWD,
            )
        )
        lines.append(
            entry(
                "user",
                [{"type": "tool_result", "tool_use_id": f"t{i}", "content": chunk}],
                "2026-01-05T10:00:02.000Z",
                session_id=UUID_HUGE,
                cwd=CWD,
            )
        )
    return jsonl(*lines)


def test_a_100mb_payload_renders_within_a_bounded_memory_ceiling() -> None:
    """The corpus' largest object is 114.2 MB. Nothing in the suite has ever
    pinned that it renders at all, let alone what it costs."""
    data = huge_session()
    assert len(data) > 100 * 1024 * 1024, len(data)
    tracemalloc.start()
    try:
        text = full_markdown(data)
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert "Run the big job" in text
    ceiling = int(len(data) * HUGE_PEAK_MULTIPLE)
    assert peak < ceiling, f"peak {peak:,} exceeded ceiling {ceiling:,} for {len(data):,} bytes"


# ---------------------------------------------------------------------------
# 5. A session with no timestamp anywhere
# ---------------------------------------------------------------------------


def test_a_session_with_no_timestamp_anywhere_renders() -> None:
    """9 real cases. Turn.first_ts/last_ts are None throughout, so every elapsed
    label and the Captured span must degrade rather than raise."""
    data = jsonl(
        {
            "type": "user",
            "sessionId": UUID_NOSTAMP,
            "cwd": CWD,
            "message": {"role": "user", "content": "No clock here"},
        },
        {
            "type": "assistant",
            "sessionId": UUID_NOSTAMP,
            "cwd": CWD,
            "message": {"role": "assistant", "content": [{"type": "text", "text": "Noted."}]},
        },
    )
    meta = parse_session(data)
    assert meta.first_ts is None
    assert meta.last_ts is None
    text = full_markdown(data)
    assert "No clock here" in text
    assert "Noted." in text
    assert "conversation.html" or full_html(data)
    assert "Noted." in full_html(data)


# ---------------------------------------------------------------------------
# 6. A single JSONL line over 1 MB
# ---------------------------------------------------------------------------


def test_a_single_jsonl_line_over_1mb_renders() -> None:
    """36 real cases. A line cap or a per-line buffer would silently truncate
    the largest single thing a session contains."""
    blob = "M" * (1_200_000)
    data = jsonl(
        entry(
            "user",
            "Paste the log",
            "2026-01-05T10:00:00.000Z",
            session_id=UUID_LONGLINE,
            cwd=CWD,
            gitBranch="main",
        ),
        entry(
            "assistant",
            [{"type": "text", "text": f"LONGLINEMARKER{blob}"}],
            "2026-01-05T10:00:01.000Z",
            session_id=UUID_LONGLINE,
            cwd=CWD,
        ),
    )
    longest = max(len(line) for line in data.splitlines())
    assert longest > 1_000_000, longest
    text = full_markdown(data)
    assert "LONGLINEMARKER" in text
    assert build_manifest(data, RenderOptions())["loss"] == {
        "skipped_lines": 0,
        "truncated_blocks": 0,
        "truncated_chars": 0,
        "unencodable_chars": 0,
    }


# ---------------------------------------------------------------------------
# 7. message.content as a bare string, not a list
# ---------------------------------------------------------------------------


def test_message_content_as_a_bare_string_renders() -> None:
    """27,913 real cases. Handled today, but nothing pinned it, so a future
    refactor that assumed a block array would have passed every gate."""
    data = jsonl(
        entry(
            "user",
            "BARESTRUSER prompt as a plain string",
            "2026-01-05T10:00:00.000Z",
            session_id=UUID_BARESTR,
            cwd=CWD,
            gitBranch="main",
        ),
        {
            "type": "assistant",
            "timestamp": "2026-01-05T10:00:01.000Z",
            "sessionId": UUID_BARESTR,
            "cwd": CWD,
            "message": {"role": "assistant", "content": "BARESTRASSISTANT reply as a plain string"},
        },
    )
    conv = build_conversation(data)
    assert conv.prompt_count == 1
    text = full_markdown(data)
    assert "BARESTRUSER" in text
    assert "BARESTRASSISTANT" in text


# ---------------------------------------------------------------------------
# The regression anchor must not move: this ticket is purely additive
# ---------------------------------------------------------------------------


def test_matrix_session_gains_no_unrecognised_types() -> None:
    """matrix_session carries only types the v1 dispatch already handled, so
    tests/golden/matrix-anchor is expected to hold byte for byte. If this fails,
    the change is not additive and the anchor is NOT the thing to regenerate."""
    conv = build_conversation(matrix_session())
    assert conv.unrecognised == ()
    assert conv.unrecognised_count == 0


def test_the_manifest_loss_key_set_is_unchanged() -> None:
    """The ruling's whole point: `unrecognised` is a new TOP-LEVEL key, not a
    third amendment to the frozen `loss` set."""
    manifest = build_manifest(matrix_session(), RenderOptions())
    assert set(cast("dict[str, object]", manifest["loss"])) == {
        "skipped_lines",
        "truncated_blocks",
        "truncated_chars",
        "unencodable_chars",
    }


def test_golden_anchor_files_are_present_and_untouched_by_this_ticket() -> None:
    """A guard rail, not a duplicate of test_matrix.py: it asserts the anchor
    directory still holds its four files so a future session cannot quietly
    delete them to make a diff pass."""
    anchor = Path(__file__).resolve().parent / "golden" / "matrix-anchor"
    names = {p.name for p in anchor.iterdir() if p.is_file()}
    assert names == {
        "transcript.md",
        "transcript.compact.md",
        "conversation.html",
        "conversation.compact.html",
    }


def test_unrecognised_reaches_manifest_json_on_disk(ccw_env: dict[str, str]) -> None:
    """End to end, because a key that exists only in build_manifest's return
    value is a key the operator never sees. Captured and built through the real
    verbs, in a sandboxed warehouse.

    The fixture carries its OWN session UUID and ASSERTS it stored: sessions
    sharing conftest's DEFAULT_UUID form a supersede chain, and a fixture that
    silently fails to capture makes every downstream assertion vacuously true
    (the two false diagnoses recorded in ticket 17).
    """
    data = jsonl(
        entry(
            "user",
            "Ship it",
            "2026-01-05T10:00:00.000Z",
            session_id=UUID_UNKNOWN,
            cwd=CWD,
            gitBranch="main",
            slug="ship-it",
        ),
        {"type": "some-future-type", "sessionId": UUID_UNKNOWN, "novelField": "x"},
        entry(
            "assistant",
            [{"type": "text", "text": "Shipped."}],
            "2026-01-05T10:00:01.000Z",
            session_id=UUID_UNKNOWN,
            cwd=CWD,
        ),
    )
    transcript = write_transcript(ccw_env, data, session_id=UUID_UNKNOWN)
    captured = run_ccw(["hook"], ccw_env, stdin=hook_payload(transcript, cwd=None))
    assert captured.code == 0, captured.err
    assert session_count(ccw_env) == 1, "fixture did not store; every assert below is vacuous"

    built = run_cli(["build"])
    assert built.code == 0, built.err
    manifests = list((warehouse_root(ccw_env) / "projections").glob("*/*/manifest.json"))
    assert len(manifests) == 1, manifests
    payload = cast(
        "dict[str, object]", json.loads(manifests[0].read_text(encoding="utf-8"))
    )
    assert payload["unrecognised"] == {"count": 1, "types": ["entry:some-future-type"]}
    assert set(cast("dict[str, object]", payload["loss"])) == {
        "skipped_lines",
        "truncated_blocks",
        "truncated_chars",
        "unencodable_chars",
    }


def test_census_counts_are_recorded_for_the_next_reader() -> None:
    """Not behaviour: provenance. The counts above are the evidence the fence
    rests on, and a reader six months from now needs to know they were measured
    on 2026-08-02 over 13,836 objects rather than invented."""
    assert sum(CENSUS_ENTRY_TYPES.values()) > 600_000
    unhandled_in_v1 = sum(
        CENSUS_ENTRY_TYPES[k]
        for k in (
            "permission-mode",
            "mode",
            "file-history-snapshot",
            "file-history-delta",
            "custom-title",
            "started",
            "result",
            "frame-link",
        )
    )
    assert unhandled_in_v1 == 62_577
    assert sum(CENSUS_BLOCK_TYPES[k] for k in ("image", "document", "fallback")) == 90
    assert json.dumps(sorted(CONSUMED_BY_PARSE_SESSION))
