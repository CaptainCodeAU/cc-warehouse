"""One-off recovery for ticket 33: re-derive `hidden` for every catalog row
currently marked hidden, using the fixed parser.py classifier (SPEC 8
amendment, 2026-09-01), and render whatever newly comes back visible.

Tracked scratch tooling (outside src/), same convention as tools/ccstats/:
not part of the oracle suite, not a permanent `ccw` verb. Read-only against
sources and archive JSONL; writes only the catalog's `hidden` column (a
derived, recomputable field, not a source or stored object) and calls the
normal `ccw render` path to (re)generate the five archive files for anything
that flips.

Usage: uv run python3 tools/recover_hidden_sessions.py [--dry-run]
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cc_warehouse import catalog, config, parser  # noqa: E402

ARCHIVE_ROOT = Path.home() / "cc-warehouse-archive"
CCW_BIN = Path.home() / ".local" / "bin" / "ccw"


def find_archive_folder(session_uuid: str) -> Path | None:
    """The one archive folder named `<timestamp>_<session_uuid>` under any
    project directory. Folder-name lookup, not a re-implementation of
    archive.py's naming: cheap, and this script never WRITES a folder path,
    only reads one that already exists."""
    matches = list(ARCHIVE_ROOT.glob(f"*/*_{session_uuid}"))
    if len(matches) == 1:
        return matches[0]
    return None


def render(short: str) -> tuple[bool, str]:
    env = dict(os.environ)
    env.pop("VIRTUAL_ENV", None)
    env["PATH"] = f"{Path.home()}/.local/bin:/usr/bin:/bin"
    result = subprocess.run(
        [str(CCW_BIN), "render", "--session", f"s:{short}"],
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode != 0:
        return False, result.stderr.strip() or f"exit {result.returncode}"
    return True, ""


def main() -> int:
    dry_run = "--dry-run" in sys.argv[1:]
    cfg = config.load_config()
    conn = catalog.open_catalog(cfg.root)
    try:
        rows = conn.execute(
            "SELECT short, session_uuid FROM session WHERE hidden = 1"
        ).fetchall()
        print(f"examining {len(rows)} hidden catalog row(s)")

        flipped: list[str] = []
        rendered_ok: list[str] = []
        rendered_failed: list[tuple[str, str]] = []
        no_folder: list[str] = []
        still_hidden = 0

        for short, session_uuid in rows:
            folder = find_archive_folder(session_uuid)
            if folder is None:
                no_folder.append(short)
                continue
            jsonl_files = list(folder.glob("*.jsonl"))
            if len(jsonl_files) != 1:
                no_folder.append(short)
                continue
            data = jsonl_files[0].read_bytes()
            parsed = parser.parse_session(data)
            if parsed.hidden:
                still_hidden += 1
                continue

            flipped.append(short)
            if dry_run:
                continue
            with catalog.writing(conn):
                conn.execute("UPDATE session SET hidden = 0 WHERE short = ?", (short,))
            ok, detail = render(short)
            if ok:
                rendered_ok.append(short)
            else:
                rendered_failed.append((short, detail))

        print(f"still hidden (untouched): {still_hidden}")
        print(f"no archive folder found (untouched, not counted as flipped): {len(no_folder)}")
        for s in no_folder[:10]:
            print(f"  no folder: s:{s}")
        print(f"flipped hidden -> visible: {len(flipped)}")
        if dry_run:
            print("dry run: no catalog writes, no renders")
            return 0
        print(f"  rendered ok: {len(rendered_ok)}")
        print(f"  render failed: {len(rendered_failed)}")
        for s, detail in rendered_failed:
            print(f"    s:{s}: {detail}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
