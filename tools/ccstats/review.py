#!/usr/bin/env python3
"""Which projects have been ruled on, and which have never been looked at.

WHY THIS EXISTS. `dashboard-defaults.json` carries two lists of substring
patterns: `keep`, the projects that belong in the numbers, and `exclude`, the
ones that do not. Deciding which is which is an ongoing judgement - new folders
appear every week, most of them worktrees and scratch directories - so a project
matching NEITHER list has never been judged. This prints the three buckets so
that backlog is a thing you can see rather than a thing you assume is empty.

`keep` IS A LEDGER, NOT A FILTER. Nothing reads it to decide what counts; that
is `exclude`'s job alone. This is deliberate and it is the whole reason the list
is not stored under `include`, which `dashboard.py` treats as an ALLOWLIST: the
moment `include` has anything in it, every project not named is switched off.
An unreviewed project would then be silently missing from a total the operator
uses to track effort, where under `exclude`-only it appears in the total AND in
this report, which is impossible to miss.

    uv run python3 tools/ccstats/review.py              # the full three buckets
    uv run python3 tools/ccstats/review.py --new        # only what is unreviewed
    uv run python3 tools/ccstats/review.py --new --record   # ...and acknowledge it

`--new` IS READ-ONLY, AND THAT SEPARATION IS THE POINT. `refresh.py` runs it on
the daily schedule and puts anything it names into the completion dialog. That
dialog closes itself after 300 seconds and the job's log is empty on a healthy
run, so an unattended run is very likely to go unseen. A check that RECORDED
what it reported would let the run nobody watched consume the warning, and it
would never appear again. Acknowledging is therefore only ever an explicit human
act, and the better fix is not to acknowledge at all: put the project in `keep`
or `exclude` and it leaves this report by itself.

Reads the database read-only. Writes one file, `review-baseline.json`, and only
when `--record` is given. Deletes nothing, ever.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from common import (  # noqa: E402
    DB_NOT_FOUND,
    BadOut,
    Window,
    matched_by,
    open_ro,
    publish_text,
    resolve_out,
    unknown_flags,
)
from dashboard import (  # noqa: E402
    load_default_since,
    pattern_list,
    read_defaults,
    resolve_unticked,
)

USAGE = "uv run python3 tools/ccstats/review.py [--out DIR] [--new [--record]]"
KNOWN = {"--out", "--new", "--record", "-h", "--help"}
BASELINE = "review-baseline.json"


def buckets(
    conn: sqlite3.Connection,
    keep: list[str],
    include: list[str],
    exclude: list[str],
    window: Window,
) -> tuple[list[tuple[str, int, int, list[str]]], ...]:
    """`(reviewed, skipped, unreviewed)`, each `(label, in_window, all_time, why)`.

    WHICH PROJECTS ARE SWITCHED OFF IS ASKED, NOT RE-DECIDED. `resolve_unticked`
    owns that policy and it is subtler than "exclude matched": a non-empty
    `include` is an allowlist, so a project matching nothing in it is off too.
    The first version of this function classified on `exclude` alone, which meant
    that with any `include` set the report printed "COUNTED" over projects the
    card had dropped - a report contradicting the thing it reports on. Explaining
    WHY still uses `matched_by`, but the verdict comes from one place.

    TWO COUNTS, because one of them alone misleads in a different direction. The
    windowed count is what actually reaches `stats-facts.json`, so the report and
    the card agree. The all-time count is what a decision needs: a folder with
    nothing since June but 500 sessions behind it is a real project having a
    quiet month, not a scratch directory, and the windowed figure alone would
    make those two look identical.

    Both are over `is_real = 1`, and the project list is the FULL range - a
    project you have not touched since the window opened still needs ruling on.
    """
    rows = conn.execute(
        "SELECT project_label,"
        f" SUM(CASE WHEN {window.session} THEN 1 ELSE 0 END),"
        " COUNT(*)"
        f" FROM session WHERE {Window().session} AND project_label IS NOT NULL GROUP BY 1"
    ).fetchall()
    counted = [(str(r[0]), int(r[1] or 0), int(r[2] or 0)) for r in rows]
    off = set(resolve_unticked([c[0] for c in counted], include, exclude)[0])
    reviewed: list[tuple[str, int, int, list[str]]] = []
    skipped: list[tuple[str, int, int, list[str]]] = []
    unreviewed: list[tuple[str, int, int, list[str]]] = []
    for label, win_n, all_n in counted:
        if label in off:
            why = matched_by(label, exclude) or ["not in the include allowlist"]
            skipped.append((label, win_n, all_n, why))
            continue
        held = matched_by(label, keep)
        (reviewed if held else unreviewed).append((label, win_n, all_n, held))
    order = lambda b: sorted(b, key=lambda r: (-r[1], -r[2], r[0]))  # noqa: E731
    return order(reviewed), order(skipped), order(unreviewed)


def read_baseline(root: Path) -> set[str]:
    """Projects already acknowledged. Unreadable or malformed means none.

    This is an acknowledgement ledger, not data: the worst case of losing it is
    one report that says more than it needed to, which is the safe direction.
    """
    try:
        data = json.loads((root / BASELINE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    seen = data.get("acknowledged") if isinstance(data, dict) else None
    return {str(x) for x in seen} if isinstance(seen, list) else set()


def main(argv: list[str]) -> int:
    if "-h" in argv or "--help" in argv:
        print((__doc__ or USAGE).strip())
        return 0

    bad = unknown_flags(argv, KNOWN)
    if bad:
        print(f"error: unknown argument(s): {bad!r}", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 2

    new_only, record = "--new" in argv, "--record" in argv
    if record and not new_only:
        print("error: --record only means something with --new", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 2

    try:
        out = resolve_out(argv)
    except BadOut as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not out.db.exists():
        print(DB_NOT_FOUND.format(out=out.root), file=sys.stderr)
        return 1

    data = read_defaults(out.root)
    keep = pattern_list(data, "keep")
    include, exclude = pattern_list(data, "include"), pattern_list(data, "exclude")


    # Through the validating reader, not `data["since"]` raw: an unvalidated
    # date string would be interpolated straight into the SQL below, and a typo
    # in a hand-edited settings file must not reach a query.
    window = Window(load_default_since(out.root))
    conn = open_ro(out.db)
    try:
        reviewed, skipped, unreviewed = buckets(conn, keep, include, exclude, window)
    finally:
        conn.close()

    if new_only:
        fresh = [r for r in unreviewed if r[0] not in read_baseline(out.root)]
        # Silence is the healthy state, matching ccw-sweep and this folder's
        # other scheduled jobs. `refresh.py` shows the dialog line only when
        # this prints something.
        for label, win_n, all_n, _ in fresh:
            print(f"{win_n:>5} since / {all_n:>5} all   {label}")
        if record:
            publish_text(
                json.dumps(
                    {"acknowledged": sorted(r[0] for r in unreviewed)},
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                out.root / BASELINE,
            )
        return 0

    def section(title: str, rows: list[tuple[str, int, int, list[str]]], why: str) -> None:
        win_total = sum(r[1] for r in rows)
        all_total = sum(r[2] for r in rows)
        print(f"\n{title}  ({len(rows)} projects, {win_total:,} in window, {all_total:,} all time)")
        for label, win_n, all_n, hits in rows:
            tail = f"   <- {why} {hits}" if hits else ""
            print(f"  {win_n:>5} {all_n:>6}   {label}{tail}")

    print(f"{out.root / 'dashboard-defaults.json'}")
    print(f"keep: {len(keep)} patterns   exclude: {len(exclude)} patterns"
          f"   window: {window.describe()}")
    print("columns: sessions in window, sessions all time")
    section("COUNTED, and named by `keep`", reviewed, "keep")
    section("SKIPPED by `exclude`", skipped, "exclude")
    section("COUNTED, but in NEITHER list - never ruled on", unreviewed, "")
    if unreviewed:
        print(
            "\nTo clear one: add a pattern to `keep` or `exclude` in that file."
            "\nTo silence it without deciding: --new --record"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
