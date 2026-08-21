#!/usr/bin/env python3
"""Build a LIVE interactive dashboard: `claude-code-dashboard-live.html`.

One self-contained HTML file, no external assets, that opens straight from
disk in a browser. Unlike `claude-code-dashboard.html` (built by hand outside
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
a pattern matches `project_label` if it appears anywhere in it, so a name IS
a valid pattern (a "substring" that happens to be the whole string). `--exclude`
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
import tempfile
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
    name). Every pattern in a list is independent; matching ANY one is enough.

    `include` is an allowlist: when given, only matches start ticked and
    everything else starts unticked. `exclude` is a denylist: matches start
    unticked. Given both, `exclude` narrows `include`'s allowlist further --
    a project must pass the allowlist AND not hit the denylist to stay ticked.
    """

    def matches(name: str, patterns: list[str]) -> bool:
        return any(pattern in name for pattern in patterns)

    ticked = {p for p in all_projects if matches(p, include)} if include else set(all_projects)
    if exclude:
        ticked -= {p for p in all_projects if matches(p, exclude)}
    unticked = sorted(p for p in all_projects if p not in ticked)

    unmatched = [
        pattern
        for pattern in (*include, *exclude)
        if not any(pattern in p for p in all_projects)
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
               wall_seconds, active_seconds, n_user_prompts, n_tool_uses, n_assistant_turns
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
        },
        "cols": {
            "S": ["date", "hour", "weekday", "project", "repo", "worktree",
                  "engagedSec", "cost", "tokIn", "tokOut", "tokCacheWrite",
                  "tokCacheRead", "tokThinking", "ccVersion", "model",
                  "wallSec", "activeSec", "prompts", "toolUses", "turns"],
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


def render(payload: dict[str, object]) -> str:
    template = TEMPLATE.read_text(encoding="utf-8")
    if DATA_MARKER not in template:
        raise SystemExit(f"{TEMPLATE} is missing the {DATA_MARKER} marker")
    blob = json.dumps(payload, separators=(",", ":"))
    return template.replace(DATA_MARKER, blob)


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

    html = render(payload)
    target = out.root / "claude-code-dashboard-live.html"
    out.ensure()
    # mkstemp + os.replace (DESIGN R2's idiom, same as collect.py's sessions.sqlite
    # publish): build into a fresh file, one atomic rename onto the target. A
    # write that fails leaves the ".building" file behind rather than deleting
    # it, matching collect.py -- this project never deletes, even its own scratch.
    fd, building_name = tempfile.mkstemp(
        dir=out.root, prefix="dashboard-live.", suffix=".html.building"
    )
    with open(fd, "w", encoding="utf-8") as f:
        f.write(html)
    Path(building_name).replace(target)

    n_sessions = len(payload["S"])  # type: ignore[arg-type]
    print(f"{target}  ({len(html):,} bytes, {n_sessions:,} sessions, {window.describe()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
