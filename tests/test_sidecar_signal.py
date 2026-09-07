"""Oracle tests: how an unarchived sibling gets attention (ticket 38, slice 38e).

RULING (e), taken 2026-09-06 by the principal: an informational `ccw doctor` line
PLUS an OS-level alert.

THE DOCTOR LINE IS NEVER BLOCKING, and that is the ticket 24.7 lesson applied
rather than a softness. This machine's `Uncaptured: N` figure sits between 250 and
350 permanently on a healthy install; a threshold on a figure like that printed
ALERT at every single session start until it was corrected. A chronic red banner
does not get read. So the line reports, and the ALERT does the interrupting,
exactly once per new anomaly.

CORPUS-WIDE, not the 25-folder recency sample doctor's desync check uses. The
entire reason this went unnoticed for four months is that nothing ever looked at
old sessions.

Contract: DESIGN 15 ruling (e), DESIGN 12 (a sink never raises into capture); F6.
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest

from cc_warehouse import notify
from cc_warehouse.config import Config
from conftest import basic_session, run_ccw, warehouse_root, write_transcript

ZONE = "Australia/Melbourne"
UUID_A = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
ENCODED = "-home-alice-projects-widget"


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


def install_hook(env: dict[str, str]) -> None:
    """A registered SessionEnd hook, so doctor's other checks pass and the exit
    code under test is about the sidecars check alone."""
    settings = Path(env["HOME"]) / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(
        json.dumps(
            {"hooks": {"SessionEnd": [{"hooks": [{"type": "command", "command": "ccw hook"}]}]}}
        ),
        encoding="utf-8",
    )


def archived_session(env: dict[str, str], archive_root: Path) -> Path:
    write_transcript(env, basic_session(session_id=UUID_A), session_id=UUID_A)
    result = run_ccw(["sweep", "--quiet"], env)
    assert result.code == 0, result.err
    folders = sorted(archive_root.glob(f"*/*_{UUID_A}"))
    assert len(folders) == 1, folders
    return folders[0]


def plant_notice(folder: Path, *names: str) -> None:
    """A notice in the shape `archive.write_sidecar_notice` produces."""
    body = {
        "schema": 1,
        "refused": [],
        "unarchived": list(names),
        "unknown_inside_subagents": [],
    }
    (folder / "sidecars.json").write_text(json.dumps(body, indent=2), encoding="utf-8")


def doctor(env: dict[str, str]) -> tuple[int, str]:
    result = run_ccw(["doctor"], env)
    return result.code, result.out


def sidecar_line(text: str) -> str:
    lines = [line for line in text.splitlines() if " sidecars " in line]
    assert len(lines) == 1, f"expected exactly one sidecars line in:\n{text}"
    return lines[0]


# ---------------------------------------------------------------------------
# The doctor line
# ---------------------------------------------------------------------------


def test_doctor_prints_a_sidecars_line_on_a_clean_archive(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    archived_session(ccw_env, archive_root)
    _code, out = doctor(ccw_env)
    assert "0 folder(s) with unarchived siblings" in sidecar_line(out)


def test_the_clean_sidecars_line_reads_ok(ccw_env: dict[str, str], tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    archived_session(ccw_env, archive_root)
    _code, out = doctor(ccw_env)
    assert sidecar_line(out).strip().startswith("ok")


def test_doctor_names_the_folder_and_the_sibling_it_found(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """A count alone cannot be acted on. The operator has to be able to go and
    look at the thing without running a second command to find out where it is."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    plant_notice(archived_session(ccw_env, archive_root), "zzz-probe")
    _code, out = doctor(ccw_env)
    line = sidecar_line(out)
    assert "1 folder(s) with unarchived siblings" in line
    assert "zzz-probe" in line
    assert UUID_A in line


def test_a_sidecars_anomaly_does_not_move_doctors_exit_code(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """RULING (e). The exit code is what `ccw-freshness-check.py` escalates on and
    what `ccw-watch` branches on. An unarchived sibling is worth knowing about and
    is not a broken capture."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    install_hook(ccw_env)
    folder = archived_session(ccw_env, archive_root)
    clean_code, _clean = doctor(ccw_env)
    plant_notice(folder, "zzz-probe")
    code, _out = doctor(ccw_env)
    assert clean_code == 0
    assert code == clean_code


def test_an_anomalous_sidecars_line_never_renders_as_FAIL(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """`ccw-watch` shows the operator every line matching `^\\s*FAIL`. A
    non-blocking check that rendered FAIL would put this in that list."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    plant_notice(archived_session(ccw_env, archive_root), "zzz-probe")
    _code, out = doctor(ccw_env)
    assert not sidecar_line(out).strip().startswith("FAIL")


def test_the_uncaptured_line_is_unchanged_by_this_ticket(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Pinned as a WHOLE LINE rather than a substring: `ccw-watch` reads a figure
    out of it with sed, so an added word before the number is as breaking as a
    renamed key."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    archived_session(ccw_env, archive_root)
    _code, out = doctor(ccw_env)
    line = next(x for x in out.splitlines() if "Uncaptured:" in x)
    projects = Path(ccw_env["HOME"]) / ".claude" / "projects"
    assert line.strip() == (
        f"ok  uncaptured  Uncaptured: 0 session(s), 0 sub-agent(s) in {projects}"
        " with no archive folder"
    )


def test_the_sidecars_figure_covers_the_whole_corpus_not_a_recent_sample(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """THE FAILURE THIS CHECK EXISTS FOR was four months old before anyone saw it.
    A check that only looks at the 25 most recent folders could not have found it,
    and would not find the next one either."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    oldest = archived_session(ccw_env, archive_root)
    label_dir = oldest.parent
    for n in range(30):
        newer = label_dir / f"20991231-2359{n:02d}+1100_bbbbbbbb-1111-4111-8111-{n:012d}"
        newer.mkdir()
        (newer / "x.jsonl").write_bytes(b"{}\n")
    plant_notice(oldest, "zzz-probe")
    _code, out = doctor(ccw_env)
    assert "1 folder(s) with unarchived siblings" in sidecar_line(out)


def test_doctor_reports_a_sidecar_dir_with_no_transcript_beside_it(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    archived_session(ccw_env, archive_root)
    projects = Path(ccw_env["HOME"]) / ".claude" / "projects" / ENCODED
    (projects / "99999999-0000-0000-0000-000000000000").mkdir(parents=True, exist_ok=True)
    _code, out = doctor(ccw_env)
    assert "1 sidecar dir(s) without a transcript" in sidecar_line(out)


def test_doctor_reports_a_project_level_stranger(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """LEVEL B. Nothing in the live tree trips this today, which is exactly why it
    is worth having: it is the instrument that says when that changes."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    archived_session(ccw_env, archive_root)
    projects = Path(ccw_env["HOME"]) / ".claude" / "projects" / ENCODED
    (projects / "settings.json").write_bytes(b"{}")
    _code, out = doctor(ccw_env)
    assert "project-level: settings.json" in sidecar_line(out)


def test_doctor_writes_nothing_while_answering_the_sidecars_question(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """Doctor runs when things are broken, so it must not materialise anything.
    Whole-tree byte snapshot of both trees, before and after."""
    from conftest import tree_snapshot

    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    plant_notice(archived_session(ccw_env, archive_root), "zzz-probe")
    projects = Path(ccw_env["HOME"]) / ".claude" / "projects"
    before = (tree_snapshot(archive_root), tree_snapshot(projects))
    doctor(ccw_env)
    assert (tree_snapshot(archive_root), tree_snapshot(projects)) == before


def test_the_sidecars_check_never_hashes_anything(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Corpus-wide means ~22,000 folders. Hashing any of them would put a
    multi-second cost on a check that runs at every session start."""
    from cc_warehouse import status, store

    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    plant_notice(archived_session(ccw_env, archive_root), "zzz-probe")

    def boom(_data: bytes) -> str:
        raise AssertionError("the sidecars check must not hash anything")

    monkeypatch.setattr(store, "sha256_hex", boom)
    from cc_warehouse.config import Config

    config = Config(root=warehouse_root(ccw_env), archive_root=archive_root)
    gap = status.sidecar_gap(config, Path(ccw_env["HOME"]) / ".claude" / "projects")
    assert gap.notices == 1


# ---------------------------------------------------------------------------
# `ccw status`
# ---------------------------------------------------------------------------


def test_status_reports_the_same_two_figures(ccw_env: dict[str, str], tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    plant_notice(archived_session(ccw_env, archive_root), "zzz-probe")
    result = run_ccw(["status"], ccw_env)
    assert result.code == 0, result.err
    assert "Sidecars: 1 unarchived, 0 without transcript" in result.out


# ---------------------------------------------------------------------------
# The alert sink
# ---------------------------------------------------------------------------


def base_config(tmp_path: Path, **kwargs: object) -> Config:
    return Config(root=tmp_path / "warehouse", **cast(dict[str, object], kwargs))  # type: ignore[arg-type]


def test_alert_shells_out_to_osascript_on_macos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[list[str]] = []

    def fake_popen(args: list[str], **_kwargs: object) -> object:
        seen.append(args)
        return object()

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    notify.alert(Config(root=tmp_path), "cc-warehouse", 'a "quoted" sibling')
    assert seen and seen[0][0] == "osascript"


def test_alert_escapes_quotes_so_the_applescript_stays_one_string(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AppleScript is assembled as source text, so an unescaped double quote in a
    directory name would end the string early and change what runs."""
    seen: list[list[str]] = []

    def fake_popen(args: list[str], **_kwargs: object) -> object:
        seen.append(args)
        return object()

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    notify.alert(Config(root=tmp_path), "cc-warehouse", 'a "quoted" sibling')
    script = seen[0][-1]
    assert '\\"quoted\\"' in script


def test_alert_is_a_no_op_off_macos(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[str]] = []

    def fake_popen(args: list[str], **_kwargs: object) -> object:
        seen.append(args)
        return object()

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    notify.alert(Config(root=tmp_path), "cc-warehouse", "anything")
    assert seen == []


def test_alert_swallows_a_failure_to_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DESIGN 12. A notification sink must never be able to raise into capture."""

    def boom(*_args: object, **_kwargs: object) -> object:
        raise OSError("no such binary")

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(subprocess, "Popen", boom)
    notify.alert(Config(root=tmp_path), "cc-warehouse", "anything")


def test_alert_is_silent_when_desktop_alerts_are_turned_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[list[str]] = []

    def fake_popen(args: list[str], **_kwargs: object) -> object:
        seen.append(args)
        return object()

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    notify.alert(Config(root=tmp_path, desktop_alerts=False), "cc-warehouse", "anything")
    assert seen == []


def test_desktop_alerts_defaults_to_true(tmp_path: Path) -> None:
    """An attention sink that defaults OFF is the F6 shape this project exists to
    remove: it parses, it is tested, and it does nothing for anyone who did not
    already know to turn it on."""
    assert Config(root=tmp_path).desktop_alerts is True


# ---------------------------------------------------------------------------
# The dedup, end to end: one alert per NEW anomaly, not one per run
# ---------------------------------------------------------------------------


def test_exactly_one_alert_fires_across_two_sweeps_of_the_same_anomaly(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE PROPERTY RULING (e) DEPENDS ON. An alert on every daily sweep is worse
    than no alert: it is the ticket 24.7 failure, where a banner that fires on a
    healthy machine trains the operator to stop reading banners.

    Run in-process (`run_cli`) rather than as a subprocess, because the point is
    to count calls inside the process that makes them.
    """
    from conftest import run_cli

    fired: list[str] = []

    def record(_config: Config, _title: str, message: str) -> None:
        fired.append(message)

    monkeypatch.setattr(notify, "alert", record)
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    probe = Path(ccw_env["HOME"]) / ".claude" / "projects" / ENCODED / UUID_A / "zzz-probe"
    probe.mkdir(parents=True)

    assert run_cli(["sweep", "--quiet"]).code == 0
    assert run_cli(["sweep", "--quiet"]).code == 0
    assert len(fired) == 1, fired
    assert "zzz-probe" in fired[0]


def test_a_cleared_anomaly_does_not_alert(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The anomaly going away is good news, and good news does not interrupt."""
    from conftest import run_cli

    fired: list[str] = []

    def record(_config: Config, _title: str, message: str) -> None:
        fired.append(message)

    monkeypatch.setattr(notify, "alert", record)
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    probe = Path(ccw_env["HOME"]) / ".claude" / "projects" / ENCODED / UUID_A / "zzz-probe"
    probe.mkdir(parents=True)
    assert run_cli(["sweep", "--quiet"]).code == 0
    probe.rmdir()
    fired.clear()
    assert run_cli(["sweep", "--quiet"]).code == 0
    assert fired == []


def test_the_notice_is_rewritten_to_empty_lists_when_the_anomaly_goes(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """R4: nothing here deletes. An empty notice is also better evidence than a
    missing one, because it says "checked, clean now" rather than nothing."""
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    probe = Path(ccw_env["HOME"]) / ".claude" / "projects" / ENCODED / UUID_A / "zzz-probe"
    probe.mkdir(parents=True)
    assert run_ccw(["sweep", "--quiet"], ccw_env).code == 0
    probe.rmdir()
    assert run_ccw(["sweep", "--quiet"], ccw_env).code == 0
    folder = sorted(archive_root.glob(f"*/*_{UUID_A}"))[0]
    body = cast(dict[str, object], json.loads((folder / "sidecars.json").read_text("utf-8")))
    assert body["unarchived"] == []
