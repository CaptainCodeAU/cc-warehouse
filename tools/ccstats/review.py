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

    uv run python3 tools/ccstats/review.py                  # one row per pattern
    uv run python3 tools/ccstats/review.py --projects       # ...and every folder
    uv run python3 tools/ccstats/review.py --new            # only what is unreviewed
    uv run python3 tools/ccstats/review.py --new --record   # ...and acknowledge it

ONE ROW PER PATTERN, NOT PER PROJECT. The first version printed a row for every
folder: 139 rows and a 242-character line on the live corpus, three quarters of
them repeating one directory prefix and two thirds printing the same number
twice. The selection is SPECIFIED as patterns, so the report answers in patterns
and `--projects` restores the folder detail. Nothing is hidden that cannot be
asked for.

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

USAGE = (
    "uv run python3 tools/ccstats/review.py [--out DIR] [--projects] [--new [--record]]"
)
KNOWN = {"--out", "--projects", "--new", "--record", "-h", "--help"}
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


def _pattern_section(
    title: str,
    pats: list[str],
    rows: list[tuple[str, int, int, list[str]]],
    show_projects: bool,
) -> None:
    """One row per PATTERN: what it holds, and what it alone holds.

    `only` - projects for which this is the SOLE matching pattern - is the
    question a reader actually has, because it says what deleting the pattern
    would cost. `proj` alone cannot: a pattern matching fifteen projects that
    are all also caught by another is holding nothing up.
    """
    owned = {p: [r for r in rows if p in r[3]] for p in pats}
    sole = {p: [r for r in owned[p] if r[3] == [p]] for p in pats}
    order = sorted(pats, key=lambda p: (-sum(r[1] for r in owned[p]), p))

    win_total = sum(r[1] for r in rows)
    all_total = sum(r[2] for r in rows)
    print(f"\n{title}  {len(pats)} patterns -> {len(rows)} projects, "
          f"{win_total:,} sessions in window, {all_total:,} all time")
    print(f"  {'win':>6} {'all':>7} {'proj':>5} {'only':>5}  pattern")
    for p in order:
        hits, mine = owned[p], sole[p]
        print(f"  {sum(r[1] for r in hits):>6} {sum(r[2] for r in hits):>7}"
              f" {len(hits):>5} {len(mine):>5}  {p}")
        if show_projects:
            prefix = _shared_prefix([r[0] for r in hits])
            for label, win_n, all_n, _ in hits:
                short = label[len(prefix):] if prefix else label
                print(f"  {win_n:>6} {all_n:>7}          {short}")
            if prefix:
                # Said, not assumed. A trimmed name the reader cannot reconstruct
                # is a different project as far as searching the folder goes.
                print(f"  {'':>6} {'':>7}          (all prefixed `{prefix}`)")

    # A project can be switched off WITHOUT any exclude pattern matching it:
    # a non-empty `include` is an allowlist, so anything it does not name is off.
    # Those rows belong to no pattern and would otherwise vanish from a
    # pattern-shaped report - present in the totals, absent from every row.
    orphans = [r for r in rows if not any(p in r[3] for p in pats)]
    if orphans:
        print(f"  {sum(r[1] for r in orphans):>6} {sum(r[2] for r in orphans):>7}"
              f" {len(orphans):>5} {len(orphans):>5}  (not in the include allowlist)")
        if show_projects:
            for label, win_n, all_n, _ in orphans:
                print(f"  {win_n:>6} {all_n:>7}          {label}")

    dead = [p for p in order if not owned[p]]
    covered = [p for p in order if owned[p] and not sole[p]]
    if dead:
        print(f"  match nothing: {', '.join(dead)}")
    if covered:
        # NOT "safe to delete". `only` is computed ONE PATTERN AT A TIME, so two
        # patterns covering each other's projects both read 0 - drop either and
        # nothing changes, drop both and the projects are gone. Live case:
        # `infisical` and `agent-vault` hold the same two folders.
        print(f"  every match also caught by another pattern: {', '.join(covered)}")
        print("    (checked one at a time - two of these may be covering each other,"
              " so removing both can still lose a project)")


def _shared_prefix(labels: list[str]) -> str:
    """The FIRST repeated segment every label shares, or `""`.

    75% of rows on the live corpus began `CaptainCodeAU-`, so trimming is worth
    a column of screen and one less thing for the eye to skip.

    The FIRST `-`, not the last. Cutting at the last boundary of the common text
    splits the project's own name: every `cc-warehouse` folder shares the prefix
    `CaptainCodeAU-cc-`, so the rows read `warehouse`, `warehouse-.worktree-...`,
    which is a different project as far as the eye is concerned. Taking one
    segment removes the noise and leaves every name intact.
    """
    if len(labels) < 2:
        return ""
    head = labels[0].split("-")[0] + "-"
    return head if all(label.startswith(head) for label in labels) else ""


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
    show_projects = "--projects" in argv
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

    print(f"ccstats review  {out.root / 'dashboard-defaults.json'}")
    print(f"window {window.describe()}  ---  "
          f"{len(reviewed)} counted, {len(skipped)} skipped, {len(unreviewed)} unruled")

    # FIRST, because it is the only part that asks for a decision. The first
    # version put it last, under 138 rows already ruled on.
    # ALWAYS printed, even when empty, so the section never moves. A block that
    # appears only sometimes is one the eye stops looking for.
    print(f"\nNEVER RULED ON - in neither list  ({len(unreviewed)})")
    if unreviewed:
        print(f"  {'win':>5} {'all':>6}   project")
        for label, win_n, all_n, _ in unreviewed:
            print(f"  {win_n:>5} {all_n:>6}   {label}")
        print("  -> add a pattern to `keep` or `exclude`, or run: review.py --new --record")
    else:
        print("  none - every project matches `keep` or `exclude`.")

    # THE OTHER KIND OF CRACK, and the quieter one. A project can be in `keep`
    # AND be excluded; `exclude` wins, so the operator's own decision to count it
    # is overruled with nothing said. It is not unreviewed - it was ruled on
    # twice, in opposite directions - so it belongs in its own block rather than
    # above.
    overruled = [r for r in skipped if matched_by(r[0], keep)]
    print(f"\nIN `keep` BUT EXCLUDED ANYWAY - exclude wins  ({len(overruled)})")
    if not overruled:
        print("  none.")
    elif show_projects:
        print(f"  {'win':>5} {'all':>6}   project")
        for label, win_n, all_n, why in overruled:
            print(f"  {win_n:>5} {all_n:>6}   {label}")
            print(f"  {'':>5} {'':>6}     keep {matched_by(label, keep)} vs exclude {why}")
    else:
        # Summarised, because on the live corpus all eight are scratch folders
        # under a real project - expected, and eighteen lines of expected every
        # day is how a report becomes wallpaper. The exclude patterns doing it
        # are what a reader needs to judge whether it is still intended.
        blame = sorted({p for r in overruled for p in r[3]})
        print(f"  {sum(r[1] for r in overruled):>5} {sum(r[2] for r in overruled):>6}"
              f"   {len(overruled)} project(s), excluded by: {', '.join(blame)}")
    print("  -> intended when these are scratch folders under a real project."
          " Otherwise narrow the exclude pattern." if overruled else "")

    _pattern_section("KEEP", keep, reviewed, show_projects)
    _pattern_section("EXCLUDE", exclude, skipped, show_projects)
    if not show_projects:
        print("\n--projects lists the folders under each pattern.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
