"""Everything more than one ccstats tool needs: paths, the window, the disclaimer.

This module exists because those things were duplicated and had already started
to diverge. Measured 2026-08-21 across the seven scripts:

  * `OUT_DIR` was defined 5 times, `DB` 3 times, `XLSX` 3 times.
  * `COST_NOTE` was defined twice WITH DIFFERENT WORDING, so the CSVs written by
    `collect.py` and the CSV written by `build_workbook.py` shipped two different
    cost disclaimers in the same folder.
  * The `--since` window had TWO independent implementations, one in `facts.py`
    and one in `build_workbook.py`, kept in agreement only by hand.
  * `--since` was parsed in three places and validated in none, so `2026-6-8`
    (a missing leading zero) silently selected zero sessions and then crashed
    inside `facts.compute` with an unpack error.

One definition each, here.

Where output lands is ALSO one definition, resolved once by `resolve_out` rather
than hardcoded per script. Added 2026-08-21 alongside the fix for a real leak:
`collect.py` used to rename the previous `sessions.sqlite` aside to
`sessions.sqlite.prev` forever, doubling a 137 MB file on every machine that ran
it. The replacement (build into a temp file, `os.replace` it onto the target)
needed a place to put that temp file, which is what finally forced OUT_DIR out
of being five different hardcoded constants.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path

# ------------------------------------------------------------------- paths

HOME = Path.home()
ARCHIVE = HOME / "cc-warehouse-archive"
LIVE = HOME / ".claude" / "projects"
CATALOG = HOME / "cc-warehouse-data" / "catalog.sqlite"

# Where generated files land when nothing overrides it. Outside the repo (a
# tracked folder inside the repo is a second publication surface, see
# `tests/test_packaging.py`) and named for what it holds, not for the
# warehouse itself.
DEFAULT_OUT = HOME / ".cc-warehouse" / "stats"

# `tools/ccstats/common.py` -> `tools/ccstats` -> `tools` -> repo root.
REPO_ROOT = Path(__file__).resolve().parents[2]

# Roots ccstats must never be pointed at, however `--out` / `CCSTATS_OUT` is
# set. Not guessed: these are exactly the things CLAUDE.md says are never
# deleted or mutated by anything this project runs, plus this repo's own tree
# (a second `temp/`-style leak waiting to happen).
_FENCED_ROOTS: tuple[tuple[str, Path], ...] = (
    ("~/.claude (never touched by anything, ever)", HOME / ".claude"),
    ("the archive", ARCHIVE),
    ("the warehouse data root", HOME / "cc-warehouse-data"),
    ("this repository", REPO_ROOT),
)


def _fenced_by(path: Path) -> str | None:
    """The label of the fenced root `path` collides with, or None."""
    for label, root in _FENCED_ROOTS:
        root = root.resolve()
        if path == root or root in path.parents:
            return label
    return None


class BadOut(ValueError):
    """An `--out` / `CCSTATS_OUT` destination that must be refused."""


def parse_out(argv: list[str]) -> str:
    """The raw `--out` value from argv, or "" when absent."""
    if "--out" not in argv:
        return ""
    index = argv.index("--out")
    if index + 1 >= len(argv):
        raise BadOut("--out needs a directory, for example --out /tmp/ccstats")
    raw = argv[index + 1].strip()
    if not raw:
        raise BadOut("--out needs a non-empty directory")
    return raw


@dataclass(frozen=True)
class Out:
    """Where one run writes, and every filename derived from that root.

    ONE resolution, built by `resolve_out` and threaded through explicitly.
    `OUT_DIR` used to be a hardcoded constant, so a `--out` flag on one script
    would never have reached the other four; this is the replacement.
    """

    root: Path

    @property
    def db(self) -> Path:
        return self.root / "sessions.sqlite"

    @property
    def xlsx(self) -> Path:
        return self.root / "claude-code-stats.xlsx"

    @property
    def doc(self) -> Path:
        return self.root / "DATA-GUIDE.md"

    @property
    def report(self) -> Path:
        return self.root / "collect-report.json"

    @property
    def cache(self) -> Path:
        return self.root / "scan-cache.sqlite"

    @property
    def sessions_csv(self) -> Path:
        return self.root / "sessions-real.csv"

    @property
    def snapshot(self) -> Path:
        return self.root / "readonly-snapshot.json"

    @property
    def manifest(self) -> Path:
        return self.root / "export-manifest.json"

    def ensure(self) -> None:
        """Create `root` if absent. The only mkdir any ccstats tool performs."""
        self.root.mkdir(parents=True, exist_ok=True)


def resolve_out(argv: list[str]) -> Out:
    """Where this run writes.

    Precedence: `--out` flag, then `CCSTATS_OUT` env, then `DEFAULT_OUT`. State
    the env var rather than repeating `--out` on all five commands: a
    destination said once beats one said five times, the same trap `--since`
    had before `export-manifest.json` (below) fixed it for the window.

    Refuses a destination inside anything this project protects, the same way
    `parse_since` refuses an unpadded date: loudly, before any write happens.
    A `--out` flag would otherwise turn "the only directory this writes to is
    OUT_DIR" into "whatever the caller says".
    """
    raw = parse_out(argv) or os.environ.get("CCSTATS_OUT", "")
    root = Path(raw).expanduser().resolve() if raw else DEFAULT_OUT.resolve()
    reason = _fenced_by(root)
    if reason is not None:
        raise BadOut(f"--out {root} is inside {reason}; refusing to write there")
    return Out(root=root)


# ------------------------------------------------------------- disclaimers

COST_NOTE = (
    "cost_usd is what this usage WOULD have cost at Anthropic API list prices. "
    "It is a usage-weight estimate, NOT a bill: Claude Code subscription usage "
    "is not billed per token."
)


def cost_note(prices_read_on: str = "") -> str:
    """The disclaimer, optionally naming the date the price table was read.

    A function rather than a second constant: the collector wants the date
    appended and the workbook does not, and when those were two separate
    constants they drifted into two different texts shipped side by side.
    """
    if not prices_read_on:
        return COST_NOTE
    return f"{COST_NOTE} Prices read {prices_read_on}."

# A day cannot hold more clock time than this. Used by the collector's own
# invariant check and by the tests.
DAY_SECONDS = 86400.0

# A pause longer than this splits engaged time from idle time. A judgement
# call, not a measurement, and named here so both the code and the docs that
# describe it read the same number.
IDLE_GAP_SECONDS = 300.0


class BadWindow(ValueError):
    """A `--since` value that is not a real ISO date."""


_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _parse_bound(argv: list[str], flag: str) -> str:
    """The validated date value for `flag` from a raw argv, or "" when absent.

    VALIDATES, because `local_date` comparisons are string comparisons: an
    unpadded `2026-6-8` sorts ABOVE every real `2026-06-..` date and therefore
    silently selects nothing (or everything, on the `--until` side). Failing
    loudly here is the whole point. Shared by `parse_since` and `parse_until`
    so the two bounds cannot drift into different validation rules.
    """
    if flag not in argv:
        return ""
    index = argv.index(flag)
    if index + 1 >= len(argv):
        raise BadWindow(f"{flag} needs a date, for example {flag} 2026-06-08")
    raw = argv[index + 1].strip()
    if not _ISO_DATE.match(raw):
        raise BadWindow(
            f"{flag} {raw!r} is not YYYY-MM-DD. Dates are compared as text, so an "
            "unpadded value such as '2026-6-8' silently matches nothing."
        )
    try:
        date.fromisoformat(raw)
    except ValueError as exc:
        raise BadWindow(f"{flag} {raw!r} is not a real date: {exc}") from exc
    return raw


def parse_since(argv: list[str]) -> str:
    """The validated `--since` value from a raw argv, or "" when absent."""
    return _parse_bound(argv, "--since")


def parse_until(argv: list[str]) -> str:
    """The validated `--until` value from a raw argv, or "" when absent.

    Inclusive, like `--since`: `--until 2026-08-21` keeps that day's sessions.
    """
    return _parse_bound(argv, "--until")


@dataclass(frozen=True)
class Window:
    """The `--since`/`--until` filter, in every form the queries need.

    ONE implementation. The session table, the child tables and `overlap_day`
    each need the window expressed differently, and having those forms derived
    from a single `since`/`until` pair is what stops them drifting apart.
    """

    since: str = ""
    until: str = ""

    @property
    def active(self) -> bool:
        return bool(self.since or self.until)

    @property
    def _bounds_sql(self) -> str:
        """`local_date >= ...` / `<= ...`, ANDed together, whichever are set."""
        parts = []
        if self.since:
            parts.append(f"local_date >= '{self.since}'")
        if self.until:
            parts.append(f"local_date <= '{self.until}'")
        return " AND ".join(parts)

    @property
    def session(self) -> str:
        """Predicate for the `session` table, unprefixed."""
        bounds = self._bounds_sql
        return f"is_real = 1 AND {bounds}" if bounds else "is_real = 1"

    @property
    def session_as_s(self) -> str:
        """Predicate for `session s`, table-qualified.

        Needed wherever the query joins `overlap_day`, which also has a
        `local_date`; without the prefix SQLite reports an ambiguous column.
        """
        bounds = self._bounds_sql.replace("local_date", "s.local_date")
        return f"s.is_real = 1 AND {bounds}" if bounds else "s.is_real = 1"

    @property
    def and_clause(self) -> str:
        """` AND local_date >= ... AND local_date <= ...`, for an existing WHERE."""
        bounds = self._bounds_sql
        return f" AND {bounds}" if bounds else ""

    @property
    def child_keys(self) -> str:
        """` AND session_key IN (...)` for turn / tool_call / attribution."""
        if not self.active:
            return ""
        return f" AND session_key IN (SELECT key FROM session WHERE {self.session})"

    @property
    def overlap_where(self) -> str:
        """A full WHERE clause for `overlap_day`, which has no is_real column."""
        bounds = self._bounds_sql
        return f" WHERE {bounds}" if bounds else ""

    def describe(self) -> str:
        if self.since and self.until:
            return f"{self.since} to {self.until}"
        if self.since:
            return f"{self.since} onward"
        if self.until:
            return f"through {self.until}"
        return "full range"


# ------------------------------------------------------------------ sqlite


def open_ro(path: Path) -> sqlite3.Connection:
    """A read-only connection. Used everywhere a tool must not mutate the data."""
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def read_meta(conn: sqlite3.Connection) -> dict[str, str]:
    """The collector's `meta` table as a plain dict."""
    try:
        return dict(conn.execute("SELECT key, value FROM meta").fetchall())
    except sqlite3.Error:
        return {}


# ------------------------------------------------------- the export window
# The window is a property of an EXPORT, not of the collection. It used to be
# retyped as `--since` on three separate commands with nothing binding them, so
# building the workbook windowed and the guide unwindowed produced two documents
# describing different datasets. Recording it once and reading it back removes
# the chance to get that wrong.


def write_manifest(window: Window, generated_at: str, out: Out) -> None:
    out.manifest.write_text(
        json.dumps(
            {"since": window.since, "generated_at": generated_at},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def read_manifest_since(out: Out) -> str:
    """The window the workbook was last built with, or "" if unknown."""
    try:
        data = json.loads(out.manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    value = data.get("since")
    return value if isinstance(value, str) else ""


def resolve_window(argv: list[str], out: Out, *, inherit: bool) -> Window:
    """The window for this run.

    An explicit `--since` always wins. When `inherit` is set and no flag was
    given, the window recorded by the last workbook build is adopted, so the
    guide and the consistency check describe the same dataset the workbook does
    without the operator having to say it three times.
    """
    since = parse_since(argv)
    if not since and inherit:
        since = read_manifest_since(out)
    return Window(since, parse_until(argv))
