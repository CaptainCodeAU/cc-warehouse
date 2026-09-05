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
from dashboard import (  # noqa: E402
    load_default_filters,
    load_default_since,
    resolve_unticked,
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


def selected_projects(conn: sqlite3.Connection, out_root: Path) -> list[str] | None:
    """The project labels to count, or None for "no project filter".

    Reads the SAME saved `dashboard-defaults.json` the page reads, and runs the
    SAME `resolve_unticked` matcher over the SAME population. Running one
    matcher over two different universes makes "the card and the page agree"
    true of the code and false of the answer.

    THAT POPULATION IS FULL-RANGE `is_real = 1`, NOT THE CARD'S OWN WINDOW.
    `dashboard.py` builds its list from `WHERE {window.session}`, and
    `refresh.py` runs it with no flags, so the page's universe is every real
    session ever - 139 labels on the live corpus. Narrowing this to the card's
    window instead gave 102, a THIRD universe agreeing with neither, and made
    13 of the operator's saved patterns report as unmatched purely because
    those projects had no sessions since June. Which projects are SELECTED is a
    standing choice; how many sessions they had inside the window is the
    question the card answers, and `facts.compute` applies the window itself.

    `resolve_unticked` returns the projects that start UNTICKED; the selection
    is everything else. Getting that the wrong way round would invert the whole
    filter while still producing a plausible-looking number, so it is stated
    once, here, and asserted in `tests/test_filtered_facts.py`.
    """
    include, exclude = load_default_filters(out_root)
    if not include and not exclude:
        return None
    labels = [
        str(r[0])
        for r in conn.execute(
            f"SELECT DISTINCT project_label FROM session WHERE {Window().session}"
            " AND project_label IS NOT NULL"
        )
    ]
    unticked, unmatched = resolve_unticked(labels, include, exclude)
    if unmatched:
        # `dashboard.py` warns about these and so must this. A typo'd `include`
        # pattern matches nothing, leaves the selection empty, and writes a card
        # of zeros with `project_filter_applied: true` - which looks exactly
        # like a quiet week rather than like a broken setting.
        print(
            f"warning: these saved include/exclude patterns matched no project_label:"
            f" {unmatched!r} (see dashboard-defaults.json)",
            file=sys.stderr,
        )
    return sorted(set(labels) - set(unticked))


def card(
    conn: sqlite3.Connection, window: Window, projects: list[str] | None = None
) -> dict[str, object]:
    """The whole file: a header saying what this is, then the numbers.

    The header is not decoration. This file is designed to be read by something
    that is not in this repository and has no README to hand, so what the
    numbers cover, and the fact that `cost_usd` is an estimate rather than a
    bill, have to travel WITH them.
    """
    # `facts.compute` filters to `is_real = 1` (see its module docstring) except
    # for `files_total` and `subagents`, which count every session FILE in the
    # window rather than every real session.
    #
    # A project filter narrows those two further, by a definition worth stating
    # because the numbers are otherwise unexplainable. The selection universe is
    # the PAGE's - labels that appear on at least one real session - so a
    # filtered card leaves out every session file whose project is not in it.
    # Measured on the live corpus: 58 files, being 8 sessions with no
    # `project_label` at all plus 50 in the 17 projects that have never had a
    # real session. `shell_pct` and `inflate` are computed from `files_total`,
    # so they move with it. Nothing here is wrong; it is just not derivable from
    # the card alone.
    head = header(read_meta(conn), window, rows="sessions with is_real = 1", projects=projects)
    # Named, not silent. Everything else honours the window and the selection;
    # these do not, and a reader of this file somewhere else has no way to work
    # that out from the numbers alone.
    head["scope"]["whole_corpus_facts"] = facts.WHOLE_CORPUS_FACTS  # type: ignore[index]
    return {
        **head,
        "facts": facts.compute(conn, window, projects),
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
        since, until = parse_since(argv), parse_until(argv)
    except (BadOut, BadWindow) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not out.db.exists():
        print(DB_NOT_FOUND.format(out=out.root), file=sys.stderr)
        return 1

    # An explicit --since always wins; the saved setting is the default, not an
    # override. Same precedence `dashboard.py` gives --include/--exclude over
    # the saved lists, for the same reason: a deliberate one-off flag must never
    # be silently merged with a stale saved value.
    #
    # THIS CARD AND THE PAGE BESIDE IT NOW DESCRIBE DIFFERENT WINDOWS, ON
    # PURPOSE, and an earlier comment here said they must not. That comment was
    # right about a page: the page embeds the full range because its date
    # pickers have to be able to widen, and narrowing the embedded data would
    # break the control. This file is not a page. It is the answer to one
    # question - "these projects, from this date" - which is why the operator
    # asked for the filtering to be baked in rather than left to a reader.
    # `scope` states which window and which projects, so the difference is
    # readable rather than something to be inferred from two files.
    window = Window(since or load_default_since(out.root), until)

    conn = open_ro(out.db)
    try:
        payload = card(conn, window, selected_projects(conn, out.root))
    finally:
        conn.close()

    out.ensure()
    text = json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"
    publish_text(text, out.facts_json)
    print(f"{out.facts_json}  ({len(text):,} bytes, {window.describe()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
