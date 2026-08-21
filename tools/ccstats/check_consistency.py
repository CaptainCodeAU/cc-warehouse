#!/usr/bin/env python3
"""Assert the workbook and the guide state the SAME numbers.

This exists because they did not. On 2026-08-21 a reviewer found the guide and
the workbook disagreeing on five figures at once: transcript count, engaged
hours, tool calls, session count and project count. Two causes, both mine.

  1. The Caveats and README sheets carried numbers as literals in the source,
     frozen at the moment the code was written, while the Overview sheet queried
     live. One workbook therefore stated two different session counts.
  2. The guide read `collect-report.json` totals, which are UNFILTERED, while
     every workbook sheet filters to `is_real = 1`.

Both are fixed by `facts.py`. This script is the fence that keeps them fixed:
it re-derives the facts, then asserts each one appears in both artefacts.

Usage: uv run python3 tools/ccstats/check_consistency.py
"""

from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import facts  # noqa: E402
from common import BadOut, BadWindow, open_ro, resolve_out, resolve_window  # noqa: E402

# (fact key, human name, formatter). Every one of these is quoted in prose in
# BOTH artefacts, so a mismatch is a real defect rather than a style difference.
CHECKED: list[tuple[str, str, str]] = [
    ("sessions_real", "real sessions", "int"),
    ("files_total", "distinct transcripts", "int"),
    ("engaged_h", "engaged hours", "float1"),
    ("active_h", "turn-duration hours", "float1"),
    ("elapsed_h", "elapsed hours", "float1"),
    ("summed_h", "summed hours", "float1"),
    ("tok_out", "output tokens", "int"),
    ("tok_cr", "cache read tokens", "int"),
    ("repos", "repositories", "int"),
    ("labels", "project labels", "int"),
    ("shell_pct", "shell percentage", "float1"),
    ("last_month_days", "days in the partial month", "int"),
    ("busiest_n", "sessions on the busiest day", "int"),
    ("peak_concurrent", "peak concurrent sessions", "int"),
]


def forms(value: object, kind: str) -> list[str]:
    """Every spelling a number might legitimately take in prose."""
    if kind == "int":
        n = int(value)  # type: ignore[arg-type]
        return [f"{n:,}", str(n)]
    v = float(value)  # type: ignore[arg-type]
    return [f"{v:,}", f"{v:,.1f}", str(v), f"{v:.1f}"]


def workbook_text(path: Path) -> str:
    """All inline-string and numeric cell content, as one searchable blob."""
    chunks: list[str] = []
    with zipfile.ZipFile(path) as zf:
        for name in zf.namelist():
            if name.startswith("xl/worksheets/"):
                raw = zf.read(name).decode("utf-8", "replace")
                chunks.append(" ".join(re.findall(r"<t>(.*?)</t>", raw, re.S)))
                chunks.append(" ".join(re.findall(r"<v>(.*?)</v>", raw, re.S)))
    return " ".join(chunks)


def main() -> int:
    try:
        out = resolve_out(sys.argv[1:])
    except BadOut as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    for path in (out.db, out.xlsx, out.doc):
        if not path.exists():
            print(f"missing {path}", file=sys.stderr)
            return 2

    try:
        window = resolve_window(sys.argv[1:], out, inherit=True)
    except BadWindow as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    since = window.since
    conn = open_ro(out.db)
    f = facts.compute(conn, window)
    conn.close()

    wb = workbook_text(out.xlsx)
    doc = out.doc.read_text(encoding="utf-8")

    failures: list[str] = []
    print(f"checking {len(CHECKED)} shared figures"
          f"{' (window from ' + since + ')' if since else ''}\n")
    for key, label, kind in CHECKED:
        want = forms(f[key], kind)
        in_wb = any(w in wb for w in want)
        in_doc = any(w in doc for w in want)
        mark = "ok  " if (in_wb and in_doc) else "FAIL"
        w, d = ("y" if in_wb else "N"), ("y" if in_doc else "N")
        print(f"  {mark} {label:<30} {want[0]:>18}   workbook={w}  guide={d}")
        if not in_wb:
            failures.append(f"{label} ({want[0]}) is not stated in the workbook")
        if not in_doc:
            failures.append(f"{label} ({want[0]}) is not stated in the guide")

    # Numbers that must NOT appear: the unfiltered totals that caused the drift.
    conn = open_ro(out.db)
    unfiltered_engaged = round(
        conn.execute("SELECT SUM(engaged_seconds)/3600.0 FROM session").fetchone()[0], 1
    )
    conn.close()
    # With a window set, the whole-corpus figure is also a wrong number to quote.
    if unfiltered_engaged != f["engaged_h"]:
        for blob, who in ((wb, "workbook"), (doc, "guide")):
            if f"{unfiltered_engaged:,}" in blob:
                failures.append(
                    f"{who} still quotes the UNFILTERED engaged hours ({unfiltered_engaged:,})"
                )
        print(f"\n  ok   unfiltered engaged hours ({unfiltered_engaged:,}) absent from both")

    print()
    if failures:
        print("INCONSISTENT:")
        for line in failures:
            print(f"  {line}")
        return 1
    print("CONSISTENT: the workbook and the guide state the same numbers.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
