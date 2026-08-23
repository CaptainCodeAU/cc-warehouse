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

# The voice sink gets the same short budget, for the same reason and one more:
# the voice server is a LOCAL process that is frequently not running, so "refused
# immediately" and "hung" are both ordinary outcomes and neither may delay
# anything. Like the webhooks, this runs in the detached helper (DESIGN 12 puts
# voice off the critical path), so the budget bounds that child alone.
_VOICE_TIMEOUT_S = 2.0

# Which capture outcomes speak. Ported verbatim from the frozen specimen's
# report() (claude-code-transcripts notify.py:116), which is what actually spoke
# on this machine until 2026-07-24: stored and failed talk, a duplicate does not.
# Kept as a named constant rather than an `in (...)` at the call site because it
# is a product decision, and the next question the principal asked about this
# feature was exactly "what should speak, and when".
SPEAKING_STATUSES = frozenset({"ok", "error"})


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
    failure is swallowed so notification infrastructure can never fail capture.

    SPAWNS FOR VOICE TOO, and the omission would have been invisible: this
    returned early on "no webhooks", so a voice-only setup - which is the only
    sink most people configure - would have been wired end to end and never
    reached, with nothing to show for it but silence."""
    if not config.webhooks and not config.voice_url:
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


def speak(config: Config, message: str) -> None:
    """Say one sentence through the configured voice server, best-effort.

    OPT-IN: with no `[notify] voice_url` this does nothing at all and attempts no
    connection, exactly as the specimen's env-var opt-in did.

    Ported from the frozen specimen (claude-code-transcripts notify.py:52), which
    is the code that actually spoke on this machine until capture broke on
    2026-07-24. `voice_url` and `voice_id` have parsed in this project's config
    since slice 13 and were consumed by NOTHING until now: the module docstring
    promised "desktop/voice sinks join in slice 13", slice 13 landed, and they did
    not. A config key that parses, is tested, and does nothing is the F6 shape
    this project exists to eliminate.

    The transport is urllib rather than the specimen's `curl` subprocess: this
    module already POSTs webhooks that way, and a second HTTP idiom would be a
    second place for the timeout, the headers and the error handling to drift
    (R9). The payload shape is the server's, unchanged: `message`,
    `voice_enabled`, and `voice_id` only when one is configured - a null id is
    not the same as the server's default and must not be sent as one.
    """
    if not config.voice_url:
        return
    payload: dict[str, object] = {"message": message, "voice_enabled": True}
    if config.voice_id:
        payload["voice_id"] = config.voice_id
    try:
        request = urllib.request.Request(
            config.voice_url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=_VOICE_TIMEOUT_S) as response:
            response.read()
    except Exception:
        return


def _open_with_system_default(path: str) -> None:
    """Hand PATH to the platform's default opener: `open` on macOS reveals a
    FOLDER in Finder but opens a FILE with its registered app (a browser, for
    `.html`); `xdg-open` does the same on Linux. One mechanism, two call sites
    below with different names because they are different opt-ins (R9: share
    the primitive, not the copies - see ticket 28.13's C12).

    Fire-and-forget: never blocks and never raises."""
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


def open_folder(config: Config, path: str) -> None:
    """Best-effort reveal of a folder in the platform file manager (opt-in).

    Fire-and-forget: the reveal never blocks and never raises into capture. Guarded by
    the CCW_OPEN_FOLDER opt-in at the call site (config.open_folder)."""
    _ = config
    _open_with_system_default(path)


def open_page(path: str) -> None:
    """Best-effort open of one rendered HTML page in the operator's browser:
    the `--open` flag on `ccw render` (ticket 28.1). `open_folder` reveals the
    FOLDER a capture landed in; nothing handed the operator their actual
    transcript page until this. No config is needed here - the gate is the
    CLI flag itself, decided at the call site, not a persistent setting."""
    _open_with_system_default(path)
