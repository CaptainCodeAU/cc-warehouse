"""The numbers quoted in prose, computed once and shared.

Both the workbook's README/Caveats sheets and DATA-GUIDE.md quote figures inside
sentences. Typing them by hand is what let the two drift apart on 2026-08-21:
the Caveats sheet carried literals frozen at the time the code was written while
the Overview sheet queried live, so one workbook stated two different session
counts. Every quoted number now comes from here.

Every figure is filtered to real sessions (`is_real = 1`) and to the `--since`
window, so a windowed workbook can never quote a whole-corpus number in its own
prose.
"""

from __future__ import annotations

import sqlite3

from common import Window

# Claude Code began emitting `output_tokens_details.thinking_tokens` at this
# version. Established by census, not assumption: 2.1.227 (2026-08-11) records
# none, 2.1.228 (2026-08-12) records it, and every later version does.
THINKING_FIRST_VERSION = "2.1.228"


def compute(conn: sqlite3.Connection, window: Window | None = None) -> dict[str, object]:
    """Every number any prose string needs, honouring the window.

    The window forms come from `common.Window`, which is the ONE place they are
    derived. They used to be rebuilt here and again in build_workbook.py, two
    implementations of one filter kept in step by hand.
    """
    window = window or Window()

    def one(sql: str) -> tuple[object, ...]:
        row = conn.execute(sql).fetchone()
        return row if row is not None else ()

    since = window.since
    win = window.and_clause
    dwin = window.overlap_where
    keys = f" WHERE 1=1{window.child_keys}" if window.active else ""

    files_total, sessions_real, subagents = one(
        f"SELECT COUNT(*), SUM(is_real), SUM(is_subagent) FROM session WHERE 1=1{win}"
    )
    (
        prompts, tool_calls, turns, engaged_s, active_s, wall_s,
        tok_in, tok_out, tok_think, tok_cw, tok_cr, cost,
        repos, labels, worktree_sessions, active_days, span_lo, span_hi,
    ) = one(
        "SELECT SUM(n_user_prompts), SUM(n_tool_uses), SUM(n_assistant_turns),"
        " SUM(engaged_seconds), SUM(active_seconds), SUM(wall_seconds),"
        " SUM(tok_input), SUM(tok_output), SUM(tok_thinking),"
        " SUM(tok_cache_write), SUM(tok_cache_read), SUM(cost_usd),"
        " COUNT(DISTINCT repo_root), COUNT(DISTINCT project_label),"
        " SUM(is_worktree), COUNT(DISTINCT local_date), MIN(first_ts), MAX(last_ts)"
        f" FROM session WHERE is_real = 1{win}"
    )
    subs_real = one(f"SELECT SUM(is_subagent) FROM session WHERE is_real=1{win}")[0]
    elapsed_h, summed_h, mean_elapsed, max_elapsed, over24 = one(
        "SELECT SUM(elapsed_hours), SUM(summed_hours), AVG(elapsed_hours),"
        f" MAX(elapsed_hours), SUM(elapsed_hours > 24.001) FROM overlap_day{dwin}"
    )
    turn_rows = one(f"SELECT COUNT(*) FROM turn{keys}")[0]
    tool_rows = one(f"SELECT COUNT(*) FROM tool_call{keys}")[0]

    # The newest month always stops on collection day, and a windowed workbook's
    # FIRST month is cut short at the other end. Both are partial, and a bar
    # chart shows both as short bars for reasons that are not a change in usage.
    last_month, last_day, last_month_days = one(
        f"SELECT substr(MAX(local_date),1,7), MAX(local_date),"
        f" (SELECT COUNT(DISTINCT local_date) FROM session WHERE is_real=1{win}"
        f"  AND substr(local_date,1,7) = substr((SELECT MAX(local_date)"
        f"  FROM session WHERE is_real=1{win}),1,7))"
        f" FROM session WHERE is_real = 1{win}"
    )
    first_month, first_day, first_month_days = one(
        f"SELECT substr(MIN(local_date),1,7), MIN(local_date),"
        f" (SELECT COUNT(DISTINCT local_date) FROM session WHERE is_real=1{win}"
        f"  AND substr(local_date,1,7) = substr((SELECT MIN(local_date)"
        f"  FROM session WHERE is_real=1{win}),1,7))"
        f" FROM session WHERE is_real = 1{win}"
    )
    thinking_from = one(
        f"SELECT MIN(local_date) FROM session WHERE is_real=1 AND tok_thinking > 0{win}"
    )[0]
    busiest_day, busiest_n = one(
        f"SELECT local_date, COUNT(*) FROM session WHERE is_real=1{win}"
        " GROUP BY 1 ORDER BY 2 DESC LIMIT 1"
    )
    peak_c, peak_day = one(f"SELECT MAX(max_concurrent), local_date FROM overlap_day{dwin}")
    busiest_engaged = one(
        f"SELECT ROUND(SUM(engaged_seconds)/3600.0,1) FROM session WHERE is_real=1{win}"
        f" AND local_date = '{busiest_day}'"
    )[0]
    busiest_elapsed = one(
        f"SELECT elapsed_hours FROM overlap_day WHERE local_date = '{busiest_day}'"
    )[0]
    multi_repos, extra_labels = one(
        "SELECT COUNT(*), COALESCE(SUM(n - 1), 0) FROM (SELECT COUNT(DISTINCT project_label) n"
        f" FROM session WHERE is_real = 1{win} GROUP BY repo_root HAVING n > 1)"
    )
    wt_labels = one(
        f"SELECT COUNT(DISTINCT project_label) FROM session WHERE is_real=1 AND is_worktree=1{win}"
    )[0]
    offsets = conn.execute(
        "SELECT tz_offset, COUNT(*) FROM session WHERE is_real = 1"
        f" AND tz_offset IS NOT NULL{win} GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall()
    # Deliberately NOT windowed. Notes describing a bug that was fixed have to
    # quote the whole corpus, or a window that excludes the affected period
    # renders the sentence as "the 0 sessions that were wrong", which is both
    # meaningless and reads as a denial that anything was wrong.
    dst_all = one(
        "SELECT COUNT(*) FROM session WHERE is_real = 1 AND tz_offset = '+1100'"
    )[0]

    shells = (files_total or 0) - (sessions_real or 0)
    shell_pct = round(100.0 * shells / files_total, 1) if files_total else 0.0
    inflate = round(files_total / sessions_real, 1) if sessions_real else 0.0
    cr_ratio = round(tok_cr / tok_out) if tok_out else 0

    return {
        "since": since,
        "files_total": files_total,
        "sessions_real": sessions_real,
        "subagents": subagents,
        "subagents_real": subs_real,
        "shell_pct": shell_pct,
        "inflate": inflate,
        "prompts": prompts,
        "tool_calls": tool_calls,
        "turns": turns,
        "turn_rows": turn_rows,
        "tool_rows": tool_rows,
        "engaged_h": round((engaged_s or 0) / 3600.0, 1),
        "active_h": round((active_s or 0) / 3600.0, 1),
        "wall_h": round((wall_s or 0) / 3600.0, 1),
        "elapsed_h": round(elapsed_h or 0, 1),
        "summed_h": round(summed_h or 0, 1),
        "mean_elapsed": round(mean_elapsed or 0, 1),
        "max_elapsed": round(max_elapsed or 0, 1),
        "days_over_24h": over24,
        "tok_in": tok_in,
        "tok_out": tok_out,
        "tok_think": tok_think,
        "tok_cw": tok_cw,
        "tok_cr": tok_cr,
        "cr_ratio": cr_ratio,
        "cost": round(cost or 0, 2),
        "repos": repos,
        "labels": labels,
        "multi_label_repos": multi_repos,
        "extra_labels": extra_labels,
        "worktree_labels": wt_labels,
        "worktree_sessions": worktree_sessions,
        "active_days": active_days,
        "span_lo": str(span_lo)[:10],
        "span_hi": str(span_hi)[:10],
        "first_month": first_month,
        "first_day": first_day,
        "first_month_days": first_month_days,
        "last_month": last_month,
        "last_day": last_day,
        "last_month_days": last_month_days,
        "thinking_from": thinking_from,
        "thinking_version": THINKING_FIRST_VERSION,
        "busiest_day": busiest_day,
        "busiest_n": busiest_n,
        "busiest_engaged": busiest_engaged,
        "busiest_elapsed": busiest_elapsed,
        "peak_concurrent": peak_c,
        "peak_concurrent_day": peak_day,
        "offsets": offsets,
        "dst_sessions": next((n for o, n in offsets if o == "+1100"), 0),
        "dst_sessions_all": dst_all,
    }
