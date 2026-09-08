"""Oracle tests: corpus-wide prompts/pastes coverage in `ccw status` and `ccw
doctor` (ticket 39f).

Complementary to `sidecar_gap` (ticket 38), not a duplicate of it. `sidecar_gap`
counts unarchived siblings a copier does not know about yet; this counts,
corpus-wide and at rest, how much of the archive already HAS a `prompts.jsonl`
(39d) and how many sessions reference paste-cache files (39e). It does not
re-derive the missing/refused counts the sweep report already shows per run
(39e's `"pastes-missing"`/`"pastes-refused"` outcomes) - that is transient,
per-run visibility; this is what the archive holds right now, corpus-wide.

Contract: DESIGN section 7 (`ccw status`/`ccw doctor` rows); ticket 38 ruling
(e) (informational, non-blocking); FINDINGS F5/R6 (never opens a payload, never
hashes anything - one manifest.json read per archived session, nothing more).
"""

import json
from pathlib import Path

from cc_warehouse import doctor as doctor_module
from cc_warehouse import status
from cc_warehouse.config import load_config
from conftest import basic_session, run_ccw, warehouse_root, write_transcript

ZONE = "Australia/Melbourne"
UUID_A = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
UUID_B = "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"
HASH_1 = "aaaa1111aaaa1111"


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


def claude_home(env: dict[str, str]) -> Path:
    return Path(env["HOME"]) / ".claude"


def load(env: dict[str, str]) -> object:
    return load_config(xdg_config_home=Path(env["XDG_CONFIG_HOME"]), env=env)


def plant_paste_and_history(env: dict[str, str], uuid: str) -> None:
    paste_cache = claude_home(env) / "paste-cache"
    paste_cache.mkdir(parents=True, exist_ok=True)
    (paste_cache / f"{HASH_1}.txt").write_bytes(b"pasted blob")
    history = claude_home(env) / "history.jsonl"
    row = json.dumps(
        {
            "display": "a prompt",
            "sessionId": uuid,
            "pastedContents": {"1": {"id": 1, "type": "text", "contentHash": HASH_1}},
        }
    )
    existing = history.read_text(encoding="utf-8") if history.is_file() else ""
    history.write_text(existing + row + "\n", encoding="utf-8")


def test_no_archive_configured_reports_zero_without_crashing(
    ccw_env: dict[str, str],
) -> None:
    config = load_config(env=ccw_env)
    gap = status.paste_gap(config)
    assert gap.sessions_total == 0
    assert gap.sessions_with_prompts == 0
    assert gap.sessions_with_pastes == 0
    assert gap.archive_root is None


def test_an_empty_archive_reports_zero(ccw_env: dict[str, str], tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    archive_root.mkdir()
    config = load(ccw_env)
    gap = status.paste_gap(config)  # type: ignore[arg-type]
    assert gap.sessions_total == 0


def test_counts_sessions_with_and_without_prompts_and_pastes(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    write_transcript(
        ccw_env,
        basic_session(session_id=UUID_B),
        session_id=UUID_B,
        encoded_dir="-home-alice-projects-b",
    )
    plant_paste_and_history(ccw_env, UUID_A)
    result = run_ccw(["sweep", "--quiet"], ccw_env)
    assert result.code == 0, result.err + result.out

    config = load(ccw_env)
    gap = status.paste_gap(config)  # type: ignore[arg-type]
    assert gap.sessions_total == 2
    assert gap.sessions_with_prompts == 1
    assert gap.sessions_with_pastes == 1


def test_paste_line_names_the_configuration_gap(ccw_env: dict[str, str]) -> None:
    config = load_config(env=ccw_env)
    line = status.paste_line(status.paste_gap(config))
    assert "no archive" in line.lower()


def test_status_text_includes_the_prompts_line(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    assert run_ccw(["sweep", "--quiet"], ccw_env).code == 0
    result = run_ccw(["status"], ccw_env)
    assert result.code == 0, result.err
    assert "prompts" in result.out.lower(), result.out


def test_doctor_prompts_check_is_never_blocking(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    write_transcript(ccw_env, basic_session(session_id=UUID_A), session_id=UUID_A)
    assert run_ccw(["sweep", "--quiet"], ccw_env).code == 0
    config = load(ccw_env)
    report = doctor_module.diagnose(config, home=Path(ccw_env["HOME"]))  # type: ignore[arg-type]
    check = next(c for c in report.checks if c.name == "prompts")
    assert check.blocking is False
    assert "session" in check.detail.lower()
