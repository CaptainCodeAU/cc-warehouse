"""Rebuild `catalog.sqlite` from the archive tree alone (ticket 27, slice 27.1).

DESIGN 15 calls the catalog a DISPOSABLE INDEX. Until this module existed that
was a claim with nothing behind it: `archive.read_projects` could reconstruct
labels and aliases from the tree, and no verb called it. Stating a guarantee the
code does not keep is the F6 class this project exists to eliminate, so the fix
is a rebuild anyone can run, not a paragraph asserting one is possible.

WHAT A REBUILD CANNOT GIVE BACK, stated here and reported by the verb, because
an incomplete restore that presents itself as complete is the same F6 class one
level down:

  - `capture_event` history. The archive never held it. After a rebuild
    `ccw status` has no "last errors" and no capture timings, and that is a
    permanent loss rather than an empty table waiting to fill.
  - Superseded VERSIONS. An archive folder is keyed by session uuid plus start
    time, so every version of one session maps to one folder and only the
    surviving copy is on disk. The rebuilt catalog therefore holds one row per
    uuid and no `supersedes` chain.
  - `captured_at`, which is warehouse bookkeeping and not a payload fact. It is
    approximated from the JSONL's mtime, which is the closest thing the tree
    records, and is wrong by design on any tree that has been copied.

ORDER OF INSERTION IS LOAD BEARING. `catalog.add_session` makes the newest
INSERT the head of a version chain regardless of what the payload says (ticket
29 mechanism 1, proved by execution 2026-08-05 and still open). A rebuild that
walked the tree in directory order would therefore make an arbitrary copy
current. Sessions are sorted by payload time and inserted oldest first, which
sidesteps the open defect instead of depending on it being fixed first.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from cc_warehouse import archive, build, catalog, parser, store

_SOURCE_KIND = "claude_code"
_CATALOG = "catalog.sqlite"
_UNLABELED = "_unlabeled"


@dataclass
class ReindexReport:
    """What a rebuild found, including everything it could not restore."""

    projects: int = 0
    aliases: int = 0
    sessions: int = 0
    sidecar_missing: list[str] = field(default_factory=lambda: cast(list[str], []))
    sidecar_unreadable: list[str] = field(default_factory=lambda: cast(list[str], []))
    failed: list[tuple[str, str]] = field(default_factory=lambda: cast(list[tuple[str, str]], []))

    def summary(self) -> str:
        return (
            f"reindex: {self.projects} projects, {self.aliases} aliases,"
            f" {self.sessions} sessions, {len(self.failed)} failed"
        )


@dataclass(frozen=True)
class _Pending:
    """One session folder, parsed and waiting for its ordered insert."""

    sort_key: str
    directory: Path
    project_id: int
    meta: catalog.SessionMeta
    # Read while the JSONL was already in hand. Deriving it at insert time
    # instead cost a second directory glob for every session in the archive.
    captured_at: str


def _label_dirs(archive_root: Path) -> list[Path]:
    """Project folders, in the same terms `archive.walk_folders` uses (R9)."""
    return sorted(
        p
        for p in archive_root.iterdir()
        if p.is_dir() and p.name not in build.RESERVED_LABELS
    )


def _project_rows(
    conn: sqlite3.Connection, archive_root: Path, now: str, report: ReindexReport
) -> dict[str, int]:
    """A project row per label FOLDER, and every alias the sidecars still carry.

    `archive.read_projects` is the single reader of a `project.json` (R9); this
    function only decides what to do about the folders it did not cover. It does
    NOT skip them the way `read_projects` does, because a skipped folder's
    sessions would have no `project_id` to attach to and would vanish from the
    rebuild entirely. Without a sidecar the label falls back to the folder name,
    which is lossy (the sanitizer that produced the folder name is not
    reversible) and is why the count is reported rather than absorbed.
    """
    records = {
        build.component(record.label) or _UNLABELED: record
        for record in archive.read_projects(archive_root)
    }
    ids: dict[str, int] = {}
    for label_dir in _label_dirs(archive_root):
        record = records.get(label_dir.name)
        if record is None:
            label, aliases = label_dir.name, ()
            if (label_dir / "project.json").exists():
                report.sidecar_unreadable.append(label_dir.name)
            else:
                report.sidecar_missing.append(label_dir.name)
        else:
            label, aliases = record.label, record.aliases
        with catalog.writing(conn):
            row = conn.execute(
                "INSERT INTO project (label, created_at) VALUES (?, ?) RETURNING id",
                (label, now),
            ).fetchone()
            project_id = cast(int, cast("tuple[object, ...]", row)[0])
            for alias in aliases:
                # A path/kind pair is UNIQUE in the schema, so a sidecar that
                # names the same alias twice must not abort the whole rebuild.
                conn.execute(
                    "INSERT OR IGNORE INTO project_alias (project_id, path, kind,"
                    " first_seen, last_seen) VALUES (?, ?, ?, ?, ?)",
                    (project_id, alias.path, alias.kind, now, now),
                )
        ids[label_dir.name] = project_id
        report.projects += 1
        report.aliases += len(aliases)
    return ids


def _captured_at(jsonl: Path) -> str:
    """The closest thing the tree records to when this session was captured.

    Not a payload fact and not recoverable: see the module docstring. Reported
    as an approximation rather than presented as the original.
    """
    stamp = datetime.fromtimestamp(jsonl.stat().st_mtime, tz=UTC)
    return stamp.isoformat(timespec="seconds").replace("+00:00", "Z")


def _pending_sessions(
    archive_root: Path, ids: dict[str, int], report: ReindexReport
) -> list[_Pending]:
    """Parse every session folder. A folder that will not parse is NAMED and
    skipped, never fatal (R10): a batch that aborts on the first bad item is
    what makes a real-corpus failure undiagnosable."""
    pending: list[_Pending] = []
    for directory in archive.walk_folders(archive_root):
        project_id = ids.get(directory.parent.name)
        if project_id is None:
            continue
        jsonl = archive.sole_jsonl(directory)
        if jsonl is None:
            report.failed.append((directory.name, "no session JSONL in the folder"))
            continue
        try:
            data = jsonl.read_bytes()
            parsed = parser.parse_session(data)
        except (OSError, ValueError) as exc:
            report.failed.append((directory.name, f"{type(exc).__name__}: {exc}"))
            continue
        if parsed.line_count == 0 or parsed.skipped_lines >= parsed.line_count:
            # `parse_session` does not RAISE on rubbish, it counts it: a file of
            # garbage comes back as line_count == skipped_lines with no uuid and
            # no timestamps. Measured 2026-08-05 rather than assumed, after a
            # first guard keyed on `session_uuid is None and line_count == 0`
            # indexed a corrupt payload as a real session. Using the parser's
            # own loss telemetry beats inventing a second notion of "readable".
            report.failed.append(
                (directory.name, f"no readable entries ({parsed.skipped_lines} lines skipped)")
            )
            continue
        meta = catalog.SessionMeta(
            sha256=store.sha256_hex(data),
            source_kind=_SOURCE_KIND,
            session_uuid=parsed.session_uuid,
            slug=parsed.slug,
            git_branch=parsed.git_branch,
            cwd=parsed.cwd,
            first_ts=parsed.first_ts,
            last_ts=parsed.last_ts,
            size_bytes=len(data),
            line_count=parsed.line_count,
            skipped_lines=parsed.skipped_lines,
            summary=parsed.summary,
            hidden=parsed.hidden,
            # The tree cannot say how the original capture resolved its project,
            # and inventing one of the four real values would be a fabrication.
            resolution_source="reindex",
        )
        pending.append(
            _Pending(
                sort_key=parsed.last_ts or parsed.first_ts or "",
                directory=directory,
                project_id=project_id,
                meta=meta,
                captured_at=_captured_at(jsonl),
            )
        )
    return pending


def rebuild(archive_root: Path, target_root: Path, dry_run: bool = False) -> ReindexReport:
    """Rebuild `catalog.sqlite` at `target_root` from `archive_root` alone.

    The catalog is built as a TEMPORARY FILE beside the live one and moved into
    place with `os.replace` (R2), so a half-built index is never observable and
    an interrupted rebuild leaves the previous catalog intact.

    THIS SHAPE WAS CHOSEN BY A FENCE, and the fence was right. The first version
    staged into a temporary DIRECTORY and removed it with `shutil.rmtree`, which
    tripped `test_no_deletion_primitives_outside_rebuild_modules` (R4: file
    removal lives only in the projections/shares rebuild modules and the lock
    helpers, a CLOSED LIST). The available dodges were adding this module to that
    list, or reaching for `tempfile.TemporaryDirectory` whose cleanup the fence
    cannot see. Both were declined: a fence anyone can defeat with a synonym is
    worse than no fence. R2's own words are "tmp FILE plus os.replace", so the
    fence was pointing at the sanctioned shape rather than blocking the work.

    The staging name is FIXED rather than pid-stamped, so a rebuild that dies
    midway leaves at most one stale file which the next run TRUNCATES and
    reuses, instead of accumulating one per crash. Truncating is a write, not a
    delete, and it is load bearing: `open_catalog_at` creates its tables IF NOT
    EXISTS, so an inherited file would otherwise be added to rather than rebuilt.

    A DRY RUN stages outside the warehouse entirely. It does the same work, so
    it needs the same scratch file, but a rehearsal that leaves a new file in
    the warehouse root is not a rehearsal (ticket 23's rule).
    """
    report = ReindexReport()
    now = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

    target_root.mkdir(parents=True, exist_ok=True)
    staging = (
        Path(tempfile.gettempdir()) / f"ccw-{_CATALOG}.reindex-dry-run"
        if dry_run
        else target_root / f".{_CATALOG}.tmp-reindex"
    )
    # Through the sanctioned primitive, not a raw handle: a SECOND fence
    # (`test_write_handles_only_in_sanctioned_modules`) caught `.write_bytes`
    # here, and R2 means every write, including a zero-byte one whose only job
    # is to reset an inherited staging file.
    store.atomic_write(staging, b"")
    conn = catalog.open_catalog_at(staging)
    try:
        ids = _project_rows(conn, archive_root, now, report)
        pending = _pending_sessions(archive_root, ids, report)
        # Oldest first: see the module docstring on ticket 29 mechanism 1.
        for item in sorted(pending, key=lambda p: (p.sort_key, p.directory.name)):
            catalog.add_session(conn, item.meta, item.project_id, item.captured_at)
            report.sessions += 1
    finally:
        conn.close()
    if not dry_run and report.sessions:
        os.replace(staging, target_root / _CATALOG)
    return report
