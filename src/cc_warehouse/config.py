"""Configuration layering (DESIGN section 8), lowest to highest precedence:

built-in defaults -> XDG file -> data-root file -> [project.<id>] sections ->
CCW_* environment variables -> CLI flags. Slice 13.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

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


def load_config(
    *,
    xdg_config_home: Path | None = None,
    env: Mapping[str, str] | None = None,
    flags: Mapping[str, str] | None = None,
    project_id: int | None = None,
) -> Config:
    """Resolve the effective Config for one invocation. Honors NO legacy TRANSCRIPT_* name."""
    raise NotImplementedError
