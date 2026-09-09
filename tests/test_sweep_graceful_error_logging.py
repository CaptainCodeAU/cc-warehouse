"""Oracle tests: a sweep item's GRACEFUL capture error reaches capture.jsonl
(ticket 42 #3).

THE GAP THIS CLOSES. `capture.capture_transcript` returns an `error`
`CaptureResult` rather than raising for an unreadable transcript (documented,
deliberate -- R5/R10, a batch caller must be told, never crashed). The hook
path logs this via `cli._report_capture`'s error branch. The sweep path did
not: `sweep._capture_item` only ever called `_log_item_failure` on a RAISED
exception, so the identical failure via `ccw sweep` reached stderr and the end
report only, invisible to capture.jsonl -- and therefore to
`reconcile.find_unrecoverable`, which reads exactly that log (ticket 42 #5,
shipped the same day this gap was found).
"""

import json
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cc_warehouse import reconcile, sweep
from cc_warehouse.config import Config
from conftest import (
    basic_session,
    run_ccw,
    warehouse_root,
    write_transcript,
)

ZONE = "Australia/Melbourne"
UUID_GOOD = "aaaaaaaa-1111-4222-8333-444444444444"
UUID_BROKEN = "bbbbbbbb-1111-4222-8333-444444444444"


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


def _log_records(env: dict[str, str]) -> list[dict[str, object]]:
    log_path = warehouse_root(env) / "logs" / "capture.jsonl"
    if not log_path.exists():
        return []
    return [json.loads(line) for line in log_path.read_text().splitlines()]


def test_sweep_graceful_capture_error_reaches_capture_jsonl(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The real 2026-09-09 shape: an unreadable item in a sweep batch is a
    GRACEFUL `error` result, not a raised exception, and used to leave zero
    durable trace."""
    archive_root = tmp_path / "archive"
    configure_archive(ccw_env, archive_root)
    write_transcript(
        ccw_env,
        basic_session(cwd="/home/alice/projects/good", session_id=UUID_GOOD),
        session_id=UUID_GOOD,
    )
    broken = write_transcript(
        ccw_env,
        basic_session(cwd="/home/alice/projects/broken", session_id=UUID_BROKEN),
        session_id=UUID_BROKEN,
        encoded_dir="-home-alice-projects-broken",
    )
    broken.chmod(0)
    try:
        result = run_ccw(["sweep"], ccw_env)
        assert result.code != 0

        records = _log_records(ccw_env)
        errors = [r for r in records if r.get("status") == "error"]
        matching = [
            r
            for r in errors
            if broken.name in str(r.get("message", ""))
            and "sweep item" in str(r.get("message", ""))
        ]
        assert matching, f"the graceful sweep item error left no durable trace: {records}"
        assert "unreadable transcript" in str(matching[-1].get("message", ""))
        assert matching[-1].get("session_uuid") == UUID_BROKEN
    finally:
        broken.chmod(stat.S_IRUSR | stat.S_IWUSR)


def test_sweep_item_error_message_is_not_excluded_by_reconcile(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The exact message shape `sweep._log_item_failure` writes for a graceful
    capture error ("sweep item <name> failed: unreadable transcript ...") names
    a real session and must survive `reconcile.find_unrecoverable`'s excluded-
    prefix filter -- unlike the per-RUN summary prefixes ("sweep: ", ticket
    42 #2), which name no session at all."""
    archive_root = tmp_path / "archive"
    configure_archive(ccw_env, archive_root)
    config = Config(root=warehouse_root(ccw_env), archive_root=archive_root, archive_timezone=ZONE)

    lost = Path(f"/x/{UUID_BROKEN}.jsonl")
    sweep._log_item_failure(  # pyright: ignore[reportPrivateUsage]
        config, lost, f"unreadable transcript {lost}: [Errno 13] Permission denied"
    )
    # Backdate the record past the 1h grace window (real writers cannot set an
    # arbitrary `at`; this mirrors test_reconcile.py's own backdating approach).
    log_path = warehouse_root(ccw_env) / "logs" / "capture.jsonl"
    lines = log_path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[-1])
    record["at"] = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    lines[-1] = json.dumps(record)
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    findings = reconcile.find_unrecoverable(
        config, home=Path(ccw_env["HOME"]), now=datetime.now(UTC)
    )

    assert any(f.session_uuid == UUID_BROKEN for f in findings), findings
