"""Configuration layering (DESIGN section 8), lowest to highest precedence:

built-in defaults -> XDG file -> data-root file -> [project.<id>] sections ->
CCW_* environment variables -> CLI flags. Slice 13.

Slice 4 implements only the subset the capture hook needs (CCW_ROOT, CCW_SKIP_HOOK,
CCW_OPEN_FOLDER env vars and the <root>/config.toml [[notify.webhook]] entries). The
full XDG/data-root/project/flags layering lands in slice 13; extend this, do not
duplicate it.
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
    redact_patterns: tuple[str, ...] = ()
    relocate_roots: tuple[Path, ...] = ()
    inbox: Path | None = None


def _webhooks_from_root(root: Path) -> tuple[WebhookSink, ...]:
    """Parse [[notify.webhook]] entries from <root>/config.toml (stdlib tomllib).

    A missing or unparseable file yields no sinks (best-effort, R5). Each sink's
    `events` defaults to ("ok", "error") so skipped/unchanged captures stay silent
    unless opted in (DESIGN section 12)."""
    config_path = root / "config.toml"
    try:
        with open(config_path, "rb") as fh:
            data = cast(dict[str, object], tomllib.load(fh))
    except (OSError, tomllib.TOMLDecodeError):
        return ()
    notify_raw = data.get("notify")
    if not isinstance(notify_raw, dict):
        return ()
    hooks_raw = cast(dict[str, object], notify_raw).get("webhook")
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


def load_config(
    *,
    xdg_config_home: Path | None = None,
    env: Mapping[str, str] | None = None,
    flags: Mapping[str, str] | None = None,
    project_id: int | None = None,
) -> Config:
    """Resolve the effective Config for one invocation. Honors NO legacy TRANSCRIPT_* name.

    Slice 4 subset: root from CCW_ROOT (required this slice; the XDG/data-root/flags
    layering that supplies a default lands in slice 13), the CCW_SKIP_HOOK and
    CCW_OPEN_FOLDER switches, and the <root>/config.toml webhook sinks. When no env
    mapping is passed the process environment is read (run_cli invokes main in-process)."""
    resolved_env = env if env is not None else os.environ
    root_str = resolved_env.get("CCW_ROOT")
    if root_str is None:
        raise ValueError("CCW_ROOT is required (full config layering lands in slice 13)")
    root = Path(root_str)
    return Config(
        root=root,
        skip_hook=resolved_env.get("CCW_SKIP_HOOK") == "1",
        open_folder=resolved_env.get("CCW_OPEN_FOLDER") == "1",
        webhooks=_webhooks_from_root(root),
    )
