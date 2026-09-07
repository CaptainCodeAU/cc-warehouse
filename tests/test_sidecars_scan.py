"""Oracle tests for the sidecars module (ticket 38, slice 38a).

THE DEFECT THIS MODULE EXISTS FOR. Claude Code has written
`<uuid>/tool-results/` beside every big-output session since 2026-05-08 and
nothing in `src/` ever looked at it: 1,067 directories, 135.7 MB, 65.4 MB of it
in no JSONL at all. It went unnoticed for four months because `capture.py` asked
for `subagents/` BY NAME and ignored whatever else was there. The general fix is
this module: one place that says what may sit beside a transcript, so the next
unknown sibling announces itself instead of waiting to be discovered.

Ruling (c), 2026-09-06: a sidecar file belongs to the session whose transcript
sits beside the sidecar dir. The transcript's identity still comes from its
content (ruling (a)); the DIR is located by that content uuid first and by the
file stem second. The dir name is a source-layout filter, never an identity.
FINDINGS F4 (path is not identity), F5 (no file is opened by a scan).
"""

import ast
from pathlib import Path

from cc_warehouse import sidecars
from conftest import SRC_ROOT, record_opens

UUID = "11111111-2222-3333-4444-555555555555"


def project_dir(tmp_path: Path) -> Path:
    d = tmp_path / "-home-alice-projects-widget"
    d.mkdir(parents=True, exist_ok=True)
    return d


def transcript(tmp_path: Path, *, name: str | None = None) -> Path:
    path = project_dir(tmp_path) / (name if name is not None else f"{UUID}.jsonl")
    path.write_bytes(b"{}\n")
    return path


# ---------------------------------------------------------------------------
# The known-names list itself
# ---------------------------------------------------------------------------


def test_the_three_copied_sidecar_names_are_the_ones_measured_in_the_source_tree() -> None:
    """A census of all 1,196 real `<uuid>/` dirs on 2026-09-06 found exactly four
    child names: these three plus `.DS_Store`. The list is the product decision,
    so it is asserted rather than left implicit."""
    assert sidecars.SESSION_SIDECARS == frozenset({"subagents", "tool-results", "workflows"})


def test_ds_store_is_ignored_rather_than_treated_as_an_unknown_sibling() -> None:
    """Finder writes one into any folder a human browses. Without this every
    browsed session folder becomes a permanent anomaly, which is the ticket 24.7
    lesson: an alert that fires on a healthy machine trains the operator to stop
    reading it."""
    assert ".DS_Store" in sidecars.IGNORED


def test_the_module_imports_no_peer_so_it_can_be_the_leaf_everything_shares() -> None:
    """`archive`, `capture` and `sweep` all need this answer. A module that
    imported any of them could not be imported by all of them (R9)."""
    tree = ast.parse((SRC_ROOT / "sidecars.py").read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("cc_warehouse"):
            imported.append(node.module or "")
        if isinstance(node, ast.Import):
            imported.extend(a.name for a in node.names if a.name.startswith("cc_warehouse"))
    assert not imported, f"sidecars.py must stay a leaf module, imports: {imported}"


# ---------------------------------------------------------------------------
# locate: uuid first, stem second (ruling (c), F4)
# ---------------------------------------------------------------------------


def test_the_sidecar_dir_is_found_by_the_payloads_own_uuid(tmp_path: Path) -> None:
    path = transcript(tmp_path)
    (project_dir(tmp_path) / UUID).mkdir()
    assert sidecars.locate(path, UUID) == project_dir(tmp_path) / UUID


def test_the_sidecar_dir_is_found_when_the_file_stem_is_not_the_bare_uuid(
    tmp_path: Path,
) -> None:
    """Claude Code sometimes writes `<uuid>.orphaned-<n>-<hash>.jsonl`; exactly
    one exists in the live source tree. Keying on the file stem misses its
    sidecar dir entirely, which is the gap `capture.py` has carried since ticket
    21 (`transcript_path.stem` at what was line 366)."""
    path = transcript(tmp_path, name=f"{UUID}.orphaned-2-9f8e7d.jsonl")
    (project_dir(tmp_path) / UUID).mkdir()
    assert sidecars.locate(path, UUID) == project_dir(tmp_path) / UUID


def test_the_file_stem_is_the_fallback_when_the_payload_has_no_uuid(tmp_path: Path) -> None:
    path = transcript(tmp_path, name="no-uuid-here.jsonl")
    (project_dir(tmp_path) / "no-uuid-here").mkdir()
    assert sidecars.locate(path, None) == project_dir(tmp_path) / "no-uuid-here"


def test_a_transcript_with_no_sidecar_dir_locates_nothing(tmp_path: Path) -> None:
    assert sidecars.locate(transcript(tmp_path), UUID) is None


# ---------------------------------------------------------------------------
# scan: three levels of stranger
# ---------------------------------------------------------------------------


def test_a_known_child_is_reported_as_known(tmp_path: Path) -> None:
    path = transcript(tmp_path)
    (project_dir(tmp_path) / UUID / "tool-results").mkdir(parents=True)
    assert sidecars.scan(path, UUID).known == ("tool-results",)


def test_an_unknown_child_is_reported_as_unknown(tmp_path: Path) -> None:
    """LEVEL A. The whole point of the ticket: a name nobody has written a copier
    for must surface, not be skipped in silence."""
    path = transcript(tmp_path)
    (project_dir(tmp_path) / UUID / "zzz-probe").mkdir(parents=True)
    assert sidecars.scan(path, UUID).unknown == ("zzz-probe",)


def test_an_unknown_file_beside_the_sidecar_dirs_is_reported_too(tmp_path: Path) -> None:
    """A stranger does not have to be a directory to be data nobody is copying."""
    path = transcript(tmp_path)
    (project_dir(tmp_path) / UUID).mkdir(parents=True)
    (project_dir(tmp_path) / UUID / "notes.txt").write_bytes(b"x")
    assert sidecars.scan(path, UUID).unknown == ("notes.txt",)


def test_ds_store_inside_the_sidecar_dir_is_neither_known_nor_unknown(tmp_path: Path) -> None:
    path = transcript(tmp_path)
    (project_dir(tmp_path) / UUID).mkdir(parents=True)
    (project_dir(tmp_path) / UUID / ".DS_Store").write_bytes(b"\x00")
    scan = sidecars.scan(path, UUID)
    assert scan.unknown == ()
    assert scan.known == ()


def test_an_unknown_directory_inside_subagents_is_reported(tmp_path: Path) -> None:
    """LEVEL C. `subagents/` already has a copier, so a stranger nested inside it
    would otherwise ride along invisibly - `subagents/` itself reads as known and
    nothing looks further. A sub-agent with its own sidecar dir does not exist
    today, which is exactly when the net is cheap to build."""
    path = transcript(tmp_path)
    subs = project_dir(tmp_path) / UUID / "subagents"
    subs.mkdir(parents=True)
    (subs / "zzz-nested").mkdir()
    assert sidecars.scan(path, UUID).unknown_inside_subagents == ("zzz-nested",)


def test_the_files_claude_code_really_writes_inside_subagents_are_not_strangers(
    tmp_path: Path,
) -> None:
    """Measured 2026-09-06: transcripts, their `.meta.json`, the two forked-skill
    companions, and the `workflows/` dir holding Workflow-tool sub-agents. All
    four shapes are expected; flagging any of them is noise."""
    path = transcript(tmp_path)
    subs = project_dir(tmp_path) / UUID / "subagents"
    subs.mkdir(parents=True)
    (subs / "agent-a94d30c1.jsonl").write_bytes(b"{}\n")
    (subs / "agent-a94d30c1.meta.json").write_bytes(b"{}\n")
    (subs / "agent-a94d30c1.forked-skill.json").write_bytes(b"{}\n")
    (subs / "agent-a94d30c1.forked-skill.marker.json").write_bytes(b"{}\n")
    (subs / "workflows").mkdir()
    assert sidecars.scan(path, UUID).unknown_inside_subagents == ()


def test_a_scan_opens_no_file_at_all(tmp_path: Path) -> None:
    """F5. This runs on the capture hook's critical path and on every session of
    a 24,000-file sweep. Reading anything here would be a cost paid ~24,000 times
    a day to answer a question directory entries already answer."""
    path = transcript(tmp_path)
    dir_ = project_dir(tmp_path) / UUID
    (dir_ / "tool-results").mkdir(parents=True)
    (dir_ / "tool-results" / "big.txt").write_bytes(b"x" * 4096)
    with record_opens(dir_) as opened:
        sidecars.scan(path, UUID)
    assert opened == []


def test_an_unreadable_sidecar_dir_yields_an_empty_scan_rather_than_raising(
    tmp_path: Path,
) -> None:
    """DESIGN 12: the signal must never be the thing that fails a capture. An
    empty scan is the safe reading - it reports no anomaly rather than inventing
    one, and the copier's own error handling reports the unreadable dir."""
    path = transcript(tmp_path)
    dir_ = project_dir(tmp_path) / UUID
    dir_.mkdir(parents=True)
    dir_.chmod(0o000)
    try:
        scan = sidecars.scan(path, UUID)
    finally:
        dir_.chmod(0o700)
    assert scan.known == ()
    assert scan.unknown == ()


def test_a_session_with_no_sidecar_dir_scans_clean(tmp_path: Path) -> None:
    scan = sidecars.scan(transcript(tmp_path), UUID)
    assert scan.sidecar_dir is None
    assert scan.unknown == ()


# ---------------------------------------------------------------------------
# Project-level: strangers and stranded dirs
# ---------------------------------------------------------------------------


def test_a_stranded_sidecar_dir_is_one_with_no_transcript_beside_it(tmp_path: Path) -> None:
    """91 of them exist in the live tree; 39 hold `tool-results/`. Their session
    is not there to carry them into the archive, so something has to name them
    (ruling (d))."""
    transcript(tmp_path)
    (project_dir(tmp_path) / UUID).mkdir()
    orphan = project_dir(tmp_path) / "99999999-0000-0000-0000-000000000000"
    orphan.mkdir()
    assert sidecars.stranded_dirs(project_dir(tmp_path)) == (orphan,)


def test_the_projects_memory_dir_is_never_stranded(tmp_path: Path) -> None:
    """`memory/` is a project-level directory Claude Code writes, not a session
    sidecar dir that lost its transcript. Ticket 40 owns it; reporting it here
    would be a permanent false positive."""
    (project_dir(tmp_path) / "memory").mkdir()
    assert sidecars.stranded_dirs(project_dir(tmp_path)) == ()


def test_a_stray_non_transcript_file_in_a_project_dir_is_a_project_level_stranger(
    tmp_path: Path,
) -> None:
    """LEVEL B, reported by `ccw doctor` only. Nothing like this exists in the
    live tree today, which is the point: the check is what tells us when that
    changes."""
    transcript(tmp_path)
    (project_dir(tmp_path) / "settings.json").write_bytes(b"{}")
    assert sidecars.scan_project_dir(project_dir(tmp_path)) == ("settings.json",)


def test_transcripts_and_session_dirs_are_not_project_level_strangers(tmp_path: Path) -> None:
    transcript(tmp_path)
    (project_dir(tmp_path) / UUID).mkdir()
    (project_dir(tmp_path) / "memory").mkdir()
    (project_dir(tmp_path) / ".DS_Store").write_bytes(b"\x00")
    assert sidecars.scan_project_dir(project_dir(tmp_path)) == ()


def test_an_unreadable_project_dir_yields_nothing_rather_than_raising(tmp_path: Path) -> None:
    d = project_dir(tmp_path)
    d.chmod(0o000)
    try:
        assert sidecars.scan_project_dir(d) == ()
        assert sidecars.stranded_dirs(d) == ()
    finally:
        d.chmod(0o700)
