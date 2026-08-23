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
from pathlib import Path

import pytest

from cc_warehouse import archive, doctor
from cc_warehouse.config import Config
from conftest import basic_session, entry, jsonl, run_ccw, warehouse_root, write_transcript

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
