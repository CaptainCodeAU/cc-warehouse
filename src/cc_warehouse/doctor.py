"""ccw doctor: is capture actually working, and if not, since when.

Ticket 23, slice 23c. DESIGN section 7 (`ccw doctor` row) and section 15 entry
"`ccw doctor`, AND WHY IT IS A VERB".

THE FAILURE THIS EXISTS FOR. Capture stopped on 2026-07-24 and nobody found out
for ten days. Every link an operator would check looked healthy: the plugin was
enabled, its cached files matched what its repo held, and the CLI it delegated to
existed and still exposed the verb being called. The break was one layer below
all of that, and the wrapper discarded the child's non-zero exit.

Nothing in the product could have said so. `ccw status` reads the catalog, so a
hook that never runs writes no row and raises no error; silence and idleness are
the same shape. The question "is the machinery working" had no owner.

READ-ONLY BY CONSTRUCTION, which is not a nicety here: doctor runs when things
are broken, so it must not materialise a warehouse that was never there. It
opens the catalog read-only and never through catalog.open_catalog, whose
docstring says "creating if needed".
"""

import json
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from cc_warehouse import parser, status, sweep
from cc_warehouse.config import Config

# How far behind the rest of the corpus a session may fall before it counts as
# missed rather than merely pending.
_OVERDUE_SECONDS = 24 * 60 * 60

# A hook that mentions either console script is ours; the plugin wrapper and a
# settings.json entry both end up as a command string containing one of these.
_OUR_COMMANDS = ("ccw", "cc-warehouse")


@dataclass(frozen=True)
class Check:
    """One diagnosis. `blocking` marks the ones that decide the exit code, so a
    figure can be reported without being an alarm."""

    name: str
    ok: bool
    detail: str
    blocking: bool = True


@dataclass(frozen=True)
class Report:
    checks: tuple[Check, ...]

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks if check.blocking)


def _hook_commands(home: Path) -> list[str]:
    """Every hook command string Claude Code would run, from both the places one
    can legitimately live: settings files, and an installed plugin's hooks.json.

    Checking only settings.json would report "no hook" for a correctly installed
    PLUGIN, which is exactly how ticket 24 delivers it.
    """
    found: list[str] = []
    candidates = [home / ".claude" / "settings.json", home / ".claude" / "settings.local.json"]
    cache = home / ".claude" / "plugins" / "cache"
    if cache.is_dir():
        candidates.extend(sorted(cache.glob("*/*/*/hooks/hooks.json")))
    for path in candidates:
        if not path.is_file():
            continue
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(loaded, dict):
            continue
        hooks = cast(dict[str, object], loaded).get("hooks")
        if not isinstance(hooks, dict):
            continue
        for groups in cast(dict[str, object], hooks).values():
            if not isinstance(groups, list):
                continue
            for group in cast(list[object], groups):
                if not isinstance(group, dict):
                    continue
                inner = cast(dict[str, object], group).get("hooks")
                if not isinstance(inner, list):
                    continue
                for hook in cast(list[object], inner):
                    if isinstance(hook, dict):
                        command = cast(dict[str, object], hook).get("command")
                        if isinstance(command, str):
                            found.append(command)
    return found


def _last_capture(root: Path) -> str | None:
    """When capture last ran, from the catalog, WITHOUT creating it.

    None means it has never run: no catalog, or no capture_event rows. That
    distinction is the whole point of this check. On 2026-07-24 the failure
    looked like "fired, but not recently" and was in fact "never fired here".
    """
    path = root / "catalog.sqlite"
    if not path.is_file():
        return None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        row = cast(
            tuple[str | None] | None,
            conn.execute("SELECT MAX(at) FROM capture_event").fetchone(),
        )
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    return row[0] if row and row[0] else None


def _last_activity(path: Path) -> str | None:
    """The payload's own final timestamp (R12), never a file mtime."""
    try:
        return parser.parse_session(path.read_bytes()).last_ts
    except (OSError, ValueError):
        return None


def _overdue(config: Config, walk_root: Path) -> tuple[int, str | None]:
    """Uncaptured sessions that the rest of the corpus has moved on without.

    RELATIVE TO THE CORPUS, not to the wall clock, and that is a deliberate
    choice rather than a convenience. A session still being written is not
    missed, so "older than N hours" would flag the session doctor is being run
    from. Comparing against the NEWEST activity anywhere in the source tree asks
    the question that actually matters: have other sessions ended since this one
    while it stayed uncaptured? It is also deterministic, so it can be tested
    without freezing a clock.
    """
    if config.archive_root is None:
        return 0, None
    archived: set[str] = set()
    if config.archive_root.is_dir():
        for label_dir in config.archive_root.iterdir():
            if label_dir.is_dir():
                for session_dir in label_dir.iterdir():
                    if session_dir.is_dir():
                        _stamp, _sep, tail = session_dir.name.partition("_")
                        archived.add(tail)
    sessions, _subagents = sweep.source_transcripts(walk_root)
    stamps: dict[Path, str] = {}
    for path in sessions:
        last = _last_activity(path)
        if last is not None:
            stamps[path] = last
    if not stamps:
        return 0, None
    newest = max(stamps.values())
    cutoff = _shift(newest, -_OVERDUE_SECONDS)
    overdue = [
        path
        for path, last in stamps.items()
        if last < cutoff and path.name.removesuffix(".jsonl") not in archived
    ]
    oldest = min((stamps[p] for p in overdue), default=None)
    return len(overdue), oldest


def _shift(stamp: str, seconds: int) -> str:
    """`stamp` moved by `seconds`, as an ISO string comparable to other stamps."""
    from datetime import datetime, timedelta

    try:
        moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return stamp
    return (moment + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def diagnose(config: Config, home: Path | None = None, source: Path | None = None) -> Report:
    """Every check, in the order an operator would ask them."""
    where = home if home is not None else Path.home()
    walk_root = source if source is not None else where / ".claude" / "projects"
    checks: list[Check] = []

    resolved = shutil.which("ccw")
    checks.append(
        Check(
            "reachable",
            resolved is not None,
            f"ccw resolves to {resolved}" if resolved else "ccw is NOT on PATH",
            blocking=False,
        )
    )

    commands = [c for c in _hook_commands(where) if any(n in c for n in _OUR_COMMANDS)]
    checks.append(
        Check(
            "hook",
            bool(commands),
            f"SessionEnd capture hook found: {commands[0]}"
            if commands
            else "NO capture hook is registered; sessions are not being captured",
        )
    )

    last = _last_capture(config.root)
    checks.append(
        Check(
            "fired",
            last is not None,
            f"last capture {last}" if last else "capture has NEVER fired on this machine",
        )
    )

    gap = status.uncaptured_gap(config, walk_root)
    checks.append(Check("uncaptured", True, status.gap_line(gap), blocking=False))

    count, oldest = _overdue(config, walk_root)
    checks.append(
        Check(
            "overdue",
            count == 0,
            "nothing overdue"
            if count == 0
            else f"{count} session(s) OVERDUE, oldest last active {oldest}",
        )
    )

    checks.append(
        Check(
            "config",
            True,
            f"root={config.root} archive_root={config.archive_root}"
            f" zone={config.archive_timezone} keep_objects={config.keep_objects}"
            f" keep_projections={config.keep_projections}",
            blocking=False,
        )
    )
    return Report(tuple(checks))


def report_text(report: Report) -> str:
    lines = [
        f"  {'ok ' if check.ok else 'FAIL' if check.blocking else '   '} "
        f"{check.name:<11} {check.detail}"
        for check in report.checks
    ]
    lines.append("")
    lines.append("doctor: capture is working" if report.ok else "doctor: capture is NOT working")
    return "\n".join(lines)
