"""Contract-derived regression tests for the slice-13 flag surface (2026-07-23).

Not oracle tests: these pin the NEW behaviours the direct build added -- the
Group-A content toggles, the config-bypass switches, and the --EXPOSED gate --
so they cannot silently regress. The locked oracle suites (test_config.py,
test_cli.py) are untouched.
"""

from pathlib import Path

from cc_warehouse import capture, share
from cc_warehouse.config import Config, load_config
from conftest import basic_session, run_ccw


def _xdg(tmp_path: Path, text: str) -> Path:
    cfg = tmp_path / "xdg" / "cc-warehouse"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "config.toml").write_text(text)
    return tmp_path / "xdg"


# --- config layering of the new render toggles -----------------------------


def test_flag_beats_config_value(tmp_path: Path) -> None:
    """A CLI flag overrides a config-file render toggle (precedence: flags win)."""
    xdg = _xdg(tmp_path, "[render]\nsubagents = false\n")
    base = load_config(xdg_config_home=xdg, env={"HOME": str(tmp_path)})
    assert base.render_subagents is False
    with_flag = load_config(
        xdg_config_home=xdg, env={"HOME": str(tmp_path)}, flags={"subagents": "1"}
    )
    assert with_flag.render_subagents is True


def test_no_config_ignores_the_config_file(tmp_path: Path) -> None:
    """--no-config drops both config files back to built-in defaults."""
    xdg = _xdg(tmp_path, "[render]\nattachments = false\n")
    assert load_config(xdg_config_home=xdg, env={"HOME": str(tmp_path)}).render_attachments is False
    bypassed = load_config(xdg_config_home=xdg, env={"HOME": str(tmp_path)}, no_config=True)
    assert bypassed.render_attachments is True


def test_config_path_substitutes_the_normal_files(tmp_path: Path) -> None:
    """--config PATH reads one named file instead of the XDG/data-root pair."""
    xdg = _xdg(tmp_path, "[render]\nextras = false\n")
    alt = tmp_path / "alt.toml"
    alt.write_text("[render]\ncommands = false\n")
    cfg = load_config(xdg_config_home=xdg, env={"HOME": str(tmp_path)}, config_path=alt)
    assert cfg.render_extras is True  # the XDG file was NOT read
    assert cfg.render_commands is False  # the substituted file WAS


def test_per_project_render_override(tmp_path: Path) -> None:
    """[project.<id>.render] overrides the global render toggle by stable id."""
    xdg = _xdg(tmp_path, "[render]\nsubagents = false\n\n[project.7.render]\nsubagents = true\n")
    base = load_config(xdg_config_home=xdg, env={"HOME": str(tmp_path)})
    scoped = load_config(xdg_config_home=xdg, env={"HOME": str(tmp_path)}, project_id=7)
    assert base.render_subagents is False
    assert scoped.render_subagents is True


# --- the --EXPOSED gate ----------------------------------------------------


def _capture(tmp_path: Path) -> tuple[Config, str]:
    root = tmp_path / "wh"
    config = Config(root=root)
    source = tmp_path / "s.jsonl"
    source.write_bytes(basic_session())
    result = capture.capture_transcript(config, source, session_id="s1", cwd="/home/alice/x")
    return config, result.short


def test_exposed_non_tty_aborts_and_publishes_nothing(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """--EXPOSED with a non-TTY stdin (a pipe) is NEVER consent: it aborts and
    writes nothing to --out (the leak switch must never fire unattended)."""
    root = Path(ccw_env["CCW_ROOT"])
    source = tmp_path / "s.jsonl"
    source.write_bytes(basic_session())
    result = capture.capture_transcript(Config(root=root), source, session_id="s1", cwd="/home/a")
    out = tmp_path / "shared"
    args = ["share", f"s:{result.short}", "--out", str(out), "--EXPOSED"]
    res = run_ccw(args, ccw_env, stdin="EXPOSED\n")
    assert res.code == 1
    assert not out.exists()


def test_exposed_commit_keeps_both_sets(tmp_path: Path) -> None:
    """On the [E] path both EXPOSED/ and SCRUBBED/ land in --out; the exposed copy
    is raw and the scrubbed copy carries the redaction token."""
    config, short = _capture(tmp_path)
    comparison = share.prepare_comparison(config, (f"s:{short}",))
    out = tmp_path / "out"
    share.commit_comparison(comparison, out, keep_exposed=True)
    assert (out / "EXPOSED").is_dir()
    assert (out / "SCRUBBED").is_dir()
    assert (out / "redaction-report.json").exists()
    assert not comparison.staging_root.exists()  # staging cleaned


def test_exposed_scrubbed_only_drops_exposed(tmp_path: Path) -> None:
    """On the [S] path only SCRUBBED/ lands; the raw EXPOSED/ never reaches --out."""
    config, short = _capture(tmp_path)
    comparison = share.prepare_comparison(config, (f"s:{short}",))
    out = tmp_path / "out"
    share.commit_comparison(comparison, out, keep_exposed=False)
    assert (out / "SCRUBBED").is_dir()
    assert not (out / "EXPOSED").exists()
