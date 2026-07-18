"""Notification sinks: webhooks, open-folder, audit log (slice 4).

Every sink is best-effort: a failing sink is logged, never raised (DESIGN section 12).
This slice wires the two sinks the capture hook needs to prove: the O_APPEND JSONL
audit log and the config-driven webhook POSTs. Desktop/voice sinks join in slice 13
(the config slice); nothing here claims a guarantee the oracle suite does not prove (R8).
"""

import json
import os
import subprocess
import sys
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from cc_warehouse.config import Config, WebhookSink

# SPEC section 5: notification POSTs carry a short (~2s) connect budget so a slow sink can
# never turn into an unbounded stall. The POSTs run in the detached notify-only helper,
# off the hook's critical path, so the budget only bounds that helper.
_WEBHOOK_TIMEOUT_S = 2.0


@dataclass(frozen=True)
class NotifyEvent:
    status: str  # ok | error | skipped_unchanged
    session_short: str | None
    project_label: str | None
    message: str
    elapsed_ms: int | None


def append_log(config: Config, record: Mapping[str, object]) -> None:
    """Append one JSON line to logs/capture.jsonl (O_APPEND; sanctioned write exception).

    O_APPEND is one of the three writes sanctioned outside the tmp-then-replace write
    primitive (DESIGN section 13, R2). Each record is a single JSON line; os.write is
    looped over its short-count return so a successful append writes the whole line (a
    partial write never silently drops the tail). The sink is best-effort per DESIGN
    section 12: an unwritable logs/ or a write error (OSError) is swallowed rather than
    raised into capture, at the cost of that one log line."""
    line = (json.dumps(record) + "\n").encode()
    try:
        log_dir = config.root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        fd = os.open(log_dir / "capture.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            offset = 0
            while offset < len(line):
                written = os.write(fd, line[offset:])
                if written <= 0:
                    break
                offset += written
        finally:
            os.close(fd)
    except OSError:
        return


def _post_webhook(sink: WebhookSink, record: Mapping[str, object]) -> None:
    """POST one event to one webhook sink, best-effort: any failure is swallowed so a
    dead or unreachable sink never breaks capture (DESIGN section 12)."""
    try:
        payload = json.dumps(record).encode()
        request = urllib.request.Request(
            sink.url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=_WEBHOOK_TIMEOUT_S) as response:
            response.read()
    except Exception:
        return


def post_webhooks(config: Config, record: Mapping[str, object]) -> None:
    """POST one capture event to every webhook whose events list opts in (DESIGN 12).

    Called only from the detached notify-only helper, never on the hook's critical path.
    The record's status drives the filter, defaulting to ok+error, so skipped_unchanged
    stays silent unless a sink opts in. Each POST is independent and best-effort."""
    status = record.get("status")
    for sink in config.webhooks:
        if status in sink.events:
            _post_webhook(sink, record)


def _spawn_notify_helper(config: Config, record: Mapping[str, object]) -> None:
    """Spawn the detached notify-only helper that POSTs the webhooks (DESIGN section 12).

    The network POSTs are ALWAYS off the hook's critical path: a tiny detached child
    (start_new_session, all stdio to DEVNULL, never waited on) re-loads config from the
    inherited CCW_ROOT and fires the sinks. Skipped when no webhook is configured (the
    only network sink this slice; desktop/voice land in slice 13). Best-effort: a spawn
    failure is swallowed so notification infrastructure can never fail capture."""
    if not config.webhooks:
        return
    try:
        subprocess.Popen(
            [sys.executable, "-m", "cc_warehouse", "notify", "--record", json.dumps(record)],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return


def report(config: Config, event: NotifyEvent) -> None:
    """Record the event: append the durable audit line INLINE, then POST webhooks OFF path.

    The O_APPEND log line is written inline by the hook (it is the fast, durable local
    record and must not be lost). The webhook POSTs are handed to a detached notify-only
    helper so a slow or dead sink never blocks the hook (DESIGN section 12). Both sinks
    are best-effort and neither can raise into the capture flow."""
    record: dict[str, object] = {
        "at": datetime.now(UTC).isoformat(),
        "status": event.status,
        "session": event.session_short,
        "project": event.project_label,
        "message": event.message,
        "elapsed_ms": event.elapsed_ms,
    }
    append_log(config, record)
    _spawn_notify_helper(config, record)


def open_folder(config: Config, path: str) -> None:
    """Best-effort reveal of a folder in the platform file manager (opt-in).

    Fire-and-forget: the reveal never blocks and never raises into capture. Guarded by
    the CCW_OPEN_FOLDER opt-in at the call site (config.open_folder)."""
    _ = config
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    try:
        subprocess.Popen(
            [opener, path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
    except Exception:
        return
