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


# --- the v1.1 per-variant matrix keys (slice 14, DESIGN 15 entry 2026-08-01) ---
# Frozen key map addition: five FLAT `[render]` keys, all default OFF. Shared rule
# (a) is what these pin -- flat keys layering key-by-key under the existing
# one-level merge, never nested sub-tables.

MATRIX_KEYS = (
    "subagents_compact",
    "attachments_compact",
    "commands_compact",
    "extras_compact",
    "tool_output_compact",
)


def test_matrix_compact_keys_default_off() -> None:
    """DESIGN section 8 defaults sentence: the full-variant render toggles default
    ON, the `_compact` toggles default OFF. An empty config changes nothing."""
    cfg = load_config(env={"HOME": "/home/alice"}, no_config=True)
    for key in MATRIX_KEYS:
        assert getattr(cfg, f"render_{key}") is False, key


def test_matrix_compact_keys_are_read_from_the_render_table(tmp_path: Path) -> None:
    """Each of the five flat `[render]` keys reaches Config on its own."""
    for key in MATRIX_KEYS:
        xdg = write_xdg(tmp_path, f"[render]\n{key} = true\n")
        cfg = load_config(xdg_config_home=xdg, env={"HOME": "/home/alice"})
        assert getattr(cfg, f"render_{key}") is True, key
        others = [k for k in MATRIX_KEYS if k != key]
        for other in others:
            assert getattr(cfg, f"render_{other}") is False, f"{key} leaked into {other}"


def test_matrix_compact_key_layers_key_by_key(tmp_path: Path) -> None:
    """Shared rule (a): flat keys layer key by key, so the data-root file changes
    only the key it names. A nested sub-table would replace [render] wholesale."""
    data_root = tmp_path / "data"
    xdg = write_xdg(
        tmp_path,
        f'root = "{data_root}"\n\n[render]\n'
        "subagents_compact = true\nattachments_compact = true\n",
    )
    data_root.mkdir()
    (data_root / "config.toml").write_text("[render]\nsubagents_compact = false\n")
    cfg = load_config(xdg_config_home=xdg, env={"HOME": "/home/alice"})
    assert cfg.render_subagents_compact is False
    assert cfg.render_attachments_compact is True, "the untouched key lost its XDG value"


def test_matrix_compact_key_honors_per_project_sections(tmp_path: Path) -> None:
    """DESIGN section 8: a per-project override is keyed by stable registry ID and
    reaches the new keys like any other."""
    xdg = write_xdg(
        tmp_path,
        "[render]\nextras_compact = false\n\n[project.4.render]\nextras_compact = true\n",
    )
    base = load_config(xdg_config_home=xdg, env={"HOME": "/home/alice"})
    scoped = load_config(xdg_config_home=xdg, env={"HOME": "/home/alice"}, project_id=4)
    assert base.render_extras_compact is False
    assert scoped.render_extras_compact is True


def test_matrix_flag_tier_beats_the_config_file(tmp_path: Path) -> None:
    """DESIGN section 8 precedence: CLI flags are the highest tier."""
    xdg = write_xdg(tmp_path, "[render]\ncommands_compact = true\n")
    assert load_config(
        xdg_config_home=xdg, env={"HOME": "/home/alice"}
    ).render_commands_compact is True
    overridden = load_config(
        xdg_config_home=xdg,
        env={"HOME": "/home/alice"},
        flags={"commands_compact": "0"},
    )
    assert overridden.render_commands_compact is False


def test_reminders_compact_gains_a_flag_tier(tmp_path: Path) -> None:
    """`reminders_compact` predates the matrix but had no flag. Full CLI parity
    (the principal's call over a config-only cut) gives it one."""
    xdg = write_xdg(tmp_path, "[render]\nreminders_compact = \"collapse\"\n")
    base = load_config(xdg_config_home=xdg, env={"HOME": "/home/alice"})
    assert base.render_reminders_compact == "collapse"
    overridden = load_config(
        xdg_config_home=xdg,
        env={"HOME": "/home/alice"},
        flags={"reminders_compact": "show"},
    )
    assert overridden.render_reminders_compact == "show"


def test_unsuffixed_keys_keep_their_v1_meaning(tmp_path: Path) -> None:
    """Shared rule (b): an unsuffixed key is the FULL variant's toggle and setting
    it must not move its `_compact` sibling."""
    xdg = write_xdg(tmp_path, "[render]\nsubagents = false\n")
    cfg = load_config(xdg_config_home=xdg, env={"HOME": "/home/alice"})
    assert cfg.render_subagents is False
    assert cfg.render_subagents_compact is False, "an unsuffixed key reached compact"
