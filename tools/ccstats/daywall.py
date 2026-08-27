#!/usr/bin/env python3
"""Build the 3D companion page: `claude-code-daywall.html`.

The 2D dashboard (`dashboard.py`) blends every session into flat panels. This
page keeps the one dimension those panels throw away: each session's real
wall-clock interval. One box per session, positioned by (day, hour-of-day),
so overlap and daily rhythm are visible directly instead of only through the
`Concurrency` panel's whole-corpus summary.

Usage:
  uv run python3 tools/ccstats/daywall.py                    # full range
  uv run python3 tools/ccstats/daywall.py --since 2026-06-08
  uv run python3 tools/ccstats/daywall.py --exclude scratch   # substring, repeatable
  uv run python3 tools/ccstats/daywall.py --out DIR

Not an extension of `dashboard.build_payload` -- this page does not need 21
columns of per-session detail, so it has its own slimmer query and its own
payload shape. See `PANEL-CONTRACT.md`'s house rules; this page follows the
same ones (engaged hours not active, cost is not a bill, US$ with a trailing
space) even though it has no panels.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from datetime import UTC, date, datetime, timedelta
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
from dashboard import (  # noqa: E402
    KIND_NAMES,
    BadFilterFlag,
    Lookup,
    load_default_filters,
    parse_repeated,
    resolve_unticked,
    session_kind,
)

DB_NOT_FOUND = (
    "no sessions.sqlite in {out}. Run collect.py first:\n"
    "  uv run python3 tools/ccstats/collect.py"
)

TEMPLATE = Path(__file__).parent / "daywall_template.html"
DATA_MARKER = "/*__CCSTATS_DATA_JSON__*/"

# `session.tz_offset` is a per-row string like "+1000" / "-0530", written by
# collect.py so local_date/local_hour reflect the SAME zone the archive tree
# is named in. `local_hour` is INT-only, though (no minutes/seconds) -- too
# coarse to place a session on an hour-scale axis, so this recomputes
# seconds-since-local-midnight straight from `first_ts` instead. NEVER the
# browser's own clock (same rule dashboard_template.html's `ymd()` follows).


def _tz_offset_minutes(tz_offset: str | None) -> int:
    """`+1000` -> 600, `-0530` -> -330. Malformed or absent -> 0 (UTC): real
    corpus fact (verified 2026-08-28), 0 of 8,682 real sessions have a null
    tz_offset, so this fallback is a safety net, not a live path."""
    if not tz_offset or len(tz_offset) < 5:
        return 0
    sign = 1 if tz_offset[0] == "+" else -1
    try:
        hours = int(tz_offset[1:3])
        minutes = int(tz_offset[3:5])
    except ValueError:
        return 0
    return sign * (hours * 60 + minutes)


def _local_seconds_of_day(first_ts: str, tz_offset: str | None) -> int:
    dt = datetime.fromisoformat(first_ts.replace("Z", "+00:00"))
    local = dt + timedelta(minutes=_tz_offset_minutes(tz_offset))
    return local.hour * 3600 + local.minute * 60 + local.second


def _duration_seconds(first_ts: str, last_ts: str) -> int:
    start = datetime.fromisoformat(first_ts.replace("Z", "+00:00"))
    end = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
    return max(0, round((end - start).total_seconds()))


def _q(conn: sqlite3.Connection, sql: str, params: tuple[object, ...] = ()) -> list[tuple]:
    return conn.execute(sql, params).fetchall()


def build_daywall_payload(
    conn: sqlite3.Connection,
    window: Window,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
) -> tuple[dict[str, object], list[str]]:
    """Everything the 3D page needs. `S` is one row per session, 8 small
    values each (not `dashboard.build_payload`'s 21); `P` is the one real
    session-to-session edge this dataset has -- sub-agent to parent.

    `days` is EVERY calendar date from the earliest to the latest session in
    range, one entry each, even a date with zero sessions -- not just the
    dates that happen to appear (a plain `Lookup` over `local_date` in
    first-seen order would skip an empty date entirely). The browser side
    clips a multi-day session by walking `dayIdx + 1, + 2, ...` and expects
    that to mean the NEXT REAL CALENDAR DAY; a gap in the index would shift
    every later segment onto the wrong slab.
    """
    projects, models = Lookup(), Lookup()

    session_rows = _q(
        conn,
        f"""
        SELECT key, session_uuid, first_ts, last_ts, local_date, tz_offset,
               engaged_seconds, cost_usd, project_label, primary_model,
               is_subagent, entrypoint, parent_session_uuid
        FROM session
        WHERE {window.session}
        ORDER BY local_date, first_ts
        """,
    )

    days = Lookup()
    if session_rows:
        cursor = date.fromisoformat(session_rows[0][4])
        last = date.fromisoformat(session_rows[-1][4])
        one_day = timedelta(days=1)
        while cursor <= last:
            days.get(cursor.isoformat())
            cursor += one_day

    S: list[list[object]] = []
    parent_row_of_uuid: dict[str, int] = {}
    subagent_rows: list[tuple[int, str]] = []  # (row index, parent_session_uuid)

    for row in session_rows:
        (
            _key, session_uuid, first_ts, last_ts, local_date, tz_offset,
            engaged_seconds, cost_usd, project_label, primary_model,
            is_subagent, entrypoint, parent_session_uuid,
        ) = row
        idx = len(S)
        S.append([
            days.get(local_date),
            _local_seconds_of_day(first_ts, tz_offset),
            _duration_seconds(first_ts, last_ts),
            round(engaged_seconds or 0.0, 1),
            projects.get(project_label),
            KIND_NAMES.index(session_kind(is_subagent, entrypoint)),
            models.get(primary_model),
            round((cost_usd or 0.0) * 1000),
        ])
        if not is_subagent and session_uuid:
            # First writer wins if two rows somehow shared a uuid (they
            # should not for non-subagent rows) -- deterministic beats
            # merely-not-crashing.
            parent_row_of_uuid.setdefault(session_uuid, idx)
        if is_subagent and parent_session_uuid:
            subagent_rows.append((idx, parent_session_uuid))

    # The join that must NOT be "session_uuid = session_uuid": a sub-agent
    # row carries its PARENT's session_uuid, not its own (real corpus fact,
    # 2,007 of 2,008 rows), so matching on session_uuid alone pairs every
    # sub-agent against every other sub-agent sharing that uuid too --
    # measured 2026-08-28, 35,471 spurious pairs on the real corpus. Matching
    # `parent_session_uuid` against the PARENT ROW's own `session_uuid`
    # (built only from is_subagent = 0 rows, above) avoids it entirely.
    P: list[list[int]] = [
        [child_idx, parent_row_of_uuid[parent_uuid]]
        for child_idx, parent_uuid in subagent_rows
        if parent_uuid in parent_row_of_uuid
    ]

    meta = read_meta(conn)
    unticked, unmatched = resolve_unticked(projects.values, include or [], exclude or [])
    payload = {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "timezone": meta.get("local_timezone", "unknown"),
        "cost_note": cost_note(meta.get("prices_read_on", "")),
        "prices_read_on": meta.get("prices_read_on", ""),
        "window_desc": window.describe(),
        "min_date": days.values[0] if days.values else "",
        "max_date": days.values[-1] if days.values else "",
        "default_unticked_projects": unticked,
        "days": days.values,
        "lookups": {"projects": projects.values, "models": models.values, "kinds": KIND_NAMES},
        "cols": {
            "S": ["dayIdx", "startSec", "durSec", "engagedSec", "project",
                  "kind", "model", "costMilli"],
            "P": ["child", "parent"],
        },
        "S": S, "P": P,
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

    if not include and not exclude:
        include, exclude = load_default_filters(out.root)

    conn = open_ro(out.db)
    try:
        payload, unmatched = build_daywall_payload(conn, window, include, exclude)
    finally:
        conn.close()

    if unmatched:
        print(
            f"warning: these --include/--exclude substrings matched no project_label: "
            f"{unmatched!r} (see sessions-real.csv for real names)",
            file=sys.stderr,
        )

    html = render(payload)
    target = out.root / "claude-code-daywall.html"
    out.ensure()
    fd, building_name = tempfile.mkstemp(
        dir=out.root, prefix="daywall.", suffix=".html.building"
    )
    with open(fd, "w", encoding="utf-8") as f:
        f.write(html)
    Path(building_name).replace(target)

    n_sessions = len(payload["S"])  # type: ignore[arg-type]
    print(f"{target}  ({len(html):,} bytes, {n_sessions:,} sessions, {window.describe()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
