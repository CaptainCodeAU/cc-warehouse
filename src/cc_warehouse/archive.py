"""Archive-first layout: one self-contained folder per session (ticket 19).

DESIGN 15 entry 2026-08-02. The product is a READABLE ARCHIVE: the projected
folder tree is the deliverable, it gets backed up, it outlives `~/.claude`, and
different consumers take the markdown, the HTML or the raw JSONL from it.

    <root>/<label>/<YYYYMMDD-HHMMSS><offset>_<uuid>/
        <uuid>.jsonl                 the source, a REAL file
        transcript.md  transcript.compact.md
        conversation.html  conversation.compact.html
        manifest.json

THE LOAD-BEARING RULE, R4 as amended 2026-08-02: once the source JSONL lives
INSIDE an archive folder, that file is store-class data sitting in the one tree
the rebuild module is allowed to delete from. This module therefore has NO
deletion primitive at all, and the fence in tests/test_fences.py enforces that
by AST. Generated files are overwritten in place by atomic_write; the JSONL is
written once and never rewritten, and no folder containing one is ever removed.
Without that rule, maintenance code can destroy the only copy.

Migration reads from `objects/`, never from `~/.claude/projects`: four stored
objects have no surviving source, and reversing the order loses them
permanently.
"""

import json
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from cc_warehouse import build, catalog, render, store
from cc_warehouse.parser import parse_session

_JSONL_SUFFIX = ".jsonl"
_MANIFEST = "manifest.json"

# Ruling (a), 2026-08-02: a file is a SESSION if any entry carries a sessionId.
# Emptiness is a SEPARATE question, already answered by the hidden flag: a
# session with no conversation is ARCHIVED (its JSONL is kept) but gets no
# markdown or HTML. Measured before adoption: the single "skip anything with no
# conversation" rule would also have discarded 139 real UUID-named sessions.
GENERATED_NAMES = (
    "transcript.md",
    "transcript.compact.md",
    "conversation.html",
    "conversation.compact.html",
    _MANIFEST,
)


@dataclass(frozen=True)
class FolderResult:
    """What one session's folder write did. `wrote_projections` is False for a
    conversation-free session, which is archived without markdown or HTML."""

    directory: Path
    jsonl: Path
    wrote_projections: bool
    replaced: bool = False
    refused_smaller: bool = False


@dataclass
class MigrationReport:
    """R10: a batch reports every failed item BY NAME and carries on.

    That rule is why the first build at scale was diagnosable at all: it named
    the nine failures and finished the other 13,599 instead of aborting on the
    first.
    """

    written: int = 0
    archived_without_projections: int = 0
    skipped_not_a_session: list[str] = field(default_factory=list[str])
    refused_smaller: list[str] = field(default_factory=list[str])
    failed: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])

    def summary(self) -> str:
        return (
            f"{self.written} folders written"
            f" ({self.archived_without_projections} archived without projections),"
            f" {len(self.skipped_not_a_session)} not sessions,"
            f" {len(self.refused_smaller)} refused as smaller,"
            f" {len(self.failed)} failed"
        )


def is_session(data: bytes) -> bool:
    """True when any entry carries a `sessionId` (ruling (a), 2026-08-02).

    Measured across all 14,066 non-agent source files, this test skips EXACTLY
    the 7 workflow journals and nothing else.
    """
    return parse_session(data).session_uuid is not None


def write_session_folder(
    archive_root: Path,
    label: str,
    data: bytes,
    options: render.RenderOptions,
    timezone: str,
    *,
    fallback_stem: str = "session",
) -> FolderResult:
    """Write one self-contained session folder. Never deletes anything.

    The JSONL is written ONCE and never rewritten: if a file already sits at
    that path, this compares sizes to decide whether the new payload supersedes
    it. Size is legal here under R1 as amended 2026-08-02 - it answers "which of
    two payloads KNOWN to differ is larger", which is a different question from
    "are these the same bytes", and only the latter is reserved to sha256.

    A refusal (the new payload is smaller) is RECORDED in manifest.json rather
    than being silent (F6).
    """
    meta = parse_session(data)
    directory = build.archive_dir(
        archive_root,
        label,
        meta.first_ts,
        meta.session_uuid,
        timezone,
        fallback_stem=fallback_stem,
    )
    directory.mkdir(parents=True, exist_ok=True)
    stem = meta.session_uuid or fallback_stem
    jsonl = directory / f"{stem}{_JSONL_SUFFIX}"

    replaced = False
    refused = False
    if jsonl.exists():
        existing = jsonl.stat().st_size
        if len(data) > existing:
            store.atomic_write(jsonl, data)
            replaced = True
        elif len(data) < existing:
            # The conservative branch (R5/F7): keep what is there, and say so.
            refused = True
        # Equal size is left alone; identical content is the common case and a
        # rewrite would churn mtimes for nothing (idempotence).
    else:
        store.atomic_write(jsonl, data)

    if meta.hidden:
        # Archived, but no markdown or HTML: today's hidden behaviour, preserved
        # deliberately by the 2026-08-02 ruling.
        return FolderResult(directory, jsonl, False, replaced, refused)

    payloads = build.projection_files(data, options)
    if refused:
        manifest = json.loads(payloads[_MANIFEST].decode("utf-8"))
        manifest["replace_refused"] = {
            "reason": "a re-captured payload was smaller than the archived one",
            "archived_bytes": jsonl.stat().st_size,
            "offered_bytes": len(data),
        }
        payloads[_MANIFEST] = (
            json.dumps(manifest, sort_keys=True, indent=2).encode("utf-8") + b"\n"
        )
    for name, payload in payloads.items():
        store.atomic_write(directory / name, payload)
    return FolderResult(directory, jsonl, True, replaced, refused)


def migrate(
    warehouse_root: Path,
    archive_root: Path,
    options: render.RenderOptions,
    timezone: str,
    *,
    progress: int = 0,
) -> MigrationReport:
    """Build the archive tree from `objects/`, beside the existing warehouse.

    Reads objects and the catalog; writes only under `archive_root`. Nothing
    under `warehouse_root` is modified or removed, so the worst outcome of a
    failure at any point is a partly-built new tree beside a completely intact
    old one.
    """
    report = MigrationReport()
    conn = catalog.open_catalog(warehouse_root)
    try:
        rows = _session_rows(conn)
    finally:
        conn.close()

    for index, (hash_, label, stem) in enumerate(rows, start=1):
        try:
            # store.object_path appends `objects/` itself; passing it again was
            # the first defect here, and R10 is why it surfaced as two named
            # items rather than as a crash on the first session.
            data = store.get(warehouse_root, hash_)
        except OSError as exc:
            report.failed.append((hash_, f"unreadable: {exc}"))
            continue
        if not is_session(data):
            report.skipped_not_a_session.append(hash_)
            continue
        try:
            result = write_session_folder(
                archive_root, label, data, options, timezone, fallback_stem=stem
            )
        except Exception as exc:  # noqa: BLE001 - R10: name it and carry on
            report.failed.append((hash_, f"{type(exc).__name__}: {exc}"))
            continue
        report.written += 1
        if not result.wrote_projections:
            report.archived_without_projections += 1
        if result.refused_smaller:
            report.refused_smaller.append(hash_)
        if progress and index % progress == 0:
            print(f"  {index}/{len(rows)} {report.summary()}", flush=True)
    return report


def _session_rows(conn: sqlite3.Connection) -> list[tuple[str, str, str]]:
    """(hash, project label, fallback stem) for every session the catalog holds.

    EVERY row, not only heads: the archive keeps what it was given, and the
    supersede chain is a catalog concept that the folder name resolves anyway
    (same uuid, same start time, same folder).
    """
    sql = (
        "SELECT s.hash, p.label, s.short"
        " FROM session s JOIN project p ON p.id = s.project_id"
    )
    out: list[tuple[str, str, str]] = []
    for row in conn.execute(sql).fetchall():
        out.append((str(row[0]), str(row[1]), f"session-{row[2]}"))
    return out


PROJECT_JSON = "project.json"


@dataclass(frozen=True)
class Alias:
    path: str
    kind: str


@dataclass(frozen=True)
class ProjectRecord:
    label: str
    aliases: tuple[Alias, ...]


def write_project_files(warehouse_root: Path, archive_root: Path) -> int:
    """One `project.json` per project folder: label plus every known path.

    This is what makes the catalog a DISPOSABLE INDEX rather than a load-bearing
    database (DESIGN 15, 2026-08-02). The LABEL survives without it, because the
    label IS the parent folder name. What does not survive is `project_alias`,
    which maps the encoded dirs and cwds Claude Code used to the name the
    operator chose; lose it and the next capture splits a renamed project in
    two. Until this file exists, "the catalog can be deleted and rebuilt by a
    rescan" is a claim the product cannot honour, and an unhonoured guarantee is
    the F6 class this project exists to ban.
    """
    conn = catalog.open_catalog(warehouse_root)
    try:
        rows = conn.execute(
            "SELECT p.label, a.path, a.kind FROM project_alias a"
            " JOIN project p ON p.id = a.project_id"
            " ORDER BY p.label, a.kind, a.path"
        ).fetchall()
        labels = [str(row[0]) for row in conn.execute("SELECT label FROM project").fetchall()]
    finally:
        conn.close()

    grouped: dict[str, list[Alias]] = {label: [] for label in labels}
    for row in rows:
        grouped.setdefault(str(row[0]), []).append(Alias(str(row[1]), str(row[2])))

    written = 0
    for label, aliases in grouped.items():
        directory = archive_root / (build.component(label) or "_unlabeled")
        if not directory.is_dir():
            # A project with no surviving session has no folder to describe.
            continue
        payload = {
            "label": label,
            "aliases": [{"path": a.path, "kind": a.kind} for a in aliases],
        }
        store.atomic_write(
            directory / PROJECT_JSON,
            json.dumps(payload, sort_keys=True, indent=2).encode("utf-8") + b"\n",
        )
        written += 1
    return written


def read_projects(archive_root: Path) -> list[ProjectRecord]:
    """Every project the TREE describes, read without touching a database.

    The round trip that proves the catalog is disposable: delete it, call this,
    and the labels and aliases come back. A folder with no sidecar, or a corrupt
    one, is SKIPPED rather than fatal (R5) - a rescan that dies on the first gap
    is a rescan nobody can run on a real archive.
    """
    out: list[ProjectRecord] = []
    for label_dir in sorted(p for p in archive_root.iterdir() if p.is_dir()):
        sidecar = label_dir / PROJECT_JSON
        if not sidecar.is_file():
            continue
        try:
            loaded: object = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(loaded, dict):
            continue
        payload = cast(dict[str, object], loaded)
        label = payload.get("label")
        raw = payload.get("aliases")
        if not isinstance(label, str) or not isinstance(raw, list):
            continue
        aliases: list[Alias] = []
        for element in cast(list[object], raw):
            if not isinstance(element, dict):
                continue
            item = cast(dict[str, object], element)
            path, kind = item.get("path"), item.get("kind")
            if isinstance(path, str) and isinstance(kind, str):
                aliases.append(Alias(path, kind))
        out.append(ProjectRecord(label, tuple(aliases)))
    return out


@dataclass(frozen=True)
class FolderProblem:
    directory: Path
    problem: str


def verify_folder(directory: Path, timezone: str) -> list[FolderProblem]:
    """Archive integrity for one folder (ruling (b), 2026-08-02).

    Three questions, all answerable from the folder alone with no vault and no
    catalog: does the JSONL still match the `source_hash` its manifest recorded,
    are all five generated files present, and does the folder NAME agree with
    the payload's own uuid and start time.
    """
    problems: list[FolderProblem] = []
    jsonl = _sole_jsonl(directory)
    if jsonl is None:
        return [FolderProblem(directory, "no session JSONL in the folder")]

    manifest_path = directory / _MANIFEST
    data = jsonl.read_bytes()
    meta = parse_session(data)

    if meta.hidden:
        # Archived without projections by design; only the name is checkable.
        return _name_problems(directory, meta, timezone)

    for name in GENERATED_NAMES:
        if not (directory / name).exists():
            problems.append(FolderProblem(directory, f"missing {name}"))
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            recorded = str(manifest.get("source_hash", ""))
        except (OSError, ValueError) as exc:
            problems.append(FolderProblem(directory, f"unreadable manifest: {exc}"))
            recorded = ""
        if recorded and recorded != store.sha256_hex(data):
            problems.append(
                FolderProblem(directory, "JSONL does not match manifest source_hash")
            )
    problems.extend(_name_problems(directory, meta, timezone))
    return problems


def _name_problems(directory: Path, meta: object, timezone: str) -> list[FolderProblem]:
    from cc_warehouse.parser import ParsedSession

    assert isinstance(meta, ParsedSession)
    expected = build.archive_folder_name(
        meta.first_ts, meta.session_uuid, timezone, fallback_stem=directory.name.split("_", 1)[-1]
    )
    if directory.name != expected:
        return [
            FolderProblem(directory, f"folder name disagrees with its payload: want {expected}")
        ]
    return []


def _sole_jsonl(directory: Path) -> Path | None:
    files = sorted(p for p in directory.glob(f"*{_JSONL_SUFFIX}") if p.is_file())
    return files[0] if files else None


def walk_folders(archive_root: Path) -> Iterator[Path]:
    """Every session folder in the archive, in sorted order.

    `<root>/<label>/<session>/`, exactly two levels, so a stray file at either
    level is skipped rather than mistaken for a session.
    """
    for label_dir in sorted(p for p in archive_root.iterdir() if p.is_dir()):
        if label_dir.name in build.RESERVED_LABELS:
            continue
        yield from sorted(p for p in label_dir.iterdir() if p.is_dir())
