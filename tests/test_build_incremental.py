"""Oracle tests: `build.build()`'s cheap pre-check (ticket 31, sibling to ticket
30's `archive.folder_is_current`). See harness/tickets/31-sweep-full-corpus-cost.md.

`build.build()` unconditionally read+rendered every catalog head, every run,
even when nothing had changed (ticket 28.20: ~6 minutes on a 14,246-session
corpus, larger now). `archive.pages_are_current`/`archive.folder_is_current`
answer "would rebuilding this head produce byte-identical output" from a
small manifest read alone, and `build._head_is_current` skips the
read-parse-render path entirely - across BOTH trees a deployment might keep -
when they say yes.

A first attempt (guarding the whole `build.build()` call in `ccw sweep` on
`keep_projections`) was caught and retracted before shipping: it would have
skipped `_mirror`, which is the ONLY thing that renders a swept session's
archive pages (the daily safety net never spawns a per-session detached
render child - see `tests/test_sweep_projects.py`). Every "must stay green"
test below pins a case that mistaken design would have broken, so it cannot
be silently reintroduced.

Contract: DESIGN section 6 (frozen manifest keys), section 15 2026-08-18 /
2026-08-20 (the ticket-30 decision, extended to `build.build()`); R1
(content-hash identity, never mtime/size), R5 (any doubt rebuilds), R9 (one
predicate, not two copies of this truth), R10/F6 (never silently do less and
say nothing).
"""

import json
from pathlib import Path
from typing import cast

import pytest

from cc_warehouse import __version__, archive
from cc_warehouse.render import RenderOptions
from conftest import (
    basic_session,
    entry,
    hook_payload,
    jsonl,
    record_opens,
    run_ccw,
    run_cli,
    warehouse_root,
    write_transcript,
)

ZONE = "Australia/Melbourne"
OPTS = RenderOptions()
UUID_A = "e3111111-2222-3333-4444-555555555561"
UUID_B = "e3111111-2222-3333-4444-555555555562"
_MANIFEST = archive.GENERATED_NAMES[-1]


def configure(env: dict[str, str], *, archive_root: Path | None, keep: bool | None) -> None:
    cfg = Path(env["HOME"]) / ".config" / "cc-warehouse"
    cfg.mkdir(parents=True, exist_ok=True)
    lines = [f'root = "{warehouse_root(env)}"', f'archive_timezone = "{ZONE}"']
    if archive_root is not None:
        lines.append(f'archive_root = "{archive_root}"')
    if keep is not None:
        lines.append(f"keep_projections = {'true' if keep else 'false'}")
    (cfg / "config.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    env["XDG_CONFIG_HOME"] = str(cfg.parent)


def capture(
    env: dict[str, str],
    data: bytes | None = None,
    *,
    uuid: str = UUID_A,
    encoded_dir: str = "-home-alice-projects-widget",
) -> None:
    payload = data if data is not None else basic_session(session_id=uuid)
    transcript = write_transcript(env, payload, session_id=uuid, encoded_dir=encoded_dir,
                                   name=f"{uuid}.jsonl")
    result = run_ccw(["hook"], env, stdin=hook_payload(transcript, session_id=uuid))
    assert result.code == 0, result.err


def projection_dirs(env: dict[str, str]) -> list[Path]:
    projections = warehouse_root(env) / "projections"
    if not projections.is_dir():
        return []
    return [p for p in projections.glob("*/*") if p.is_dir()]


def manifest_of(directory: Path) -> dict[str, object]:
    return json.loads((directory / _MANIFEST).read_text(encoding="utf-8"))


def write_manifest(directory: Path, manifest: dict[str, object]) -> None:
    (directory / _MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")


def mtimes_of(directory: Path) -> dict[str, int]:
    return {name: (directory / name).stat().st_mtime_ns for name in archive.GENERATED_NAMES}


# ---------------------------------------------------------------------------
# The big win: skipping before the stored payload is even read
# ---------------------------------------------------------------------------


def test_a_second_build_opens_no_session_payload_at_all(ccw_env: dict[str, str]) -> None:
    """THE BIG WIN, proved black-box - same instrument ticket 30 used for
    `ccw archive` (record_opens), applied to `ccw build`."""
    capture(ccw_env)
    root = warehouse_root(ccw_env)
    with record_opens(root / "objects") as first_opens:
        assert run_cli(["build"]).code == 0
    assert first_opens, "control failed: build never touched objects/, instrument not live"

    with record_opens(root / "objects") as second_opens:
        assert run_cli(["build"]).code == 0
    assert second_opens == [], "build.build() re-read the payload though nothing changed"


def test_a_second_build_reports_the_session_as_unchanged_not_built(ccw_env: dict[str, str]) -> None:
    capture(ccw_env)
    assert run_cli(["build"]).code == 0
    result = run_cli(["build"])
    assert result.code == 0, result.err
    assert "1 unchanged" in result.out
    assert "0 built" in result.out


def test_a_projection_only_warehouse_reaches_unchanged(ccw_env: dict[str, str]) -> None:
    configure(ccw_env, archive_root=None, keep=None)
    capture(ccw_env)
    assert run_cli(["build"]).code == 0
    result = run_cli(["build"])
    assert result.code == 0, result.err
    assert "1 unchanged" in result.out


def test_an_archive_only_warehouse_reaches_unchanged(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """This deployment's actual configuration: `keep_projections = false`."""
    target = tmp_path / "archive"
    configure(ccw_env, archive_root=target, keep=False)
    capture(ccw_env)
    assert run_cli(["build"]).code == 0
    result = run_cli(["build"])
    assert result.code == 0, result.err
    assert "1 unchanged" in result.out
    assert "0 built" in result.out
    assert projection_dirs(ccw_env) == [], "the retired tree must never regrow"


def test_pages_are_current_but_not_folder_is_current_on_a_projection_dir(
    ccw_env: dict[str, str],
) -> None:
    """Pins WHY the split exists: a projection manifest never has a `subagents`
    key, so `folder_is_current` unmodified would always return False there."""
    capture(ccw_env)
    assert run_cli(["build"]).code == 0
    directory = projection_dirs(ccw_env)[0]
    source_hash = str(manifest_of(directory)["source_hash"])
    assert archive.pages_are_current(directory, source_hash, OPTS)
    assert not archive.folder_is_current(directory, source_hash, OPTS)


# ---------------------------------------------------------------------------
# The regression net: everything that was already true must still be true
# ---------------------------------------------------------------------------


def test_the_archive_half_and_the_projection_half_must_both_be_current(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The AND, pinned. Both trees live; only the archive side is damaged; a
    plain `ccw build` must still repair it even though projections are fine."""
    target = tmp_path / "archive"
    configure(ccw_env, archive_root=target, keep=True)
    capture(ccw_env)
    assert run_cli(["build"]).code == 0
    archive_folder = next(archive.walk_folders(target))
    (archive_folder / "transcript.md").unlink()

    result = run_cli(["build"])
    assert result.code == 0, result.err
    assert (archive_folder / "transcript.md").is_file(), "the archive half was not checked"


def test_a_deleted_projection_file_is_restored_by_a_plain_build(ccw_env: dict[str, str]) -> None:
    capture(ccw_env)
    assert run_cli(["build"]).code == 0
    directory = projection_dirs(ccw_env)[0]
    (directory / "transcript.md").unlink()

    result = run_cli(["build"])
    assert result.code == 0, result.err
    assert (directory / "transcript.md").is_file()


def test_a_renderer_version_change_forces_a_rebuild_through_the_new_path(
    ccw_env: dict[str, str],
) -> None:
    """H1 at build level (ticket 30's hazard, previously only pinned for
    `ccw archive`). Without this, a `ccw` upgrade would leave an existing
    projection dir frozen at the old format forever."""
    capture(ccw_env)
    assert run_cli(["build"]).code == 0
    directory = projection_dirs(ccw_env)[0]
    manifest = manifest_of(directory)
    assert manifest["renderer_version"] == __version__
    manifest["renderer_version"] = "0.0.0-older"
    write_manifest(directory, manifest)

    result = run_cli(["build"])
    assert result.code == 0, result.err
    assert manifest_of(directory)["renderer_version"] == __version__


def test_a_render_config_change_forces_a_rebuild_through_the_new_path(
    ccw_env: dict[str, str],
) -> None:
    capture(ccw_env)
    assert run_cli(["build"]).code == 0
    directory = projection_dirs(ccw_env)[0]
    before = cast(dict[str, object], manifest_of(directory)["config"])
    assert before["breadcrumbs"] is False

    result = run_cli(["build", "--breadcrumbs"])
    assert result.code == 0, result.err
    after = cast(dict[str, object], manifest_of(directory)["config"])
    assert after["breadcrumbs"] is True


def test_an_interrupted_write_is_not_trusted_as_current(ccw_env: dict[str, str]) -> None:
    """Ticket 30's third hazard, at build level: fresh-looking pages sitting
    beside a manifest whose `source_hash` no longer matches the real payload
    must never be read as "done"."""
    capture(ccw_env)
    assert run_cli(["build"]).code == 0
    directory = projection_dirs(ccw_env)[0]
    stale_manifest = manifest_of(directory)
    (directory / "transcript.md").write_text("garbage from an interrupted write", encoding="utf-8")

    grown = basic_session(session_id=UUID_A) + jsonl(
        entry("user", "more", "2026-01-05T11:00:00.000Z", session_id=UUID_A)
    )
    capture(ccw_env, grown)

    result = run_cli(["build"])
    assert result.code == 0, result.err
    dirs = projection_dirs(ccw_env)
    assert len(dirs) == 1, "a grown payload must land in its own s-<hash12> dir, not overwrite"
    new_manifest = manifest_of(dirs[0])
    assert new_manifest["source_hash"] != stale_manifest["source_hash"]
    restored = (dirs[0] / "transcript.md").read_text(encoding="utf-8")
    assert restored != "garbage from an interrupted write"


def test_a_changed_payload_is_never_skipped(ccw_env: dict[str, str]) -> None:
    capture(ccw_env)
    assert run_cli(["build"]).code == 0
    first = projection_dirs(ccw_env)[0].name

    grown = basic_session(session_id=UUID_A) + jsonl(
        entry("user", "more", "2026-01-05T11:00:00.000Z", session_id=UUID_A)
    )
    capture(ccw_env, grown)
    result = run_cli(["build"])
    assert result.code == 0, result.err
    assert "1 built" in result.out
    dirs = projection_dirs(ccw_env)
    assert len(dirs) == 1
    assert dirs[0].name != first, "the grown payload landed in a new s-<hash12> dir"


def test_a_skipped_head_is_still_expected_by_the_prune(ccw_env: dict[str, str]) -> None:
    """The `expected.add(directory)` ordering, pinned directly. Two sessions,
    build twice: after the all-skipped second build, BOTH projection dirs
    still stand - a skipped head must never look "retired" to `_prune`."""
    capture(ccw_env, uuid=UUID_A, encoded_dir="-home-alice-projects-widget")
    capture(ccw_env, uuid=UUID_B, encoded_dir="-home-alice-projects-gadget")
    assert run_cli(["build"]).code == 0
    assert len(projection_dirs(ccw_env)) == 2

    result = run_cli(["build"])
    assert result.code == 0, result.err
    assert "2 unchanged" in result.out
    assert len(projection_dirs(ccw_env)) == 2, "a skipped-but-current dir was wrongly pruned"


def test_rebuild_forces_every_head_through_the_full_path(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Also pins the F-1 fix: `--rebuild` must move the ARCHIVE folder's
    mtimes too, not just the projection dir's - `_mirror` used to drop the
    `rebuild` flag on the floor, silently."""
    target = tmp_path / "archive"
    configure(ccw_env, archive_root=target, keep=True)
    capture(ccw_env)
    assert run_cli(["build"]).code == 0

    projection_before = mtimes_of(projection_dirs(ccw_env)[0])
    archive_folder = next(archive.walk_folders(target))
    archive_before = mtimes_of(archive_folder)

    result = run_cli(["build", "--rebuild"])
    assert result.code == 0, result.err
    assert "1 built" in result.out
    assert "0 unchanged" in result.out
    assert mtimes_of(projection_dirs(ccw_env)[0]) != projection_before
    assert mtimes_of(archive_folder) != archive_before, "F-1: --rebuild did not force the archive"


def test_hidden_sessions_are_still_projected_by_include_hidden(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """A hidden session's ARCHIVE folder holds only its JSONL, never the five
    generated files (`write_session_folder`'s own early return) - so
    `folder_is_current` can never return True for it, and a hidden head can
    never be wrongly skipped once an archive is configured, even though the
    old `projections/` tree (which has no such hidden concept in `build.py`'s
    own loop) genuinely does hold five files for it."""
    target = tmp_path / "archive"
    configure(ccw_env, archive_root=target, keep=True)
    capture(ccw_env, jsonl(entry("user", "warmup", "2026-01-05T10:00:00.000Z", session_id=UUID_A)))

    assert run_cli(["build", "--include-hidden"]).code == 0
    assert len(projection_dirs(ccw_env)) == 1, "the old tree still projects a hidden head"
    result = run_cli(["build", "--include-hidden"])
    assert result.code == 0, result.err
    assert "0 unchanged" in result.out, "a hidden head must never report as current"


# ---------------------------------------------------------------------------
# Ticket 34: a mirror failure must surface as an error, never a silent "built"
# ---------------------------------------------------------------------------


def test_a_mirror_failure_is_reported_as_an_error_not_built(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_mirror` used to swallow any exception from `write_session_folder` and
    return as if nothing happened, so `build()`'s per-head loop recorded
    "built" (success) for a head whose archive folder was never actually
    written. Real incident, 2026-08-04 (cli.py's `_run_sweep` comment):
    a sweep-triggered build stored 642 sessions with zero rendered pages,
    invisible until a manual `ccw archive --verify`. This pins the fix:
    the failure must reach `build()`'s own existing per-head `except`, which
    already knows how to report it (R10)."""
    target = tmp_path / "archive"
    configure(ccw_env, archive_root=target, keep=True)
    capture(ccw_env)

    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("simulated mirror failure")

    monkeypatch.setattr(archive, "write_session_folder", boom)
    result = run_cli(["build"])
    assert result.code != 0, "a swallowed mirror failure reported success"
    assert "1 failed" in result.out, result.out
    assert "0 built" in result.out, result.out
    assert "RuntimeError: simulated mirror failure" in result.err, result.err


def test_a_mirror_failure_blocks_pruning_of_the_projections_tree(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`build()` only prunes retired projection dirs after a fully-successful
    run (F7/F9: keep the last-good tree rather than strand a session with
    zero projections). A swallowed mirror failure hid errors from that guard
    too. Grow a session's payload (the existing "landed in a new dir" fixture
    above) so its OLD projection dir becomes genuinely retired, then make the
    grown head's mirror fail: the retired dir must still stand, because the
    build as a whole did not succeed."""
    target = tmp_path / "archive"
    configure(ccw_env, archive_root=target, keep=True)
    capture(ccw_env)
    assert run_cli(["build"]).code == 0
    retired = projection_dirs(ccw_env)[0]
    assert retired.is_dir()

    grown = basic_session(session_id=UUID_A) + jsonl(
        entry("user", "more", "2026-01-05T11:00:00.000Z", session_id=UUID_A)
    )
    capture(ccw_env, grown)

    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("simulated mirror failure")

    monkeypatch.setattr(archive, "write_session_folder", boom)
    result = run_cli(["build"])
    assert result.code != 0
    assert retired.is_dir(), "pruning ran despite a failed head; a bad build ate a good dir"
