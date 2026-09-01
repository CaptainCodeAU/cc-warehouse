"""Oracle tests: ticket 35, closing the "silently worked or silently failed,
zero trace" gap in `ccw build`, `ccw sweep`'s own build step, and `ccw repair`.

Before this, three surfaces only ever printed to stdout/stderr: durable
exactly when the caller happened to be redirected to a file (true for the
three scheduled launchd jobs, false for any manual/interactive run), and for
`ccw repair --quiet` specifically, a SUCCESSFUL fix left no trace anywhere at
all (`--quiet` drops the stdout summary; the fixed-count was never printed
elsewhere). All three now also append a record to the existing durable
`logs/capture.jsonl` audit log (`notify.append_log`), matching this project's
established convention (capture.py's `_log_stage_failure`, __main__.py's
`_log_crash`): the SAME six-field schema, the extra context folded into
`message` rather than a new JSON key, so nothing that already reads
capture.jsonl needs to change.
"""

import json
import sqlite3
from pathlib import Path

import pytest

from cc_warehouse import archive
from conftest import (
    basic_session,
    hook_payload,
    run_ccw,
    run_cli,
    warehouse_root,
    write_transcript,
)

ZONE = "Australia/Melbourne"
UUID_A = "aaaaaaaa-3535-4111-8111-aaaaaaaaaaaa"
UUID_B = "bbbbbbbb-3535-4222-8222-bbbbbbbbbbbb"


def configure_archive(env: dict[str, str], archive_root: Path) -> None:
    cfg = Path(env["HOME"]) / ".config" / "cc-warehouse"
    cfg.mkdir(parents=True, exist_ok=True)
    lines = [
        f'root = "{warehouse_root(env)}"',
        f'archive_timezone = "{ZONE}"',
        f'archive_root = "{archive_root}"',
    ]
    (cfg / "config.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    env["XDG_CONFIG_HOME"] = str(cfg.parent)


def install_hook(env: dict[str, str]) -> None:
    settings = Path(env["HOME"]) / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(
        json.dumps(
            {"hooks": {"SessionEnd": [{"hooks": [{"type": "command", "command": "ccw hook"}]}]}}
        ),
        encoding="utf-8",
    )


def _log_records(env: dict[str, str]) -> list[dict[str, object]]:
    log_path = warehouse_root(env) / "logs" / "capture.jsonl"
    if not log_path.exists():
        return []
    return [json.loads(line) for line in log_path.read_text().splitlines()]


def test_ccw_build_failure_is_logged_durably(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive_root = tmp_path / "archive"
    configure_archive(ccw_env, archive_root)
    transcript = write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    assert run_ccw(["hook"], ccw_env, stdin=hook_payload(transcript)).code == 0

    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("simulated build mirror failure")

    monkeypatch.setattr(archive, "write_session_folder", boom)
    result = run_cli(["build", "--rebuild"])
    assert result.code == 1, "a real per-item build failure must exit non-zero"

    records = _log_records(ccw_env)
    errors = [r for r in records if r.get("status") == "error"]
    assert errors, f"build failure left no durable trace: {records}"
    assert "simulated build mirror failure" in str(errors[-1].get("message", ""))


def test_sweep_triggered_build_failure_is_logged_durably(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real 2026-08-04 shape: a sweep captures fine, then its own call to
    build.build() fails to render one item. That failure must be as
    recoverable afterward as a capture-time failure already is."""
    archive_root = tmp_path / "archive"
    configure_archive(ccw_env, archive_root)
    transcript = write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    _ = transcript  # captured by the sweep walk below, not the hook

    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("simulated sweep-triggered build failure")

    monkeypatch.setattr(archive, "write_session_folder", boom)
    result = run_cli(["sweep"])
    assert result.code == 1, "a sweep-triggered build failure must exit non-zero"

    records = _log_records(ccw_env)
    errors = [r for r in records if r.get("status") == "error"]
    assert errors, f"sweep-triggered build failure left no durable trace: {records}"
    assert "simulated sweep-triggered build failure" in str(errors[-1].get("message", ""))


def _break_render(folder: Path) -> None:
    for name in archive.GENERATED_NAMES:
        path = folder / name
        if path.exists():
            path.unlink()


def test_repair_success_is_logged_even_when_quiet(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The gap this closes: a --quiet scheduled repair that silently FIXED a
    real problem used to leave zero trace anywhere that it had ever run, let
    alone what it fixed."""
    archive_root = tmp_path / "archive"
    configure_archive(ccw_env, archive_root)
    install_hook(ccw_env)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    assert run_ccw(["sweep"], ccw_env).code == 0

    folder = next(archive.walk_folders(archive_root))
    _break_render(folder)

    result = run_ccw(["repair", "--quiet"], ccw_env)
    assert result.code == 0
    assert result.out == "", "--quiet must still drop the stdout summary"

    records = _log_records(ccw_env)
    fixed = [r for r in records if r.get("status") == "ok" and "repair" in str(r.get("message"))]
    assert fixed, f"a quiet successful repair left no durable trace: {records}"
    assert fixed[-1].get("message") == "repair: fixed"
    assert fixed[-1].get("session"), "the fixed record must name which session it recovered"


def test_repair_failure_is_logged_even_when_quiet(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """A repair attempt that could not actually fix the folder (here: the
    stored payload's hash no longer matches what the catalog recorded, so the
    render subprocess genuinely fails) must be as durably recorded as a
    successful one, --quiet or not."""
    archive_root = tmp_path / "archive"
    configure_archive(ccw_env, archive_root)
    install_hook(ccw_env)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    assert run_ccw(["sweep"], ccw_env).code == 0

    folder = next(archive.walk_folders(archive_root))
    _break_render(folder)

    # Corrupt the catalog's recorded hash for this row so the render
    # subprocess's own integrity check genuinely fails (a real failure, not a
    # simulated one -- this crosses a real process boundary, so monkeypatch
    # cannot reach it).
    conn = sqlite3.connect(str(warehouse_root(ccw_env) / "catalog.sqlite"))
    conn.execute("UPDATE session SET hash = 'deadbeef' || substr(hash, 9)")
    conn.commit()
    conn.close()

    result = run_ccw(["repair", "--quiet"], ccw_env)
    assert result.code == 1, "a genuinely unfixable folder must exit non-zero"
    assert result.out == "", "--quiet must still drop the stdout summary"

    records = _log_records(ccw_env)
    failures = [r for r in records if r.get("status") == "error"]
    assert failures, f"a quiet failed repair attempt left no durable trace: {records}"
    assert "repair" in str(failures[-1].get("message", ""))
