"""Oracle tests: `ccw import` and the `_not-sessions` reserved label (ticket 25.4/25.6).

Contract: DESIGN section 7 (verb table), section 10 (import routes through the one
capture routine), section 14 R2/R4/R9/R10, section 15 ruling (a) as narrowed by
ticket 21; FINDINGS F1, F4, F7, F9.

WHY A SEPARATE VERB rather than extending `migrate` (principal, 2026-08-04): DESIGN 7
already lists `ccw import` and config.py already reserves `[import] inbox`, so the verb
is anticipated; folding a second source layout into `migrate` would make it two tools
wearing one name.

Frozen here (ticket 25.4): the per-file manifest is written to
<root>/logs/import-manifest.json; `--from DIR` names the source; `--dry-run` rehearses
without writing; `_DELETE` is skipped by name and the skip is REPORTED.

THE MEASUREMENTS THESE TESTS ENCODE, taken over all 4,754 real orphan payloads on
2026-08-04 (a full census, not a sample): 0 are sub-agent transcripts, 0 fail to parse,
0 uuids exist only inside the quarantine, and exactly 2 carry no `sessionId` (they are
CURSOR transcripts, a different tool's format entirely). The last two are why the
non-session route exists: ruling (a) says a payload with no sessionId is not a session,
so it cannot be given a session folder.
"""

import json
import stat
from pathlib import Path
from typing import cast

import pytest

from cc_warehouse import archive, build
from conftest import (
    basic_session,
    jsonl,
    record_opens,
    run_ccw,
    run_cli,
    session_count,
    subagent_session,
    tree_snapshot,
    warehouse_root,
)

UUID_A = "bbbbbbbb-0000-0000-0000-00000000000a"
UUID_B = "bbbbbbbb-0000-0000-0000-00000000000b"
UUID_QUARANTINED = "bbbbbbbb-0000-0000-0000-00000000000c"
ZONE = "Australia/Melbourne"


# ---------------------------------------------------------------------------
# Fixtures: a miniature of the real legacy exporter tree
# ---------------------------------------------------------------------------


def cursor_payload() -> bytes:
    """A payload in the shape of the 2 real non-Claude-Code files in the legacy tree.

    Measured 2026-08-04: `{"role":..,"message":..}` with NO `type` key, no `sessionId`,
    no timestamp, and a body referencing a `.cursor/projects/..` path. Reproduced
    here rather than copied, so the fixture carries no personal path.
    """
    return jsonl(
        {
            "role": "user",
            "message": {
                "content": [
                    {"type": "text", "text": "@/home/alice/.cursor/projects/widget notes"}
                ]
            },
        },
        {"role": "assistant", "message": {"content": [{"type": "text", "text": "Noted."}]}},
        {"type": "turn_ended"},
    )


def legacy_tree(tmp_path: Path) -> Path:
    """The exporter's real layout, including everything that made it awkward.

    Sessions sit at MIXED DEPTHS (measured: depths 1 to 4 in the real tree), the HTML
    the exporter generated sits beside each transcript, there is a `duplicates/`
    subtree, and there is a `_DELETE/` quarantine that the operator filled by hand.
    """
    root = tmp_path / "legacy"
    a = basic_session(cwd="/home/alice/projects/widget", session_id=UUID_A)
    b = basic_session(cwd="/home/alice/projects/gadget", session_id=UUID_B)
    quarantined = basic_session(
        cwd="/home/alice/projects/widget", session_id=UUID_QUARANTINED
    )
    for relative, uuid, data in (
        ("widget", UUID_A, a),
        ("gadget/worktrees/ui", UUID_B, b),  # deeper than two levels, on purpose
        ("duplicates/widget", UUID_A, a),  # the same bytes again
        ("_DELETE/drift-dedupe", UUID_QUARANTINED, quarantined),
    ):
        session_dir = root / relative / uuid
        session_dir.mkdir(parents=True)
        (session_dir / f"{uuid}.jsonl").write_bytes(data)
        # The exporter's own output, which import must ignore rather than translate.
        (session_dir / "index.html").write_text("<html>theirs</html>", encoding="utf-8")
        (session_dir / "page-001.html").write_text("<html>theirs</html>", encoding="utf-8")
    return root


def configure(env: dict[str, str], archive_root: Path | None = None) -> None:
    """Write an XDG config, optionally turning archive dual-write on."""
    cfg = Path(env["HOME"]) / ".config" / "cc-warehouse"
    cfg.mkdir(parents=True, exist_ok=True)
    lines = [f'root = "{warehouse_root(env)}"', f'archive_timezone = "{ZONE}"']
    if archive_root is not None:
        lines.append(f'archive_root = "{archive_root}"')
    (cfg / "config.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    env["XDG_CONFIG_HOME"] = str(Path(env["HOME"]) / ".config")


# ---------------------------------------------------------------------------
# 25.6 The reserved label
# ---------------------------------------------------------------------------


def test_the_non_session_label_is_reserved() -> None:
    """A top-level folder that is not a project must be RESERVED, or the archive
    walk yields its children as session folders and `--verify` reports garbage."""
    assert archive.NOT_SESSIONS_LABEL in build.RESERVED_LABELS


def test_a_folder_under_the_reserved_label_is_not_a_session_folder(tmp_path: Path) -> None:
    """The property the reservation buys, asserted on the walk itself rather than
    on the constant: `walk_folders` is what `ccw archive --verify` iterates."""
    archive_root = tmp_path / "archive"
    session_folder = f"20260105-210000+1100_{UUID_A}"
    (archive_root / "widget" / session_folder).mkdir(parents=True)
    (archive_root / archive.NOT_SESSIONS_LABEL / "journals").mkdir(parents=True)
    found = [p.name for p in archive.walk_folders(archive_root)]
    assert found == [session_folder]


def test_the_reserved_label_is_neutralised_as_a_project_label(tmp_path: Path) -> None:
    """A project genuinely called `_not-sessions` must not be able to collide with
    the reserved folder; build neutralises it rather than dropping the session."""
    directory = build.archive_dir(
        tmp_path, archive.NOT_SESSIONS_LABEL, "2026-01-05T10:00:00Z", UUID_A, ZONE
    )
    assert directory.parent.name == "_" + archive.NOT_SESSIONS_LABEL


def test_archive_verify_passes_with_the_reserved_folder_present(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """End to end: a real `--verify` over a tree that holds the reserved folder
    reports zero problems, which is the whole reason the label is reserved."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    source = tmp_path / "one.jsonl"
    source.write_bytes(basic_session(session_id=UUID_A))
    assert run_ccw(["sweep", "--source", str(tmp_path)], ccw_env).code == 0
    reserved = archive_root / archive.NOT_SESSIONS_LABEL / "journals"
    reserved.mkdir(parents=True, exist_ok=True)
    (reserved / "workflow.jsonl").write_bytes(b'{"note":"not a session"}\n')

    result = run_ccw(["archive", "--verify", "--to", str(archive_root)], ccw_env)
    assert result.code == 0, result.err + result.out
    assert "0 problems" in result.out or "no problems" in result.out.lower()


# ---------------------------------------------------------------------------
# 25.4 The import verb
# ---------------------------------------------------------------------------


def test_import_stores_every_distinct_session_and_dedupes_by_hash(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """F1: the duplicate copy collapses by hash, never by size. Three transcript
    folders outside the quarantine, two distinct sessions."""
    source = legacy_tree(tmp_path)
    result = run_ccw(["import", "--from", str(source)], ccw_env)
    assert result.code == 0, result.err
    assert session_count(ccw_env) == 2


def test_import_counts_distinct_sessions_not_folders(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The trap this closes: a first pass over the real tree reported 4,756
    sessions as 9,541 because it counted FOLDERS. The report says sessions."""
    source = legacy_tree(tmp_path)
    result = run_ccw(["import", "--from", str(source)], ccw_env)
    assert result.code == 0, result.err
    assert "2 stored" in result.out


def test_import_reads_only_jsonl_and_never_opens_their_html(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The exporter's HTML is THEIRS, not ours: ignored entirely rather than
    translated. Proved by audit hook, not by reading the code."""
    source = legacy_tree(tmp_path)
    with record_opens(source) as opened:
        assert run_cli(["import", "--from", str(source)]).code == 0
    assert opened, "the audit hook recorded nothing; the probe itself is broken"
    assert not [p for p in opened if p.endswith(".html")]


def test_import_skips_the_quarantine_branch_and_reports_the_count(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """`_DELETE/` is the operator's OWN quarantine (6,719 session dirs in the real
    tree). Importing it back would be the opposite of help. Skipping silently
    would be just as bad, so the count is printed."""
    source = legacy_tree(tmp_path)
    result = run_ccw(["import", "--from", str(source)], ccw_env)
    assert result.code == 0, result.err
    assert session_count(ccw_env) == 2  # the quarantined third is NOT imported
    assert "_DELETE" in result.out
    assert "1 skipped" in result.out or "skipped 1" in result.out


def test_import_is_idempotent(ccw_env: dict[str, str], tmp_path: Path) -> None:
    source = legacy_tree(tmp_path)
    assert run_ccw(["import", "--from", str(source)], ccw_env).code == 0
    assert run_ccw(["import", "--from", str(source)], ccw_env).code == 0
    assert session_count(ccw_env) == 2


def test_import_reports_an_already_present_payload_rather_than_going_quiet(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """A silent skip and a silent failure look identical from outside."""
    source = legacy_tree(tmp_path)
    run_ccw(["import", "--from", str(source)], ccw_env)
    second = run_ccw(["import", "--from", str(source)], ccw_env)
    assert second.code == 0, second.err
    assert "0 stored" in second.out


def test_import_never_touches_the_source_tree(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """F9 oracle, and the load-bearing one on this ticket: the source tree holds
    the ONLY copy of 4,754 sessions."""
    source = legacy_tree(tmp_path)
    before = tree_snapshot(source)
    result = run_ccw(["import", "--from", str(source)], ccw_env)
    # An import that did NOTHING also leaves the source untouched, so the
    # read-only claim is only worth anything once work has happened (19f's
    # lesson: a round trip over an empty set passes for the wrong reason).
    assert result.code == 0, result.err
    assert session_count(ccw_env) == 2
    assert tree_snapshot(source) == before


def test_import_continues_past_an_unreadable_item(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """R10: name the failed item, import the rest, exit non-zero."""
    source = legacy_tree(tmp_path)
    broken = source / "gadget" / "worktrees" / "ui" / UUID_B / f"{UUID_B}.jsonl"
    broken.chmod(0)
    try:
        result = run_ccw(["import", "--from", str(source)], ccw_env)
        assert result.code != 0
        assert session_count(ccw_env) == 1  # UUID_A still imported
        assert broken.name in result.out + result.err
    finally:
        broken.chmod(stat.S_IRUSR | stat.S_IWUSR)


def test_import_writes_a_per_file_manifest(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """R2: one atomic write, through the store, naming every source file."""
    source = legacy_tree(tmp_path)
    assert run_ccw(["import", "--from", str(source)], ccw_env).code == 0
    manifest = warehouse_root(ccw_env) / "logs" / "import-manifest.json"
    assert manifest.exists()
    entries = cast(list[dict[str, object]], json.loads(manifest.read_text()))
    sources = [str(e["source"]) for e in entries]
    assert len(entries) == 3  # the three outside the quarantine
    assert not [s for s in sources if "_DELETE" in s]
    for e in entries:
        assert e["source"]
        assert e["outcome"]


# ---------------------------------------------------------------------------
# The two guards the census produced
# ---------------------------------------------------------------------------


def test_import_refuses_a_subagent_payload_instead_of_overwriting_its_parent(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """THE HAZARD: a sub-agent carries its PARENT'S sessionId, so the ordinary
    capture path would compute the parent's folder, name the file
    <parent-uuid>.jsonl, and let replace-if-larger overwrite the parent (a
    sub-agent's median 192 KB against a session's 3.7 KB).

    `migrate` hands capture_transcript every file it finds and has no such guard.
    Measured 2026-08-04: 0 of the 4,754 real orphans are sub-agents, so import
    REFUSES and reports rather than growing a route nothing uses.
    """
    source = tmp_path / "legacy"
    parent_dir = source / "widget" / UUID_A
    parent_dir.mkdir(parents=True)
    (parent_dir / f"{UUID_A}.jsonl").write_bytes(basic_session(session_id=UUID_A))
    agent_dir = source / "widget" / UUID_B
    agent_dir.mkdir(parents=True)
    (agent_dir / f"{UUID_B}.jsonl").write_bytes(subagent_session(parent_uuid=UUID_A))

    result = run_ccw(["import", "--from", str(source)], ccw_env)
    assert session_count(ccw_env) == 1
    assert f"{UUID_B}.jsonl" in result.out + result.err
    assert "sub-agent" in (result.out + result.err)


def test_a_payload_with_no_session_id_lands_under_the_reserved_home(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Ruling (a): no sessionId means not a session, so it cannot be given a
    session folder. It is still RESCUED, because it exists in exactly one place.

    Both real instances are Cursor transcripts, so this is also the seam where a
    second source kind arrives.
    """
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    source = tmp_path / "legacy"
    odd = source / "_UNKNOWN" / UUID_A
    odd.mkdir(parents=True)
    (odd / f"{UUID_A}.jsonl").write_bytes(cursor_payload())

    result = run_ccw(["import", "--from", str(source)], ccw_env)
    assert result.code == 0, result.err
    assert session_count(ccw_env) == 0
    landed = sorted(
        (archive_root / archive.NOT_SESSIONS_LABEL).rglob("*.jsonl")
    )
    assert len(landed) == 1
    assert landed[0].read_bytes() == cursor_payload()
    assert "not a session" in result.out.lower()


def test_a_non_session_import_is_idempotent(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Content-addressed naming, so a re-import writes the same path rather than
    a second copy."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    source = tmp_path / "legacy"
    odd = source / "_UNKNOWN" / UUID_A
    odd.mkdir(parents=True)
    (odd / f"{UUID_A}.jsonl").write_bytes(cursor_payload())
    run_ccw(["import", "--from", str(source)], ccw_env)
    first = tree_snapshot(archive_root)
    # Two empty snapshots also compare equal; assert the payload arrived first.
    assert [k for k in first if k.endswith(".jsonl")]
    run_ccw(["import", "--from", str(source)], ccw_env)
    assert tree_snapshot(archive_root) == first


# ---------------------------------------------------------------------------
# The rehearsal
# ---------------------------------------------------------------------------


def test_dry_run_writes_nothing_at_all(ccw_env: dict[str, str], tmp_path: Path) -> None:
    """Exit 0 plus output is NOT evidence that nothing happened: `ccw sweep -h`
    imported 13,836 sessions on 2026-08-01. The assertion is a SNAPSHOT."""
    source = legacy_tree(tmp_path)
    root = warehouse_root(ccw_env)
    root.mkdir(parents=True, exist_ok=True)
    before = tree_snapshot(root)
    result = run_ccw(["import", "--from", str(source), "--dry-run"], ccw_env)
    assert result.code == 0, result.err
    assert tree_snapshot(root) == before


def test_dry_run_on_a_fresh_root_creates_no_warehouse(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The two traps sweep.plan documents: acquire_lock creates <root>/locks/ and
    open_catalog creates the database. A rehearsal must do neither."""
    source = legacy_tree(tmp_path)
    root = warehouse_root(ccw_env)
    assert not root.exists()
    assert run_ccw(["import", "--from", str(source), "--dry-run"], ccw_env).code == 0
    assert not root.exists()


def test_dry_run_names_each_candidate_rather_than_only_counting(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """A count alone cannot be checked against the run that follows it."""
    source = legacy_tree(tmp_path)
    result = run_ccw(["import", "--from", str(source), "--dry-run"], ccw_env)
    assert result.code == 0, result.err
    assert f"{UUID_A}.jsonl" in result.out
    assert f"{UUID_B}.jsonl" in result.out
    assert "would-store" in result.out


def test_quiet_drops_the_per_item_lines(ccw_env: dict[str, str], tmp_path: Path) -> None:
    source = legacy_tree(tmp_path)
    result = run_ccw(["import", "--from", str(source), "--dry-run", "--quiet"], ccw_env)
    assert result.code == 0, result.err
    assert result.out.strip() == ""


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


def test_import_is_listed_in_the_top_level_help() -> None:
    """A bare `"import" in result.out` PASSES BEFORE THE VERB EXISTS, because
    migrate's blurb reads "one-shot import of a legacy archive". The assertion
    has to be on the verb COLUMN, which only a listed verb can occupy."""
    result = run_cli(["-h"])
    assert result.code == 0
    verbs = [line.split()[0] for line in result.out.splitlines() if line.startswith("  ")]
    assert "import" in verbs


def test_import_requires_a_source(ccw_env: dict[str, str]) -> None:
    result = run_ccw(["import"], ccw_env)
    assert result.code == 2
    assert "--from" in result.err


def test_import_refuses_a_missing_source_directory(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    result = run_ccw(["import", "--from", str(tmp_path / "nope")], ccw_env)
    assert result.code == 2
    assert "not a directory" in result.err


@pytest.mark.parametrize("flag", ["--dry-runn", "--totally-bogus"])
def test_import_refuses_an_unknown_flag_before_doing_any_work(
    ccw_env: dict[str, str], tmp_path: Path, flag: str
) -> None:
    """The 2026-08-03 defect class: an unrecognised option must never reach a
    handler that would then do the real work."""
    source = legacy_tree(tmp_path)
    result = run_ccw(["import", "--from", str(source), flag], ccw_env)
    assert result.code == 2
    # An UNKNOWN VERB also exits 2 and also writes nothing, so both halves pass
    # before the verb exists. The message has to name the FLAG.
    assert flag in result.err
    assert "unrecognised option" in result.err
    assert not warehouse_root(ccw_env).exists()
