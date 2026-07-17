"""Notification sinks: desktop, voice, webhooks, open-folder, audit log (slice 4).

Every sink is best-effort: a failing sink is logged, never raised (DESIGN section 12).
"""

from dataclasses import dataclass

from cc_warehouse.config import Config


@dataclass(frozen=True)
class NotifyEvent:
    status: str  # ok | error | skipped_unchanged
    session_short: str | None
    project_label: str | None
    message: str
    elapsed_ms: int | None


def report(config: Config, event: NotifyEvent) -> None:
    """Fan the event out to log + desktop + voice + webhooks per config and event status."""
    raise NotImplementedError


def append_log(config: Config, record: dict[str, object]) -> None:
    """Append one JSON line to logs/capture.jsonl (O_APPEND; sanctioned non-atomic write)."""
    raise NotImplementedError


def open_folder(config: Config, path: str) -> None:
    """Best-effort reveal of a folder in the platform file manager (opt-in)."""
    raise NotImplementedError
