"""Oracle tests: an equal-size, content-different refusal must not render
(ticket 30's flagged case, mechanism 2's twin, closed 2026-08-23).

Contract: DESIGN 15 entry 2026-08-02 (replace-if-larger), R1 as amended (size
answers "which of two differing payloads is larger", never "are these the same
bytes"), R5/F7 (the conservative branch), F6 (loss is never silent).

THE DEFECT, flagged in `harness/tickets/30-incremental-archive-rebuild.md`'s
"Not done here" section when mechanism 2 (test_refused_render.py) shipped, and
closed here. `archive.write_session_folder` treated EQUAL size as proof of
identical content ("Equal size is left alone; identical content is the common
case") without ever checking. A re-captured payload that happened to be the
same LENGTH as the one already archived, but not the same BYTES, left the
JSONL on disk untouched (correct) while `refused` stayed False, so the folder
went on to render its FOUR generated files (markdown/HTML/manifest) from the
NEW, un-written payload - the exact "two halves of a folder describe different
payloads" failure mechanism `ccw archive --verify` exists to catch, mechanism
2 already fixed for the size-KNOWN-different case, and this file proves is now
also fixed for the size-EQUAL case.

WHAT IS NOT CHANGED, and it is a locked oracle test:
`test_archive_layout.py::test_re_writing_an_identical_payload_leaves_the_jsonl_untouched`
protects the true idempotent no-op (same size, same bytes): still not replaced,
still not refused, still no mtime churn. This file's fixtures are deliberately
same-LENGTH-but-different-BYTES, never identical, so they never exercise that
branch.
"""

import json
from pathlib import Path

from cc_warehouse import archive, build, store
from cc_warehouse.render import RenderOptions
from conftest import entry, jsonl, run_ccw, warehouse_root

ZONE = "Australia/Melbourne"
OPTS = RenderOptions()
LABEL = "widget"
UUID_A = "e2222222-2222-3333-4444-555555555552"

_RENDERED = ("transcript.md", "transcript.compact.md", "conversation.html",
             "conversation.compact.html")


def archived() -> bytes:
    """The payload already sitting in the archive."""
    return jsonl(
        entry("user", "Do the thing", "2026-05-07T03:47:45.000Z",
              session_id=UUID_A, gitBranch="main", version="2.0.0"),
        entry("assistant", [{"type": "text", "text": "Working on it."}],
              "2026-05-07T03:47:50.000Z", session_id=UUID_A),
    )


def offered() -> bytes:
    """A DIFFERENT session, at the SAME total length ("Do the thing" and
    "Do the OTHER" are both 12 bytes) - a real-world equivalent is two
    distinct sessions whose payloads happen to be the same byte count, or a
    re-capture that rewrote content without changing its length."""
    return jsonl(
        entry("user", "Do the OTHER", "2026-05-07T03:47:45.000Z",
              session_id=UUID_A, gitBranch="main", version="2.0.0"),
        entry("assistant", [{"type": "text", "text": "Working on it."}],
              "2026-05-07T03:47:50.000Z", session_id=UUID_A),
    )


def test_the_fixture_pair_is_actually_equal_length_but_different() -> None:
    """Guard the fixture itself: if these two ever stop being equal-length and
    unequal, every test below is asserting something other than what it claims."""
    assert len(archived()) == len(offered())
    assert archived() != offered()


def test_an_equal_size_mismatch_does_not_rewrite_the_rendered_files(tmp_path: Path) -> None:
    """THE DEFECT. The four rendered files must still describe the payload that
    survived (`archived()`), not the one that was declined (`offered()`)."""
    archive.write_session_folder(tmp_path, LABEL, archived(), OPTS, ZONE)
    result = archive.write_session_folder(tmp_path, LABEL, offered(), OPTS, ZONE)
    assert result.refused_equal_size
    expected = archive.write_session_folder(
        tmp_path / "control", LABEL, archived(), OPTS, ZONE
    )
    for name in _RENDERED:
        assert (result.directory / name).read_bytes() == (
            expected.directory / name
        ).read_bytes(), f"{name} was rendered from the declined payload"


def test_after_an_equal_size_refusal_the_manifest_still_agrees_with_the_jsonl(
    tmp_path: Path,
) -> None:
    """The property `ccw archive --verify` actually checks. A manifest naming a
    payload the folder does not hold is the failure this whole family opened on."""
    archive.write_session_folder(tmp_path, LABEL, archived(), OPTS, ZONE)
    result = archive.write_session_folder(tmp_path, LABEL, offered(), OPTS, ZONE)
    manifest = json.loads((result.directory / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_hash"] == store.sha256_hex(result.jsonl.read_bytes())
    assert manifest["source_hash"] == store.sha256_hex(archived())


def test_an_equal_size_refusal_names_its_own_reason(tmp_path: Path) -> None:
    """F6: never silent, and never MISLEADING either - a same-size mismatch
    must not be reported with the smaller-payload wording."""
    archive.write_session_folder(tmp_path, LABEL, archived(), OPTS, ZONE)
    result = archive.write_session_folder(tmp_path, LABEL, offered(), OPTS, ZONE)
    manifest = json.loads((result.directory / "manifest.json").read_text(encoding="utf-8"))
    reason = manifest["replace_refused"]["reason"]
    assert "same size" in reason
    assert "smaller" not in reason


def test_whichever_one_arrives_first_is_the_one_that_stays_and_renders(tmp_path: Path) -> None:
    """UNLIKE the smaller/larger case, an equal-size pair has no size-based
    winner - so, correctly, arrival order decides which payload survives. What
    must NOT depend on order is internal consistency: whichever one wins, the
    JSONL and the rendered files must agree with EACH OTHER, not swap partners
    depending on which arrived first (that swap is the mechanism-2 failure
    shape this file exists to keep fixed)."""
    a_first = tmp_path / "a"
    archive.write_session_folder(a_first, LABEL, archived(), OPTS, ZONE)
    second_in_a = archive.write_session_folder(a_first, LABEL, offered(), OPTS, ZONE)
    b_first = tmp_path / "b"
    archive.write_session_folder(b_first, LABEL, offered(), OPTS, ZONE)
    second_in_b = archive.write_session_folder(b_first, LABEL, archived(), OPTS, ZONE)

    assert second_in_a.refused_equal_size and second_in_b.refused_equal_size
    assert second_in_a.jsonl.read_bytes() == archived(), "the FIRST payload in `a` must survive"
    assert second_in_b.jsonl.read_bytes() == offered(), "the FIRST payload in `b` must survive"
    for result, surviving in ((second_in_a, archived()), (second_in_b, offered())):
        manifest = json.loads((result.directory / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["source_hash"] == store.sha256_hex(surviving)


def test_archive_verify_reports_no_problem_after_an_equal_size_refusal(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """End to end through the real verb, because the unit assertions above are
    about a function and the operator's evidence is this command's exit line."""
    archive_root = tmp_path / "archive"
    cfg = Path(ccw_env["HOME"]) / ".config" / "cc-warehouse"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "config.toml").write_text(
        f'root = "{warehouse_root(ccw_env)}"\narchive_timezone = "{ZONE}"\n'
        f'archive_root = "{archive_root}"\n',
        encoding="utf-8",
    )
    ccw_env["XDG_CONFIG_HOME"] = str(cfg.parent)

    archive.write_session_folder(archive_root, LABEL, archived(), OPTS, ZONE)
    archive.write_session_folder(archive_root, LABEL, offered(), OPTS, ZONE)

    result = run_ccw(["archive", "--verify", "--to", str(archive_root)], ccw_env)
    assert result.code == 0, result.err + result.out
    assert "0 problems" in result.out


def test_the_reserved_label_set_is_unchanged_by_this_fix() -> None:
    """A cheap fence: this fix touches the writer, never the label set."""
    assert archive.NOT_SESSIONS_LABEL in build.RESERVED_LABELS
    assert archive.ORPHAN_LABEL in build.RESERVED_LABELS
