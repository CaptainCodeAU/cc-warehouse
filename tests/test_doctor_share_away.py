"""`ccw doctor` on a machine whose share is mounted only for its sweep.

The design (Network_Plan's close.md for 2026-11-28, item 5): between sweeps a
box's archive root is an empty root-owned folder with no `_archive-root.json`.
The SessionEnd hook refuses it and, with `keep_objects = true`, keeps the
session in the local vault; the next sweep files it. So every session end on
such a box meets a refused root, and before this change doctor failed three
blocking lines at every session start: `archive root`, `desync` (the sampled
folders are all absent) and `unreadable` (every uuid-less head is absent).

The states, agreed with cc-warehouse-main (268e2629) on 2026-11-28:

1. SHARE AWAY: archive_root set, keep_objects true, no marker, and the root is
   absent or an EMPTY folder. `archive root` is an ok line naming how many
   captures were refused since the last share write; `desync` and
   `unreadable` are not checked, because nothing is mounted to check.
2. AWAY TOO LONG: as 1, but the local heartbeat is missing, unreadable, or its
   last share write is more than 3 days old. `archive root` is a blocking FAIL.
3. UNCHANGED: keep_objects false (nothing else holds the sessions), a
   non-empty folder with no marker (a real tree, not adopted), a bad marker,
   and a marked root (the Mac) all read exactly as before.

The heartbeat is the LOCAL `<config.root>/heartbeat.json` the sweep writes
(plan 2026-11-28-ccw-share-sweep-side.md), never the share's copy. Its last
share write is `share_written_at` when present, else `at` when `share` is
"written"; an "unreachable" heartbeat with no `share_written_at` is no proof
the share was ever written.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from cc_warehouse import capture, doctor, notify
from cc_warehouse.config import Config
from conftest import basic_session, jsonl, load_hook_module, run_ccw, warehouse_root

ZONE = "Australia/Melbourne"
UUID_A = "a5a5a5a5-1111-4111-8111-aaaaaaaaaaaa"
UUID_B = "b5b5b5b5-2222-4222-8222-bbbbbbbbbbbb"
MARKER = "_archive-root.json"
PROJECT_DIR = "-home-alice-projects-widget"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def config_for(tmp_path: Path, archive_root: Path, *, keep_objects: bool = True) -> Config:
    return Config(
        root=tmp_path / "warehouse",
        archive_root=archive_root,
        archive_timezone=ZONE,
        keep_objects=keep_objects,
    )


def mount_point(tmp_path: Path) -> Path:
    """The box between sweeps: an empty folder where the share mounts."""
    target = tmp_path / "mnt" / "archive"
    target.mkdir(parents=True)
    return target


def stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def heartbeat(
    config: Config,
    *,
    at: datetime,
    share: str = "written",
    share_written_at: datetime | None = None,
) -> Path:
    """The local heartbeat, in the contract's shape, written by hand."""
    payload: dict[str, object] = {
        "machine": "box",
        "at": stamp(at),
        "ccw_version": "0.0.0",
        "items": 3,
        "stored": 1,
        "failed": 0,
        "archive_root": str(config.archive_root),
        "share": share,
    }
    if share_written_at is not None:
        payload["share_written_at"] = stamp(share_written_at)
    config.root.mkdir(parents=True, exist_ok=True)
    path = config.root / "heartbeat.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def capture_refused(home: Path, config: Config, uuid: str = UUID_A) -> None:
    """A real SessionEnd capture against the refused root: the vault keeps it,
    the catalog gets its row, capture.jsonl gets the refusal line."""
    project = home / ".claude" / "projects" / PROJECT_DIR
    project.mkdir(parents=True, exist_ok=True)
    path = project / f"{uuid}.jsonl"
    path.write_bytes(basic_session(session_id=uuid))
    result = capture.capture_transcript(config, path, session_id=uuid, cwd=None)
    assert result.action == "stored"


def capture_uuidless_refused(tmp_path: Path, config: Config) -> None:
    """A visible uuid-less head (a `claude -p` stream-json file): the shape the
    `unreadable` check reads, captured against the refused root."""
    ts = "2026-09-29T14:01:24.763Z"
    cwd = "/home/alice/projects/widget"
    data = jsonl(
        {"type": "system", "subtype": "init", "cwd": cwd, "timestamp": ts},
        {
            "type": "user",
            "timestamp": ts,
            "cwd": cwd,
            "message": {"role": "user", "content": "prompt one"},
        },
        {
            "type": "assistant",
            "timestamp": ts,
            "cwd": cwd,
            "message": {"role": "assistant", "content": [{"type": "text", "text": "Done."}]},
        },
    )
    path = tmp_path / "home" / ".claude" / "projects" / PROJECT_DIR / "stream.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    capture.capture_transcript(config, path, session_id=None, cwd=None)


def refusal_line(config: Config, at: datetime, session: str) -> None:
    """A refusal line in capture.jsonl, in capture._log_root_refusal's shape."""
    notify.append_log(
        config,
        {
            "at": at.isoformat(),
            "status": "error",
            "session": session,
            "project": None,
            "message": "archive write refused, the vault holds the session: MISSING ...",
            "elapsed_ms": None,
        },
    )


def check(report: doctor.Report, name: str) -> doctor.Check:
    found = [c for c in report.checks if c.name == name]
    assert len(found) == 1, [c.name for c in report.checks]
    return found[0]


def install_hook(home: Path) -> None:
    """A SessionEnd `ccw hook` in settings.json, so the `hook` line is not
    what decides the verdict (the shape test_doctor_external_contract uses)."""
    settings = home / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(
        json.dumps(
            {"hooks": {"SessionEnd": [{"hooks": [{"type": "command", "command": "ccw hook"}]}]}}
        ),
        encoding="utf-8",
    )


def diagnose(tmp_path: Path, config: Config) -> doctor.Report:
    install_hook(tmp_path / "home")
    return doctor.diagnose(config, home=tmp_path / "home")


NOW = datetime.now(UTC)


# ---------------------------------------------------------------------------
# State 1: share away, sessions safe locally, recent share write
# ---------------------------------------------------------------------------


def test_share_away_with_a_fresh_heartbeat_is_ok_and_says_so(tmp_path: Path) -> None:
    config = config_for(tmp_path, mount_point(tmp_path))
    capture_refused(tmp_path / "home", config)
    heartbeat(config, at=NOW - timedelta(hours=5))
    report = diagnose(tmp_path, config)
    line = check(report, "archive root")
    assert line.ok, line.detail
    assert line.blocking
    assert line.detail.startswith("share away:"), line.detail
    assert "1 capture(s) refused" in line.detail
    assert "kept locally" in line.detail
    assert "last share write" in line.detail
    assert report.ok, doctor.report_text(report)


def test_share_away_skips_desync_and_unreadable_which_cannot_be_checked(
    tmp_path: Path,
) -> None:
    """Without the change both FAIL: the sampled folder and the uuid-less head
    are absent because nothing is mounted, not because anything is broken."""
    config = config_for(tmp_path, mount_point(tmp_path))
    capture_refused(tmp_path / "home", config)
    capture_uuidless_refused(tmp_path, config)
    heartbeat(config, at=NOW - timedelta(hours=5))
    report = diagnose(tmp_path, config)
    for name in ("desync", "unreadable"):
        line = check(report, name)
        assert line.ok, (name, line.detail)
        assert line.detail.startswith("share away: not checked"), (name, line.detail)
    assert report.ok, doctor.report_text(report)


def test_share_away_also_holds_when_the_mount_point_itself_is_absent(tmp_path: Path) -> None:
    """A laptop's mount point under /Volumes vanishes when unmounted."""
    target = tmp_path / "Volumes" / "archive"
    config = config_for(tmp_path, target)
    capture_refused(tmp_path / "home", config)
    heartbeat(config, at=NOW - timedelta(days=1))
    report = diagnose(tmp_path, config)
    assert check(report, "archive root").ok, check(report, "archive root").detail
    assert report.ok, doctor.report_text(report)
    assert not target.exists()


def test_refusals_before_the_last_share_write_are_not_counted(tmp_path: Path) -> None:
    """The sweep that wrote the share filed them."""
    config = config_for(tmp_path, mount_point(tmp_path))
    refusal_line(config, NOW - timedelta(days=2), "1" * 64)
    refusal_line(config, NOW - timedelta(hours=2), "2" * 64)
    refusal_line(config, NOW - timedelta(hours=1), "2" * 64)
    heartbeat(config, at=NOW - timedelta(days=1))
    line = check(diagnose(tmp_path, config), "archive root")
    assert line.ok, line.detail
    assert "1 capture(s) refused" in line.detail


def test_share_away_with_nothing_refused_yet_says_zero(tmp_path: Path) -> None:
    config = config_for(tmp_path, mount_point(tmp_path))
    heartbeat(config, at=NOW - timedelta(hours=1))
    line = check(diagnose(tmp_path, config), "archive root")
    assert line.ok, line.detail
    assert "0 capture(s) refused" in line.detail


def test_an_unreachable_sweep_reads_the_carried_share_write(tmp_path: Path) -> None:
    config = config_for(tmp_path, mount_point(tmp_path))
    heartbeat(
        config,
        at=NOW - timedelta(hours=1),
        share="unreachable",
        share_written_at=NOW - timedelta(days=1),
    )
    line = check(diagnose(tmp_path, config), "archive root")
    assert line.ok, line.detail


# ---------------------------------------------------------------------------
# State 2: share away too long, or no proof the share was ever written
# ---------------------------------------------------------------------------


def test_a_share_write_more_than_3_days_old_fails(tmp_path: Path) -> None:
    config = config_for(tmp_path, mount_point(tmp_path))
    capture_refused(tmp_path / "home", config)
    heartbeat(config, at=NOW - timedelta(days=4))
    report = diagnose(tmp_path, config)
    line = check(report, "archive root")
    assert not line.ok
    assert line.blocking
    assert line.detail.startswith("share away for"), line.detail
    assert "more than 3 days ago" in line.detail
    assert "kept only on this machine" in line.detail
    assert not report.ok
    # The FAIL is the root line's alone.
    assert check(report, "desync").ok
    assert check(report, "unreadable").ok


def test_just_inside_3_days_is_still_ok(tmp_path: Path) -> None:
    config = config_for(tmp_path, mount_point(tmp_path))
    heartbeat(config, at=NOW - timedelta(days=3) + timedelta(hours=1))
    assert check(diagnose(tmp_path, config), "archive root").ok


def test_no_heartbeat_fails_as_no_proof_the_share_was_written(tmp_path: Path) -> None:
    config = config_for(tmp_path, mount_point(tmp_path))
    capture_refused(tmp_path / "home", config)
    line = check(diagnose(tmp_path, config), "archive root")
    assert not line.ok
    assert line.blocking
    assert "no heartbeat" in line.detail, line.detail


def test_an_unreadable_heartbeat_fails_and_does_not_raise(tmp_path: Path) -> None:
    config = config_for(tmp_path, mount_point(tmp_path))
    config.root.mkdir(parents=True)
    (config.root / "heartbeat.json").write_text("{not json", encoding="utf-8")
    line = check(diagnose(tmp_path, config), "archive root")
    assert not line.ok
    assert "heartbeat" in line.detail


def test_an_unreachable_sweep_with_no_carried_write_fails(tmp_path: Path) -> None:
    config = config_for(tmp_path, mount_point(tmp_path))
    heartbeat(config, at=NOW - timedelta(hours=1), share="unreachable")
    line = check(diagnose(tmp_path, config), "archive root")
    assert not line.ok
    assert "never" in line.detail or "no proof" in line.detail, line.detail


def test_an_unreachable_sweep_with_a_stale_carried_write_fails(tmp_path: Path) -> None:
    config = config_for(tmp_path, mount_point(tmp_path))
    heartbeat(
        config,
        at=NOW - timedelta(hours=1),
        share="unreachable",
        share_written_at=NOW - timedelta(days=5),
    )
    line = check(diagnose(tmp_path, config), "archive root")
    assert not line.ok
    assert "more than 3 days ago" in line.detail


# ---------------------------------------------------------------------------
# State 3: unchanged
# ---------------------------------------------------------------------------


def test_without_the_vault_an_empty_root_still_fails_as_before(tmp_path: Path) -> None:
    """keep_objects false: nothing holds the sessions, so it is not share away."""
    target = mount_point(tmp_path)
    config = config_for(tmp_path, target, keep_objects=False)
    heartbeat(config, at=NOW - timedelta(hours=1))
    report = diagnose(tmp_path, config)
    line = check(report, "archive root")
    assert not line.ok
    assert line.detail.startswith(f"MISSING at {target}"), line.detail
    assert not check(report, "desync").detail.startswith("share away")


def test_a_non_empty_folder_with_no_marker_still_fails_as_before(tmp_path: Path) -> None:
    """A real tree that was never adopted needs `--init`, not patience."""
    target = mount_point(tmp_path)
    folder = target / "widget" / f"20260105-210000+1100_{UUID_B}"
    folder.mkdir(parents=True)
    (folder / f"{UUID_B}.jsonl").write_bytes(basic_session(session_id=UUID_B))
    config = config_for(tmp_path, target)
    heartbeat(config, at=NOW - timedelta(hours=1))
    line = check(diagnose(tmp_path, config), "archive root")
    assert not line.ok
    assert line.detail.startswith(f"MISSING at {target}"), line.detail


def test_a_wrong_zone_marker_still_fails_as_before(tmp_path: Path) -> None:
    target = mount_point(tmp_path)
    (target / MARKER).write_text(
        json.dumps({"cc_warehouse": "archive_root", "archive_timezone": "Europe/London"}),
        encoding="utf-8",
    )
    config = config_for(tmp_path, target)
    heartbeat(config, at=NOW - timedelta(hours=1))
    line = check(diagnose(tmp_path, config), "archive root")
    assert not line.ok
    assert "zone mismatch" in line.detail


def test_a_marked_root_reads_exactly_as_before(tmp_path: Path) -> None:
    """The Mac: its share is mounted all the time. No heartbeat needed."""
    target = mount_point(tmp_path)
    (target / MARKER).write_text(
        json.dumps({"cc_warehouse": "archive_root", "archive_timezone": ZONE}),
        encoding="utf-8",
    )
    config = config_for(tmp_path, target, keep_objects=False)
    report = diagnose(tmp_path, config)
    line = check(report, "archive root")
    assert line.ok
    assert line.detail == f"marker present at {target / MARKER}, zone {ZONE}"
    assert not check(report, "desync").detail.startswith("share away")
    assert not check(report, "unreadable").detail.startswith("share away")


# ---------------------------------------------------------------------------
# Through the real verb and the real freshness hook
# ---------------------------------------------------------------------------


def _configure(env: dict[str, str], archive_root: Path) -> Config:
    cfg = Path(env["HOME"]) / ".config" / "cc-warehouse"
    cfg.mkdir(parents=True, exist_ok=True)
    root = warehouse_root(env)
    lines = [
        f'root = "{root}"',
        f'archive_timezone = "{ZONE}"',
        f'archive_root = "{archive_root}"',
        "keep_objects = true",
    ]
    (cfg / "config.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    env["XDG_CONFIG_HOME"] = str(cfg.parent)
    return Config(root=root, archive_root=archive_root, archive_timezone=ZONE)


def test_the_doctor_verb_exits_0_while_the_share_is_away(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """The exit code is what ccw-freshness-check.py reads."""
    config = _configure(ccw_env, mount_point(tmp_path))
    install_hook(Path(ccw_env["HOME"]))
    capture_refused(Path(ccw_env["HOME"]), config)
    heartbeat(config, at=NOW - timedelta(hours=2))
    result = run_ccw(["doctor"], ccw_env)
    assert result.code == 0, result.out
    assert not any(line.lstrip().startswith("FAIL") for line in result.out.splitlines())
    assert "share away:" in result.out
    assert "Uncaptured:" in result.out


def test_the_doctor_verb_exits_non_zero_when_away_too_long(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    config = _configure(ccw_env, mount_point(tmp_path))
    heartbeat(config, at=NOW - timedelta(days=6))
    result = run_ccw(["doctor"], ccw_env)
    assert result.code != 0
    assert any(
        line.lstrip().startswith("FAIL") and "archive root" in line
        for line in result.out.splitlines()
    )


def _freshness() -> ModuleType:
    return load_hook_module("ccw_freshness_check", "ccw-freshness-check.py")


def test_the_freshness_hook_says_nothing_alarming_while_the_share_is_away(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The real share-away doctor report, fed to the real hook's main()."""
    config = config_for(tmp_path, mount_point(tmp_path))
    capture_refused(tmp_path / "home", config)
    heartbeat(config, at=NOW - timedelta(hours=5))
    report = diagnose(tmp_path, config)
    assert report.ok
    text = doctor.report_text(report)

    monkeypatch.setenv("HOME", str(tmp_path / "scratch-home"))
    monkeypatch.delenv("CCW_ROOT", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    freshness = _freshness()
    monkeypatch.setattr(freshness, "LOG", tmp_path / "ccw-hook.log")
    monkeypatch.setattr(freshness, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(freshness, "LOCK_PATH", tmp_path / "freshness.lock")
    monkeypatch.setattr(freshness, "find_ccw", lambda: "/fake/bin/ccw")
    monkeypatch.setattr(freshness.sys, "platform", "linux")
    popened: list[list[str]] = []

    def fake_run(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        if argv[0] == "/fake/bin/ccw":
            return subprocess.CompletedProcess(argv, 0, text + "\n", "")
        return subprocess.CompletedProcess(argv, 0, "\tlast exit code = 0\n", "")

    def fake_popen(argv: list[str], **_kwargs: Any) -> object:
        popened.append(argv)
        return object()

    def no_network(*_args: Any, **_kwargs: Any) -> object:
        raise AssertionError("the hook tried to speak or post")

    monkeypatch.setattr(freshness.subprocess, "run", fake_run)
    monkeypatch.setattr(freshness.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(freshness.urllib.request, "urlopen", no_network)
    capsys.readouterr()
    assert freshness.main() == 0
    out = capsys.readouterr().out
    assert "broken" not in out.lower(), out
    assert "not working" not in out.lower(), out
    assert popened == []
    state = freshness._read_state(tmp_path / "state.json")  # pyright: ignore[reportPrivateUsage]
    assert freshness.carried_broken_since(state, datetime.now(UTC)) is None


# ---------------------------------------------------------------------------
# `share_away_days`: the threshold is a config key (cc-warehouse-main, 7:50 PM
# 28 Nov: a laptop that stays home while its owner travels is away for longer)
# ---------------------------------------------------------------------------


def _xdg(tmp_path: Path, body: str) -> Path:
    cfg = tmp_path / "xdg" / "cc-warehouse"
    cfg.mkdir(parents=True)
    (cfg / "config.toml").write_text(body, encoding="utf-8")
    return cfg.parent


def test_share_away_days_defaults_to_3(tmp_path: Path) -> None:
    from cc_warehouse.config import load_config

    cfg = load_config(xdg_config_home=_xdg(tmp_path, ""), env={"HOME": "/home/alice"})
    assert cfg.share_away_days == 3


def test_share_away_days_reads_a_non_default_value(tmp_path: Path) -> None:
    from cc_warehouse.config import load_config

    cfg = load_config(
        xdg_config_home=_xdg(tmp_path, "share_away_days = 21\n"), env={"HOME": "/home/alice"}
    )
    assert cfg.share_away_days == 21
    assert cfg.config_errors == ()


@pytest.mark.parametrize("value", ["0", "-2", '"ten"', "2.5", "true"])
def test_an_illegal_share_away_days_is_recorded_and_3_kept(tmp_path: Path, value: str) -> None:
    from cc_warehouse.config import load_config

    cfg = load_config(
        xdg_config_home=_xdg(tmp_path, f"share_away_days = {value}\n"),
        env={"HOME": "/home/alice"},
    )
    assert cfg.share_away_days == 3
    assert any("share_away_days" in problem for problem in cfg.config_errors)


def test_a_longer_threshold_keeps_a_week_away_ok(tmp_path: Path) -> None:
    config = Config(
        root=tmp_path / "warehouse",
        archive_root=mount_point(tmp_path),
        archive_timezone=ZONE,
        keep_objects=True,
        share_away_days=21,
    )
    heartbeat(config, at=NOW - timedelta(days=7))
    line = check(diagnose(tmp_path, config), "archive root")
    assert line.ok, line.detail
    assert "21 days" in line.detail


def test_the_fail_line_names_the_threshold_it_used(tmp_path: Path) -> None:
    config = Config(
        root=tmp_path / "warehouse",
        archive_root=mount_point(tmp_path),
        archive_timezone=ZONE,
        keep_objects=True,
        share_away_days=5,
    )
    heartbeat(config, at=NOW - timedelta(days=6))
    line = check(diagnose(tmp_path, config), "archive root")
    assert not line.ok
    assert "more than 5 days ago" in line.detail
    assert "share_away_days = 5" in line.detail


# ---------------------------------------------------------------------------
# Red-team R2: the detached render child on an away share
# (cc-warehouse-main, 7:53 PM 28 Nov). Before: it refused the root, notified an
# error (a desktop alert on a laptop) and returned 1 before writing the local
# projection, at every session end on such a machine.
# ---------------------------------------------------------------------------


def _stored_then_away(env: dict[str, str], tmp_path: Path, *, keep_objects: bool) -> str:
    """A session stored while the share was mounted, then the share away."""
    from conftest import catalog_rows, run_cli, write_transcript

    first = tmp_path / "first"
    first.mkdir()
    (first / MARKER).write_text(
        json.dumps({"cc_warehouse": "archive_root", "archive_timezone": ZONE}),
        encoding="utf-8",
    )
    _configure(env, first)
    write_transcript(env, basic_session(session_id=UUID_A), session_id=UUID_A)
    assert run_cli(["sweep"]).code == 0
    away = mount_point(tmp_path)
    _configure(env, away)
    if not keep_objects:
        cfg = Path(env["XDG_CONFIG_HOME"]) / "cc-warehouse" / "config.toml"
        cfg.write_text(
            cfg.read_text(encoding="utf-8").replace("keep_objects = true", "keep_objects = false"),
            encoding="utf-8",
        )
    return str(catalog_rows(env, "SELECT short FROM session")[0][0])  # type: ignore[index]


def _log(env: dict[str, str]) -> list[dict[str, object]]:
    path = warehouse_root(env) / "logs" / "capture.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_the_render_child_writes_the_local_projection_while_the_share_is_away(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    from conftest import run_cli, tree_snapshot

    short = _stored_then_away(ccw_env, tmp_path, keep_objects=True)
    projections = warehouse_root(ccw_env) / "projections"
    for page in projections.rglob("conversation.html"):
        page.unlink()
    before = len(_log(ccw_env))
    result = run_cli(["render", "--session", f"s:{short}"])
    assert result.code == 0, result.err
    assert any(projections.rglob("conversation.html"))
    assert tree_snapshot(tmp_path / "mnt" / "archive") == {}
    new = _log(ccw_env)[before:]
    assert not [r for r in new if r.get("status") == "error"], new
    assert any(
        r.get("status") == "info" and "share away" in str(r.get("message")) for r in new
    ), new
    assert any(r.get("status") == "render-done" for r in new), new


def test_without_the_vault_the_render_child_still_refuses_and_reports(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    from conftest import run_cli, tree_snapshot

    short = _stored_then_away(ccw_env, tmp_path, keep_objects=False)
    before = len(_log(ccw_env))
    result = run_cli(["render", "--session", f"s:{short}"])
    assert result.code != 0
    assert tree_snapshot(tmp_path / "mnt" / "archive") == {}
    assert any(r.get("status") == "error" for r in _log(ccw_env)[before:])


def test_no_share_away_line_tells_anyone_to_init_the_mount_point(tmp_path: Path) -> None:
    """Red-team R9: root_problem's `--init` hint would have an agent mark the
    empty mount point as an archive. Every share-away line, ok or FAIL, leaves
    it out and still names the path."""
    target = mount_point(tmp_path)
    config = config_for(tmp_path, target)
    capture_refused(tmp_path / "home", config)
    for beat in (None, NOW - timedelta(hours=1), NOW - timedelta(days=9)):
        path = config.root / "heartbeat.json"
        if beat is None:
            if path.exists():
                path.unlink()
        else:
            heartbeat(config, at=beat)
        text = doctor.report_text(diagnose(tmp_path, config))
        assert "--init" not in text, text
        assert "ccw archive --to" not in text, text
    assert f"MISSING at {target}" in check(diagnose(tmp_path, config), "archive root").detail


def test_the_heartbeat_unfiled_figure_is_named_when_non_zero(tmp_path: Path) -> None:
    """Red-team R1's `unfiled` key: heads the last sweep's build left out of
    the archive. Named on the line; it does not change the verdict."""
    config = config_for(tmp_path, mount_point(tmp_path))
    path = heartbeat(config, at=NOW - timedelta(hours=1))
    beat = json.loads(path.read_text(encoding="utf-8"))
    beat["unfiled"] = 4
    path.write_text(json.dumps(beat), encoding="utf-8")
    line = check(diagnose(tmp_path, config), "archive root")
    assert line.ok, line.detail
    assert "4 the last sweep left unfiled" in line.detail


# ---------------------------------------------------------------------------
# From the independent review of the first cut (28 Nov)
# ---------------------------------------------------------------------------


def test_a_heartbeat_that_is_not_utf8_fails_and_does_not_raise(tmp_path: Path) -> None:
    config = config_for(tmp_path, mount_point(tmp_path))
    config.root.mkdir(parents=True)
    (config.root / "heartbeat.json").write_bytes(b"\xff\xfe\x00not utf-8")
    line = check(diagnose(tmp_path, config), "archive root")
    assert not line.ok
    assert "heartbeat unreadable" in line.detail


def test_a_capture_log_line_that_is_not_an_object_is_skipped(tmp_path: Path) -> None:
    config = config_for(tmp_path, mount_point(tmp_path))
    heartbeat(config, at=NOW - timedelta(days=1))
    logs = config.root / "logs"
    logs.mkdir(parents=True)
    (logs / "capture.jsonl").write_text(
        json.dumps("archive write refused, a bare string") + "\n"
        + json.dumps(["archive write refused"]) + "\n",
        encoding="utf-8",
    )
    line = check(diagnose(tmp_path, config), "archive root")
    assert line.ok, line.detail
    assert "0 capture(s) refused" in line.detail


def test_the_fail_line_gives_days_and_hours(tmp_path: Path) -> None:
    config = config_for(tmp_path, mount_point(tmp_path))
    heartbeat(config, at=NOW - timedelta(days=3, hours=20, minutes=10))
    line = check(diagnose(tmp_path, config), "archive root")
    assert not line.ok
    assert "share away for 3 days 20 hours" in line.detail, line.detail


def test_with_no_projections_a_share_away_render_claims_no_render(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """keep_projections = false and the share away: nothing is rendered anywhere,
    so no `render-done` (doctor reads it as the pipeline finishing)."""
    from conftest import run_cli

    short = _stored_then_away(ccw_env, tmp_path, keep_objects=True)
    cfg = Path(ccw_env["XDG_CONFIG_HOME"]) / "cc-warehouse" / "config.toml"
    cfg.write_text(
        cfg.read_text(encoding="utf-8") + "keep_projections = false\n", encoding="utf-8"
    )
    before = len(_log(ccw_env))
    result = run_cli(["render", "--session", f"s:{short}"])
    assert result.code == 0, result.err
    new = _log(ccw_env)[before:]
    assert not [r for r in new if r.get("status") in ("error", "render-done")], new
    assert any("nothing rendered here" in str(r.get("message")) for r in new), new


def test_no_doctor_log_reader_raises_on_a_line_that_is_not_an_object(tmp_path: Path) -> None:
    """The class, not the instance: every capture.jsonl reader in doctor, on
    the Mac shape (marked root) and the share-away shape, with lines that
    parse as strings and lists and carry each reader's filter token."""
    tokens = [
        '"sweep: 1 items',
        '"sweep',
        '"repair',
        '"archive',
        '"render-done',
        '"companions: ',
        "archive write refused",
    ]
    junk = "".join(json.dumps(token) + "\n" + json.dumps([token]) + "\n" for token in tokens)
    marked = tmp_path / "marked"
    marked.mkdir()
    (marked / MARKER).write_text(
        json.dumps({"cc_warehouse": "archive_root", "archive_timezone": ZONE}),
        encoding="utf-8",
    )
    for config in (
        config_for(tmp_path / "a", marked, keep_objects=False),
        config_for(tmp_path / "b", mount_point(tmp_path / "b")),
    ):
        logs = config.root / "logs"
        logs.mkdir(parents=True)
        (logs / "capture.jsonl").write_text(junk, encoding="utf-8")
        doctor.report_text(diagnose(tmp_path, config))
