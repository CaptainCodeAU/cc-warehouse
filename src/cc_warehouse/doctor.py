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
import re
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import cc_warehouse
from cc_warehouse import parser, status, sweep
from cc_warehouse.config import Config

# How far behind the rest of the corpus a session may fall before it counts as
# missed rather than merely pending.
_OVERDUE_SECONDS = 24 * 60 * 60

# A hook that mentions either console script is ours; the plugin wrapper and a
# settings.json entry both end up as a command string containing one of these.
_OUR_COMMANDS = ("ccw", "cc-warehouse")

# A hook wrapper is a small script. Anything larger is not one, and reading it
# would turn a diagnosis into an unbounded file read.
_WRAPPER_READ_LIMIT = 64 * 1024


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


def install_mode(module_file: Path) -> str:
    """`frozen` or `editable`, from where the code was ACTUALLY loaded.

    `pyproject.toml` can pin the mode, but a pin is a REQUEST: advisory, honoured
    only by the operator's own shell functions, inert on another machine, and
    overridable by an explicit flag. It says what should be installed, never what
    is. This says what is running.

    THE IMPORT PATH RATHER THAN PEP 610, deliberately. `direct_url.json` is the
    standard record of how a distribution was installed, and it is the right
    answer to a different question; it also sits four levels down under a
    version-stamped `.dist-info`, so a lookup can MISS. A miss returns nothing,
    nothing reads as "no editable flag", and that reads as FROZEN, which is the
    dangerous wrong answer delivered silently. I shipped exactly that bug in a
    documented command on 2026-08-03 and it printed empty for an hour without
    anyone noticing. `__file__` cannot miss.
    """
    parts = set(module_file.parts)
    return "frozen" if {"site-packages", "dist-packages"} & parts else "editable"


def _mentions_ccw(command: str, plugin_root: Path | None) -> bool:
    """Whether this hook command runs OUR capture, following one level of wrapper.

    A plugin registers its hook as `python3 ${CLAUDE_PLUGIN_ROOT}/hooks/ccw-hook.py`,
    so the word `ccw` can be absent from the command entirely while the script it
    names calls nothing else. Matching only the command string reported NO HOOK
    REGISTERED while capture worked, and an instrument that cries wolf is ignored,
    which is the same as not having one.

    ONE level, and only files that already exist: this is a diagnosis, not an
    interpreter, and it must stay read-only and bounded (F9).
    """
    if any(name in command for name in _OUR_COMMANDS):
        return True
    for token in command.split():
        if plugin_root is not None:
            token = token.replace("${CLAUDE_PLUGIN_ROOT}", str(plugin_root))
        candidate = Path(token)
        if candidate.suffix not in {".py", ".sh", ".ts", ".js"} or not candidate.is_file():
            continue
        try:
            # R1 (as amended): size here is a RESOURCE BOUND, never identity and
            # never a version ordering. Nothing about this file is decided by how
            # big it is; the comparison only refuses to slurp something that is
            # not a hook wrapper, so a diagnosis cannot be turned into an
            # unbounded read by a path that happens to end in .py. Identity in
            # this function is decided by the CONTENT that follows (F1/F4).
            if candidate.stat().st_size > _WRAPPER_READ_LIMIT:
                continue
            body = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if any(name in body for name in _OUR_COMMANDS):
            return True
    return False


def _hook_commands(home: Path) -> list[tuple[str, Path | None]]:
    """Every hook command Claude Code would run, paired with its plugin root.

    Both places a capture hook can legitimately live: settings files, and an
    installed plugin's hooks.json. Checking only settings.json would report "no
    hook" for a correctly installed PLUGIN, which is exactly how ticket 24
    delivers it. The plugin root travels alongside so `${CLAUDE_PLUGIN_ROOT}` can
    be resolved.
    """
    found: list[tuple[str, Path | None]] = []
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
                            is_plugin = path.parent.name == "hooks"
                            root = path.parent.parent if is_plugin else None
                            found.append((command, root))
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


def _moment(stamp: str | None) -> datetime | None:
    """An ISO payload timestamp as an aware datetime, or None if unusable."""
    if not stamp:
        return None
    try:
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _folder_moment(name: str) -> datetime | None:
    """The session start encoded in an archive folder name, `YYYYMMDD-HHMMSS+ZZZZ_<uuid>`.

    Payload-derived (archive.py builds it from the payload's first timestamp in
    the pinned zone), so it is a legitimate R12 source and costs only the
    directory listing this function already does.
    """
    stamp = name.partition("_")[0]
    match = re.match(r"^(\d{8})-(\d{6})([+-]\d{4})$", stamp)
    if not match:
        return None
    try:
        return datetime.strptime("".join(match.groups()), "%Y%m%d%H%M%S%z")
    except ValueError:
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
    newest_archived: datetime | None = None
    if config.archive_root.is_dir():
        for label_dir in config.archive_root.iterdir():
            if label_dir.is_dir():
                for session_dir in label_dir.iterdir():
                    if session_dir.is_dir():
                        _stamp, _sep, tail = session_dir.name.partition("_")
                        archived.add(tail)
                        moment = _folder_moment(session_dir.name)
                        if moment is not None and (
                            newest_archived is None or moment > newest_archived
                        ):
                            newest_archived = moment
    # ONLY THE UNCAPTURED ARE READ. The first version parsed every transcript in
    # the source tree to find the newest activity: 35 SECONDS on a 14,000-session
    # corpus. A health check nobody wants to wait for does not get run, which is
    # the crying-wolf failure wearing different clothes.
    #
    # THE ANCHOR STAYS IN PAYLOAD TIME. An earlier attempt used the catalog's
    # last capture, which is WALL-CLOCK, and comparing it to session timestamps
    # made January fixtures look overdue on an August machine. Archive folder
    # names carry the session's own start time in the pinned zone, so the newest
    # of them is a payload-derived anchor that costs a directory listing (R12).
    sessions, _subagents = sweep.source_transcripts(walk_root)
    stamps: dict[Path, datetime] = {}
    for path in sessions:
        if path.name.removesuffix(".jsonl") in archived:
            continue
        moment = _moment(_last_activity(path))
        if moment is not None:
            stamps[path] = moment
    if not stamps:
        return 0, None
    anchor = max([*stamps.values(), *filter(None, (newest_archived,))])
    cutoff = anchor - timedelta(seconds=_OVERDUE_SECONDS)
    overdue = [path for path, last in stamps.items() if last < cutoff]
    oldest = min((stamps[p] for p in overdue), default=None)
    return len(overdue), (oldest.isoformat() if oldest else None)


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

    commands = [c for c, root in _hook_commands(where) if _mentions_ccw(c, root)]
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

    module = Path(cc_warehouse.__file__).parent
    mode = install_mode(module)
    checks.append(
        Check(
            "install",
            True,
            f"{mode}: running from {module}"
            + (
                "  <- edits to this checkout ARE the capture path"
                if mode == "editable"
                else ""
            ),
            blocking=False,
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
