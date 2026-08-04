"""Oracle tests: a REFUSED payload must not render (ticket 29, mechanism 2).

Contract: DESIGN 15 entry 2026-08-02 (replace-if-larger), R1 as amended (size
answers "which of two differing payloads is larger"), R5/F7 (the conservative
branch), F6 (loss is never silent).

THE DEFECT, measured on real data 2026-08-04 and the reason this file exists.
`archive.write_session_folder` refused to shrink the folder's JSONL when handed a
smaller payload, set `refused = True`, and then fell straight through and wrote
ALL FIVE generated files from the payload it had just refused. The folder was
left holding the FULL session's JSONL beside the TRUNCATED session's markdown,
HTML and manifest, and `ccw archive --verify` reported it:

    JSONL does not match manifest source_hash

It surfaced on the ticket 25.5 rehearsal, where one session had two copies in the
legacy tree and one was a strict byte prefix of the other. `build._mirror` and
`ccw archive --to` both route through this function, so it was never specific to
`ccw import`.

WHAT IS NOT CHANGED, and it is a locked oracle test:
`test_archive_layout.py::test_a_smaller_payload_is_refused_and_the_refusal_is_recorded`
protects "a truncated re-capture must not be able to shrink the archive WITHOUT
SAYING SO IN THE MANIFEST". Its letter and its decision agree, so it was not
narrowed. The manifest is one of the five files, so "skip the projections on
refusal" would have satisfied half of that decision by breaking the other half.
The refusal is still recorded; what changes is WHICH payload the folder renders.
"""

import json
from pathlib import Path

from cc_warehouse import archive, build, store
from cc_warehouse.render import RenderOptions
from conftest import entry, jsonl, run_ccw, tree_snapshot, warehouse_root

ZONE = "Australia/Melbourne"
OPTS = RenderOptions()
LABEL = "widget"
UUID_A = "e1111111-2222-3333-4444-555555555551"

_RENDERED = ("transcript.md", "transcript.compact.md", "conversation.html",
             "conversation.compact.html")


def truncated() -> bytes:
    """The shorter payload: a real session captured mid-flight."""
    return jsonl(
        entry("user", "Do the thing", "2026-05-07T03:47:45.000Z",
              session_id=UUID_A, gitBranch="main", version="2.0.0"),
        entry("assistant", [{"type": "text", "text": "Working on it."}],
              "2026-05-07T03:47:50.000Z", session_id=UUID_A),
    )


def full() -> bytes:
    """The same session, captured at the end. A strict byte PREFIX relationship,
    which is what the three real pairs in the legacy tree look like."""
    return truncated() + jsonl(
        entry("assistant", [{"type": "text", "text": "Done, and here is the detail."}],
              "2026-05-07T03:48:10.000Z", session_id=UUID_A),
    )


def test_the_fixture_pair_is_actually_a_prefix() -> None:
    """Guard the fixture itself: if these two ever stop being a prefix pair, every
    test below is asserting something other than what it claims."""
    assert full().startswith(truncated())
    assert len(full()) > len(truncated())


def test_a_refused_payload_does_not_rewrite_the_rendered_files(tmp_path: Path) -> None:
    """THE DEFECT. The four rendered files must still describe the payload that
    survived, not the one that was refused."""
    archive.write_session_folder(tmp_path, LABEL, full(), OPTS, ZONE)
    result = archive.write_session_folder(tmp_path, LABEL, truncated(), OPTS, ZONE)
    assert result.refused_smaller
    expected = archive.write_session_folder(
        tmp_path / "control", LABEL, full(), OPTS, ZONE
    )
    for name in _RENDERED:
        assert (result.directory / name).read_bytes() == (
            expected.directory / name
        ).read_bytes(), f"{name} was rendered from the refused payload"


def test_after_a_refusal_the_manifest_still_agrees_with_the_jsonl(tmp_path: Path) -> None:
    """The property `ccw archive --verify` actually checks. A manifest naming a
    payload the folder does not hold is the failure this ticket opened on."""
    archive.write_session_folder(tmp_path, LABEL, full(), OPTS, ZONE)
    result = archive.write_session_folder(tmp_path, LABEL, truncated(), OPTS, ZONE)
    manifest = json.loads((result.directory / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_hash"] == store.sha256_hex(result.jsonl.read_bytes())
    assert manifest["source_hash"] == store.sha256_hex(full())


def test_a_refusal_is_still_recorded_in_the_manifest(tmp_path: Path) -> None:
    """F6: never silent. Fixing WHICH payload renders must not lose the fact that
    something was offered and declined."""
    archive.write_session_folder(tmp_path, LABEL, full(), OPTS, ZONE)
    result = archive.write_session_folder(tmp_path, LABEL, truncated(), OPTS, ZONE)
    manifest = json.loads((result.directory / "manifest.json").read_text(encoding="utf-8"))
    assert "replace_refused" in manifest
    assert manifest["replace_refused"]["offered_bytes"] == len(truncated())
    assert manifest["replace_refused"]["archived_bytes"] == len(full())


def test_the_larger_payload_still_wins_whichever_order_it_arrives_in(
    tmp_path: Path,
) -> None:
    """The property replace-if-larger is supposed to buy, asserted on the WHOLE
    folder rather than on the JSONL alone. Order-dependence in the rendered half
    is exactly what made the rehearsal's damage a coin toss."""
    smaller_first = tmp_path / "a"
    archive.write_session_folder(smaller_first, LABEL, truncated(), OPTS, ZONE)
    archive.write_session_folder(smaller_first, LABEL, full(), OPTS, ZONE)
    larger_first = tmp_path / "b"
    archive.write_session_folder(larger_first, LABEL, full(), OPTS, ZONE)
    archive.write_session_folder(larger_first, LABEL, truncated(), OPTS, ZONE)

    def contents(root: Path) -> dict[str, bytes]:
        return {
            k: v for k, v in tree_snapshot(root).items()
            if not k.endswith("manifest.json")  # carries the refusal note on one side
        }

    assert contents(smaller_first) == contents(larger_first)


def test_archive_verify_reports_no_problem_after_a_refusal(
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

    archive.write_session_folder(archive_root, LABEL, full(), OPTS, ZONE)
    archive.write_session_folder(archive_root, LABEL, truncated(), OPTS, ZONE)

    result = run_ccw(["archive", "--verify", "--to", str(archive_root)], ccw_env)
    assert result.code == 0, result.err + result.out
    assert "0 problems" in result.out


def test_an_equal_sized_payload_still_leaves_the_folder_alone(tmp_path: Path) -> None:
    """The third branch, kept honest: equal size is neither replaced nor refused,
    and re-writing identical bytes would churn mtimes a backup tool reads."""
    first = archive.write_session_folder(tmp_path, LABEL, full(), OPTS, ZONE)
    before = first.jsonl.stat().st_mtime_ns
    second = archive.write_session_folder(tmp_path, LABEL, full(), OPTS, ZONE)
    assert not second.replaced
    assert not second.refused_smaller
    assert second.jsonl.stat().st_mtime_ns == before


def test_a_refused_payload_does_not_resurrect_a_hidden_folder(tmp_path: Path) -> None:
    """A hidden session is archived WITHOUT markdown or HTML (2026-08-02 ruling).
    A refused payload must not be the thing that decides that, either way."""
    hidden = jsonl(
        entry("user", "<command-name>/clear</command-name>", "2026-05-07T03:00:00.000Z",
              session_id=UUID_A),
    )
    archive.write_session_folder(tmp_path, LABEL, hidden + hidden, OPTS, ZONE)
    result = archive.write_session_folder(tmp_path, LABEL, hidden, OPTS, ZONE)
    assert result.refused_smaller
    assert result.jsonl.read_bytes() == hidden + hidden


def test_the_reserved_label_set_is_unchanged_by_this_ticket() -> None:
    """A cheap fence: ticket 29 touches the writer, never the label set."""
    assert archive.NOT_SESSIONS_LABEL in build.RESERVED_LABELS
    assert archive.ORPHAN_LABEL in build.RESERVED_LABELS
