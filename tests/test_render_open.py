"""Oracle tests: `ccw render --open` (ticket 28.1).

`notify.open_folder` reveals the FOLDER a capture landed in; there was no
equivalent for the PAGE itself, so an operator got a directory to browse
rather than their transcript. `--open` hands the rendered `conversation.html`
straight to the platform opener via the new `notify.open_page`.

Contract: DESIGN section 12 (every notification sink is best-effort, none may
fail the command it rides on); R9 (one opener implementation, not two -
`notify._open_with_system_default` is shared by `open_folder` and `open_page`,
per ticket 28.13's C12 recommendation).
"""

from pathlib import Path
from typing import cast

import pytest

from conftest import (
    basic_session,
    catalog_rows,
    hook_payload,
    run_ccw,
    run_cli,
    warehouse_root,
    write_transcript,
)

ZONE = "Australia/Melbourne"
UUID_A = "a1111111-2222-3333-4444-555555555551"


def configure(env: dict[str, str], tmp_path: Path, *, archive: bool) -> Path | None:
    """XDG config: no archive by default; `archive=True` also retires personal
    projections, matching the real machine's configuration (borrowed from
    test_reveal_target.py's fixture of the same shape)."""
    cfg = Path(env["HOME"]) / ".config" / "cc-warehouse"
    cfg.mkdir(parents=True, exist_ok=True)
    lines = [f'root = "{warehouse_root(env)}"', f'archive_timezone = "{ZONE}"']
    archive_root = tmp_path / "archive" if archive else None
    if archive_root is not None:
        lines.append(f'archive_root = "{archive_root}"')
        lines.append("keep_projections = false")
    (cfg / "config.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    env["XDG_CONFIG_HOME"] = str(cfg.parent)
    return archive_root


def stored_short(env: dict[str, str]) -> str:
    """Capture one session via the hook and return its short hash, for the
    `--session s:<key>` form."""
    transcript = write_transcript(env, basic_session(session_id=UUID_A))
    assert run_ccw(["hook"], env, stdin=hook_payload(transcript)).code == 0
    rows = catalog_rows(env, "SELECT short FROM session LIMIT 1")
    return str(cast("tuple[str]", rows[0])[0])


# --- ad-hoc form -------------------------------------------------------


def test_adhoc_open_flag_opens_the_actual_page(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cc_warehouse import notify

    opened: list[str] = []
    def record_open(path: str) -> None:
        opened.append(path)

    monkeypatch.setattr(notify, "open_page", record_open)

    source = tmp_path / "adhoc.jsonl"
    source.write_bytes(basic_session())
    out = tmp_path / "out"
    result = run_cli(["render", str(source), "--out", str(out), "--open"])
    assert result.code == 0, result.err
    assert opened == [str(out / "conversation.html")]
    assert Path(opened[0]).is_file()


def test_adhoc_without_open_never_opens_anything(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cc_warehouse import notify

    opened: list[str] = []
    def record_open(path: str) -> None:
        opened.append(path)

    monkeypatch.setattr(notify, "open_page", record_open)

    source = tmp_path / "adhoc.jsonl"
    source.write_bytes(basic_session())
    out = tmp_path / "out"
    result = run_cli(["render", str(source), "--out", str(out)])
    assert result.code == 0, result.err
    assert opened == []


def test_adhoc_open_flag_survives_a_failing_opener(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DESIGN 12: a broken opener must never fail the render itself."""
    from cc_warehouse import notify

    def explode(_path: object) -> None:
        raise RuntimeError("no browser on this box")

    monkeypatch.setattr(notify, "open_page", explode)
    source = tmp_path / "adhoc.jsonl"
    source.write_bytes(basic_session())
    out = tmp_path / "out"
    result = run_cli(["render", str(source), "--out", str(out), "--open"])
    assert result.code == 0, result.err


# --- catalog (--session) form -------------------------------------------


def test_session_open_flag_opens_the_projections_copy_without_an_archive(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cc_warehouse import notify

    configure(ccw_env, tmp_path, archive=False)
    short = stored_short(ccw_env)

    opened: list[str] = []
    def record_open(path: str) -> None:
        opened.append(path)

    monkeypatch.setattr(notify, "open_page", record_open)
    result = run_cli(["render", "--session", f"s:{short}", "--open"])
    assert result.code == 0, result.err
    assert len(opened) == 1
    revealed = Path(opened[0])
    assert revealed.name == "conversation.html"
    assert revealed.is_file()
    assert "projections" in revealed.parts


def test_session_open_flag_prefers_the_archive_folder(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mirrors `_reveal_target`'s own precedent: the archive folder is the
    deliverable when one is configured, even with personal projections
    retired (`keep_projections = false`)."""
    from cc_warehouse import notify

    archive_root = configure(ccw_env, tmp_path, archive=True)
    assert archive_root is not None
    short = stored_short(ccw_env)

    opened: list[str] = []
    def record_open(path: str) -> None:
        opened.append(path)

    monkeypatch.setattr(notify, "open_page", record_open)
    result = run_cli(["render", "--session", f"s:{short}", "--open"])
    assert result.code == 0, result.err
    assert len(opened) == 1
    revealed = Path(opened[0])
    assert revealed.name == "conversation.html"
    assert revealed.is_file()
    assert archive_root in revealed.parents


def test_session_without_open_never_opens_anything(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cc_warehouse import notify

    configure(ccw_env, tmp_path, archive=False)
    short = stored_short(ccw_env)

    opened: list[str] = []
    def record_open(path: str) -> None:
        opened.append(path)

    monkeypatch.setattr(notify, "open_page", record_open)
    result = run_cli(["render", "--session", f"s:{short}"])
    assert result.code == 0, result.err
    assert opened == []


# --- help / flag surface -------------------------------------------------


def test_open_is_listed_in_render_help(ccw_env: dict[str, str]) -> None:
    result = run_ccw(["render", "-h"], ccw_env)
    assert result.code == 0
    assert "--open" in result.out


def test_unknown_flag_check_still_rejects_typos(ccw_env: dict[str, str], tmp_path: Path) -> None:
    """`--open` joining the known-flags table must not loosen the typo guard
    (2026-08-03 incident) for the rest of the verb."""
    source = tmp_path / "adhoc.jsonl"
    source.write_bytes(basic_session())
    result = run_ccw(["render", str(source), "--opne"], ccw_env)
    assert result.code != 0
    assert "--opne" in result.err
