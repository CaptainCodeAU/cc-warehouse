"""One-off repair for W-20261001-A56: move uuid-less session folders from the
name the pre-fix capture hook wrote to the name every reader looks for.

    old: <archive>/<label>/<stamp>_session/session.jsonl
    new: <archive>/<label>/<stamp>_session-<short>/session-<short>.jsonl

Tracked scratch tooling (outside src/), same convention as tools/ccstats/ and
tools/recover_hidden_sessions.py: not part of the oracle suite, not a `ccw`
verb. Its tests are tests/test_rename_uuidless_tool.py.

RULES, each one a refusal rather than a guess:
- DRY RUN unless `--apply`; `--apply` needs `--record`, a path that must not
  exist yet, so every rename can be reversed from it.
- The catalog is opened read-only (`?mode=ro`). Nothing is written to it.
- A row is acted on only when the old JSONL exists AND its sha256 is that
  row's hash. Otherwise SKIP with the reason: a folder holding some other
  payload is not this row's to move.
- REFUSE when the new folder already exists. Never overwrite, never delete.
- The folder is renamed first, then the JSONL inside it, so anything else in
  the folder moves with it. Both are same-volume `os.rename` calls.
- The archive root's own marker must name `--zone`, the zone folder names are
  rendered in (ticket 44a); a mismatch stops before anything is read.

Usage:
    uv run python3 tools/rename_uuidless_folders.py \\
        --archive-root DIR --catalog FILE --zone ZONE [--apply --record FILE]
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cc_warehouse import archive, build, store  # noqa: E402

# The bare stem the pre-fix writers used. Named here only to find what they
# left behind; nothing in src/ may use it any more.
_LEGACY_STEM = "session"


@dataclass(frozen=True)
class Plan:
    short: str
    sha256: str
    old_jsonl: Path
    new_jsonl: Path
    verdict: str  # RENAME | SKIP | REFUSE
    reason: str


def _rows(catalog_path: Path) -> list[tuple[str, str, str, str | None]]:
    """(hash, short, label, first_ts) for every uuid-less catalog row."""
    conn = sqlite3.connect(f"file:{catalog_path}?mode=ro", uri=True)
    try:
        return [
            (str(r[0]), str(r[1]), str(r[2]), None if r[3] is None else str(r[3]))
            for r in conn.execute(
                "SELECT s.hash, s.short, p.label, s.first_ts FROM session s"
                " JOIN project p ON p.id = s.project_id"
                " WHERE s.session_uuid IS NULL ORDER BY p.label, s.first_ts, s.short"
            ).fetchall()
        ]
    finally:
        conn.close()


def plan(archive_root: Path, catalog_path: Path, zone: str) -> list[Plan]:
    out: list[Plan] = []
    for sha256, short, label, first_ts in _rows(catalog_path):
        stem = build.session_stem(None, short)
        old_dir = build.archive_dir(
            archive_root, label, first_ts, None, zone, fallback_stem=_LEGACY_STEM
        )
        new_dir = build.archive_dir(archive_root, label, first_ts, None, zone, fallback_stem=stem)
        old_jsonl = old_dir / f"{_LEGACY_STEM}.jsonl"
        new_jsonl = new_dir / f"{stem}.jsonl"
        kind, reason = _verdict(sha256, old_jsonl, new_jsonl)
        out.append(Plan(short, sha256, old_jsonl, new_jsonl, kind, reason))
    return out


def _verdict(sha256: str, old_jsonl: Path, new_jsonl: Path) -> tuple[str, str]:
    new_dir = new_jsonl.parent
    if new_dir.exists():
        if new_jsonl.is_file() and store.sha256_hex(new_jsonl.read_bytes()) == sha256:
            return "SKIP", "already at the new name"
        return "REFUSE", f"new folder already exists: {new_dir}"
    if not old_jsonl.is_file():
        return "SKIP", f"no old JSONL at {old_jsonl}"
    if store.sha256_hex(old_jsonl.read_bytes()) != sha256:
        return "SKIP", "old JSONL hash is not the catalog's"
    return "RENAME", ""


def _write_record(path: Path, renames: list[dict[str, str]]) -> None:
    """tmp file + os.replace (DESIGN R2), rewritten after every rename so a
    crash part-way leaves a record of exactly what moved."""
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps({"renames": renames}, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _rel(archive_root: Path, path: Path) -> str:
    return str(path.relative_to(archive_root))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--archive-root", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--zone", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--record", type=Path)
    args = parser.parse_args(argv)
    archive_root: Path = args.archive_root
    record: Path | None = args.record

    if args.apply and record is None:
        parser.error("--apply needs --record FILE, so every rename can be reversed")
    if record is not None and (record.exists() or record.is_symlink()):
        parser.error(f"--record {record} already exists; it is never overwritten")
    problem = archive.root_problem(archive_root, args.zone, warehouse_root=None)
    if problem is not None:
        parser.error(f"archive root refused: {problem}")
    if not args.catalog.is_file():
        parser.error(f"no catalog at {args.catalog}")

    plans = plan(archive_root, args.catalog, args.zone)
    renames: list[dict[str, str]] = []
    skipped = refused = 0
    for item in plans:
        old_dir, new_dir = item.old_jsonl.parent, item.new_jsonl.parent
        if item.verdict == "SKIP":
            skipped += 1
            print(f"SKIP s:{item.short}: {item.reason}")
            continue
        if item.verdict == "REFUSE":
            refused += 1
            print(f"REFUSE s:{item.short}: {item.reason}")
            continue
        print(f"RENAME {_rel(archive_root, old_dir)} -> {_rel(archive_root, new_dir)}")
        if not args.apply:
            continue
        assert record is not None
        # Re-checked at the moment of acting: a plan is a claim about the past.
        if new_dir.exists() or not item.old_jsonl.is_file():
            refused += 1
            print(f"REFUSE s:{item.short}: tree changed since the plan")
            continue
        old_dir.rename(new_dir)
        (new_dir / item.old_jsonl.name).rename(item.new_jsonl)
        renames.append({
            "old": str(item.old_jsonl),
            "new": str(item.new_jsonl),
            "sha256": item.sha256,
            "at": datetime.now(UTC).isoformat(),
        })
        _write_record(record, renames)

    if args.apply:
        assert record is not None
        if not renames:
            _write_record(record, renames)
        print(f"{len(renames)} renamed, {skipped} skipped, {refused} refused; record: {record}")
    else:
        to_rename = sum(1 for p in plans if p.verdict == "RENAME")
        print(
            f"{to_rename} to rename, {skipped} skipped, {refused} refused"
            " (dry run; nothing changed, --apply --record FILE to act)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
