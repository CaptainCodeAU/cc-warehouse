"""Oracle tests: `ccw doctor` reads the archive INDEX, not the archive tree (ticket 44b/44c).

Contract: ticket 44 (`harness/tickets/44-archive-root-on-a-network-share.md`),
DESIGN section 15 entry "2026-09-28, ticket 44", DESIGN rule R12 (payload time,
never mtime).

THE FAILURE THIS EXISTS FOR. Measured 2026-09-28 on the real archive: one `ccw
doctor` run made 292,286 filesystem calls under `archive_root` (six full walks of
31,112 session folders, two of them opening one file per folder). Local disk:
33.7 s. On the SMB share the archive is moving to (3 ms per stat, 10 ms per
open): 15 to 40 minutes, against a 55 s SessionStart hook budget. Every session
start would block and report doctor `unreachable`.

WHAT IS PINNED HERE, and why each is a property rather than a number:

  1. doctor touches NOTHING under the archive outside the bounded recency sample
     (a folder older than the sample is never stat'ed, listed or opened), so the
     cost cannot creep back with the tree's size;
  2. the archived set and the recency sample come from the catalog, whose
     session_uuid set equals the archive walk's on real data (31,112 = 31,112,
     0 either way, measured 2026-09-28);
  3. the pending-render grace is measured from CAPTURE time (catalog
     `captured_at`), not from the session's own start time in the folder name,
     which is what a slow render child needs to be judged against;
  4. the two corpus-wide coverage lines (`sidecars`, `prompts`; ticket 38 ruling
     (e)) keep their corpus-wide meaning by moving the WALK to the daily sweep:
     sweep writes `logs/coverage.json`, doctor prints it with its age;
  5. the `Uncaptured: N session` figure `ccw-freshness-check.py` parses is
     unchanged in shape; the sub-agent count, which only the tree can answer
     until ticket 44d indexes sub-agents, moves to `ccw status`.
"""

import builtins
import json
import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from cc_warehouse import archive, doctor, status
from cc_warehouse.config import Config
from conftest import (
    basic_session,
    entry,
    jsonl,
    mark_archive,
    run_ccw,
    tree_snapshot,
    warehouse_root,
    write_transcript,
)

ZONE = "Australia/Melbourne"
UUID_A = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
UUID_B = "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"
UUID_OLD = "cccccccc-3333-4333-8333-cccccccccccc"
OLD = "2020-01-01T00:00:00.000Z"


def configure(env: dict[str, str], archive_root: Path) -> None:
    cfg = Path(env["HOME"]) / ".config" / "cc-warehouse"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "config.toml").write_text(
        f'root = "{warehouse_root(env)}"\n'
        f'archive_timezone = "{ZONE}"\n'
        f'archive_root = "{archive_root}"\n',
        encoding="utf-8",
    )
    env["XDG_CONFIG_HOME"] = str(cfg.parent)
    # Ticket 44a: every writer refuses an unmarked root, so a configured
    # archive is marked exactly as `ccw archive --to DIR --init` would.
    mark_archive(archive_root, ZONE)


def install_hook(env: dict[str, str]) -> None:
    settings = Path(env["HOME"]) / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(
        json.dumps(
            {"hooks": {"SessionEnd": [{"hooks": [{"type": "command", "command": "ccw hook"}]}]}}
        ),
        encoding="utf-8",
    )


def stale_session(session_id: str) -> bytes:
    return jsonl(
        entry("user", "hello", OLD, session_id=session_id),
        entry("assistant", "hi", OLD, session_id=session_id),
    )


def config_of(env: dict[str, str], archive_root: Path) -> Config:
    return Config(root=warehouse_root(env), archive_root=archive_root, archive_timezone=ZONE)


def folder_of(archive_root: Path, uuid: str) -> Path:
    folders = sorted(archive_root.glob(f"*/*_{uuid}"))
    assert len(folders) == 1, folders
    return folders[0]


def projects_of(env: dict[str, str]) -> Path:
    return Path(env["HOME"]) / ".claude" / "projects"


def overdue(env: dict[str, str], archive_root: Path) -> tuple[int, str | None]:
    return doctor._overdue(config_of(env, archive_root), projects_of(env))  # pyright: ignore[reportPrivateUsage]


def age_capture(env: dict[str, str], uuid: str, *, seconds_ago: int) -> None:
    """Move a catalog row's `captured_at` into the past. Test-only, on a scratch
    catalog: the product never rewrites this column."""
    stamp = (datetime.now(UTC) - timedelta(seconds=seconds_ago)).isoformat()
    conn = sqlite3.connect(warehouse_root(env) / "catalog.sqlite")
    try:
        with conn:
            conn.execute(
                "UPDATE session SET captured_at = ? WHERE session_uuid = ?", (stamp, uuid)
            )
    finally:
        conn.close()


class ArchiveTouches:
    """Every path under `root` that any filesystem call touched while active."""

    def __init__(self, root: Path) -> None:
        self.root = str(root)
        self.paths: set[str] = set()

    def _note(self, target: object) -> None:
        if isinstance(target, (str, bytes, os.PathLike)):
            text = os.fsdecode(cast("str | bytes | os.PathLike[str]", target))
            if text.startswith(self.root):
                self.paths.add(text)

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in ("stat", "lstat", "listdir", "scandir"):
            original = getattr(os, name)

            def wrapped(*args: object, _orig: object = original, **kwargs: object) -> object:
                if args:
                    self._note(args[0])
                elif "path" in kwargs:
                    self._note(kwargs["path"])
                return _orig(*args, **kwargs)  # type: ignore[operator]

            monkeypatch.setattr(os, name, wrapped)
        real_open = builtins.open

        def wrapped_open(file: object, *args: object, **kwargs: object) -> object:
            self._note(file)
            return real_open(file, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(builtins, "open", wrapped_open)

    def under(self, folder: Path) -> set[str]:
        prefix = str(folder)
        return {p for p in self.paths if p == prefix or p.startswith(prefix + os.sep)}


# ---------------------------------------------------------------------------
# 1. doctor never walks the archive
# ---------------------------------------------------------------------------


def test_doctor_never_touches_a_folder_outside_the_recency_sample(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE PROPERTY. With the sample bounded to one folder, the other archived
    folder must not be stat'ed, listed or opened by anything doctor does. On
    master every one of six walkers touched it."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    install_hook(ccw_env)
    write_transcript(ccw_env, stale_session(UUID_OLD), session_id=UUID_OLD)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    assert run_ccw(["sweep", "--quiet"], ccw_env).code == 0
    old_folder = folder_of(archive_root, UUID_OLD)
    new_folder = folder_of(archive_root, UUID_A)

    monkeypatch.setattr(doctor, "_DESYNC_SAMPLE", 1)
    touches = ArchiveTouches(archive_root)
    touches.install(monkeypatch)
    report = doctor.diagnose(config_of(ccw_env, archive_root), home=Path(ccw_env["HOME"]))

    assert touches.under(new_folder), "the control folder in the sample was never read"
    assert touches.under(old_folder) == set(), (
        "doctor touched a folder outside the recency sample: "
        f"{sorted(touches.under(old_folder))[:5]}"
    )
    assert touches.under(old_folder.parent) <= touches.under(new_folder), (
        "doctor listed the label directory itself"
    )
    assert [c.name for c in report.checks].count("desync") == 1


def test_doctor_touch_set_is_independent_of_tree_size(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Thirty extra folders that are NOT in the catalog (planted by hand, the
    shape a foreign or half-copied tree has) add zero touches: doctor asks the
    catalog what is recent, not the tree."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    install_hook(ccw_env)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    assert run_ccw(["sweep", "--quiet"], ccw_env).code == 0
    label_dir = folder_of(archive_root, UUID_A).parent
    config = config_of(ccw_env, archive_root)

    small = ArchiveTouches(archive_root)
    small.install(monkeypatch)
    doctor.diagnose(config, home=Path(ccw_env["HOME"]))
    monkeypatch.undo()

    for n in range(30):
        planted = label_dir / f"20991231-2359{n:02d}+1100_bbbbbbbb-1111-4111-8111-{n:012d}"
        planted.mkdir()
        (planted / "x.jsonl").write_bytes(b"{}\n")
    big = ArchiveTouches(archive_root)
    big.install(monkeypatch)
    doctor.diagnose(config, home=Path(ccw_env["HOME"]))

    assert big.paths == small.paths, sorted(big.paths - small.paths)[:5]


# ---------------------------------------------------------------------------
# 2. the archived set comes from the catalog
# ---------------------------------------------------------------------------


def test_a_cataloged_session_is_not_overdue_even_with_its_folder_gone(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The semantics, stated: 'captured' now means 'has a catalog row'. A folder
    that vanished after capture is the desync check's finding (below), not an
    overdue one. Documents the trade the ticket records; the negative arm is
    `test_a_missing_folder_in_the_sample_is_a_desync_problem`."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    write_transcript(ccw_env, stale_session(UUID_OLD), session_id=UUID_OLD)
    assert run_ccw(["sweep", "--quiet"], ccw_env).code == 0
    folder = folder_of(archive_root, UUID_OLD)
    folder.rename(folder.with_name("aside_" + folder.name))

    count, _oldest = overdue(ccw_env, archive_root)
    assert count == 0


def test_a_session_with_no_catalog_row_is_overdue(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Control for the test above: the check still fires on what it exists for."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    assert run_ccw(["sweep", "--quiet"], ccw_env).code == 0
    write_transcript(ccw_env, stale_session(UUID_OLD), session_id=UUID_OLD)

    count, oldest = overdue(ccw_env, archive_root)
    assert count == 1
    assert oldest is not None and oldest.startswith("2020-01-01")


def test_a_missing_folder_in_the_sample_is_a_desync_problem(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """THE HONESTY CONTROL on the catalog. A row whose folder is not on disk
    (a half-copied share, a folder removed by hand) must FAIL the desync check,
    never be skipped as 'not there to verify'."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    write_transcript(ccw_env, stale_session(UUID_OLD), session_id=UUID_OLD)
    assert run_ccw(["sweep", "--quiet"], ccw_env).code == 0
    folder = folder_of(archive_root, UUID_OLD)
    folder.rename(folder.with_name("aside_" + folder.name))
    age_capture(ccw_env, UUID_OLD, seconds_ago=3600)

    checked, problems, pending, first = doctor._desync(config_of(ccw_env, archive_root))  # pyright: ignore[reportPrivateUsage]
    assert checked == 1
    assert problems >= 1, "a cataloged session with no folder passed the desync check"
    assert pending == 0
    assert first is not None and UUID_OLD in first


def test_no_catalog_means_nothing_archived_and_no_exception(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Doctor runs when things are broken (module docstring). No catalog file at
    all: every check answers, none raises, nothing is created."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    install_hook(ccw_env)
    root = warehouse_root(ccw_env)
    before = tree_snapshot(tmp_path)

    report = doctor.diagnose(config_of(ccw_env, archive_root), home=Path(ccw_env["HOME"]))

    assert not (root / "catalog.sqlite").exists()
    assert tree_snapshot(tmp_path) == before
    names = [c.name for c in report.checks]
    assert {"overdue", "desync", "uncaptured", "sidecars", "prompts"} <= set(names)


# ---------------------------------------------------------------------------
# 3. the pending grace is measured from capture time (44c)
# ---------------------------------------------------------------------------


def _break_render(folder: Path) -> None:
    for name in archive.GENERATED_NAMES:
        path = folder / name
        if path.exists():
            path.unlink()


def test_an_old_session_captured_seconds_ago_is_pending_not_broken(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """A 2020 session swept just now with its render still missing is the live
    shape of a slow render child on a slow disk. Master keyed the grace on the
    folder name's 2020 start time and called it broken."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    write_transcript(ccw_env, stale_session(UUID_OLD), session_id=UUID_OLD)
    assert run_ccw(["sweep", "--quiet"], ccw_env).code == 0
    _break_render(folder_of(archive_root, UUID_OLD))

    checked, problems, pending, _first = doctor._desync(config_of(ccw_env, archive_root))  # pyright: ignore[reportPrivateUsage]
    assert checked == 1
    assert problems == 0, "a render captured seconds ago was called broken"
    assert pending >= 1


def test_the_same_folder_captured_an_hour_ago_is_broken(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Negative arm: the grace is a WINDOW, and an old capture is outside it."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    write_transcript(ccw_env, stale_session(UUID_OLD), session_id=UUID_OLD)
    assert run_ccw(["sweep", "--quiet"], ccw_env).code == 0
    _break_render(folder_of(archive_root, UUID_OLD))
    age_capture(ccw_env, UUID_OLD, seconds_ago=3600)

    checked, problems, pending, _first = doctor._desync(config_of(ccw_env, archive_root))  # pyright: ignore[reportPrivateUsage]
    assert checked == 1
    assert pending == 0
    assert problems >= 1


# ---------------------------------------------------------------------------
# 4. corpus-wide coverage lines: sweep computes, doctor shows with age
# ---------------------------------------------------------------------------


def test_sweep_writes_the_coverage_file(ccw_env: dict[str, str], tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    assert run_ccw(["sweep", "--quiet"], ccw_env).code == 0

    path = warehouse_root(ccw_env) / "logs" / "coverage.json"
    assert path.is_file()
    body = json.loads(path.read_text(encoding="utf-8"))
    assert body["schema"] == 1
    assert body["sidecars"]["notices"] == 0
    assert body["prompts"]["sessions_total"] == 1
    datetime.fromisoformat(body["at"])


def test_doctor_reports_the_sweeps_figures_with_their_age(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The line still names the corpus-wide figure and now says WHEN it was
    measured, so a stale sweep reads as stale rather than as clean."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    assert run_ccw(["sweep", "--quiet"], ccw_env).code == 0

    result = run_ccw(["doctor"], ccw_env)
    sidecars = next(x for x in result.out.splitlines() if " sidecars " in x)
    prompts = next(x for x in result.out.splitlines() if " prompts " in x)
    assert "0 folder(s) with unarchived siblings" in sidecars
    assert "as of " in sidecars
    assert "Prompts: 0/1 session(s) have prompts.jsonl" in prompts
    assert "as of " in prompts


def test_doctor_without_a_coverage_file_says_so_and_stays_ok(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """A fresh install, or one upgraded before its first sweep: an honest
    'not measured yet' line, non-blocking, never an exception, never a walk."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    install_hook(ccw_env)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    assert run_ccw(["sweep", "--quiet"], ccw_env).code == 0
    (warehouse_root(ccw_env) / "logs" / "coverage.json").unlink()

    report = doctor.diagnose(config_of(ccw_env, archive_root), home=Path(ccw_env["HOME"]))
    sidecars = next(c for c in report.checks if c.name == "sidecars")
    prompts = next(c for c in report.checks if c.name == "prompts")
    assert sidecars.ok and not sidecars.blocking
    assert prompts.ok and not prompts.blocking
    assert "sweep" in sidecars.detail.lower()
    assert "sweep" in prompts.detail.lower()


def test_status_still_computes_coverage_live(ccw_env: dict[str, str], tmp_path: Path) -> None:
    """`ccw status` is run by hand and may pay the walk: a notice planted AFTER
    the last sweep shows up there at once, while doctor shows the sweep's view."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    assert run_ccw(["sweep", "--quiet"], ccw_env).code == 0
    folder = folder_of(archive_root, UUID_A)
    (folder / "sidecars.json").write_text(
        json.dumps({"schema": 1, "refused": [], "unarchived": ["zzz-probe"],
                    "unknown_inside_subagents": []}),
        encoding="utf-8",
    )

    live = run_ccw(["status"], ccw_env)
    assert "Sidecars: 1 unarchived" in live.out
    doc = run_ccw(["doctor"], ccw_env)
    assert "0 folder(s) with unarchived siblings" in next(
        x for x in doc.out.splitlines() if " sidecars " in x
    )


# ---------------------------------------------------------------------------
# 5. the Uncaptured figure the freshness hook parses
# ---------------------------------------------------------------------------


def test_doctors_uncaptured_line_keeps_the_parsed_figure_and_points_to_status(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """`ccw-freshness-check.py` reads `Uncaptured:\\s*(\\d+)\\s*session`; that
    prefix is pinned byte for byte. The sub-agent count needs the tree (ticket
    44d indexes it) and is reported by `ccw status` instead."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    assert run_ccw(["sweep", "--quiet"], ccw_env).code == 0
    write_transcript(ccw_env, basic_session(session_id=UUID_B), session_id=UUID_B)

    result = run_ccw(["doctor"], ccw_env)
    line = next(x for x in result.out.splitlines() if "Uncaptured:" in x)
    projects = Path(ccw_env["HOME"]) / ".claude" / "projects"
    assert line.strip() == (
        f"ok  uncaptured  Uncaptured: 1 session(s) in {projects}"
        " with no catalog row (sub-agents: ccw status)"
    )


def test_status_uncaptured_line_still_counts_subagents(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    assert run_ccw(["sweep", "--quiet"], ccw_env).code == 0

    gap = status.uncaptured_gap(config_of(ccw_env, archive_root), projects_of(ccw_env))
    assert gap.subagents == 0
    assert "sub-agent(s)" in status.gap_line(gap)
    fast = status.uncaptured_gap(
        config_of(ccw_env, archive_root), projects_of(ccw_env), subagents=False
    )
    assert fast.subagents is None
    assert fast.sessions == gap.sessions
