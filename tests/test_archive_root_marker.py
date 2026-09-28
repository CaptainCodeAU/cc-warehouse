"""Oracle tests: the archive root marker (ticket 44, slice 44a).

Contract: `harness/tickets/44-archive-root-on-a-network-share.md`, section
"44a. Archive root marker" and "Edge cases the build must cover";
`contract/DESIGN.md` section 15, entry "2026-09-28, ticket 44".

THE FAILURE THIS EXISTS FOR. Nothing checked that `archive_root` is the tree it
was configured as. When the archive lives on a network share and the share is
not mounted, a leftover empty mount directory lets the hook `mkdir` the tree
onto the boot disk; the catalog records it, and once the share re-mounts
somewhere else the archive has silently forked. The marker turns that into a
named refusal (R10, R14). It also closes an older gap the config file only
warned about in prose: a changed `archive_timezone` now refuses instead of
naming every new session in a second zone beside the old ones.

Every writer that targets the archive is checked here through its REAL entry
point (the verb or the capture function), and each one proves the refusal by
showing the archive tree did not change, never by exit code alone: exit
non-zero plus a message is not evidence that nothing was written.
"""

import json
import os
from pathlib import Path

import pytest

from cc_warehouse import archive, build, capture, catalog, doctor, sweep
from cc_warehouse.config import Config
from conftest import (
    basic_session,
    catalog_rows,
    hook_payload,
    run_ccw,
    run_cli,
    subagent_session,
    tree_snapshot,
    warehouse_root,
    write_transcript,
)

ZONE = "Australia/Melbourne"
OTHER_ZONE = "Europe/London"
UUID_A = "a4a4a4a4-1111-4111-8111-aaaaaaaaaaaa"
UUID_B = "b4b4b4b4-2222-4222-8222-bbbbbbbbbbbb"
MARKER = "_archive-root.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def configure(
    env: dict[str, str], archive_root: Path, *, keep_objects: bool = False, zone: str = ZONE
) -> None:
    """config.toml under the sandboxed HOME. `keep_objects = false` by default
    because that is the live machine's setting and the arm where a refusal has
    to be loud (nothing else holds the session)."""
    cfg = Path(env["HOME"]) / ".config" / "cc-warehouse"
    cfg.mkdir(parents=True, exist_ok=True)
    lines = [
        f'root = "{warehouse_root(env)}"',
        f'archive_timezone = "{zone}"',
        f'archive_root = "{archive_root}"',
        f"keep_objects = {'true' if keep_objects else 'false'}",
    ]
    (cfg / "config.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    env["XDG_CONFIG_HOME"] = str(cfg.parent)


def raw_marker(archive_root: Path, payload: object) -> Path:
    """Write a marker by hand, bypassing the product, for the malformed arms."""
    archive_root.mkdir(parents=True, exist_ok=True)
    path = archive_root / MARKER
    text = payload if isinstance(payload, str) else json.dumps(payload)
    path.write_text(text, encoding="utf-8")
    return path


def good_marker(archive_root: Path, zone: str = ZONE, created: str = "2026-09-28T00:00:00Z") -> Path:
    return raw_marker(
        archive_root,
        {"cc_warehouse": "archive_root", "archive_timezone": zone, "created": created},
    )


def stale_tree(archive_root: Path) -> None:
    """An archive tree with a session folder but NO marker: the shape a real
    archive has on the day this slice ships, and the shape a stale directory
    has after an unmount."""
    folder = archive_root / "widget" / f"20260105-210000+1100_{UUID_B}"
    folder.mkdir(parents=True)
    (folder / f"{UUID_B}.jsonl").write_bytes(basic_session(session_id=UUID_B))


def config_for(tmp_path: Path, archive_root: Path | None, **kw: object) -> Config:
    return Config(
        root=tmp_path / "warehouse",
        archive_root=archive_root,
        archive_timezone=ZONE,
        **kw,  # type: ignore[arg-type]
    )


def place_transcript(tmp_path: Path, uuid: str = UUID_A, *, with_subagent: bool = False) -> Path:
    project = tmp_path / "home" / ".claude" / "projects" / "-home-alice-projects-widget"
    project.mkdir(parents=True, exist_ok=True)
    path = project / f"{uuid}.jsonl"
    path.write_bytes(basic_session(session_id=uuid))
    if with_subagent:
        agents = project / uuid / "subagents"
        agents.mkdir(parents=True)
        (agents / "agent-a94d30c1d877f964d.jsonl").write_bytes(
            subagent_session(parent_uuid=uuid)
        )
    return path


def capture_log(root: Path) -> list[dict[str, object]]:
    log = root / "logs" / "capture.jsonl"
    if not log.is_file():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line]


def check(report: doctor.Report, name: str) -> doctor.Check:
    found = [c for c in report.checks if c.name == name]
    assert len(found) == 1, [c.name for c in report.checks]
    return found[0]


# ---------------------------------------------------------------------------
# The shared check: archive.require_root
# ---------------------------------------------------------------------------


def test_the_marker_name_is_a_reserved_label() -> None:
    """The marker sits at the top of the tree beside the label folders, so it
    must never be mistaken for one (R4 as amended, RESERVED LABELS)."""
    assert archive.ROOT_MARKER == MARKER
    assert archive.ROOT_MARKER in build.RESERVED_LABELS


def test_require_root_passes_on_a_matching_marker(tmp_path: Path) -> None:
    root = tmp_path / "archive"
    good_marker(root)
    assert archive.require_root(root, ZONE) == root


def test_require_root_refuses_a_missing_marker_and_names_it(tmp_path: Path) -> None:
    root = tmp_path / "archive"
    stale_tree(root)
    with pytest.raises(archive.ArchiveRootRefused) as caught:
        archive.require_root(root, ZONE)
    message = str(caught.value)
    assert str(root) in message
    assert "--init" in message


def test_require_root_refuses_a_different_zone(tmp_path: Path) -> None:
    """A zone change renames the whole tree. Refusing is what stops it forking
    into two zones side by side."""
    root = tmp_path / "archive"
    good_marker(root, zone=OTHER_ZONE)
    with pytest.raises(archive.ArchiveRootRefused) as caught:
        archive.require_root(root, ZONE)
    assert OTHER_ZONE in str(caught.value)
    assert ZONE in str(caught.value)


@pytest.mark.parametrize(
    "payload",
    [
        "{not json",
        "[1, 2, 3]",
        json.dumps({"cc_warehouse": "something-else", "archive_timezone": ZONE}),
        "",
    ],
    ids=["bad-json", "not-an-object", "wrong-kind", "empty-file"],
)
def test_require_root_refuses_a_malformed_marker_and_names_the_file(
    tmp_path: Path, payload: str
) -> None:
    """Edge case: marker present but unreadable or malformed. Refuse, name the file."""
    root = tmp_path / "archive"
    path = raw_marker(root, payload)
    with pytest.raises(archive.ArchiveRootRefused) as caught:
        archive.require_root(root, ZONE)
    assert str(path) in str(caught.value)


def test_require_root_refuses_a_marker_with_no_zone(tmp_path: Path) -> None:
    """Edge case: an older marker with the zone key missing is a mismatch."""
    root = tmp_path / "archive"
    raw_marker(root, {"cc_warehouse": "archive_root", "created": "2026-09-28T00:00:00Z"})
    with pytest.raises(archive.ArchiveRootRefused):
        archive.require_root(root, ZONE)


def test_require_root_refuses_an_absent_path_and_creates_nothing(tmp_path: Path) -> None:
    """Edge case: the configured path is not there at all (the share is not
    mounted). The refusal must not bring the directory into being."""
    root = tmp_path / "mnt" / "archive"
    with pytest.raises(archive.ArchiveRootRefused) as caught:
        archive.require_root(root, ZONE)
    assert str(root) in str(caught.value)
    assert not (tmp_path / "mnt").exists()


def test_the_created_field_is_informational_and_never_compared(tmp_path: Path) -> None:
    root = tmp_path / "archive"
    for created in ("1999-01-01T00:00:00Z", "not a date at all", ""):
        good_marker(root, created=created)
        assert archive.require_root(root, ZONE) == root
    raw_marker(root, {"cc_warehouse": "archive_root", "archive_timezone": ZONE})
    assert archive.require_root(root, ZONE) == root


# ---------------------------------------------------------------------------
# The walkers never see the marker as a label
# ---------------------------------------------------------------------------


def test_walkers_never_treat_the_marker_name_as_a_label(tmp_path: Path) -> None:
    """Belt and braces: `walk_folders` also skips non-directories and the marker
    is a file, but the reserved set must hold on its own. A DIRECTORY under the
    marker's name, holding a session-shaped folder and a project.json, is still
    not a label."""
    root = tmp_path / "archive"
    impostor = root / MARKER / f"20260105-210000+1100_{UUID_A}"
    impostor.mkdir(parents=True)
    (impostor / f"{UUID_A}.jsonl").write_bytes(basic_session(session_id=UUID_A))
    (root / MARKER / archive.PROJECT_JSON).write_text(
        json.dumps({"label": MARKER, "aliases": []}), encoding="utf-8"
    )
    assert list(archive.walk_folders(root)) == []
    assert [r.label for r in archive.read_projects(root)] == []


def test_a_marker_file_beside_real_labels_changes_nothing_the_walkers_yield(
    tmp_path: Path,
) -> None:
    root = tmp_path / "archive"
    stale_tree(root)
    before = [p.name for p in archive.walk_folders(root)]
    good_marker(root)
    assert [p.name for p in archive.walk_folders(root)] == before


def test_underscore_labels_that_are_not_the_marker_behave_exactly_as_before(
    tmp_path: Path,
) -> None:
    """Edge case: a label starting with `_` is only skipped when it is reserved.
    `_not-sessions` stays skipped; `_unlabeled` (the real fallback label) is
    still walked. A regression pin: this passes on master and must keep passing."""
    root = tmp_path / "archive"
    good_marker(root)
    for label in ("_not-sessions", "_unlabeled"):
        folder = root / label / f"20260105-210000+1100_{UUID_A}"
        folder.mkdir(parents=True)
        (folder / f"{UUID_A}.jsonl").write_bytes(basic_session(session_id=UUID_A))
    assert [p.parent.name for p in archive.walk_folders(root)] == ["_unlabeled"]


# ---------------------------------------------------------------------------
# `ccw archive --to X --init`, the one way a marker is created
# ---------------------------------------------------------------------------


def test_init_creates_the_marker_with_the_pinned_zone(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    target = tmp_path / "archive"
    configure(ccw_env, target)
    result = run_cli(["archive", "--to", str(target), "--init"])
    assert result.code == 0, result.err
    marker = json.loads((target / MARKER).read_text(encoding="utf-8"))
    assert marker["cc_warehouse"] == "archive_root"
    assert marker["archive_timezone"] == ZONE
    assert isinstance(marker["created"], str) and marker["created"]
    assert archive.require_root(target, ZONE) == target


def test_init_honours_the_zone_flag(ccw_env: dict[str, str], tmp_path: Path) -> None:
    target = tmp_path / "archive"
    configure(ccw_env, target)
    assert run_cli(["archive", "--to", str(target), "--init", "--zone", OTHER_ZONE]).code == 0
    marker = json.loads((target / MARKER).read_text(encoding="utf-8"))
    assert marker["archive_timezone"] == OTHER_ZONE


def test_init_marks_an_existing_tree_and_touches_nothing_else(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    target = tmp_path / "archive"
    configure(ccw_env, target)
    stale_tree(target)
    before = tree_snapshot(target)
    result = run_cli(["archive", "--to", str(target), "--init"])
    assert result.code == 0, result.err
    after = tree_snapshot(target)
    assert set(after) - set(before) == {MARKER}
    assert {k: v for k, v in after.items() if k != MARKER} == before


def test_init_refuses_a_marker_that_names_a_different_zone(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    target = tmp_path / "archive"
    configure(ccw_env, target)
    good_marker(target, zone=OTHER_ZONE)
    before = tree_snapshot(target)
    result = run_cli(["archive", "--to", str(target), "--init"])
    assert result.code != 0
    assert OTHER_ZONE in result.err
    assert tree_snapshot(target) == before


def test_init_on_a_same_zone_marker_is_a_no_op_that_rewrites_nothing(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Bytes AND inode: `atomic_write` replaces the inode, so an identical-bytes
    rewrite would still show here even though `tree_snapshot` could not see it."""
    target = tmp_path / "archive"
    configure(ccw_env, target)
    assert run_cli(["archive", "--to", str(target), "--init"]).code == 0
    stat_before = os.stat(target / MARKER)
    before = tree_snapshot(target)
    result = run_cli(["archive", "--to", str(target), "--init"])
    assert result.code == 0, result.err
    assert tree_snapshot(target) == before
    stat_after = os.stat(target / MARKER)
    assert (stat_after.st_ino, stat_after.st_mtime_ns) == (
        stat_before.st_ino,
        stat_before.st_mtime_ns,
    )


def test_init_refuses_when_the_parent_of_the_target_is_missing(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """A missing mount point must not be conjured into existence by `--init`
    either: it creates the archive directory itself, never its parents."""
    target = tmp_path / "mnt" / "archive"
    configure(ccw_env, target)
    result = run_cli(["archive", "--to", str(target), "--init"])
    assert result.code != 0
    assert str(target.parent) in result.err
    assert not (tmp_path / "mnt").exists()


def test_init_does_not_build_the_archive(ccw_env: dict[str, str], tmp_path: Path) -> None:
    """`--init` marks and stops. Building is a separate, later run of the verb,
    so marking an 18 GB tree never turns into a full rebuild by accident."""
    target = tmp_path / "archive"
    configure(ccw_env, target, keep_objects=True)
    other = tmp_path / "other"
    configure(ccw_env, other, keep_objects=True)
    assert run_cli(["archive", "--to", str(other), "--init"]).code == 0
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    assert run_cli(["sweep"]).code == 0
    assert run_cli(["archive", "--to", str(target), "--init"]).code == 0
    assert list(archive.walk_folders(target)) == []


# ---------------------------------------------------------------------------
# `ccw archive --to X` without --init
# ---------------------------------------------------------------------------


def test_archive_refuses_a_populated_tree_with_no_marker(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The stale-directory guard: session folders but no marker is refused."""
    target = tmp_path / "archive"
    configure(ccw_env, target)
    stale_tree(target)
    before = tree_snapshot(target)
    result = run_cli(["archive", "--to", str(target)])
    assert result.code != 0
    assert str(target) in result.err
    assert "--init" in result.err
    assert tree_snapshot(target) == before


def test_archive_refuses_an_absent_target_and_creates_nothing(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    target = tmp_path / "archive"
    configure(ccw_env, target)
    result = run_cli(["archive", "--to", str(target)])
    assert result.code != 0
    assert not target.exists()


def test_archive_refuses_a_zone_mismatch(ccw_env: dict[str, str], tmp_path: Path) -> None:
    target = tmp_path / "archive"
    configure(ccw_env, target)
    good_marker(target, zone=OTHER_ZONE)
    before = tree_snapshot(target)
    result = run_cli(["archive", "--to", str(target)])
    assert result.code != 0
    assert tree_snapshot(target) == before


def test_archive_builds_into_a_marked_target(ccw_env: dict[str, str], tmp_path: Path) -> None:
    """The positive control for the three refusals above."""
    target = tmp_path / "archive"
    configure(ccw_env, target, keep_objects=True)
    other = tmp_path / "other"
    good_marker(other)
    configure(ccw_env, other, keep_objects=True)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    assert run_cli(["sweep"]).code == 0
    good_marker(target)
    result = run_cli(["archive", "--to", str(target)])
    assert result.code == 0, result.err
    assert [p.name.partition("_")[2] for p in archive.walk_folders(target)] == [UUID_A]


def test_archive_verify_is_unchanged_on_an_unmarked_tree(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Read-only verbs are untouched: `--verify` reads an unmarked tree exactly
    as before, and writes nothing (not even a marker)."""
    target = tmp_path / "archive"
    configure(ccw_env, target)
    stale_tree(target)
    before = tree_snapshot(target)
    result = run_cli(["archive", "--to", str(target), "--verify"])
    assert "no marker" not in result.err.lower()
    assert tree_snapshot(target) == before


# ---------------------------------------------------------------------------
# The capture path: the hook and capture._archive_source
# ---------------------------------------------------------------------------


def test_hook_refuses_an_unmarked_empty_archive_root(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """THE incident shape: an empty directory where the share should be."""
    target = tmp_path / "archive"
    target.mkdir()
    configure(ccw_env, target)
    transcript = write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    result = run_ccw(["hook"], ccw_env, stdin=hook_payload(transcript, session_id=UUID_A))
    assert result.code == 0  # the hook never raises into Claude Code (SPEC 2.6)
    assert tree_snapshot(target) == {}


def test_hook_refuses_an_absent_archive_root_and_creates_no_directory(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Edge case: the path is absent entirely. No directory is created anywhere."""
    target = tmp_path / "mnt" / "archive"
    configure(ccw_env, target)
    transcript = write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    run_ccw(["hook"], ccw_env, stdin=hook_payload(transcript, session_id=UUID_A))
    assert not (tmp_path / "mnt").exists()


def test_hook_writes_into_a_marked_archive_root(ccw_env: dict[str, str], tmp_path: Path) -> None:
    """The positive control for the two refusals above."""
    target = tmp_path / "archive"
    good_marker(target)
    configure(ccw_env, target)
    transcript = write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    assert run_ccw(["hook"], ccw_env, stdin=hook_payload(transcript, session_id=UUID_A)).code == 0
    assert (next(archive.walk_folders(target)) / f"{UUID_A}.jsonl").is_file()


def test_capture_without_the_vault_reraises_the_refusal(tmp_path: Path) -> None:
    """keep_objects = false: nothing else holds the session, so a swallowed
    refusal would be a hook reporting success while nothing holds it."""
    target = tmp_path / "archive"
    target.mkdir()
    config = config_for(tmp_path, target, keep_objects=False)
    transcript = place_transcript(tmp_path)
    with pytest.raises(archive.ArchiveRootRefused):
        capture.capture_transcript(config, transcript, session_id=UUID_A, cwd=None)
    assert tree_snapshot(target) == {}
    conn = catalog.open_catalog(config.root)
    try:
        assert conn.execute("SELECT COUNT(*) FROM session").fetchone()[0] == 0
    finally:
        conn.close()


def test_capture_with_the_vault_stores_it_and_logs_the_refusal(tmp_path: Path) -> None:
    """keep_objects = true: the vault write is the safety net, so the capture
    succeeds, the archive is untouched (sub-agents included), and the refusal is
    on record in capture.jsonl rather than swallowed."""
    target = tmp_path / "archive"
    target.mkdir()
    config = config_for(tmp_path, target, keep_objects=True)
    transcript = place_transcript(tmp_path, with_subagent=True)
    result = capture.capture_transcript(config, transcript, session_id=UUID_A, cwd=None)
    assert result.action == "stored"
    assert any((config.root / "objects").rglob("*"))
    assert tree_snapshot(target) == {}
    refusals = [r for r in capture_log(config.root) if MARKER in str(r.get("message", ""))]
    assert len(refusals) == 1, capture_log(config.root)
    assert refusals[0]["status"] == "error"


def test_the_companions_child_writes_nothing_into_an_unmarked_root(tmp_path: Path) -> None:
    """`archive_companions` is the detached companions child's whole body. With
    the parent refused, a sub-agent would otherwise land in `_orphaned-subagents`
    and bring the unmarked tree into being on its own."""
    target = tmp_path / "archive"
    target.mkdir()
    config = config_for(tmp_path, target, keep_objects=True)
    transcript = place_transcript(tmp_path, with_subagent=True)
    conn = catalog.open_catalog(config.root)
    try:
        capture.archive_companions(config, conn, 1, transcript, UUID_A)
    finally:
        conn.close()
    assert tree_snapshot(target) == {}


# ---------------------------------------------------------------------------
# The batch writers: sweep, build, render --session, import, repair
# ---------------------------------------------------------------------------


def test_sweep_refuses_before_any_write(ccw_env: dict[str, str], tmp_path: Path) -> None:
    target = tmp_path / "archive"
    stale_tree(target)
    configure(ccw_env, target, keep_objects=True)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    before = tree_snapshot(target)
    result = run_ccw(["sweep"], ccw_env)
    assert result.code != 0
    assert MARKER in result.err
    assert tree_snapshot(target) == before
    # Refused at the TOP of the run: not even the vault or the catalog moved.
    assert not (warehouse_root(ccw_env) / "objects").exists()


def test_sweep_refusal_is_in_the_library_not_only_the_verb(tmp_path: Path) -> None:
    target = tmp_path / "archive"
    target.mkdir()
    config = config_for(tmp_path, target, keep_objects=True)
    place_transcript(tmp_path)
    report = sweep.sweep(config, tmp_path / "home" / ".claude" / "projects")
    assert len(report.failures) == 1
    assert MARKER in report.failures[0].detail
    assert tree_snapshot(target) == {}


def test_sweep_writes_into_a_marked_root(ccw_env: dict[str, str], tmp_path: Path) -> None:
    target = tmp_path / "archive"
    good_marker(target)
    configure(ccw_env, target)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    result = run_ccw(["sweep"], ccw_env)
    assert result.code == 0, result.err
    assert [p.name.partition("_")[2] for p in archive.walk_folders(target)] == [UUID_A]


def _vault_only_capture(env: dict[str, str], tmp_path: Path) -> None:
    """A stored session with a marked archive, then the config repointed at a
    DIFFERENT, unmarked root: the catalog now names a session the new root
    has never seen, which is exactly what a re-mount somewhere else looks like."""
    first = tmp_path / "first"
    good_marker(first)
    configure(env, first, keep_objects=True)
    write_transcript(env, basic_session(session_id=UUID_A), session_id=UUID_A)
    assert run_cli(["sweep"]).code == 0


def test_build_refuses_to_mirror_into_an_unmarked_root(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    _vault_only_capture(ccw_env, tmp_path)
    target = tmp_path / "archive"
    target.mkdir()
    configure(ccw_env, target, keep_objects=True)
    result = run_cli(["build", "--rebuild"])
    assert result.code != 0
    assert MARKER in result.err
    assert tree_snapshot(target) == {}


def test_render_session_refuses_to_mirror_into_an_unmarked_root(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    _vault_only_capture(ccw_env, tmp_path)
    target = tmp_path / "archive"
    target.mkdir()
    configure(ccw_env, target, keep_objects=True)
    short = str(catalog_rows(ccw_env, "SELECT short FROM session")[0][0])  # type: ignore[index]
    result = run_cli(["render", "--session", f"s:{short}"])
    assert result.code != 0
    assert tree_snapshot(target) == {}


def test_import_refuses_before_any_write(ccw_env: dict[str, str], tmp_path: Path) -> None:
    target = tmp_path / "archive"
    target.mkdir()
    configure(ccw_env, target, keep_objects=True)
    source = tmp_path / "legacy" / "widget"
    source.mkdir(parents=True)
    (source / f"{UUID_A}.jsonl").write_bytes(basic_session(session_id=UUID_A))
    result = run_cli(["import", "--from", str(tmp_path / "legacy")])
    assert result.code != 0
    assert MARKER in result.err
    assert tree_snapshot(target) == {}
    assert not (warehouse_root(ccw_env) / "objects").exists()


def test_repair_refuses_an_unmarked_root(ccw_env: dict[str, str], tmp_path: Path) -> None:
    target = tmp_path / "archive"
    stale_tree(target)
    configure(ccw_env, target)
    before = tree_snapshot(target)
    result = run_cli(["repair"])
    assert result.code != 0
    assert MARKER in result.err
    assert tree_snapshot(target) == before


# ---------------------------------------------------------------------------
# ccw doctor's `archive root` line
# ---------------------------------------------------------------------------


def test_doctor_archive_root_line_is_ok_on_a_marked_root(tmp_path: Path) -> None:
    target = tmp_path / "archive"
    good_marker(target)
    line = check(doctor.diagnose(config_for(tmp_path, target), home=tmp_path / "home"), "archive root")
    assert line.ok
    assert line.blocking
    assert "marker present" in line.detail


def test_doctor_archive_root_line_fails_on_a_missing_marker(tmp_path: Path) -> None:
    target = tmp_path / "archive"
    stale_tree(target)
    report = doctor.diagnose(config_for(tmp_path, target), home=tmp_path / "home")
    line = check(report, "archive root")
    assert not line.ok
    assert line.blocking
    assert f"MISSING at {target}" in line.detail
    assert not report.ok
    assert "FAIL archive root" in doctor.report_text(report)


def test_doctor_archive_root_line_fails_and_does_not_raise_on_an_absent_path(
    tmp_path: Path,
) -> None:
    target = tmp_path / "mnt" / "archive"
    report = doctor.diagnose(config_for(tmp_path, target), home=tmp_path / "home")
    line = check(report, "archive root")
    assert not line.ok
    assert f"MISSING at {target}" in line.detail
    assert not (tmp_path / "mnt").exists()


def test_doctor_archive_root_line_fails_on_a_zone_mismatch(tmp_path: Path) -> None:
    target = tmp_path / "archive"
    good_marker(target, zone=OTHER_ZONE)
    line = check(doctor.diagnose(config_for(tmp_path, target), home=tmp_path / "home"), "archive root")
    assert not line.ok
    assert OTHER_ZONE in line.detail


def test_doctor_archive_root_line_is_ok_with_no_archive_configured(tmp_path: Path) -> None:
    line = check(doctor.diagnose(config_for(tmp_path, None), home=tmp_path / "home"), "archive root")
    assert line.ok


def test_doctor_verb_exits_non_zero_on_a_missing_marker(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Through the real verb, so ccw-watch's `^\\s*FAIL` grep and the freshness
    hook's exit-code read both see it."""
    target = tmp_path / "archive"
    stale_tree(target)
    configure(ccw_env, target)
    result = run_ccw(["doctor"], ccw_env)
    assert result.code != 0
    assert any(
        line.lstrip().startswith("FAIL") and "archive root" in line
        for line in result.out.splitlines()
    )


# ---------------------------------------------------------------------------
# Fresh install; and the one edge case that belongs to 44b
# ---------------------------------------------------------------------------


def test_fresh_install_with_a_marked_empty_archive_runs_clean(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Edge case: catalog empty, archive marked and empty. Doctor and sweep run
    with no exception and no archive-related failure."""
    target = tmp_path / "archive"
    configure(ccw_env, target)
    assert run_cli(["archive", "--to", str(target), "--init"]).code == 0
    sweep_result = run_ccw(["sweep"], ccw_env)
    assert sweep_result.code == 0, sweep_result.err
    report = doctor.diagnose(
        config_for(tmp_path, target), home=Path(ccw_env["HOME"])
    )
    assert check(report, "archive root").ok
    assert check(report, "desync").ok


@pytest.mark.xfail(
    strict=True,
    reason=(
        "ticket 44b: doctor's recency sample comes from the catalog. On 44a alone"
        " the sample walks the archive, so a catalog row with no folder is never"
        " seen. strict=True turns this into a failure the moment 44b makes it"
        " pass, so the mark cannot outlive the fix."
    ),
)
def test_doctor_fails_on_a_catalog_row_whose_folder_is_missing(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Edge case: after a partial copy the catalog names a session whose folder
    the share does not hold. The 25-folder verify must FAIL on it, not skip it."""
    _vault_only_capture(ccw_env, tmp_path)
    target = tmp_path / "archive"
    good_marker(target)
    report = doctor.diagnose(
        config_for(tmp_path, target, keep_objects=True), home=Path(ccw_env["HOME"])
    )
    assert not check(report, "desync").ok
