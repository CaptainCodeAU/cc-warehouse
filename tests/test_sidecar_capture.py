"""Oracle tests: the capture hook brings a session's sidecars with it (38c).

THE HOOK PATH IS THE ONE THAT MATTERS for new sessions. The sweep is the net for
what the hook missed, but a session ends, its hook fires, and if nothing copies
the sidecars at that moment they sit in `~/.claude` waiting on a daily job. The
whole ticket exists because they sat there for four months.

NEVER FATAL (DESIGN 12). A session that is already stored must not be turned into
a reported failure by a copier, a scan, or a notice. Every test below that plants
something broken asserts the hook still exits 0 (its own success signal; it prints
nothing) and that the archived payload is there.

Contract: SPEC 8 (`archive_tool_results`, default ON), DESIGN 12, section 15
ruling (c); R5, R10; FINDINGS F6, F9.
"""

import json
from pathlib import Path
from typing import cast

from conftest import (
    basic_session,
    hook_payload,
    run_ccw,
    settle_companions,
    subagent_meta,
    subagent_session,
    warehouse_root,
    write_transcript,
)

ZONE = "Australia/Melbourne"
PARENT = "d3111111-2222-3333-4444-555555555551"
AGENT = "a94d30c1d877f964d"
WF_AGENT = "b7c2e9f10a3b4c5d6"
ENCODED = "-home-alice-projects-widget"
STDOUT_NAME = "hook-9c2f1a7b-3d4e-5f60-8a91-b2c3d4e5f607-stdout.txt"
STDOUT_BYTES = b"Output too large (132.9KB). Full output saved to: /home/alice/x\n"


def configure(env: dict[str, str], archive_root: Path, *, tool_results: bool | None = None) -> None:
    cfg = Path(env["HOME"]) / ".config" / "cc-warehouse"
    cfg.mkdir(parents=True, exist_ok=True)
    lines = [
        f'root = "{warehouse_root(env)}"',
        f'archive_timezone = "{ZONE}"',
        f'archive_root = "{archive_root}"',
    ]
    if tool_results is not None:
        lines.append(f"archive_tool_results = {'true' if tool_results else 'false'}")
    (cfg / "config.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    env["XDG_CONFIG_HOME"] = str(cfg.parent)


def sidecar_root(env: dict[str, str]) -> Path:
    return Path(env["HOME"]) / ".claude" / "projects" / ENCODED / PARENT


def plant(env: dict[str, str]) -> Path:
    """A session plus the sidecars Claude Code really writes beside it."""
    transcript = write_transcript(
        env, basic_session(session_id=PARENT), session_id=PARENT, name=f"{PARENT}.jsonl"
    )
    root = sidecar_root(env)
    (root / "tool-results" / "pdf-4f1e").mkdir(parents=True, exist_ok=True)
    (root / "tool-results" / STDOUT_NAME).write_bytes(STDOUT_BYTES)
    (root / "tool-results" / "pdf-4f1e" / "page-01.jpg").write_bytes(b"JPEGISH")
    (root / "workflows").mkdir(parents=True, exist_ok=True)
    (root / "workflows" / "wf_abc.json").write_bytes(b'{"id":"wf_abc"}\n')
    return transcript


def grow(transcript: Path) -> None:
    """Append one entry so the next hook fire sees a FRESH identity.

    Capture is idempotent by hash (R14), so re-firing on unchanged bytes
    short-circuits before it reaches any archive write. A test that needs the
    second fire to actually do work has to change the payload."""
    extra = json.dumps({"type": "user", "sessionId": PARENT, "message": {"role": "user"}})
    transcript.write_bytes(transcript.read_bytes() + extra.encode() + b"\n")


def fire_hook(env: dict[str, str], transcript: Path) -> str:
    result = run_ccw(["hook"], env, stdin=hook_payload(transcript, session_id=PARENT))
    assert result.code == 0, result.err
    return result.out


def session_folder(archive_root: Path) -> Path:
    folders = sorted(archive_root.glob(f"*/*_{PARENT}"))
    assert len(folders) == 1, f"expected one session folder, got {folders}"
    return folders[0]


def log_lines(env: dict[str, str], status: str) -> list[dict[str, object]]:
    log = warehouse_root(env) / "logs" / "capture.jsonl"
    if not log.is_file():
        return []
    out: list[dict[str, object]] = []
    for line in log.read_text(encoding="utf-8").splitlines():
        record = cast(object, json.loads(line))
        if isinstance(record, dict):
            typed = cast(dict[str, object], record)
            if typed.get("status") == status:
                out.append(typed)
    return out


# ---------------------------------------------------------------------------
# The copy
# ---------------------------------------------------------------------------


def test_the_hook_brings_tool_results_into_the_session_folder(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    fire_hook(ccw_env, plant(ccw_env))
    settle_companions(ccw_env)
    landed = session_folder(archive_root) / "tool-results" / STDOUT_NAME
    assert landed.read_bytes() == STDOUT_BYTES


def test_the_hook_keeps_the_nesting_inside_tool_results(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    fire_hook(ccw_env, plant(ccw_env))
    settle_companions(ccw_env)
    assert (session_folder(archive_root) / "tool-results" / "pdf-4f1e" / "page-01.jpg").is_file()


def test_the_hook_brings_workflows_too(ccw_env: dict[str, str], tmp_path: Path) -> None:
    """9 dirs and 1.1 MB, archived in this ticket rather than deferred. Deferring
    would mean every install alerts on day one about a sibling we already know
    about, which is the alert-fatigue failure ruling (e) depends on avoiding."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    fire_hook(ccw_env, plant(ccw_env))
    settle_companions(ccw_env)
    assert (session_folder(archive_root) / "workflows" / "wf_abc.json").is_file()


def test_the_hook_brings_the_custom_title_too(ccw_env: dict[str, str], tmp_path: Path) -> None:
    """Found 2026-09-10: a single flat FILE, not a directory, so it needs its own
    assertion separate from the tool-results/workflows coverage above."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    transcript = plant(ccw_env)
    (sidecar_root(ccw_env) / "custom-title.json").write_bytes(b'{"customTitle":"np1"}\n')
    fire_hook(ccw_env, transcript)
    settle_companions(ccw_env)
    landed = session_folder(archive_root) / "custom-title.json"
    assert landed.read_bytes() == b'{"customTitle":"np1"}\n'


def test_the_source_tree_is_not_modified_by_the_copy(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """F9. Sources are read-only, and a copier is exactly the shape that forgets."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    transcript = plant(ccw_env)
    before = {
        str(p.relative_to(sidecar_root(ccw_env))): p.read_bytes()
        for p in sorted(sidecar_root(ccw_env).rglob("*"))
        if p.is_file()
    }
    fire_hook(ccw_env, transcript)
    after = {
        str(p.relative_to(sidecar_root(ccw_env))): p.read_bytes()
        for p in sorted(sidecar_root(ccw_env).rglob("*"))
        if p.is_file()
    }
    assert after == before


def test_the_switch_off_stops_the_hook_copying(ccw_env: dict[str, str], tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root, tool_results=False)
    fire_hook(ccw_env, plant(ccw_env))
    settle_companions(ccw_env)
    assert not (session_folder(archive_root) / "tool-results").exists()


def test_the_session_is_still_captured_when_the_switch_is_off(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root, tool_results=False)
    fire_hook(ccw_env, plant(ccw_env))
    assert (session_folder(archive_root) / f"{PARENT}.jsonl").is_file()


def test_a_second_hook_fire_of_the_same_session_writes_no_sidecar_again(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    transcript = plant(ccw_env)
    fire_hook(ccw_env, transcript)
    settle_companions(ccw_env)
    landed = session_folder(archive_root) / "tool-results" / STDOUT_NAME
    before = landed.stat().st_mtime_ns
    fire_hook(ccw_env, transcript)
    after = landed.stat().st_mtime_ns
    assert before == after


# ---------------------------------------------------------------------------
# The sub-agent gaps this slice also closes
# ---------------------------------------------------------------------------


def test_the_hook_reaches_a_workflow_tool_subagent(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """`subagents/workflows/wf_<id>/agent-*.jsonl`: 432 files, 33 MB, 211 distinct
    transcripts. The hook's glob was not recursive so it reached none of them. The
    daily sweep's os.walk did, so all 211 are already archived - a hook-path gap
    with a working net, fixed anyway because a net is not the plan."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    transcript = plant(ccw_env)
    nested = sidecar_root(ccw_env) / "subagents" / "workflows" / "wf_abc"
    nested.mkdir(parents=True)
    (nested / f"agent-{WF_AGENT}.jsonl").write_bytes(
        subagent_session(agent_id=WF_AGENT, parent_uuid=PARENT)
    )
    fire_hook(ccw_env, transcript)
    settle_companions(ccw_env)
    landed = sorted(session_folder(archive_root).glob(f"subagents/*_{WF_AGENT}/{WF_AGENT}.jsonl"))
    assert len(landed) == 1, landed


def test_a_forked_skill_companion_travels_with_its_subagent(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    transcript = plant(ccw_env)
    subs = sidecar_root(ccw_env) / "subagents"
    subs.mkdir(parents=True, exist_ok=True)
    (subs / f"agent-{AGENT}.jsonl").write_bytes(
        subagent_session(agent_id=AGENT, parent_uuid=PARENT)
    )
    (subs / f"agent-{AGENT}.meta.json").write_bytes(subagent_meta())
    (subs / f"agent-{AGENT}.forked-skill.json").write_bytes(b'{"skill":"tdd"}\n')
    fire_hook(ccw_env, transcript)
    settle_companions(ccw_env)
    landed = sorted(
        session_folder(archive_root).glob(f"subagents/*_{AGENT}/agent-{AGENT}.forked-skill.json")
    )
    assert len(landed) == 1, landed


def test_a_sidecar_dir_is_found_even_when_the_file_stem_is_not_the_bare_uuid(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Ruling (c) on the hook path. One such transcript exists in the live tree,
    and `capture.py` has keyed on the file stem since ticket 21."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    plant(ccw_env)
    projects = Path(ccw_env["HOME"]) / ".claude" / "projects" / ENCODED
    odd = projects / f"{PARENT}.orphaned-2-9f8e7d.jsonl"
    odd.write_bytes(basic_session(session_id=PARENT))
    (projects / f"{PARENT}.jsonl").unlink()
    fire_hook(ccw_env, odd)
    settle_companions(ccw_env)
    assert (session_folder(archive_root) / "tool-results" / STDOUT_NAME).is_file()


# ---------------------------------------------------------------------------
# The signal
# ---------------------------------------------------------------------------


def test_an_unknown_sibling_is_named_in_the_session_folders_notice(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    transcript = plant(ccw_env)
    (sidecar_root(ccw_env) / "zzz-probe").mkdir()
    fire_hook(ccw_env, transcript)
    settle_companions(ccw_env)
    notice = json.loads(
        (session_folder(archive_root) / "sidecars.json").read_text(encoding="utf-8")
    )
    assert notice["unarchived"] == ["zzz-probe"]


def test_an_unknown_sibling_writes_exactly_one_log_line(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """THE DEDUP IS THE NOTICE COMPARE, not a timer and not a counter. Once per
    session per CHANGE of the set, so a machine with a permanent anomaly logs it
    once and then stays quiet - the ticket 24.7 lesson, which cost this project a
    daily ALERT banner on a healthy install."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    transcript = plant(ccw_env)
    (sidecar_root(ccw_env) / "zzz-probe").mkdir()
    fire_hook(ccw_env, transcript)
    fire_hook(ccw_env, transcript)
    settle_companions(ccw_env)
    assert len(log_lines(ccw_env, "unarchived-sibling")) == 1


def test_the_log_line_names_the_sibling_and_carries_the_six_standard_keys(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    transcript = plant(ccw_env)
    (sidecar_root(ccw_env) / "zzz-probe").mkdir()
    fire_hook(ccw_env, transcript)
    settle_companions(ccw_env)
    record = log_lines(ccw_env, "unarchived-sibling")[0]
    assert set(record) == {"at", "status", "session", "project", "message", "elapsed_ms"}
    assert "zzz-probe" in str(record["message"])


def test_ds_store_beside_a_transcript_raises_no_notice(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    transcript = plant(ccw_env)
    (sidecar_root(ccw_env) / ".DS_Store").write_bytes(b"\x00")
    fire_hook(ccw_env, transcript)
    settle_companions(ccw_env)
    assert not (session_folder(archive_root) / "sidecars.json").exists()


def test_a_clean_session_gets_no_notice(ccw_env: dict[str, str], tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    fire_hook(ccw_env, plant(ccw_env))
    settle_companions(ccw_env)
    assert not (session_folder(archive_root) / "sidecars.json").exists()


# ---------------------------------------------------------------------------
# Never fatal (DESIGN 12)
# ---------------------------------------------------------------------------


def test_an_unreadable_sidecar_dir_never_costs_the_capture(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    transcript = plant(ccw_env)
    blocked = sidecar_root(ccw_env) / "tool-results"
    blocked.chmod(0o000)
    try:
        fire_hook(ccw_env, transcript)
    finally:
        blocked.chmod(0o700)
    # `fire_hook` already asserts exit 0, which is the hook's own success signal
    # (it prints nothing on stdout). The archived payload is the durable half of
    # the proof; the generated files arrive later, from the detached render child.
    landed = session_folder(archive_root) / f"{PARENT}.jsonl"
    assert landed.read_bytes() == basic_session(session_id=PARENT)


def test_one_unreadable_file_does_not_stop_the_others_being_copied(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """R10: name the item and carry on. One bad file must not cost the other
    2,083 in the same directory."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    transcript = plant(ccw_env)
    blocked = sidecar_root(ccw_env) / "tool-results" / STDOUT_NAME
    blocked.chmod(0o000)
    try:
        fire_hook(ccw_env, transcript)
    finally:
        blocked.chmod(0o600)
    settle_companions(ccw_env)
    assert (session_folder(archive_root) / "tool-results" / "pdf-4f1e" / "page-01.jpg").is_file()


def test_a_refused_sidecar_is_recorded_rather_than_swallowed(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """F6. Unlike the sub-agent twin, every refusal on this path is logged AND
    named in the notice: a tool result has no manifest of its own to record a
    refusal in, and silence is what let this whole class hide for four months.

    THE SECOND FIRE HAS TO CARRY A FRESH IDENTITY. Capture is idempotent by hash
    (R14), so re-firing on unchanged bytes short-circuits before it reaches any
    archive write at all - which is correct, and is why the sweep's third pass
    exists to catch a sidecar that arrives after the last capture."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    transcript = plant(ccw_env)
    fire_hook(ccw_env, transcript)
    settle_companions(ccw_env)
    (sidecar_root(ccw_env) / "tool-results" / STDOUT_NAME).write_bytes(b"different bytes here")
    grow(transcript)
    fire_hook(ccw_env, transcript)
    settle_companions(ccw_env, expected=2)
    notice = json.loads(
        (session_folder(archive_root) / "sidecars.json").read_text(encoding="utf-8")
    )
    assert notice["refused"] == [f"tool-results/{STDOUT_NAME}"]
    assert (session_folder(archive_root) / "tool-results" / STDOUT_NAME).read_bytes() == (
        STDOUT_BYTES
    )


def test_a_refused_sidecar_is_named_in_the_audit_log_too(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    transcript = plant(ccw_env)
    fire_hook(ccw_env, transcript)
    settle_companions(ccw_env)
    (sidecar_root(ccw_env) / "tool-results" / STDOUT_NAME).write_bytes(b"different bytes here")
    grow(transcript)
    fire_hook(ccw_env, transcript)
    settle_companions(ccw_env, expected=2)
    records = log_lines(ccw_env, "refused")
    assert len(records) == 1, records
    assert STDOUT_NAME in str(records[0]["message"])
