#!/usr/bin/env python3
"""Build a LIVE interactive dashboard: `claude-code-dashboard-live.html`.

One self-contained HTML file, no external assets, that opens straight from
disk in a browser, PLUS `dashboard-data.json`: the same payload the page
embeds, written out as a file so a program that is not a browser can render
the same numbers. It is the identical string, not a second dump, so the two
can never disagree - see `to_blob`. Unlike `claude-code-dashboard.html` (built by hand outside
this repo for one fixed window), this one embeds a compact per-session dataset
and draws every chart in JavaScript, so a reader can change the date range and
exclude projects THEMSELVES, in the page, with no re-run.

Usage:
  uv run python3 tools/ccstats/dashboard.py                    # full range
  uv run python3 tools/ccstats/dashboard.py --since 2026-06-08 # bound what's embedded
  uv run python3 tools/ccstats/dashboard.py --exclude scratch  # substring, repeatable
  uv run python3 tools/ccstats/dashboard.py --include cc-ware  # allowlist, repeatable
  uv run python3 tools/ccstats/dashboard.py --out DIR          # write elsewhere

`--since`/`--until` bound what gets EMBEDDED (smaller file, if wanted); they do
not need to match the range the reader starts on, which is chosen with the
page's own date pickers (defaulted to 2026-06-08 onward, the operator's own
preferred start).

`--exclude SUBSTRING` / `--include SUBSTRING` (both repeatable) set which
projects start TICKED in the page's own project checklist -- every project
is still embedded and still choosable either way, this only changes the
starting state, and Reset restores it. Substring, not exact-match or a glob:
a pattern matches `project_label` if it appears anywhere in it, case-insensitive,
so a name IS a valid pattern (a "substring" that happens to be the whole
string). `--exclude`
is a denylist (those matches start unticked, everything else stays ticked).
`--include` is an allowlist (only those matches start ticked, everything else
starts unticked). Given both, `--exclude` narrows `--include`'s allowlist
further. A pattern matching zero projects only warns (stderr), it does not
fail the build, since a typo here is easy and should not block the file.

Privacy: this embeds `project_label` (folder names) per session, the same
column the static dashboard already ships. It writes only under the resolved
output root (`~/.cc-warehouse/stats` by default), which is gitignored and
"must never be committed" per this folder's own README. It is never uploaded
anywhere by this script.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

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

DB_NOT_FOUND = (
    "no sessions.sqlite in {out}. Run collect.py first:\n"
    "  uv run python3 tools/ccstats/collect.py"
)

TEMPLATE = Path(__file__).parent / "dashboard_template.html"
DATA_MARKER = "/*__CCSTATS_DATA_JSON__*/"


class BadFilterFlag(ValueError):
    """A `--exclude`/`--include` given with no substring to go with it."""


# A `session` row with `is_real = 1` (Claude replied at least once) can still
# be three very different things, and the dashboard used to blend all three
# into every tile with no way to tell them apart -- measured 2026-08-24: 46.5%
# of "sessions" in a typical range are Task sub-agent runs or one-shot
# automated calls (hooks, titling), which drags "typical session length" down
# by about 96x versus the operator's own interactive sessions. The client-side
# template (dashboard_template.html) is what actually acts on this label:
# `KIND_MINE` is always counted; `KIND_AUTOMATED` stays a reader-toggle
# (default off); `KIND_SUBAGENT` is no longer a toggle at all as of
# 2026-08-27 -- it is hardcoded IN for cost/token/tool panels (real extra
# spend, ~US$11,000 measured) and hardcoded OUT of hours/session-count panels
# (a sub-agent's time sits inside its parent session's own clock time, so
# counting it there would double-count minutes, not add new ones).
KIND_MINE = "mine"
KIND_SUBAGENT = "subagent"
KIND_AUTOMATED = "automated"
KIND_NAMES = [KIND_MINE, KIND_SUBAGENT, KIND_AUTOMATED]


def session_kind(is_subagent: int | None, entrypoint: str | None) -> str:
    """Which of the three populations one `session` row belongs to.

    `is_subagent` wins first: a Task sub-agent invocation is never "mine"
    even if something upstream also set an `entrypoint`. Among the rest,
    `entrypoint = 'sdk-cli'` is an automated one-shot call (hooks, titling --
    measured: one prompt, zero tool calls, a few seconds). Everything else
    (`cli`, `local-agent`, and NULL -- transcripts older than Claude Code
    recording the field, verified 2026-02-14..2026-03-11, genuinely
    interactive) is the operator's own session.
    """
    if is_subagent:
        return KIND_SUBAGENT
    if entrypoint == "sdk-cli":
        return KIND_AUTOMATED
    return KIND_MINE


def parse_repeated(argv: list[str], flag: str) -> list[str]:
    """Every value for a repeatable `flag`, in the order given.

    Repeatable, unlike `--since`/`--until`: `--exclude a --exclude b` gives
    two independent substrings, either one enough to match a project.
    """
    values: list[str] = []
    i = 0
    while i < len(argv):
        if argv[i] == flag:
            if i + 1 >= len(argv):
                raise BadFilterFlag(f"{flag} needs a substring, for example {flag} scratch")
            values.append(argv[i + 1])
            i += 2
        else:
            i += 1
    return values


def resolve_unticked(
    all_projects: list[str], include: list[str], exclude: list[str]
) -> tuple[list[str], list[str]]:
    """Which projects start UNTICKED in the page's checklist, and which
    `--include`/`--exclude` substrings matched nothing (a likely typo).

    Substring matching, not exact or glob: a pattern matches `project_label`
    if it appears anywhere in it -- start, middle, end, or the whole string
    (an exact match is just the special case of a pattern that IS the whole
    name). Case-insensitive, so `--exclude tax` also matches `Tax_Bhencho`.
    Every pattern in a list is independent; matching ANY one is enough.

    `include` is an allowlist: when given, only matches start ticked and
    everything else starts unticked. `exclude` is a denylist: matches start
    unticked. Given both, `exclude` narrows `include`'s allowlist further --
    a project must pass the allowlist AND not hit the denylist to stay ticked.
    """

    def matches(name: str, patterns: list[str]) -> bool:
        lname = name.lower()
        return any(pattern.lower() in lname for pattern in patterns)

    ticked = {p for p in all_projects if matches(p, include)} if include else set(all_projects)
    if exclude:
        ticked -= {p for p in all_projects if matches(p, exclude)}
    unticked = sorted(p for p in all_projects if p not in ticked)

    unmatched = [
        pattern
        for pattern in (*include, *exclude)
        if not any(pattern.lower() in p.lower() for p in all_projects)
    ]
    return unticked, unmatched


class Lookup:
    """A dedup table: string -> stable integer index, in first-seen order.

    Session rows reference `project_label`, `repo_root`, `cc_version` and
    `model` by index rather than repeating the string per row; with ~120
    distinct values over ~10k sessions that is most of the payload's size.
    """

    def __init__(self) -> None:
        self._index: dict[str, int] = {}
        self.values: list[str] = []

    def get(self, value: str | None) -> int:
        value = value or ""
        if value not in self._index:
            self._index[value] = len(self.values)
            self.values.append(value)
        return self._index[value]


def _q(conn: sqlite3.Connection, sql: str, params: tuple[object, ...] = ()) -> list[tuple]:
    return conn.execute(sql, params).fetchall()


def build_payload(
    conn: sqlite3.Connection,
    window: Window,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
) -> tuple[dict[str, object], list[str]]:
    """Everything the page needs, keyed for compact JSON.

    `S`/`M`/`T`/`A`/`O` are row-major arrays (not arrays of objects) with a
    fixed column order documented beside each query below; the JS side knows
    the order. This alone is why 87 tool names and 118 project names do not
    get repeated per row.
    """
    projects, repos, models, ccversions, tools = (Lookup() for _ in range(5))

    session_rows = _q(
        conn,
        f"""
        SELECT key, local_date, local_hour, local_weekday, project_label, repo_root,
               is_worktree, engaged_seconds, cost_usd,
               tok_input, tok_output, tok_cache_write, tok_cache_read, tok_thinking,
               cc_version, primary_model,
               wall_seconds, active_seconds, n_user_prompts, n_tool_uses, n_assistant_turns,
               is_subagent, entrypoint
        FROM session
        WHERE {window.session}
        ORDER BY local_date, local_hour
        """,
    )

    session_index: dict[str, int] = {}
    S: list[list[object]] = []
    for row in session_rows:
        (
            key, local_date, local_hour, local_weekday, project_label, repo_root,
            is_worktree, engaged_seconds, cost_usd,
            tok_input, tok_output, tok_cache_write, tok_cache_read, tok_thinking,
            cc_version, primary_model,
            wall_seconds, active_seconds, n_user_prompts, n_tool_uses, n_assistant_turns,
            is_subagent, entrypoint,
        ) = row
        session_index[key] = len(S)
        S.append([
            local_date, local_hour, local_weekday,
            projects.get(project_label), repos.get(repo_root),
            1 if is_worktree else 0,
            round(engaged_seconds or 0.0, 1), round(cost_usd or 0.0, 4),
            tok_input or 0, tok_output or 0, tok_cache_write or 0,
            tok_cache_read or 0, tok_thinking or 0,
            ccversions.get(cc_version), models.get(primary_model),
            round(wall_seconds or 0.0, 1), round(active_seconds or 0.0, 1),
            n_user_prompts or 0, n_tool_uses or 0, n_assistant_turns or 0,
            KIND_NAMES.index(session_kind(is_subagent, entrypoint)),
        ])

    model_rows = _q(
        conn,
        f"""
        SELECT session_key, model, SUM(cost_usd),
               SUM(input_tokens), SUM(output_tokens),
               SUM(cache_write_5m) + SUM(cache_write_1h), SUM(cache_read), SUM(thinking_tokens)
        FROM turn
        WHERE model IS NOT NULL AND model <> ''{window.child_keys}
        GROUP BY session_key, model
        """,
    )
    M = [
        [session_index[key], models.get(model), round(cost or 0.0, 4),
         tin or 0, tout or 0, cw or 0, cr or 0, think or 0]
        for key, model, cost, tin, tout, cw, cr, think in model_rows
        if key in session_index
    ]

    tool_rows = _q(
        conn,
        f"""
        SELECT session_key, tool_name, COUNT(*), SUM(is_error)
        FROM tool_call
        WHERE 1=1{window.child_keys}
        GROUP BY session_key, tool_name
        """,
    )
    T = [
        [session_index[key], tools.get(tool_name), count, errors or 0]
        for key, tool_name, count, errors in tool_rows
        if key in session_index
    ]

    attr_rows = _q(
        conn,
        f"""
        SELECT session_key, kind, name, count
        FROM attribution
        WHERE 1=1{window.child_keys}
        """,
    )
    ATTR_KINDS = ["agent", "mcp_server", "mcp_tool", "plugin", "skill"]
    kind_index = {k: i for i, k in enumerate(ATTR_KINDS)}
    A = [
        [session_index[key], kind_index.get(kind, -1), name, count]
        for key, kind, name, count in attr_rows
        if key in session_index and kind in kind_index
    ]

    overlap_rows = _q(
        conn,
        f"""
        SELECT local_date, sessions_active, sessions_started, summed_hours,
               elapsed_hours, concurrency, max_concurrent
        FROM overlap_day
        {window.overlap_where}
        ORDER BY local_date
        """,
    )
    overlap = [list(r) for r in overlap_rows]

    meta = read_meta(conn)
    dates = [row[1] for row in session_rows]
    unticked, unmatched = resolve_unticked(projects.values, include or [], exclude or [])
    payload = {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "timezone": meta.get("local_timezone", "unknown"),
        "cost_note": cost_note(meta.get("prices_read_on", "")),
        "prices_read_on": meta.get("prices_read_on", ""),
        "window_desc": window.describe(),
        "scope": (
            "project-filtered: every row here honours the page's project tick list. "
            "stats-facts.json does NOT apply that list, so the two must not be mixed."
        ),
        "min_date": min(dates) if dates else "",
        "max_date": max(dates) if dates else "",
        "default_unticked_projects": unticked,
        "lookups": {
            "projects": projects.values,
            "repos": repos.values,
            "models": models.values,
            "ccversions": ccversions.values,
            "tools": tools.values,
            "attrKinds": ATTR_KINDS,
            "kinds": KIND_NAMES,
        },
        "cols": {
            "S": ["date", "hour", "weekday", "project", "repo", "worktree",
                  "engagedSec", "cost", "tokIn", "tokOut", "tokCacheWrite",
                  "tokCacheRead", "tokThinking", "ccVersion", "model",
                  "wallSec", "activeSec", "prompts", "toolUses", "turns", "kind"],
            "M": ["session", "model", "cost", "tokIn", "tokOut", "tokCacheWrite",
                  "tokCacheRead", "tokThinking"],
            "T": ["session", "tool", "count", "errors"],
            "A": ["session", "kind", "name", "count"],
            "O": ["date", "sessionsActive", "sessionsStarted", "summedHours",
                  "elapsedHours", "concurrency", "maxConcurrent"],
        },
        "S": S, "M": M, "T": T, "A": A, "O": overlap,
    }
    return payload, unmatched


DEFAULTS_FILENAME = "dashboard-defaults.json"


def load_default_filters(out_root: Path) -> tuple[list[str], list[str]]:
    """The project include/exclude lists `/dashboard` saves at
    `<out_root>/dashboard-defaults.json` (shape: `{"exclude": [...], "include": [...]}`).

    A DIRECT run of this script used to silently ignore that file - only the
    `/dashboard` command ever read it - so the page it built carried no
    exclusions at all even when a real defaults file sat right beside the
    database (measured 2026-08-24: the live page had `default_unticked_
    projects: []` while `dashboard-defaults.json` listed six patterns).
    Reading it here means a direct run and a `/dashboard` run agree.

    Missing file, unreadable file, or malformed JSON all degrade to "no
    defaults" (R5/R10) rather than failing the build - a build must never
    depend on a file only the operator-facing command writes.
    """
    try:
        data = json.loads((out_root / DEFAULTS_FILENAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], []
    if not isinstance(data, dict):
        return [], []
    include = data.get("include") or []
    exclude = data.get("exclude") or []
    if not isinstance(include, list) or not isinstance(exclude, list):
        return [], []
    return [str(x) for x in include], [str(x) for x in exclude]


def to_blob(payload: dict[str, object]) -> str:
    """The payload as the compact JSON string that gets embedded AND written out.

    Built once and used twice, on purpose. If `dashboard-data.json` were dumped
    from the payload a second time it could drift from the page's copy by a key
    order or a float repr and nothing here would notice; sharing the string
    makes them identical by construction rather than by test.
    """
    return json.dumps(payload, separators=(",", ":"))


def render_blob(blob: str) -> str:
    template = TEMPLATE.read_text(encoding="utf-8")
    if DATA_MARKER not in template:
        raise SystemExit(f"{TEMPLATE} is missing the {DATA_MARKER} marker")
    return template.replace(DATA_MARKER, blob)


def render(payload: dict[str, object]) -> str:
    """The whole page for `payload`. Kept for callers that hold no blob."""
    return render_blob(to_blob(payload))


def main(argv: list[str]) -> int:
    try:
        out = resolve_out(argv)
        window = Window(parse_since(argv), parse_until(argv))
        include = parse_repeated(argv, "--include")
        exclude = parse_repeated(argv, "--exclude")
    except (BadOut, BadWindow, BadFilterFlag) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not out.db.exists():
        print(DB_NOT_FOUND.format(out=out.root), file=sys.stderr)
        return 1

    # An explicit --include/--exclude on the command line always wins; only
    # fall back to the saved defaults file when NEITHER was given, so a
    # deliberate one-off flag is never silently merged with a stale saved list.
    if not include and not exclude:
        include, exclude = load_default_filters(out.root)

    conn = open_ro(out.db)
    try:
        payload, unmatched = build_payload(conn, window, include, exclude)
    finally:
        conn.close()

    if unmatched:
        print(
            f"warning: these --include/--exclude substrings matched no project_label: "
            f"{unmatched!r} (see the Projects panel, or sessions-real.csv, for real names)",
            file=sys.stderr,
        )

    blob = to_blob(payload)
    html = render_blob(blob)
    target = out.root / "claude-code-dashboard-live.html"
    out.ensure()
    publish_text(html, target, prefix="dashboard-live.", suffix=".html.building")
    # The SAME string, written a second time as a file another program can read.
    # It is not a summary of the page and not a re-query: it is the page's own
    # data, so a JS app fetching it and a reader looking at the page can never
    # be shown different numbers.
    publish_text(blob, out.data_json, prefix="dashboard-data.", suffix=".json.building")

    n_sessions = len(payload["S"])  # type: ignore[arg-type]
    print(f"{target}  ({len(html):,} bytes, {n_sessions:,} sessions, {window.describe()})")
    # Second line, and deliberately not the same shape as the first: `refresh.py`
    # reads the HTML path back out of this stdout by looking for the page's own
    # filename, so this line must never be mistakable for that one.
    print(f"{out.data_json}  ({len(blob):,} bytes of payload)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
