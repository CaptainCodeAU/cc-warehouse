"""Oracle tests: `ccw build` must not act on a head superseded during its own run.

Open item W-20260929-A58, ruling option A (principal, 2026-09-29). `build.build()`
takes ONE snapshot of the heads and iterates it; on the network share that loop
runs for over two hours. A SessionEnd hook capture during the run can insert a
newer row for a session the loop has not reached yet and rewrite that session's
archive JSONL. Measured live 2026-09-28 (session 0279e609, 5f32 -> 086a): the
build later reached the stale head, the archive JSONL no longer hashed to it,
`archive.read_payload` fell back to a vault that `keep_objects = false` had
retired, and the item was reported as a FAILURE although nothing was wrong.

Three consequences of the one stale snapshot, one test each:

1. `keep_objects = false`: a spurious "error" outcome (the live incident).
2. `keep_objects = true` (the shipped default): the stale, SMALLER payload is
   offered to the archive folder, refused, and the refusal is written into the
   manifest as `replace_refused` - a record of a refusal that only happened
   because the build was stale (F6-shaped misinformation).
3. `keep_projections = true`: the new head's projection dir, written by the
   hook's render child, is not in the build's `expected` set, so the end-of-run
   prune deletes it (R4 deletes something current).

The race is made DETERMINISTIC, never by sleeps or threads: `build._heads` is
wrapped so that the newer version is captured (in-process, the same
`capture.capture_transcript` the hook runs) and the render child is run (the same
`ccw render --session` verb the hook spawns) immediately AFTER the real snapshot
is taken and BEFORE the loop reaches the item. That is exactly the ordering the
2026-09-28 incident had.
"""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from cc_warehouse import build, capture, catalog
from cc_warehouse.config import Config, load_config
from cc_warehouse.reports import BatchReport
from conftest import (
    catalog_rows,
    entry,
    jsonl,
    mark_archive,
    run_cli,
    warehouse_root,
    write_transcript,
)

ZONE = "UTC"
CWD = "/home/alice/projects/widget"
UUID = "c0ffee00-1111-4222-8333-444444444444"
OTHER = "c0ffee00-5555-4666-8777-888888888888"


def _v1(uuid: str = UUID) -> bytes:
    return jsonl(
        entry(
            "user", "Please fix the widget", "2026-05-07T03:47:45.000Z", session_id=uuid, cwd=CWD
        ),
        entry(
            "assistant",
            [{"type": "text", "text": "Fixed."}],
            "2026-05-07T03:47:50.000Z",
            session_id=uuid,
            cwd=CWD,
        ),
    )


def _v2(uuid: str = UUID) -> bytes:
    """The same session, grown in place: strictly larger, strictly later."""
    return _v1(uuid) + jsonl(
        entry("user", "And the gadget too", "2026-05-07T04:10:00.000Z", session_id=uuid, cwd=CWD),
        entry(
            "assistant",
            [{"type": "text", "text": "Gadget fixed as well."}],
            "2026-05-07T04:10:05.000Z",
            session_id=uuid,
            cwd=CWD,
        ),
    )


def _configure(
    env: dict[str, str],
    archive_root: Path | None,
    *,
    keep_objects: bool,
    keep_projections: bool,
) -> Config:
    cfg = Path(env["HOME"]) / ".config" / "cc-warehouse"
    cfg.mkdir(parents=True, exist_ok=True)
    lines = [f'root = "{warehouse_root(env)}"', f'archive_timezone = "{ZONE}"']
    if archive_root is not None:
        lines.append(f'archive_root = "{archive_root}"')
        mark_archive(archive_root, ZONE)
    lines.append(f"keep_objects = {'true' if keep_objects else 'false'}")
    lines.append(f"keep_projections = {'true' if keep_projections else 'false'}")
    (cfg / "config.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return load_config()


def _capture(env: dict[str, str], config: Config, data: bytes, uuid: str = UUID) -> str:
    """Capture `data` exactly as the hook does (in-process) and return its short."""
    transcript = write_transcript(env, data, session_id=uuid, name=f"{uuid}.jsonl")
    result = capture.capture_transcript(config, transcript, session_id=uuid, cwd=CWD)
    assert result.action == "stored", result
    return result.short


def _render_child(short: str) -> None:
    """What the hook's detached render child does for the new version."""
    result = run_cli(["render", "--session", f"s:{short}"])
    assert result.code == 0, result.err


def _race_after_snapshot(
    monkeypatch: pytest.MonkeyPatch, action: Callable[[], None]
) -> None:
    """Run `action` once, right after the build's real heads snapshot is taken."""
    real = build._heads  # pyright: ignore[reportPrivateUsage]
    fired: list[bool] = []

    def racing(conn: object, include_hidden: bool) -> list[object]:
        heads = real(conn, include_hidden)  # type: ignore[arg-type]
        if not fired:
            fired.append(True)
            action()
        return heads  # type: ignore[return-value]

    monkeypatch.setattr(build, "_heads", racing)


def _actions(report: BatchReport) -> list[str]:
    return sorted(outcome.action for outcome in report.outcomes)


def _manifest(archive_root: Path) -> dict[str, object]:
    manifests = sorted(archive_root.rglob("manifest.json"))
    assert len(manifests) == 1, manifests
    return json.loads(manifests[0].read_text(encoding="utf-8"))


def _hash_of(short: str, env: dict[str, str]) -> str:
    rows = catalog_rows(env, "SELECT hash FROM session WHERE short = ?", (short,))
    return str(rows[0][0])  # type: ignore[index]


# ---------------------------------------------------------------------------
# 1. keep_objects = false: the live incident
# ---------------------------------------------------------------------------


def test_a_head_superseded_mid_run_is_skipped_not_failed_without_a_vault(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive_root = tmp_path / "archive"
    config = _configure(ccw_env, archive_root, keep_objects=False, keep_projections=False)
    _capture(ccw_env, config, _v1())
    assert _actions(build.build(config)) == ["built"]

    def newer_version_lands() -> None:
        _render_child(_capture(ccw_env, config, _v2()))

    _race_after_snapshot(monkeypatch, newer_version_lands)
    report = build.build(config)

    assert report.failures == (), report.failures
    assert _actions(report) == ["superseded"]
    # Nothing this run did disturbed the newer version the hook laid down.
    manifest = _manifest(archive_root)
    assert manifest["source_hash"] == catalog_rows(
        ccw_env, "SELECT hash FROM session ORDER BY rowid DESC LIMIT 1"
    )[0][0]  # type: ignore[index]


# ---------------------------------------------------------------------------
# 2. keep_objects = true: no misleading refusal note
# ---------------------------------------------------------------------------


def test_a_head_superseded_mid_run_writes_no_refusal_note_with_a_vault(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive_root = tmp_path / "archive"
    config = _configure(ccw_env, archive_root, keep_objects=True, keep_projections=False)
    _capture(ccw_env, config, _v1())
    assert _actions(build.build(config)) == ["built"]

    new_short: list[str] = []

    def newer_version_lands() -> None:
        new_short.append(_capture(ccw_env, config, _v2()))
        _render_child(new_short[0])

    _race_after_snapshot(monkeypatch, newer_version_lands)
    report = build.build(config)

    manifest = _manifest(archive_root)
    assert "replace_refused" not in manifest, manifest.get("replace_refused")
    assert manifest["source_hash"] == _hash_of(new_short[0], ccw_env)
    assert _actions(report) == ["superseded"]


# ---------------------------------------------------------------------------
# 3. keep_projections = true: the new head's projections survive the prune
# ---------------------------------------------------------------------------


def test_the_new_heads_projection_dir_survives_the_prune(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive_root = tmp_path / "archive"
    config = _configure(ccw_env, archive_root, keep_objects=True, keep_projections=True)
    _capture(ccw_env, config, _v1())
    assert _actions(build.build(config)) == ["built"]
    projections = warehouse_root(ccw_env) / "projections"

    new_short: list[str] = []

    def newer_version_lands() -> None:
        new_short.append(_capture(ccw_env, config, _v2()))
        _render_child(new_short[0])

    _race_after_snapshot(monkeypatch, newer_version_lands)
    build.build(config)

    dirs = [p.name for p in projections.glob("*/*") if p.is_dir()]
    assert any(name.endswith(f"s-{new_short[0]}") for name in dirs), (
        f"the new head's projection dir was pruned by a stale build: {dirs}"
    )


def test_a_new_version_landing_after_its_old_head_was_built_is_not_pruned_or_lost(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Edge case 2: the loop has ALREADY rendered the old head when the new row
    lands. This run must not prune the new head's dir, and the NEXT build must
    pick the new version up (no permanent staleness) and retire the old dir."""
    archive_root = tmp_path / "archive"
    config = _configure(ccw_env, archive_root, keep_objects=True, keep_projections=True)
    _capture(ccw_env, config, _v1())
    projections = warehouse_root(ccw_env) / "projections"

    new_short: list[str] = []
    real_mirror = build._mirror  # pyright: ignore[reportPrivateUsage]

    def mirror_then_land(*args: object, **kwargs: object) -> None:
        real_mirror(*args, **kwargs)  # type: ignore[arg-type]
        if not new_short:
            new_short.append(_capture(ccw_env, config, _v2()))
            _render_child(new_short[0])

    monkeypatch.setattr(build, "_mirror", mirror_then_land)
    assert _actions(build.build(config)) == ["built"]
    dirs = [p.name for p in projections.glob("*/*") if p.is_dir()]
    assert any(name.endswith(f"s-{new_short[0]}") for name in dirs), dirs

    monkeypatch.setattr(build, "_mirror", real_mirror)
    assert build.build(config).failures == ()
    dirs = [p.name for p in projections.glob("*/*") if p.is_dir()]
    assert len(dirs) == 1 and dirs[0].endswith(f"s-{new_short[0]}"), dirs
    assert _manifest(archive_root)["source_hash"] == _hash_of(new_short[0], ccw_env)


# ---------------------------------------------------------------------------
# 4. an ordinary build is unchanged
# ---------------------------------------------------------------------------


def test_an_ordinary_build_is_unchanged(ccw_env: dict[str, str], tmp_path: Path) -> None:
    """No concurrent capture: the same outcomes, and the same CLI summary line,
    as before this fix. Nothing in an ordinary run is ever "superseded"."""
    config = _configure(ccw_env, tmp_path / "archive", keep_objects=True, keep_projections=True)
    _capture(ccw_env, config, _v1(UUID), UUID)
    _capture(ccw_env, config, _v1(OTHER), OTHER)
    first = run_cli(["build"])
    assert first.code == 0, first.err
    assert first.out.strip() == "build: 2 sessions, 2 built, 0 unchanged, 0 failed"
    second = run_cli(["build"])
    assert second.code == 0, second.err
    assert second.out.strip() == "build: 2 sessions, 0 built, 2 unchanged, 0 failed"


def test_the_cli_reports_superseded_as_its_own_segment_not_a_failure(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _configure(ccw_env, tmp_path / "archive", keep_objects=False, keep_projections=False)
    _capture(ccw_env, config, _v1(UUID), UUID)
    _capture(ccw_env, config, _v1(OTHER), OTHER)
    assert build.build(config).failures == ()

    def newer_version_lands() -> None:
        _render_child(_capture(ccw_env, config, _v2(UUID), UUID))

    _race_after_snapshot(monkeypatch, newer_version_lands)
    result = run_cli(["build"])
    assert result.code == 0, result.err
    assert "failed:" not in result.err, result.err
    assert result.out.strip() == (
        "build: 2 sessions, 0 built, 1 unchanged, 0 failed, 1 superseded during this run"
    )


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_superseded_by_a_hidden_version_is_still_skipped(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Edge case 1: the new head is hidden and the build does not include hidden
    rows. The stale visible head is still not current, so it is still skipped:
    the check asks "is this still the head", not "is there a visible head"."""
    archive_root = tmp_path / "archive"
    config = _configure(ccw_env, archive_root, keep_objects=False, keep_projections=False)
    _capture(ccw_env, config, _v1())
    assert _actions(build.build(config)) == ["built"]
    hidden_v2 = jsonl(
        entry("user", "warmup", "2026-05-07T05:00:00.000Z", session_id=UUID, cwd=CWD)
    )

    def hidden_version_lands() -> None:
        short = _capture(ccw_env, config, hidden_v2)
        rows = catalog_rows(ccw_env, "SELECT hidden FROM session WHERE short = ?", (short,))
        # Control: the fixture must really be a newer, hidden head, or this proves nothing.
        assert rows == [(1,)], rows

    _race_after_snapshot(monkeypatch, hidden_version_lands)
    report = build.build(config)
    assert report.failures == (), report.failures
    assert _actions(report) == ["superseded"]


def test_a_failed_head_check_is_one_failed_item_not_an_aborted_batch(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Edge case 4 (R10): the catalog is locked past busy_timeout at the instant
    of one re-check. That item is reported as failed (the conservative branch: it
    was not shown to be current, so it is neither built nor skipped as current),
    and every other item still runs."""
    config = _configure(ccw_env, tmp_path / "archive", keep_objects=False, keep_projections=False)
    _capture(ccw_env, config, _v1(UUID), UUID)
    _capture(ccw_env, config, _v1(OTHER), OTHER)
    real = catalog.latest_version
    calls: list[str | None] = []

    def flaky(conn: object, session_uuid: str | None) -> str | None:
        calls.append(session_uuid)
        if len(calls) == 1:
            import sqlite3

            raise sqlite3.OperationalError("database is locked")
        return real(conn, session_uuid)  # type: ignore[arg-type]

    monkeypatch.setattr(catalog, "latest_version", flaky)
    report = build.build(config)
    assert _actions(report) == ["built", "error"], report.outcomes
    assert "database is locked" in report.failures[0].detail
