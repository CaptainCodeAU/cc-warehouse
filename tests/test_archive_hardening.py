"""Oracle tests: the three archive gaps the coverage census found (2026-08-02).

None of these was found by reading the code. They came from asking what the
archive path does NOT have that every comparable surface does, and from asking
which real-data classes had never travelled it.

1. R14. archive.py was the only write surface in the codebase taking no lock,
   while build, capture, migrate, relocate and sweep all take one. Its
   replace-if-larger path stats a file and then writes it, which is a TOCTOU
   window, so identity-idempotence does NOT make the race harmless and R14's
   own wording therefore requires a lock.
2. Lone surrogates. 11 real sessions carry them and they broke the first build
   at scale on 2026-08-01. They survived the real migration, but by luck rather
   than by proof: the only mention in the archive tests was a comment string.
3. Scale. test_real_shapes pins a 100 MB RENDER; nothing pinned a 100 MB
   archive WRITE, though the corpus' largest object is 114 MB.

Contract: R14 (locks, F3), R2 (atomic writes), R1 as amended (size answers a
different question from identity), F6 (loss is never silent), DESIGN 15
2026-08-01 (lone surrogates: the store keeps the original bytes).
"""

import json
import tracemalloc
from pathlib import Path

from cc_warehouse import archive, store
from cc_warehouse.render import RenderOptions
from conftest import DEAD_PID, entry, jsonl, warehouse_root

ZONE = "Australia/Melbourne"
OPTS = RenderOptions()
LABEL = "widget"
UUID_S = "b9111111-2222-3333-4444-555555555551"
UUID_H = "b9111111-2222-3333-4444-555555555552"


# ---------------------------------------------------------------------------
# 1. R14: the archive takes a lock, and a live holder makes it refuse
# ---------------------------------------------------------------------------


def test_archive_is_not_the_one_write_surface_without_a_lock() -> None:
    """A structural fence, because this gap was invisible for a whole slice and
    would be invisible again. Every module that writes into the warehouse takes
    a `locks/<op>` lock; archive.py was the exception and R14 has no exception
    clause for it."""
    import ast

    from conftest import SRC_ROOT

    tree = ast.parse((SRC_ROOT / "archive.py").read_text(encoding="utf-8"))
    names = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "acquire_lock" in names, "archive.py performs writes without taking a lock (R14)"
    assert "release_lock" in names, "archive.py acquires a lock it never releases"


def test_migrate_refuses_while_a_live_holder_owns_the_lock(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Coordination by assumption is a rejection (R14/F3). A second migration
    into the same tree must refuse rather than interleave with the first."""
    root = warehouse_root(ccw_env)
    root.mkdir(parents=True, exist_ok=True)
    assert store.acquire_lock(root, archive.ARCHIVE_LOCK), "fixture failed to take the lock"
    try:
        report = archive.migrate(root, tmp_path / "archive", OPTS, ZONE)
    finally:
        store.release_lock(root, archive.ARCHIVE_LOCK)
    assert report.lock_held
    assert report.written == 0
    assert "lock" in report.summary().lower()


def test_a_stale_lock_from_a_dead_holder_does_not_block_forever(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """acquire_lock takes over a dead-PID lock. Asserted here because the
    opposite failure - an archive permanently unbuildable after one crash - is
    the kind that gets 'fixed' by deleting a lock file by hand."""
    root = warehouse_root(ccw_env)
    lock = root / "locks" / f"{archive.ARCHIVE_LOCK}.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(str(DEAD_PID), encoding="utf-8")

    report = archive.migrate(root, tmp_path / "archive", OPTS, ZONE)
    assert not report.lock_held


def test_the_lock_is_released_so_a_second_run_succeeds(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The other half: a lock taken and never released turns a one-shot failure
    into a permanent one."""
    root = warehouse_root(ccw_env)
    target = tmp_path / "archive"
    first = archive.migrate(root, target, OPTS, ZONE)
    second = archive.migrate(root, target, OPTS, ZONE)
    assert not first.lock_held
    assert not second.lock_held


# ---------------------------------------------------------------------------
# 2. Lone surrogates: the class that broke the first build at scale
# ---------------------------------------------------------------------------


def surrogate_session(uuid: str = UUID_S) -> bytes:
    r"""A payload carrying a LONE surrogate, exactly as Claude Code emits one.

    `\ud83d` is the HIGH half of an emoji pair, left behind when a field is
    truncated mid-character. json.loads decodes it into a legal Python str that
    has no utf-8 encoding at all, so the render succeeds and the WRITE fails.
    Written as a raw escape in the JSON text, which is how it arrives.
    """
    good = jsonl(
        entry(
            "user",
            "Look at this emoji",
            "2026-05-07T03:47:45.000Z",
            session_id=uuid,
            gitBranch="main",
        )
    )
    broken = (
        '{"type":"assistant","timestamp":"2026-05-07T03:47:50.000Z","sessionId":"'
        + uuid
        + '","message":{"role":"assistant","content":[{"type":"text",'
        '"text":"SURROGATEMARKER \\ud83d here"}]}}\n'
    )
    return good + broken.encode("utf-8")


def test_a_lone_surrogate_payload_writes_an_archive_folder_at_all(
    tmp_path: Path,
) -> None:
    """The regression itself: this exact shape raised UnicodeEncodeError and
    killed 9 of 13,608 sessions on 2026-08-01."""
    result = archive.write_session_folder(
        tmp_path, LABEL, surrogate_session(), OPTS, ZONE
    )
    assert result.jsonl.exists()
    assert result.wrote_projections
    assert (result.directory / "transcript.md").exists()


def test_the_archived_jsonl_keeps_the_ORIGINAL_bytes(tmp_path: Path) -> None:
    """The property DESIGN 15 promises: "the store is untouched by construction:
    the original bytes, escape and all, stay recoverable". Under archive-first
    the archive IS the store, so the promise moves to this file. The scrub is a
    RENDERING decision and must not reach the source."""
    data = surrogate_session()
    result = archive.write_session_folder(tmp_path, LABEL, data, OPTS, ZONE)
    assert result.jsonl.read_bytes() == data
    assert rb"\ud83d" in result.jsonl.read_bytes()


def test_the_projection_replaced_it_and_the_manifest_counted_it(
    tmp_path: Path,
) -> None:
    """F6: replacing silently is the failure, not the replacement."""
    result = archive.write_session_folder(
        tmp_path, LABEL, surrogate_session(), OPTS, ZONE
    )
    text = (result.directory / "transcript.md").read_text(encoding="utf-8")
    assert "SURROGATEMARKER" in text
    assert "�" in text
    manifest = json.loads((result.directory / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["loss"]["unencodable_chars"] == 1


def test_verify_passes_a_surrogate_folder(tmp_path: Path) -> None:
    """source_hash is computed over the ORIGINAL bytes, so a scrubbed projection
    must not make its own folder fail integrity."""
    result = archive.write_session_folder(
        tmp_path, LABEL, surrogate_session(), OPTS, ZONE
    )
    assert archive.verify_folder(result.directory, ZONE) == []


# ---------------------------------------------------------------------------
# 3. Scale: a 100 MB payload through the archive WRITE path
# ---------------------------------------------------------------------------

# MEASURED 2026-08-02, per stage, after a first guess of 14x was wrong by 5x and
# the cause turned out not to be where I assumed:
#
#     build_conversation   0.39 GiB    4.0x
#     render_markdown      0.88 GiB    9.0x   ->  100 MiB of markdown
#     render_html          7.26 GiB   74.3x   ->  633 MiB of HTML
#     build_manifest       0.39 GiB    4.0x
#
# The HTML emitter is the whole cost. Each block's markdown fragment is carried
# base64 in its row's data-copy-src AND again inside the phase's, so content
# appears about three times over with a 33% base64 penalty on two of them.
#
# THE FIXTURE IS A DELIBERATE WORST CASE and the ceiling is not a target. Its
# tool results carry no `toolUseResult`, so each 5 MiB blob renders as a raw
# fence. Real data does not look like this: the corpus' largest object is 114 MB
# and renders to about 6 MB of HTML, and the largest page in the whole migrated
# archive is 17.7 MiB. So this pins a LATENT bound, not a live problem, and it
# exists so a change that doubles the cost is caught rather than discovered on
# the day someone's session finally is shaped like this.
ARCHIVE_PEAK_MULTIPLE = 90.0

# The same measurement stated the way a reader cares about: how big is the file
# I have to open. 633 MiB of HTML from 100 MiB of payload is 6.3x.
ARCHIVE_HTML_MULTIPLE = 8.0


def huge_session() -> bytes:
    """~100 MB in the shape the real 114 MB object has: a few enormous tool
    results, not many small entries."""
    chunk = "y" * (5 * 1024 * 1024)
    lines: list[dict[str, object] | str] = [
        entry(
            "user",
            "Run the big job",
            "2026-05-07T03:47:45.000Z",
            session_id=UUID_H,
            gitBranch="main",
        )
    ]
    for i in range(20):
        lines.append(
            entry(
                "assistant",
                [{"type": "tool_use", "id": f"t{i}", "name": "Bash", "input": {"command": "run"}}],
                "2026-05-07T03:47:46.000Z",
                session_id=UUID_H,
            )
        )
        lines.append(
            entry(
                "user",
                [{"type": "tool_result", "tool_use_id": f"t{i}", "content": chunk}],
                "2026-05-07T03:47:47.000Z",
                session_id=UUID_H,
            )
        )
    return jsonl(*lines)


def test_a_100mb_payload_archives_within_a_bounded_ceiling(tmp_path: Path) -> None:
    """The corpus' largest object is 114,154,804 bytes and it migrated fine in
    the real run. Nothing pinned that, so nothing would notice if a future
    change made the archive path hold two copies instead of one."""
    data = huge_session()
    assert len(data) > 100 * 1024 * 1024, len(data)
    tracemalloc.start()
    try:
        result = archive.write_session_folder(tmp_path, LABEL, data, OPTS, ZONE)
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    ceiling = int(len(data) * ARCHIVE_PEAK_MULTIPLE)
    assert peak < ceiling, f"peak {peak:,} exceeded ceiling {ceiling:,}"
    assert result.jsonl.stat().st_size == len(data)

    # The operator-facing half of the same fact: the page has to be openable.
    page = (result.directory / "conversation.html").stat().st_size
    assert page < len(data) * ARCHIVE_HTML_MULTIPLE, (
        f"conversation.html is {page:,} bytes from a {len(data):,} byte payload"
    )


def test_the_huge_archived_jsonl_is_byte_identical(tmp_path: Path) -> None:
    """Hashed rather than compared in memory: holding a second 100 MB copy to
    assert equality would make the test the thing that runs out of memory."""
    data = huge_session()
    result = archive.write_session_folder(tmp_path, LABEL, data, OPTS, ZONE)
    assert store.sha256_hex(result.jsonl.read_bytes()) == store.sha256_hex(data)
