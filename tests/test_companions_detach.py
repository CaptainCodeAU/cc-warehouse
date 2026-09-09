"""Oracle tests: ticket 37 Part B moves the hook's companion-copying (sub-agents,
tool-results/workflows sidecars, file-history/todos, the unknown-sibling notice)
off the SessionEnd timing budget into a detached child, `ccw companions`.

Measured 2026-09-09: a big session's sub-agents alone are 14-18 MB across 30-90
files, ~90% of the hook's elapsed time, and the slowest real capture in two days
(4,331 ms) was still nowhere near the 40s/45s timeout budgets - so a hook lost
mid-run is being killed by an exit-driven signal, not a timeout, and shortening
this window is what lowers the odds of getting caught in it.

THIS FILE covers the NEW entry points directly: the `defer_companions` flag,
`capture.archive_companions` producing the same tree whether called inline or
after the fact, the `ccw companions` verb's catalog lookup and logging, and the
`doctor.py` `companions` check that reads that logging. Per-copier behaviour
(sub-agents, sidecars, file-history, the notice) is already covered end to end
by test_subagent_capture.py / test_sidecar_capture.py / test_external_capture.py,
which now wait on the detached child via conftest.settle_companions rather than
being duplicated here.
"""

import json
from pathlib import Path

from cc_warehouse import capture, catalog, doctor, notify
from cc_warehouse.config import Config
from conftest import (
    basic_session,
    run_ccw,
    run_cli,
    subagent_meta,
    subagent_session,
    warehouse_root,
    write_transcript,
)

ZONE = "Australia/Melbourne"
PARENT = "d3111111-2222-3333-4444-555555555551"
AGENT = "a94d30c1d877f964d"


def _plant_source(base: Path, session_id: str = PARENT) -> Path:
    """A transcript plus the sub-agent dir Claude Code writes beside it, under
    an arbitrary directory rather than a faked ~/.claude/projects - capture only
    ever anchors on `transcript_path.parent`, so any parent directory does."""
    project_dir = base / "-home-alice-projects-widget"
    project_dir.mkdir(parents=True, exist_ok=True)
    transcript = project_dir / f"{session_id}.jsonl"
    transcript.write_bytes(basic_session(session_id=session_id))
    subagents = project_dir / session_id / "subagents"
    subagents.mkdir(parents=True)
    (subagents / f"agent-{AGENT}.jsonl").write_bytes(
        subagent_session(agent_id=AGENT, parent_uuid=session_id)
    )
    (subagents / f"agent-{AGENT}.meta.json").write_bytes(subagent_meta())
    return transcript


def _archive_files(archive_root: Path) -> list[str]:
    return sorted(str(p.relative_to(archive_root)) for p in archive_root.rglob("*") if p.is_file())


# ---------------------------------------------------------------------------
# capture.capture_transcript(defer_companions=...) and capture.archive_companions
# ---------------------------------------------------------------------------


def test_defer_companions_true_leaves_the_subagent_uncopied(tmp_path: Path) -> None:
    transcript = _plant_source(tmp_path / "source")
    config = Config(root=tmp_path / "wh", archive_root=tmp_path / "archive", archive_timezone=ZONE)
    result = capture.capture_transcript(
        config, transcript, session_id=None, cwd="/home/alice/x", defer_companions=True
    )
    assert result.action == "stored"
    assert config.archive_root is not None
    files = _archive_files(config.archive_root)
    assert any(f.endswith(f"{PARENT}.jsonl") for f in files), "the source JSONL must still land"
    assert not any("subagents" in f for f in files), (
        f"a deferred capture archived companions inline: {files}"
    )


def test_defer_companions_false_is_the_default_and_archives_inline(tmp_path: Path) -> None:
    """Today's behaviour, byte for byte: omitting the flag must still write the
    sub-agent synchronously, exactly as it did before this ticket."""
    transcript = _plant_source(tmp_path / "source")
    config = Config(root=tmp_path / "wh", archive_root=tmp_path / "archive", archive_timezone=ZONE)
    result = capture.capture_transcript(config, transcript, session_id=None, cwd="/home/alice/x")
    assert result.action == "stored"
    assert config.archive_root is not None
    files = _archive_files(config.archive_root)
    assert any(f.endswith(f"{AGENT}.jsonl") and "subagents" in f for f in files), files


def test_archive_companions_produces_the_identical_tree_to_the_inline_path(
    tmp_path: Path,
) -> None:
    """The whole point of `archive_companions`: called separately after a
    deferred capture, it must write EXACTLY what the inline path would have -
    compared across the whole session folder, not one file (the standing "a
    census on one file is still an instance fix" lesson)."""
    source = _plant_source(tmp_path / "source")

    inline_config = Config(
        root=tmp_path / "wh-inline", archive_root=tmp_path / "archive-inline", archive_timezone=ZONE
    )
    inline_result = capture.capture_transcript(
        inline_config, source, session_id=None, cwd="/home/alice/x"
    )
    assert inline_result.action == "stored"

    deferred_config = Config(
        root=tmp_path / "wh-deferred",
        archive_root=tmp_path / "archive-deferred",
        archive_timezone=ZONE,
    )
    deferred_result = capture.capture_transcript(
        deferred_config, source, session_id=None, cwd="/home/alice/x", defer_companions=True
    )
    assert deferred_result.action == "stored"
    assert deferred_result.project_id is not None
    conn = catalog.open_catalog(deferred_config.root)
    try:
        capture.archive_companions(
            deferred_config, conn, deferred_result.project_id, source, PARENT
        )
    finally:
        conn.close()

    def relabelled(root: Path, other_root: Path) -> dict[str, bytes]:
        """Every file's bytes, keyed by its path with the archive root itself
        stripped - the two captures use different tmp_path archive roots, so
        only the relative shape needs to match, not the absolute prefix."""
        out: dict[str, bytes] = {}
        for path in sorted(root.rglob("*")):
            if path.is_file():
                out[str(path.relative_to(root))] = path.read_bytes()
        assert out, f"fixture precondition: nothing archived under {root}"
        return out

    assert inline_config.archive_root is not None
    assert deferred_config.archive_root is not None
    assert relabelled(inline_config.archive_root, inline_config.archive_root) == relabelled(
        deferred_config.archive_root, deferred_config.archive_root
    )


# ---------------------------------------------------------------------------
# `ccw companions --session s:<key> --transcript PATH`
# ---------------------------------------------------------------------------


def _configure(env: dict[str, str], archive_root: Path) -> None:
    cfg = Path(env["HOME"]) / ".config" / "cc-warehouse"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "config.toml").write_text(
        "\n".join(
            [
                f'root = "{warehouse_root(env)}"',
                f'archive_timezone = "{ZONE}"',
                f'archive_root = "{archive_root}"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    env["XDG_CONFIG_HOME"] = str(cfg.parent)


def _log_records(env: dict[str, str]) -> list[dict[str, object]]:
    log = warehouse_root(env) / "logs" / "capture.jsonl"
    if not log.is_file():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def test_the_companions_verb_archives_via_the_catalog_lookup(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    _configure(ccw_env, archive_root)
    transcript = _plant_source(tmp_path / "source")
    config = Config(root=warehouse_root(ccw_env), archive_root=archive_root, archive_timezone=ZONE)
    result = capture.capture_transcript(
        config, transcript, session_id=None, cwd="/home/alice/x", defer_companions=True
    )
    assert result.action == "stored"
    files_before = _archive_files(archive_root)
    assert not any("subagents" in f for f in files_before), "fixture precondition"

    cli_result = run_cli(
        ["companions", "--session", f"s:{result.short}", "--transcript", str(transcript)]
    )
    assert cli_result.code == 0, cli_result.err

    files_after = _archive_files(archive_root)
    assert any(f.endswith(f"{AGENT}.jsonl") and "subagents" in f for f in files_after), files_after

    records = _log_records(ccw_env)
    started = [r for r in records if r.get("status") == "companions-started"]
    done = [r for r in records if r.get("status") == "companions-done"]
    assert started and started[-1].get("session") == result.short
    assert done and done[-1].get("session") == result.short
    assert str(started[-1].get("message", "")).startswith("companions: ")
    assert str(done[-1].get("message", "")).startswith("companions: ")


def test_a_missing_catalog_row_logs_an_error_and_never_a_started_line(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The `ccw companions` twin of `_render_session`'s own missing-row case:
    something else deleted the row between spawn and run. This must report an
    error, not silently do nothing - and it must NOT log companions-started for
    a session it never touched, or doctor's stalled-child check would flag a
    session that was never really running."""
    archive_root = tmp_path / "archive"
    _configure(ccw_env, archive_root)
    transcript = _plant_source(tmp_path / "source")

    cli_result = run_cli(
        ["companions", "--session", "s:deadbeef0000", "--transcript", str(transcript)]
    )
    assert cli_result.code == 1

    records = _log_records(ccw_env)
    errors = [r for r in records if r.get("status") == "error"]
    assert errors, f"no error record among: {records}"
    assert "no catalog row" in str(errors[-1].get("message", ""))
    assert str(errors[-1].get("message", "")).startswith("companions: ")
    started = [r for r in records if r.get("status") == "companions-started"]
    assert not started, f"a never-run session should not log companions-started: {started}"


# ---------------------------------------------------------------------------
# doctor.py's `companions` check
# ---------------------------------------------------------------------------


def test_a_healthy_completed_pass_reads_ok(tmp_path: Path) -> None:
    config = Config(root=tmp_path / "wh", archive_root=tmp_path / "archive", archive_timezone=ZONE)
    from datetime import UTC, datetime

    now = datetime.now(UTC).isoformat()
    notify.append_log(
        config,
        {
            "at": now,
            "status": "companions-started",
            "session": "abc123",
            "project": None,
            "message": "companions: started",
            "elapsed_ms": None,
        },
    )
    notify.append_log(
        config,
        {
            "at": now,
            "status": "companions-done",
            "session": "abc123",
            "project": None,
            "message": "companions: archived",
            "elapsed_ms": 42,
        },
    )
    ok, detail = doctor._companions_stalled(config)  # pyright: ignore[reportPrivateUsage]
    assert ok is True
    assert "1 companions pass" in detail


def _install_hook(env: dict[str, str]) -> None:
    """A SessionEnd hook in settings.json, the shape Claude Code reads (same
    fixture `tests/test_doctor.py`'s `install_hook` builds)."""
    settings = Path(env["HOME"]) / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(
        json.dumps(
            {"hooks": {"SessionEnd": [{"hooks": [{"type": "command", "command": "ccw hook"}]}]}}
        ),
        encoding="utf-8",
    )


def test_a_stalled_companions_pass_is_flagged_but_never_flips_doctors_exit_code(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """NEVER BLOCKING (same posture as `sidecars`/`history`/`prompts`, ticket 38
    ruling (e)): a stalled companions pass is worth knowing about, not a broken
    capture, and must not move the exit code `ccw-freshness-check.py` escalates
    on. A fully healthy install is built first (hook registered, capture fired
    via a synchronous `ccw sweep` so nothing races the detached child, nothing
    overdue) so ONLY the check under test can fail `report.ok` - the same
    isolation `test_doctor.py`'s own history/sidecars tests use."""
    from datetime import UTC, datetime, timedelta

    archive_root = tmp_path / "archive"
    _configure(ccw_env, archive_root)
    _install_hook(ccw_env)
    session_id = "a1a1a1a1-2222-4222-8222-a1a1a1a1a1a1"
    write_transcript(ccw_env, basic_session(session_id=session_id), session_id=session_id)
    assert run_ccw(["sweep"], ccw_env).code == 0

    config = Config(root=warehouse_root(ccw_env), archive_root=archive_root, archive_timezone=ZONE)
    long_ago = (datetime.now(UTC) - timedelta(minutes=20)).isoformat()
    notify.append_log(
        config,
        {
            "at": long_ago,
            "status": "companions-started",
            "session": "deadbeef0000",
            "project": None,
            "message": "companions: started",
            "elapsed_ms": None,
        },
    )
    ok, detail = doctor._companions_stalled(config)  # pyright: ignore[reportPrivateUsage]
    assert ok is False
    assert "deadbeef0000" in detail
    assert "stalled" in detail

    report = doctor.diagnose(config, home=Path(ccw_env["HOME"]))
    companions_check = next(c for c in report.checks if c.name == "companions")
    assert companions_check.ok is False
    assert companions_check.blocking is False
    assert report.ok, "a stalled companions pass alone must not fail doctor"


def test_no_capture_jsonl_yet_is_not_an_alarm(tmp_path: Path) -> None:
    config = Config(root=tmp_path / "wh", archive_root=tmp_path / "archive", archive_timezone=ZONE)
    ok, detail = doctor._companions_stalled(config)  # pyright: ignore[reportPrivateUsage]
    assert ok is True
    assert "no capture.jsonl" in detail


def test_no_archive_configured_is_not_an_alarm(tmp_path: Path) -> None:
    config = Config(root=tmp_path / "wh")
    ok, detail = doctor._companions_stalled(config)  # pyright: ignore[reportPrivateUsage]
    assert ok is True
    assert "no archive configured" in detail
