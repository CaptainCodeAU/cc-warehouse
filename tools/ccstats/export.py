#!/usr/bin/env python3
"""Write `stats-facts.json`: the top-line numbers, small enough to read anywhere.

WHY THIS EXISTS. The other two data files in the output root are both too big
for a glance. `sessions.sqlite` needs a query. `dashboard-data.json` is ~1.6 MB
of row-major arrays that only make sense with its own `cols` map. Neither is
something a menu-bar app, a status badge, a shell script or an LLM can read in
one gulp. This one is a few kilobytes of named numbers.

WHY IT IS A SEPARATE PROGRAM, not another write inside `dashboard.py`. Only
because `facts.compute` is aggregate-over-a-window and `build_payload` is
per-session, so they share no query and no shape. That is a weak reason and it
is stated as one.

THE FIRST VERSION OF THIS FILE GAVE A STRONGER REASON AND IT WAS FALSE. It said
`dashboard-data.json` is project-FILTERED and this one is not, so the two cover
different populations. `build_payload` applies NO project predicate: it selects
`FROM session WHERE is_real = 1` plus the date bounds, and `default_unticked_projects`
is a starting state the BROWSER applies to its own checkboxes. Measured on the
real corpus after the claim shipped: 4,350 of the 10,214 embedded sessions belong
to the 65 projects that start unticked. Both files cover the same window and the
same `is_real = 1` rows. That is why `scope` is now a STRUCTURE built by
`common.header`, comparable with `==`, instead of an English sentence no test
could check - the tests that were supposed to guard the claim asserted
`"project" in scope`, which passes on almost any sentence.

The one population difference that IS real: `facts.files_total` counts every
session file in the window (31,036), where the payload's per-session rows are
`is_real = 1` only (10,214).

NOTHING IS RECOMPUTED HERE. Every figure comes from `facts.compute`, which is
already the single source for the numbers quoted in the workbook's prose and in
DATA-GUIDE.md. That function exists because those two documents once carried
different session counts for the same corpus; adding a third hand-rolled query
here would be that same bug with a new face.

    uv run python3 tools/ccstats/export.py [--out DIR] [--since YYYY-MM-DD] [--until YYYY-MM-DD]

Writes one file, `stats-facts.json`, under the resolved output root and nowhere
else. Reads the database read-only. Deletes nothing, ever.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import facts  # noqa: E402
from common import (  # noqa: E402
    DB_NOT_FOUND,
    BadOut,
    BadWindow,
    Window,
    header,
    open_ro,
    parse_since,
    parse_until,
    publish_text,
    read_meta,
    resolve_out,
)

USAGE = (
    "uv run python3 tools/ccstats/export.py "
    "[--out DIR] [--since YYYY-MM-DD] [--until YYYY-MM-DD]"
)

KNOWN = {"--out", "--since", "--until", "-h", "--help"}


def unknown(argv: list[str]) -> list[str]:
    """Flags this command does not accept.

    An unknown argument must fail loudly rather than be ignored: a silently
    dropped `--sicne` produces a whole-corpus card that looks exactly like a
    correct windowed one. Only `-`-prefixed arguments are candidates, because
    the values here are dates and paths.
    """
    return [a for a in argv if a.startswith("-") and a not in KNOWN]


def card(conn: sqlite3.Connection, window: Window) -> dict[str, object]:
    """The whole file: a header saying what this is, then the numbers.

    The header is not decoration. This file is designed to be read by something
    that is not in this repository and has no README to hand, so what the
    numbers cover, and the fact that `cost_usd` is an estimate rather than a
    bill, have to travel WITH them.
    """
    return {
        # `facts.compute` filters to `is_real = 1` (see its module docstring)
        # except for `files_total`, which counts every session file in the
        # window - the one figure here that is drawn from a wider population.
        **header(read_meta(conn), window, rows="sessions with is_real = 1"),
        "facts": facts.compute(conn, window),
    }


def main(argv: list[str]) -> int:
    if "-h" in argv or "--help" in argv:
        print((__doc__ or USAGE).strip())
        return 0

    bad = unknown(argv)
    if bad:
        print(f"error: unknown argument(s): {bad!r}", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 2

    try:
        out = resolve_out(argv)
        # Mirrors `dashboard.py` rather than using `resolve_window`'s manifest
        # inheritance: these two run back to back in `refresh.py` and describing
        # different windows would be worse than describing a wide one.
        window = Window(parse_since(argv), parse_until(argv))
    except (BadOut, BadWindow) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not out.db.exists():
        print(DB_NOT_FOUND.format(out=out.root), file=sys.stderr)
        return 1

    conn = open_ro(out.db)
    try:
        payload = card(conn, window)
    finally:
        conn.close()

    out.ensure()
    text = json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"
    publish_text(text, out.facts_json)
    print(f"{out.facts_json}  ({len(text):,} bytes, {window.describe()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
