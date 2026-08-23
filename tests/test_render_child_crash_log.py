"""Oracle tests: a detached child (render or notify, SPEC section 2.5/5) that
crashes before reaching its own error-notify path must leave a durable trace.

Real incident, 2026-08-23: a captured session (JSONL + catalog row both
written, hook reported "ok") whose render child produced none of its four
generated files. No crash report, no OOM, no sleep/wake event, and no "error"
line in logs/capture.jsonl -- meaning the exception happened before
`_render_session`'s own try/except (cli.py, the `archive.read_payload` block),
in a stretch SPEC section 5's locked "all stdio to DEVNULL" makes genuinely
invisible today. `__main__.py` is the one place that wraps BOTH detached
children (never used for a normal `ccw` invocation -- the console script maps
straight to cli.main, per pyproject.toml `[project.scripts]`), so a safety net
there catches this without touching the locked stdio decision at all.
"""

import json
import subprocess
import sys

from conftest import (
    basic_session,
    catalog_path,
    hook_payload,
    run_ccw,
    warehouse_root,
    write_transcript,
)


def test_a_crash_before_the_childs_own_error_path_is_still_logged(
    ccw_env: dict[str, str],
) -> None:
    transcript = write_transcript(ccw_env, basic_session())
    assert run_ccw(["hook"], ccw_env, stdin=hook_payload(transcript)).code == 0

    # Corrupt the catalog so `catalog.open_catalog` raises INSIDE
    # `_render_session`, before its own try/except begins -- exactly the
    # stretch of code the real incident's silence points at.
    catalog_path(ccw_env).write_bytes(b"not a sqlite file")

    proc = subprocess.run(
        [sys.executable, "-m", "cc_warehouse", "render", "--session", "s:deadbeef0000"],
        capture_output=True,
        text=True,
        env=ccw_env,
        timeout=30,
    )
    assert proc.returncode != 0, "a corrupt catalog did not crash the render child"

    log_path = warehouse_root(ccw_env) / "logs" / "capture.jsonl"
    assert log_path.exists(), "the crash left no durable trace at all"
    records = [json.loads(line) for line in log_path.read_text().splitlines()]
    crashes = [r for r in records if r.get("status") == "error"]
    assert crashes, f"no error record among: {records}"
    assert "render" in crashes[-1]["message"]


def test_the_original_exception_still_propagates(ccw_env: dict[str, str]) -> None:
    """Logging the crash must not swallow it: SPEC's "detached child, non-zero
    exit on failure" behavior is unchanged, only now with a trace left behind."""
    transcript = write_transcript(ccw_env, basic_session())
    assert run_ccw(["hook"], ccw_env, stdin=hook_payload(transcript)).code == 0
    catalog_path(ccw_env).write_bytes(b"not a sqlite file")

    proc = subprocess.run(
        [sys.executable, "-m", "cc_warehouse", "render", "--session", "s:deadbeef0000"],
        capture_output=True,
        text=True,
        env=ccw_env,
        timeout=30,
    )
    assert proc.returncode != 0
    assert "DatabaseError" in proc.stderr or "sqlite3" in proc.stderr, proc.stderr
