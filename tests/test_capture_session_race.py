"""Oracle tests: the archive ends on a session's newest payload (W-20260929-A104).

THE HOLE. The capture lock is per payload HASH, so two captures of ONE session
with different payloads (the SessionEnd hook for an older copy and a later one,
or the hook racing the sweep) run at once. `archive.write_source` decides "is
there a file / is mine larger" and then writes; with both deciding before either
writes, the older, smaller payload can land last. The catalog's head is then the
newer payload, the sweep's pre-filter skips it (its hash is cataloged), and with
the vault retired the build cannot even read it: the archive keeps the older copy
for good.

THE RULE (Gavin, 2026-09-29, option C). Prevent: every JSONL writer decides and
writes under one per-session lock (`archive.session_lock`). Repair: for sessions
whose catalog holds two or more versions, the sweep puts the head payload back
when the archive's JSONL is shorter than the source that hashes to the head.

THE RACE IS DETERMINISTIC, never a sleep to hope for an interleaving: the older
capture's JSONL write is paused (holding whatever it holds at that moment) while
the newer capture runs in a second thread. Without the lock the newer one
finishes first and the older write lands last; with it, the newer one waits.

Contract: R1 as amended, R5, R9, R14, F3.
"""

import ast
import threading
from collections.abc import Callable
from pathlib import Path

import pytest

from cc_warehouse import build, capture, store, sweep
from cc_warehouse.config import Config, load_config
from conftest import SRC_ROOT, entry, jsonl, mark_archive, warehouse_root, write_transcript

ZONE = "UTC"
UUID = "0a104000-1111-4222-8333-444444444444"
CWD = "/home/alice/projects/widget"


def _version(turns: int) -> bytes:
    lines = [
        entry(
            "user", "Please fix the widget", "2026-05-07T03:47:45.000Z", session_id=UUID, cwd=CWD
        )
    ]
    for n in range(1, turns):
        lines.append(
            entry(
                "user", f"and step {n}", f"2026-05-07T04:{n:02d}:00.000Z", session_id=UUID, cwd=CWD
            )
        )
    return jsonl(*lines)


OLDER, NEWER, NEWEST = _version(1), _version(2), _version(3)


def _configure(env: dict[str, str], archive_root: Path) -> Config:
    cfg = Path(env["HOME"]) / ".config" / "cc-warehouse"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "config.toml").write_text(
        f'root = "{warehouse_root(env)}"\narchive_root = "{archive_root}"\n'
        f'archive_timezone = "{ZONE}"\nkeep_objects = false\nkeep_projections = false\n',
        encoding="utf-8",
    )
    mark_archive(archive_root, ZONE)
    return load_config()


def _archived_jsonl(archive_root: Path) -> Path:
    found = sorted(archive_root.rglob(f"{UUID}.jsonl"))
    assert len(found) == 1, found
    return found[0]


def _capture(config: Config, transcript: Path) -> None:
    result = capture.capture_transcript(config, transcript, session_id=UUID, cwd=CWD)
    assert result.action == "stored", result


def _race(
    monkeypatch: pytest.MonkeyPatch, config: Config, older: Path, rivals: list[Callable[[], None]]
) -> None:
    """Capture `older`, pausing its JSONL write while each rival runs in its own
    thread; the rivals get one second to finish (no lock) or block (lock)."""
    real = store.atomic_write
    paused = threading.Event()
    go_on = threading.Event()

    def racing(path: Path, data: bytes) -> None:
        if path.name == f"{UUID}.jsonl" and data == OLDER and not paused.is_set():
            paused.set()
            assert go_on.wait(30), "the race harness never released the older write"
        real(path, data)

    monkeypatch.setattr(store, "atomic_write", racing)
    errors: list[BaseException] = []

    def run(fn: Callable[[], None]) -> threading.Thread:
        def body() -> None:
            try:
                fn()
            except BaseException as exc:  # noqa: BLE001 - surfaced by the assert below
                errors.append(exc)

        thread = threading.Thread(target=body)
        thread.start()
        return thread

    first = run(lambda: _capture(config, older))
    assert paused.wait(30), "the older capture never reached its JSONL write"
    others = [run(rival) for rival in rivals]
    for thread in others:
        thread.join(1.0)
    go_on.set()
    for thread in [first, *others]:
        thread.join(60)
    assert not errors, errors


def test_two_captures_of_one_session_end_on_the_newer_payload(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive_root = tmp_path / "archive"
    config = _configure(ccw_env, archive_root)
    older = write_transcript(ccw_env, OLDER, session_id=UUID, name="older.jsonl")
    newer = write_transcript(ccw_env, NEWER, session_id=UUID, name="newer.jsonl")

    _race(monkeypatch, config, older, [lambda: _capture(config, newer)])

    assert _archived_jsonl(archive_root).read_bytes() == NEWER, (
        "the older payload landed last and the archive kept it"
    )


def test_three_captures_at_once_end_on_the_newest(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive_root = tmp_path / "archive"
    config = _configure(ccw_env, archive_root)
    older = write_transcript(ccw_env, OLDER, session_id=UUID, name="older.jsonl")
    newer = write_transcript(ccw_env, NEWER, session_id=UUID, name="newer.jsonl")
    newest = write_transcript(ccw_env, NEWEST, session_id=UUID, name="newest.jsonl")

    _race(
        monkeypatch,
        config,
        older,
        [lambda: _capture(config, newest), lambda: _capture(config, newer)],
    )

    assert _archived_jsonl(archive_root).read_bytes() == NEWEST


def test_a_capture_racing_the_sweep_ends_on_the_newer_payload(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive_root = tmp_path / "archive"
    config = _configure(ccw_env, archive_root)
    older = tmp_path / "older.jsonl"  # outside the sweep's source, like a hook's stale copy
    older.write_bytes(OLDER)
    write_transcript(ccw_env, NEWER, session_id=UUID, name=f"{UUID}.jsonl")
    source = Path(ccw_env["HOME"]) / ".claude" / "projects"

    _race(monkeypatch, config, older, [lambda: sweep.sweep(config, source) and None])

    assert _archived_jsonl(archive_root).read_bytes() == NEWER


# ---------------------------------------------------------------------------
# The repair half
# ---------------------------------------------------------------------------


def _lost_race(ccw_env: dict[str, str], config: Config, archive_root: Path) -> None:
    """The end state the race used to leave: two versions cataloged, the newer
    the head and the source, the older on the archive."""
    older = write_transcript(ccw_env, OLDER, session_id=UUID, name="older.jsonl")
    _capture(config, older)
    older.unlink()
    _capture(config, write_transcript(ccw_env, NEWER, session_id=UUID, name=f"{UUID}.jsonl"))
    store.atomic_write(_archived_jsonl(archive_root), OLDER)


def test_a_later_sweep_puts_the_head_payload_back(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    config = _configure(ccw_env, archive_root)
    _lost_race(ccw_env, config, archive_root)

    report = sweep.sweep(config, Path(ccw_env["HOME"]) / ".claude" / "projects")
    build.build(config)

    assert _archived_jsonl(archive_root).read_bytes() == NEWER
    assert sweep.REPAIRED_JSONL in {o.action for o in report.outcomes}
    assert sweep.REPAIRED_JSONL in sweep.SIDECAR_ARCHIVED_ACTIONS  # the build re-renders it


def test_the_repair_never_recreates_a_missing_jsonl(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Whether a deleted folder self-heals from its source is an open ruling
    (ticket 45); the repair only ever replaces a SHORTER file."""
    archive_root = tmp_path / "archive"
    config = _configure(ccw_env, archive_root)
    _lost_race(ccw_env, config, archive_root)
    jsonl_path = _archived_jsonl(archive_root)
    jsonl_path.unlink()

    report = sweep.sweep(config, Path(ccw_env["HOME"]) / ".claude" / "projects")

    assert not jsonl_path.exists()
    assert sweep.REPAIRED_JSONL not in {o.action for o in report.outcomes}


def test_the_repair_leaves_a_single_version_session_alone(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Narrow by ruling: one version cannot have lost a same-session race, and
    checking every session would cost a share stat per session per day."""
    archive_root = tmp_path / "archive"
    config = _configure(ccw_env, archive_root)
    _capture(config, write_transcript(ccw_env, NEWER, session_id=UUID, name=f"{UUID}.jsonl"))
    store.atomic_write(_archived_jsonl(archive_root), OLDER)

    report = sweep.sweep(config, Path(ccw_env["HOME"]) / ".claude" / "projects")

    assert sweep.REPAIRED_JSONL not in {o.action for o in report.outcomes}


def test_every_product_caller_passes_the_warehouse_root() -> None:
    """The lock is keyed in the warehouse root, and a writer called without one
    takes no lock. Only tests of the folder writer alone may omit it."""
    missing: list[str] = []
    for path in sorted(SRC_ROOT.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name in {"write_source", "write_session_folder"} and not any(
                kw.arg == "warehouse_root" for kw in node.keywords
            ):
                missing.append(f"{path.name}:{node.lineno}")
    assert missing == []
