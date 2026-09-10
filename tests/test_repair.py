"""Oracle tests: `ccw repair` (ticket 32), the write-side companion to
`ccw doctor`'s desync check (ticket 31.5).

Real incident, 2026-08-23: a captured session (JSONL + catalog row both
written, hook reported "ok") whose detached render child never produced its
five generated files (`archive.GENERATED_NAMES`). `doctor` already finds this
(the desync check) but only REPORTS it -- fixing it needed manually resolving
the folder's session_uuid to a catalog short key and running `ccw render` by
hand. `repair` automates exactly that, over the same bounded recent sample
`doctor` already uses.

`doctor` stays untouched and read-only on purpose (its own module docstring:
"READ-ONLY BY CONSTRUCTION, which is not a nicety here"). `repair` is a
separate, explicitly-named verb precisely so doctor's output -- a public
compatibility surface an external tool (ccw-watch) parses -- never gains a
silent write side effect.
"""

import json
import subprocess
from pathlib import Path

import pytest

from cc_warehouse import archive, doctor
from cc_warehouse.config import Config
from conftest import basic_session, entry, jsonl, run_ccw, run_cli, warehouse_root, write_transcript

ZONE = "Australia/Melbourne"
UUID_A = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
UUID_B = "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"


def configure(env: dict[str, str], archive_root: Path) -> None:
    cfg = Path(env["HOME"]) / ".config" / "cc-warehouse"
    cfg.mkdir(parents=True, exist_ok=True)
    lines = [
        f'root = "{warehouse_root(env)}"',
        f'archive_timezone = "{ZONE}"',
        f'archive_root = "{archive_root}"',
    ]
    (cfg / "config.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    env["XDG_CONFIG_HOME"] = str(cfg.parent)


def install_hook(env: dict[str, str], *, command: str = "ccw hook") -> None:
    """A SessionEnd hook in settings.json, the shape Claude Code reads -- needed
    only so `ccw doctor`'s unrelated `hook` check doesn't fail the overall exit
    code and mask the `desync` result this file actually tests."""
    settings = Path(env["HOME"]) / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(
        json.dumps(
            {"hooks": {"SessionEnd": [{"hooks": [{"type": "command", "command": command}]}]}}
        ),
        encoding="utf-8",
    )


def _break_render(folder: Path) -> None:
    """Simulate the real incident: the JSONL + subagents/ arrive (the hook's
    synchronous, safe half); none of the five generated files do (the
    detached render child's half, which silently never finished)."""
    for name in archive.GENERATED_NAMES:
        path = folder / name
        if path.exists():
            path.unlink()


def test_repair_fixes_a_session_missing_all_generated_files(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    install_hook(ccw_env)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    assert run_ccw(["sweep"], ccw_env).code == 0

    folder = next(archive.walk_folders(archive_root))
    _break_render(folder)
    assert run_ccw(["doctor"], ccw_env).code != 0, "fixture precondition: not yet broken"

    result = run_ccw(["repair"], ccw_env)
    assert result.code == 0, f"repair did not report success: {result.out!r} {result.err!r}"

    for name in archive.GENERATED_NAMES:
        assert (folder / name).exists(), f"{name} was not restored by repair"
    assert run_ccw(["doctor"], ccw_env).code == 0, "doctor still unhappy after repair"


def test_repair_never_opens_finder_even_when_open_folder_is_configured_on(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`ccw repair` runs unattended, on a daily schedule -- nobody is at the
    machine to want (or dismiss) a folder popping open in Finder. `open_folder`
    is a single config switch shared with the live hook's own detached render
    child, which DOES want the reveal (a human just ended a real session by
    hand). Found 2026-09-10 by reading the code: repair's render subprocess
    inherited the ambient environment unmodified, so a machine with
    `open_folder = true` (set for the live hook's own benefit) would ALSO pop a
    folder open every time an unattended repair run fixed something. Never yet
    observed live on the reporting machine only because doctor's desync check
    had not yet found anything for repair to fix there.

    The real subprocess boundary matters here (same reasoning `run_ccw`'s own
    docstring gives), so this spies on `subprocess.run` rather than mocking
    `notify.open_folder`: the render child is a SEPARATE process that reloads
    its own config from scratch, so an in-process patch of `notify` cannot
    reach it, and this repo's own `ccw_env` fixture leaves `CCW_OPEN_FOLDER`
    unset by default specifically because only tests that opt in should risk a
    real popup - a lesson already paid for once, in this same fixture's
    `CCW_DESKTOP_ALERTS=0` default."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    cfg_path = Path(ccw_env["HOME"]) / ".config" / "cc-warehouse" / "config.toml"
    cfg_path.write_text(
        cfg_path.read_text(encoding="utf-8") + "\n[notify]\nopen_folder = true\n",
        encoding="utf-8",
    )
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    assert run_ccw(["sweep"], ccw_env).code == 0
    folder = next(archive.walk_folders(archive_root))
    _break_render(folder)

    real_run = subprocess.run
    captured_envs: list[dict[str, str] | None] = []

    def spy_run(
        argv: list[str],
        *,
        capture_output: bool = False,
        text: bool = False,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        captured_envs.append(env)
        return real_run(argv, capture_output=capture_output, text=text, env=env)

    monkeypatch.setattr(subprocess, "run", spy_run)
    result = run_cli(["repair"])
    assert result.code == 0, f"repair did not report success: {result.err!r}"
    for name in archive.GENERATED_NAMES:
        assert (folder / name).exists(), f"{name} was not restored by repair"

    assert captured_envs, "repair never spawned its render child"
    for env in captured_envs:
        assert env is not None and env.get("CCW_OPEN_FOLDER") != "1", (
            "repair's render child can still open Finder on an unattended run"
        )


def test_repair_is_a_quiet_no_op_when_nothing_is_broken(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    assert run_ccw(["sweep"], ccw_env).code == 0
    folder = next(archive.walk_folders(archive_root))
    before = {p.name: p.read_bytes() for p in folder.rglob("*") if p.is_file()}

    result = run_ccw(["repair"], ccw_env)
    assert result.code == 0

    after = {p.name: p.read_bytes() for p in folder.rglob("*") if p.is_file()}
    assert before == after, "repair touched files that were never broken"


def test_repair_quiet_drops_stdout_but_not_the_exit_code_or_failures(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Matches `sweep --quiet` (cli.py `_run_sweep`): silent on stdout either
    way, but the exit code and any per-item failure lines on stderr are
    unaffected -- a scheduled `ccw repair --quiet` stays quiet when nothing is
    wrong and still speaks (on stderr) when something needs a human."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    assert run_ccw(["sweep"], ccw_env).code == 0

    clean = run_ccw(["repair", "--quiet"], ccw_env)
    assert clean.code == 0
    assert clean.out == "", f"--quiet still printed to stdout: {clean.out!r}"

    folder = next(archive.walk_folders(archive_root))
    _break_render(folder)
    fixed = run_ccw(["repair", "--quiet"], ccw_env)
    assert fixed.code == 0
    assert fixed.out == "", f"--quiet still printed to stdout: {fixed.out!r}"
    for name in archive.GENERATED_NAMES:
        assert (folder / name).exists(), "--quiet must not skip the actual repair"


def test_repair_is_bounded_to_the_same_recent_sample_as_doctor(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DELIBERATE SCOPE, matching `_desync`'s own bound: an old, long-standing
    desync outside the sample is out of scope for a session-start-cheap check.
    `ccw archive --verify` (by hand or the weekly job) is the full answer."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    write_transcript(
        ccw_env,
        jsonl(
            entry("user", "hello", "2020-01-01T00:00:00.000Z", session_id=UUID_A),
            entry("assistant", "hi", "2020-01-01T00:00:05.000Z", session_id=UUID_A),
        ),
        session_id=UUID_A,
    )
    write_transcript(ccw_env, basic_session(session_id=UUID_B), session_id=UUID_B)
    assert run_ccw(["sweep"], ccw_env).code == 0

    folders = {f.name.rpartition("_")[2]: f for f in archive.walk_folders(archive_root)}
    _break_render(folders[UUID_A])  # the OLDER (2020) session -- outside a sample of 1

    monkeypatch.setattr(doctor, "_DESYNC_SAMPLE", 1)
    config = Config(root=warehouse_root(ccw_env), archive_root=archive_root, archive_timezone=ZONE)
    checked, broken = doctor.desync_detail(config)
    assert len(checked) == 1
    assert broken == [], "an out-of-sample desync was caught; the scope decision changed"
