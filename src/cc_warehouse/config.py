"""Configuration layering (DESIGN section 8), lowest to highest precedence:

built-in defaults -> XDG file -> data-root file -> [project.<id>] sections ->
CCW_* environment variables -> CLI flags. Slice 13.

The TOML key map is frozen (Phase 2, expanded 2026-07-23 with the principal for the
render toggles): top-level `root`; [notify] voice_url voice_id open_folder;
[render] breadcrumbs reminders_full reminders_compact subagents attachments commands
extras tool_output; [share] redact_patterns; [relocate] roots; [import] inbox;
[[notify.webhook]] name url events template; [project.<id>.<table>] overrides.
"""

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

ENV_PREFIX = "CCW_"
ENV_VARS = (
    "CCW_ROOT",
    "CCW_SKIP_HOOK",
    "CCW_VOICE_URL",
    "CCW_VOICE_ID",
    "CCW_OPEN_FOLDER",
    "CCW_WEBHOOKS",
)

_DEFAULT_ROOT_NAME = "cc-warehouse-data"


@dataclass(frozen=True)
class WebhookSink:
    name: str
    url: str
    events: tuple[str, ...] = ("ok", "error")
    template: str | None = None


@dataclass(frozen=True)
class Config:
    root: Path
    skip_hook: bool = False
    voice_url: str | None = None
    voice_id: str | None = None
    open_folder: bool = False
    webhooks: tuple[WebhookSink, ...] = ()
    render_breadcrumbs: bool = False
    render_reminders_full: str = "collapse"
    render_reminders_compact: str = "strip"
    # Group A render toggles (frozen-map expansion 2026-07-23). All default ON.
    render_subagents: bool = True
    render_attachments: bool = True
    render_commands: bool = True
    render_extras: bool = True
    render_tool_output: bool = True
    redact_patterns: tuple[str, ...] = ()
    relocate_roots: tuple[Path, ...] = ()
    inbox: Path | None = None


def _read_toml(path: Path) -> dict[str, object]:
    """Parse one config.toml (stdlib tomllib). A missing or unparseable file
    yields an empty mapping (best-effort, R5), never raising into the loader."""
    try:
        with open(path, "rb") as fh:
            return cast(dict[str, object], tomllib.load(fh))
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _table(data: Mapping[str, object], name: str) -> dict[str, object]:
    value = data.get(name)
    return cast(dict[str, object], value) if isinstance(value, dict) else {}


def _merge(base: Mapping[str, object], overlay: Mapping[str, object]) -> dict[str, object]:
    """Overlay one config mapping onto another KEY BY KEY (DESIGN section 8): a
    table present in both merges field by field, so the data-root file changes
    only the keys it names and leaves the rest of the XDG table intact."""
    out: dict[str, object] = dict(base)
    for key, value in overlay.items():
        current = out.get(key)
        if isinstance(value, dict) and isinstance(current, dict):
            merged = dict(cast(dict[str, object], current))
            merged.update(cast(dict[str, object], value))
            out[key] = merged
        else:
            out[key] = value
    return out


def _apply_project(data: dict[str, object], project_id: int | None) -> dict[str, object]:
    """Overlay the [project.<id>.<table>] sections onto the top-level tables.
    Keyed by the STABLE registry id, never a label (R3)."""
    if project_id is None:
        return data
    projects = _table(data, "project")
    scoped = projects.get(str(project_id))
    if not isinstance(scoped, dict):
        return data
    out = dict(data)
    for table_name, table_val in cast(dict[str, object], scoped).items():
        if isinstance(table_val, dict):
            out[table_name] = _merge(_table(out, table_name), cast(dict[str, object], table_val))
    return out


def _webhooks_from_config(data: Mapping[str, object]) -> tuple[WebhookSink, ...]:
    """Parse [[notify.webhook]] entries from the merged config (DESIGN section 12).
    Each sink's `events` defaults to ("ok", "error")."""
    hooks_raw = _table(data, "notify").get("webhook")
    if not isinstance(hooks_raw, list):
        return ()
    sinks: list[WebhookSink] = []
    for entry_raw in cast(list[object], hooks_raw):
        if not isinstance(entry_raw, dict):
            continue
        entry = cast(dict[str, object], entry_raw)
        name = entry.get("name")
        url = entry.get("url")
        if not isinstance(name, str) or not isinstance(url, str):
            continue
        events_field = entry.get("events")
        if isinstance(events_field, list):
            events = tuple(str(item) for item in cast(list[object], events_field))
        else:
            events = ("ok", "error")
        template_field = entry.get("template")
        template = template_field if isinstance(template_field, str) else None
        sinks.append(WebhookSink(name=name, url=url, events=events, template=template))
    return tuple(sinks)


def _bool(value: object, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _str_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _flag_bool(flags: Mapping[str, str], key: str, current: bool) -> bool:
    """A flag value ('1'/'true'/'0'/'false') overriding the config-derived value."""
    raw = flags.get(key)
    if raw is None:
        return current
    return raw.lower() in ("1", "true", "yes", "on")


def load_config(
    *,
    xdg_config_home: Path | None = None,
    env: Mapping[str, str] | None = None,
    flags: Mapping[str, str] | None = None,
    project_id: int | None = None,
    no_config: bool = False,
    config_path: Path | None = None,
) -> Config:
    """Resolve the effective Config for one invocation (DESIGN section 8).

    Precedence, lowest to highest: built-in defaults -> XDG file -> data-root
    file -> [project.<id>] -> CCW_* env -> CLI flags. Honors NO legacy
    TRANSCRIPT_* name. `no_config` ignores both config files (defaults + env +
    flags only); `config_path` reads one named file INSTEAD of the two normal
    ones. When no env mapping is passed the process environment is read.
    """
    resolved_env = env if env is not None else os.environ
    flag_map = flags or {}
    home = resolved_env.get("HOME") or str(Path.home())

    # --- config files (skipped by --no-config; replaced by --config PATH) ---
    if no_config:
        file_data: dict[str, object] = {}
    elif config_path is not None:
        file_data = _read_toml(config_path)
    else:
        xdg_dir = xdg_config_home or Path(
            resolved_env.get("XDG_CONFIG_HOME") or (Path(home) / ".config")
        )
        xdg_data = _read_toml(xdg_dir / "cc-warehouse" / "config.toml")
        # root must be known before the data-root file (it lives inside root),
        # so resolve it from xdg/env/flags first, then read <root>/config.toml.
        root_probe = _resolve_root(home, xdg_data, resolved_env, flag_map)
        data_root_data = _read_toml(root_probe / "config.toml")
        file_data = _merge(xdg_data, data_root_data)

    merged = _apply_project(file_data, project_id)
    root = _resolve_root(home, merged, resolved_env, flag_map)

    notify = _table(merged, "notify")
    render = _table(merged, "render")
    share = _table(merged, "share")
    relocate = _table(merged, "relocate")
    imp = _table(merged, "import")

    voice_url = _str_or_none(notify.get("voice_url"))
    voice_id = _str_or_none(notify.get("voice_id"))
    open_folder = _bool(notify.get("open_folder"), False)
    if "CCW_VOICE_URL" in resolved_env:
        voice_url = _str_or_none(resolved_env["CCW_VOICE_URL"])
    if "CCW_VOICE_ID" in resolved_env:
        voice_id = _str_or_none(resolved_env["CCW_VOICE_ID"])
    if "CCW_OPEN_FOLDER" in resolved_env:
        open_folder = resolved_env["CCW_OPEN_FOLDER"] == "1"
    voice_url = _str_or_none(flag_map.get("voice_url")) or voice_url

    redact_patterns = tuple(
        str(p) for p in cast(list[object], share.get("redact_patterns", []))
        if isinstance(share.get("redact_patterns"), list)
    )
    relocate_roots = tuple(
        Path(str(p)) for p in cast(list[object], relocate.get("roots", []))
        if isinstance(relocate.get("roots"), list)
    )
    inbox_raw = _str_or_none(imp.get("inbox"))

    return Config(
        root=root,
        skip_hook=resolved_env.get("CCW_SKIP_HOOK") == "1",
        voice_url=voice_url,
        voice_id=voice_id,
        open_folder=open_folder,
        webhooks=_webhooks_from_config(merged),
        render_breadcrumbs=_flag_bool(
            flag_map, "breadcrumbs", _bool(render.get("breadcrumbs"), False)
        ),
        render_reminders_full=_str_or_none(flag_map.get("reminders"))
        or _str_or_none(render.get("reminders_full"))
        or "collapse",
        render_reminders_compact=_str_or_none(render.get("reminders_compact")) or "strip",
        render_subagents=_flag_bool(
            flag_map, "subagents", _bool(render.get("subagents"), True)
        ),
        render_attachments=_flag_bool(
            flag_map, "attachments", _bool(render.get("attachments"), True)
        ),
        render_commands=_flag_bool(
            flag_map, "commands", _bool(render.get("commands"), True)
        ),
        render_extras=_flag_bool(flag_map, "extras", _bool(render.get("extras"), True)),
        render_tool_output=_flag_bool(
            flag_map, "tool_output", _bool(render.get("tool_output"), True)
        ),
        redact_patterns=redact_patterns,
        relocate_roots=relocate_roots,
        inbox=Path(inbox_raw) if inbox_raw is not None else None,
    )


def _resolve_root(
    home: str,
    file_data: Mapping[str, object],
    env: Mapping[str, str],
    flags: Mapping[str, str],
) -> Path:
    """Root precedence: default ($HOME/cc-warehouse-data) < file `root` < CCW_ROOT
    env < flags `root`. The data-root config file cannot set root (it lives inside
    root), so only the XDG-tier `root` participates here."""
    root = Path(home) / _DEFAULT_ROOT_NAME
    file_root = _str_or_none(file_data.get("root"))
    if file_root is not None:
        root = Path(file_root)
    if "CCW_ROOT" in env:
        env_root = env["CCW_ROOT"]
        if env_root:
            root = Path(env_root)
    flag_root = _str_or_none(flags.get("root"))
    if flag_root is not None:
        root = Path(flag_root)
    return root
