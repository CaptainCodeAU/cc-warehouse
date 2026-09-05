#!/usr/bin/env python3
"""Write `stats-facts.json`: the top-line numbers, small enough to read anywhere.

WHY THIS EXISTS. The other two data files in the output root are both too big
for a glance. `sessions.sqlite` needs a query. `dashboard-data.json` is ~1.6 MB
of row-major arrays that only make sense with its own `cols` map. Neither is
something a menu-bar app, a status badge, a shell script or an LLM can read in
one gulp. This one is a few kilobytes of named numbers.

WHY IT IS A SEPARATE PROGRAM, not another write inside `dashboard.py`. Its
SCOPE is different, and the difference is easy to miss and expensive to get
wrong. `dashboard-data.json` is project-FILTERED: it holds exactly the sessions
the page's project tick list leaves ticked. The numbers here honour the date
window but apply NO project filter, so they describe the same population as
`collect-report.json`. Two scopes in one file would invite a consumer to average
across them and be quietly wrong, so each file states its scope inline and they
stay apart.

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
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import facts  # noqa: E402
from common import (  # noqa: E402
    BadOut,
    BadWindow,
    Window,
    cost_note,
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

DB_NOT_FOUND = (
    "no sessions.sqlite in {out}. Run collect.py first:\n"
    "  uv run python3 tools/ccstats/collect.py"
)

SCOPE = (
    "date window only: these numbers are NOT filtered by the dashboard's project "
    "tick list, so they cover the same population as collect-report.json. "
    "dashboard-data.json IS project-filtered; do not mix the two."
)

# Flags that take a value, and so are followed by an argument that is not itself
# an unknown flag. Listed rather than inferred: an unknown argument must fail
# loudly (a silently ignored `--sicne` would produce a whole-corpus card that
# looks exactly like a correct windowed one).
VALUED = {"--out", "--since", "--until"}


def known(argv: list[str]) -> list[str]:
    """Arguments that are neither a known flag nor a known flag's value."""
    unknown: list[str] = []
    skip = False
    for arg in argv:
        if skip:
            skip = False
            continue
        if arg in VALUED:
            skip = True
            continue
        if arg in {"-h", "--help"}:
            continue
        unknown.append(arg)
    return unknown


def card(conn, window: Window) -> dict[str, object]:
    """The whole file: a header saying what this is, then the numbers.

    The header is not decoration. This file is designed to be read by something
    that is not in this repository and has no README to hand, so what the
    numbers cover, and the fact that `cost_usd` is an estimate rather than a
    bill, have to travel WITH them.
    """
    meta = read_meta(conn)
    return {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window_desc": window.describe(),
        "timezone": meta.get("local_timezone", "unknown"),
        "scope": SCOPE,
        "cost_note": cost_note(meta.get("prices_read_on", "")),
        "prices_read_on": meta.get("prices_read_on", ""),
        "facts": facts.compute(conn, window),
    }


def main(argv: list[str]) -> int:
    if "-h" in argv or "--help" in argv:
        print((__doc__ or USAGE).strip())
        return 0

    unknown = known(argv)
    if unknown:
        print(f"error: unknown argument(s): {unknown!r}", file=sys.stderr)
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
    publish_text(text, out.facts_json, prefix="stats-facts.", suffix=".json.building")
    print(f"{out.facts_json}  ({len(text):,} bytes, {window.describe()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
