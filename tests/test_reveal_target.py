"""Oracle tests: what folder a capture REVEALS (open_folder opt-in).

Contract: DESIGN section 12 (notification sinks, all best-effort, none may fail a
capture), section 4 (the hook path), R9 (one answer, not two), F6 (never silent).

THE DEFECT, measured on the real warehouse 2026-08-04. The skip branch revealed
`<root>/projections`. That directory stopped existing the previous day, when
`keep_projections = false` was set. `notify.open_folder` is a fire-and-forget
Popen whose exceptions are swallowed by design, so the reveal silently did
nothing and there was no way to tell that from "the feature is off".

Worse, the two branches disagreed: a FRESH capture reveals the session's own
archive folder (via the detached render child), while an unchanged re-fire
revealed a top-level projections directory. Same opt-in, two different answers,
one of them pointing at nothing.

NOT CHANGED, and it is a locked oracle test:
`test_capture.py::test_skip_path_honors_open_folder_opt_in` asserts THAT the skip
branch honours the opt-in. It says nothing about WHICH folder, so it constrains
the behaviour these tests sharpen rather than conflicting with it, and it passes
unchanged.
"""

import sqlite3
from pathlib import Path

import pytest

from conftest import (
    basic_session,
    catalog_path,
    hook_payload,
    run_ccw,
    run_cli,
    warehouse_root,
    write_transcript,
)


def backdate_events(env: dict[str, str]) -> None:
    """Push existing capture events out of the duplicate-suppression window, so
    the second hook run reports `skipped_unchanged` rather than being silent.

    Duplicated from test_capture.py rather than imported across test modules:
    conftest owns shared helpers, and a cross-file import would make this file's
    collection depend on that one's.
    """
    with sqlite3.connect(catalog_path(env)) as conn:
        conn.execute("UPDATE capture_event SET at = '2026-01-01T00:00:00Z'")
        conn.commit()

ZONE = "Australia/Melbourne"
UUID_A = "f1111111-2222-3333-4444-555555555551"


def configure(env: dict[str, str], tmp_path: Path, *, archive: bool) -> Path | None:
    """XDG config with the archive on or off, and projections retired either way."""
    cfg = Path(env["HOME"]) / ".config" / "cc-warehouse"
    cfg.mkdir(parents=True, exist_ok=True)
    lines = [f'root = "{warehouse_root(env)}"', f'archive_timezone = "{ZONE}"']
    archive_root = tmp_path / "archive" if archive else None
    if archive_root is not None:
        lines.append(f'archive_root = "{archive_root}"')
    (cfg / "config.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    env["XDG_CONFIG_HOME"] = str(cfg.parent)
    return archive_root


def capture_then_refire(
    env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> list[str]:
    """Capture once, backdate so the re-fire is `skipped_unchanged`, and record
    every path the reveal was handed."""
    from cc_warehouse import notify

    transcript = write_transcript(env, basic_session(session_id=UUID_A))
    assert run_ccw(["hook"], env, stdin=hook_payload(transcript)).code == 0
    backdate_events(env)

    opened: list[str] = []

    def record_open(_config: object, path: object) -> None:
        opened.append(str(path))

    monkeypatch.setattr(notify, "open_folder", record_open)
    monkeypatch.setenv("CCW_OPEN_FOLDER", "1")
    assert run_cli(["hook"], stdin=hook_payload(transcript)).code == 0
    return opened


def test_the_revealed_folder_exists(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE DEFECT, stated as the property that actually matters to the operator:
    whatever is revealed has to be a real directory. Revealing a path that was
    deleted yesterday is indistinguishable from the feature being off."""
    configure(ccw_env, tmp_path, archive=True)
    opened = capture_then_refire(ccw_env, monkeypatch)
    assert opened, "the reveal was not invoked at all"
    for path in opened:
        assert Path(path).is_dir(), f"revealed a path that does not exist: {path}"


def test_the_skip_branch_reveals_the_sessions_own_archive_folder(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R9: both branches answer the same question, so both show the same thing.
    A fresh capture reveals the session folder via the render child; an unchanged
    re-fire must not reveal something else."""
    archive_root = configure(ccw_env, tmp_path, archive=True)
    assert archive_root is not None
    opened = capture_then_refire(ccw_env, monkeypatch)
    assert opened
    revealed = Path(opened[-1])
    assert revealed.name.endswith(UUID_A), f"not the session's folder: {revealed}"
    assert archive_root in revealed.parents


def test_the_revealed_folder_holds_that_sessions_transcript(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Naming the folder correctly is not enough; the point of revealing it is
    that the operator finds the session in it."""
    configure(ccw_env, tmp_path, archive=True)
    opened = capture_then_refire(ccw_env, monkeypatch)
    revealed = Path(opened[-1])
    assert (revealed / f"{UUID_A}.jsonl").is_file()


def test_without_an_archive_the_old_target_is_kept(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No archive configured means the vault-era layout is still in use, so the
    projections tree remains the right answer. The fix narrows the behaviour, it
    does not replace it."""
    configure(ccw_env, tmp_path, archive=False)
    opened = capture_then_refire(ccw_env, monkeypatch)
    assert opened
    assert opened[-1].endswith("projections")


def test_a_reveal_never_fails_the_capture(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DESIGN 12: every sink is best-effort and cannot fail a capture. Resolving
    the target now touches the catalog, which is new work on the hook path, so
    the guarantee is asserted rather than assumed."""
    from cc_warehouse import notify

    configure(ccw_env, tmp_path, archive=True)
    transcript = write_transcript(ccw_env, basic_session(session_id=UUID_A))
    assert run_ccw(["hook"], ccw_env, stdin=hook_payload(transcript)).code == 0
    backdate_events(ccw_env)

    def explode(_config: object, _path: object) -> None:
        raise RuntimeError("the file manager is on fire")

    monkeypatch.setattr(notify, "open_folder", explode)
    monkeypatch.setenv("CCW_OPEN_FOLDER", "1")
    assert run_cli(["hook"], stdin=hook_payload(transcript)).code == 0
