#!/usr/bin/env python3
"""Prove the collector changed nothing, and that its numbers agree with the catalog.

Usage:
  uv run python3 tools/ccstats/verify.py snapshot   # BEFORE the collector runs
  uv run python3 tools/ccstats/verify.py compare    # AFTER it runs
  ... --out DIR   check against a non-default output root (or set CCSTATS_OUT)

`snapshot` hashes a fixed sample of source transcripts from both trees and
counts the archive folders. `compare` re-hashes the same files and fails loudly
on any difference. This proves the read-only claim by EXECUTION rather than by
reading the source, which is the project's own standing lesson: a
read-only-looking command must be proved read-only.

`compare` also reconciles first_ts / last_ts / line_count against
`~/cc-warehouse-data/catalog.sqlite` for every session present in both.
"""

from __future__ import annotations

import hashlib
import json
import random
import sys
from pathlib import Path

from common import ARCHIVE, CATALOG, LIVE, BadOut, Out, open_ro, resolve_out

SAMPLE_SIZE = 200
SEED = 20260821


def sample_files() -> list[Path]:
    """The same deterministic sample every run: 100 archive, 100 live."""
    arch = sorted(ARCHIVE.glob("*/*/*.jsonl"))
    live = sorted(LIVE.glob("*/*.jsonl"))
    rng = random.Random(SEED)
    half = SAMPLE_SIZE // 2
    picked: list[Path] = []
    if arch:
        picked += rng.sample(arch, min(half, len(arch)))
    if live:
        picked += rng.sample(live, min(half, len(live)))
    return picked


def fingerprint(paths: list[Path] | None = None) -> dict[str, object]:
    """Hash `paths`, or a fresh sample when none is given.

    `compare` MUST pass the snapshot's own paths. Re-sampling instead was a real
    defect here on 2026-08-21: the sample is drawn from a sorted listing, so two
    transcripts written by another Claude session between snapshot and compare
    shifted the whole list and `rng.sample` picked different files with the same
    seed. Files merely absent from the NEW sample were reported as VANISHED,
    which reads as data loss and is not. A file-set check must re-check the
    files it recorded, never a fresh draw.
    """
    files: dict[str, list[object]] = {}
    for path in paths if paths is not None else sample_files():
        stat = path.stat()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        files[str(path)] = [stat.st_mtime_ns, stat.st_size, digest]
    return {
        "files": files,
        "archive_folders": sum(1 for _ in ARCHIVE.glob("*/*")) if ARCHIVE.is_dir() else 0,
        "archive_jsonl": sum(1 for _ in ARCHIVE.glob("*/*/*.jsonl")) if ARCHIVE.is_dir() else 0,
        "live_jsonl": sum(1 for _ in LIVE.glob("*/*.jsonl")) if LIVE.is_dir() else 0,
    }


def do_snapshot(out: Out) -> int:
    out.ensure()
    data = fingerprint()
    out.snapshot.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"snapshot: {len(data['files'])} files hashed")  # type: ignore[arg-type]
    print(f"  archive folders : {data['archive_folders']:,}")
    print(f"  archive jsonl   : {data['archive_jsonl']:,}")
    print(f"  live jsonl      : {data['live_jsonl']:,}")
    print(f"wrote {out.snapshot}")
    return 0


def do_compare(out: Out) -> int:
    if not out.snapshot.exists():
        print("no snapshot; run `snapshot` first", file=sys.stderr)
        return 2
    before = json.loads(out.snapshot.read_text())
    b_files: dict[str, list[object]] = before["files"]

    # Re-hash exactly what was recorded, not a fresh sample.
    recorded = [Path(p) for p in b_files]
    missing = [p for p in recorded if not p.exists()]
    after = fingerprint([p for p in recorded if p.exists()])
    failures: list[str] = []

    # Counts may GROW while this runs: other Claude Code sessions on this
    # machine write new transcripts continuously, and the daily sweep captures
    # them. Growth is normal. A DROP is the thing that would mean data loss.
    for key in ("archive_folders", "archive_jsonl", "live_jsonl"):
        b, a = before[key], after[key]
        if a < b:
            failures.append(f"{key} SHRANK: {b:,} -> {a:,}")
        elif a > b:
            print(f"  note: {key} grew {b:,} -> {a:,} (other sessions are running; expected)")

    for path in missing:
        failures.append(f"VANISHED: {path}")
    a_files: dict[str, list[object]] = after["files"]
    for path, want in b_files.items():
        got = a_files.get(path)
        if got is not None and got != want:
            failures.append(f"CHANGED: {path} {want} -> {got}")

    print(f"read-only check: {len(b_files)} recorded files re-hashed")
    if failures:
        print("FAILED. The collector is NOT read-only:")
        for line in failures:
            print(f"  {line}")
        return 1
    print("  PASS: every recorded file byte-identical, mtime unchanged, none missing;"
          " no tree shrank")

    # ------------------------------------------------- catalog reconciliation
    db = out.db
    if not db.exists() or not CATALOG.exists():
        print("skipping catalog reconcile (a database is missing)")
        return 0

    conn = open_ro(db)
    # Parameterised, not interpolated: a path is data, and building SQL by
    # string concatenation is the habit that produced the hand-rolled quote
    # escaping this refactor removed elsewhere.
    conn.execute("ATTACH DATABASE ? AS cat", (f"file:{CATALOG}?mode=ro",))

    # The catalog legitimately holds SEVERAL rows per session_uuid: one per
    # capture, superseding each other. Joining on uuid alone therefore matches
    # a session against every older, shorter capture of itself and reports
    # mismatches that are not mismatches. Compare against the FULLEST capture
    # per uuid, which is the one this collector also selects.
    best = (
        "SELECT session_uuid, MAX(line_count) AS line_count FROM cat.session"
        " WHERE session_uuid IS NOT NULL GROUP BY session_uuid"
    )
    both = conn.execute(
        f"WITH b AS ({best}) SELECT COUNT(*) FROM session s"
        " JOIN b ON b.session_uuid = s.session_uuid WHERE s.is_subagent = 0"
    ).fetchone()[0]
    mismatch_ts = conn.execute(
        "SELECT COUNT(*) FROM session s JOIN cat.session c"
        " ON c.session_uuid = s.session_uuid"
        " WHERE s.is_subagent = 0 AND s.line_count = c.line_count"
        "   AND (s.first_ts IS NOT c.first_ts OR s.last_ts IS NOT c.last_ts)"
    ).fetchone()[0]
    mismatch_lines = conn.execute(
        f"WITH b AS ({best}) SELECT COUNT(*) FROM session s"
        " JOIN b ON b.session_uuid = s.session_uuid"
        " WHERE s.is_subagent = 0 AND s.line_count <> b.line_count"
    ).fetchone()[0]
    conn.close()

    print(f"catalog reconcile: {both:,} uuid pairs present in both")
    print(f"  line_count mismatches            : {mismatch_lines:,}")
    print(f"  timestamp mismatches (same lines): {mismatch_ts:,}")
    if mismatch_ts:
        print("  FAIL: the timestamp rule disagrees with parse_session")
        return 1
    print("  PASS: timestamps agree wherever the payloads are the same length")
    return 0


if __name__ == "__main__":
    _argv = sys.argv[1:]
    _mode = _argv[0] if _argv else ""
    try:
        _out = resolve_out(_argv)
    except BadOut as _exc:
        print(f"error: {_exc}", file=sys.stderr)
        raise SystemExit(2) from None
    if _mode == "snapshot":
        raise SystemExit(do_snapshot(_out))
    if _mode == "compare":
        raise SystemExit(do_compare(_out))
    print(__doc__)
    raise SystemExit(2)
