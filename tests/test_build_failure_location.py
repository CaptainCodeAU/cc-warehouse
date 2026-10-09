"""Oracle tests: W-20261006-A43, a failed build names WHERE it failed.

On 2026-10-06 and 2026-10-09 the nightly sweep's own build failed one old
session each with exactly `OSError: [Errno 22] Invalid argument` and nothing
else: no path, no call site. The record said what broke and never where, so
the root cause could not be traced from the log at all. A per-item build
failure now carries the innermost frame it was raised from and, when that
frame is outside this package (a stdlib call, say), the last frame inside it.

The `<via> failed: <ExcType>: <message>` prefix is unchanged, because
`reconcile.py` and the run summary key on it.
"""

import json
from pathlib import Path

import pytest

from cc_warehouse import archive
from conftest import basic_session, mark_archive, run_cli, warehouse_root, write_transcript

ZONE = "Australia/Melbourne"
UUID_A = "aaaaaaaa-4343-4111-8111-aaaaaaaaaaaa"


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
    mark_archive(archive_root, ZONE)


def _item_failures(env: dict[str, str], via: str) -> list[str]:
    log_path = warehouse_root(env) / "logs" / "capture.jsonl"
    records = [json.loads(line) for line in log_path.read_text().splitlines()]
    return [
        str(r["message"])
        for r in records
        if r.get("status") == "error" and str(r.get("message", "")).startswith(f"{via} failed: ")
    ]


def _fd_level_einval(*_args: object, **_kwargs: object) -> None:
    """The real shape: an fd-level call, so the OSError carries no filename."""
    raise OSError(22, "Invalid argument")


@pytest.mark.parametrize(
    ("argv", "via"), [(["sweep"], "sweep-triggered build"), (["build", "--rebuild"], "build")]
)
def test_build_failure_names_the_raising_frame_and_the_package_frame(
    ccw_env: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
    via: str,
) -> None:
    configure_archive(ccw_env, tmp_path / "archive")
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    if argv[0] == "build":
        assert run_cli(["sweep"]).code == 0
    monkeypatch.setattr(archive, "write_session_folder", _fd_level_einval)

    assert run_cli(argv).code == 1

    failures = _item_failures(ccw_env, via)
    assert len(failures) == 1, failures
    message = failures[0]
    assert message.startswith(f"{via} failed: OSError: [Errno 22] Invalid argument"), message
    assert "test_build_failure_location.py:" in message and "in _fd_level_einval" in message, (
        f"the raising frame is not named: {message}"
    )
    assert "via build.py:" in message and "in _mirror" in message, (
        f"the last frame inside cc_warehouse is not named: {message}"
    )


def test_filename_bearing_errors_keep_their_path(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure_archive(ccw_env, tmp_path / "archive")
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    assert run_cli(["sweep"]).code == 0

    def path_error(*_args: object, **_kwargs: object) -> None:
        raise OSError(22, "Invalid argument", "/share/some/folder/conversation.html")

    monkeypatch.setattr(archive, "write_session_folder", path_error)
    assert run_cli(["build", "--rebuild"]).code == 1

    message = _item_failures(ccw_env, "build")[0]
    assert "'/share/some/folder/conversation.html'" in message, message
