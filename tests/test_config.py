"""Oracle tests: configuration layering (slice 13).

Contract: DESIGN section 8. Precedence, lowest to highest: built-in defaults
-> XDG file -> data-root file -> [project.<registry-id>] sections -> CCW_*
env vars -> CLI flags. The CCW_ prefix is locked; NO legacy TRANSCRIPT_* name
is honored. Frozen here (Phase 2, with the config module): the TOML key map
used below (top-level `root`; [notify], [render], [share], [relocate],
[import] tables; [[notify.webhook]] entries; [project.<id>.<table>] overrides).
"""

from pathlib import Path

from cc_warehouse.config import load_config


def write_xdg(tmp_path: Path, text: str) -> Path:
    xdg = tmp_path / "xdg"
    cfg_dir = xdg / "cc-warehouse"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.toml").write_text(text)
    return xdg


def test_default_root_is_under_home() -> None:
    cfg = load_config(env={"HOME": "/home/alice"})
    assert cfg.root == Path("/home/alice/cc-warehouse-data")
    assert cfg.open_folder is False
    assert cfg.webhooks == ()


def test_xdg_file_sets_root_and_notify_keys(tmp_path: Path) -> None:
    xdg = write_xdg(
        tmp_path,
        f'root = "{tmp_path / "data"}"\n\n[notify]\nvoice_url = "http://localhost:8888"\n',
    )
    cfg = load_config(xdg_config_home=xdg, env={"HOME": "/home/alice"})
    assert cfg.root == tmp_path / "data"
    assert cfg.voice_url == "http://localhost:8888"


def test_data_root_file_overrides_xdg_key_by_key(tmp_path: Path) -> None:
    """DESIGN section 8: the data-root overlay wins key by key; untouched keys
    keep their XDG values."""
    data_root = tmp_path / "data"
    xdg = write_xdg(
        tmp_path,
        f'root = "{data_root}"\n\n[notify]\nvoice_url = "xdg-voice"\nvoice_id = "xdg-id"\n',
    )
    data_root.mkdir()
    (data_root / "config.toml").write_text('[notify]\nvoice_url = "data-voice"\n')
    cfg = load_config(xdg_config_home=xdg, env={"HOME": "/home/alice"})
    assert cfg.voice_url == "data-voice"
    assert cfg.voice_id == "xdg-id"
    assert cfg.root == data_root


def test_project_section_overrides_by_registry_id(tmp_path: Path) -> None:
    """DESIGN section 8: per-project sections are keyed by stable registry ID,
    never by label."""
    xdg = write_xdg(
        tmp_path,
        "[render]\nbreadcrumbs = false\n\n[project.3.render]\nbreadcrumbs = true\n",
    )
    base = load_config(xdg_config_home=xdg, env={"HOME": "/home/alice"})
    assert base.render_breadcrumbs is False
    scoped = load_config(xdg_config_home=xdg, env={"HOME": "/home/alice"}, project_id=3)
    assert scoped.render_breadcrumbs is True


def test_env_overrides_files(tmp_path: Path) -> None:
    xdg = write_xdg(tmp_path, f'root = "{tmp_path / "file-root"}"\n')
    cfg = load_config(
        xdg_config_home=xdg,
        env={
            "HOME": "/home/alice",
            "CCW_ROOT": str(tmp_path / "env-root"),
            "CCW_VOICE_URL": "http://env-voice",
            "CCW_OPEN_FOLDER": "1",
        },
    )
    assert cfg.root == tmp_path / "env-root"
    assert cfg.voice_url == "http://env-voice"
    assert cfg.open_folder is True


def test_flags_override_env(tmp_path: Path) -> None:
    cfg = load_config(
        env={"HOME": "/home/alice", "CCW_ROOT": str(tmp_path / "env-root")},
        flags={"root": str(tmp_path / "flag-root")},
    )
    assert cfg.root == tmp_path / "flag-root"


def test_skip_hook_env() -> None:
    cfg = load_config(env={"HOME": "/home/alice", "CCW_SKIP_HOOK": "1"})
    assert cfg.skip_hook is True


def test_legacy_transcript_env_names_are_ignored() -> None:
    """DESIGN section 8 (locked): the code honors NO legacy TRANSCRIPT_* name."""
    cfg = load_config(
        env={
            "HOME": "/home/alice",
            "TRANSCRIPT_VOICE_URL": "http://legacy",
            "TRANSCRIPT_EXPORT_DIR": "/legacy/dir",
            "TRANSCRIPT_OPEN_FOLDER": "1",
        }
    )
    assert cfg.voice_url is None
    assert cfg.open_folder is False
    assert cfg.root == Path("/home/alice/cc-warehouse-data")


def test_webhook_entries_default_to_ok_and_error_events(tmp_path: Path) -> None:
    """DESIGN section 12: webhook events default ok+error, skipped silent."""
    xdg = write_xdg(
        tmp_path,
        '[[notify.webhook]]\nname = "tg"\nurl = "https://example.invalid/tg"\n',
    )
    cfg = load_config(xdg_config_home=xdg, env={"HOME": "/home/alice"})
    assert len(cfg.webhooks) == 1
    hook = cfg.webhooks[0]
    assert hook.name == "tg"
    assert hook.events == ("ok", "error")
