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

from cc_warehouse import build, catalog, parser, render, store
from cc_warehouse.config import Config
from cc_warehouse.parser import parse_session

_JSONL_SUFFIX = ".jsonl"
_MANIFEST = "manifest.json"

# The O_EXCL lock this operation runs under (R14). Public so the CLI and the
# oracle tests name the same lock rather than two spellings of it.
ARCHIVE_LOCK = "archive"

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
    # R14: a live holder makes the run refuse rather than interleave. Reported
    # as its own field so the CLI can exit non-zero on a refusal WITHOUT
    # counting a no-op that wrote nothing as a success.
    lock_held: bool = False
    skipped_not_a_session: list[str] = field(default_factory=list[str])
    refused_smaller: list[str] = field(default_factory=list[str])
    failed: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])

    def summary(self) -> str:
        if self.lock_held:
            return "refused: the archive lock is held by a live holder"
        return (
            f"{self.written} folders written"
            f" ({self.archived_without_projections} archived without projections),"
            f" {len(self.skipped_not_a_session)} not sessions,"
            f" {len(self.refused_smaller)} refused as smaller,"
            f" {len(self.failed)} failed"
        )


_CONVERSATION_ROLES = ("user", "assistant")


def agent_id_of(data: bytes) -> str | None:
    """The `agentId` of a sub-agent transcript, or None if this is not one.

    THE DISCRIMINATOR, and it is measured rather than assumed. "Any entry has an
    agentId" is WRONG twice over: a main session's `started` / `result` entries
    carry one (173 of each in the corpus), and a main session that embeds
    sidechain entries carries one on those. Both would be misread as sub-agent
    transcripts, and the second was caught by a fixture rather than by reasoning.

    What separates them cleanly, sampled 2026-08-03 over 200 sub-agent files and
    1,500 main sessions: in a sub-agent transcript EVERY conversational entry
    carries the agentId (10,182 of 10,182, 100%); in a main session NONE do
    (0 of 34,732). A session that merely embeds a sidechain has some but not
    all, so requiring ALL of them keeps it a session.

    Identity from CONTENT, never from the filename. `agent-` is a path
    convention of `~/.claude`, and F4 exists because the specimen derived
    identity from paths and it cost it correctness.
    """
    found: str | None = None
    seen = 0
    for entry in parser.entries_of(data):
        if entry.get("type") not in _CONVERSATION_ROLES:
            continue
        seen += 1
        value = entry.get("agentId")
        if not isinstance(value, str) or not value:
            return None  # one conversational entry without it is enough
        found = found or value
    return found if seen else None


def parent_uuid_of(data: bytes) -> str | None:
    """The session a sub-agent belongs to: its `sessionId`, which is the
    PARENT'S uuid rather than its own (measured across all 1,420 real files)."""
    return parse_session(data).session_uuid


def is_subagent(data: bytes) -> bool:
    """True when this payload is a sub-agent transcript rather than a session."""
    return agent_id_of(data) is not None


def is_session(data: bytes) -> bool:
    """True when any entry carries a `sessionId` AND no `agentId`.

    Ruling (a), 2026-08-02, said a file is a session if any entry carries a
    sessionId. NARROWED 2026-08-03 (ticket 21) after measuring what sub-agent
    transcripts actually contain: all 1,420 carry a sessionId, and the value is
    THE PARENT'S. So the rule as written says yes to every sub-agent file, and
    acting on it would compute the parent's folder, name the payload
    `<parent-uuid>.jsonl`, and let the replace-if-larger rule OVERWRITE the
    parent's transcript - the common case, not the edge one, since a sub-agent
    has a median 192 KB against a session's 3.7 KB.

    The rule was right about what it was written for and blind to a case absent
    from the corpus it was measured on. It is narrowed, not replaced: the
    7 workflow journals it was written to exclude are still excluded.
    """
    return parse_session(data).session_uuid is not None and not is_subagent(data)


# Where a sub-agent goes when its parent session is not in the archive. Measured
# 2026-08-03: ZERO of the 1,420 real sub-agents are orphaned against the
# warehouse, so this is a net for a case that does not exist yet - which is
# exactly when it is cheap to build and expensive to retrofit.
ORPHAN_LABEL = "_orphaned-subagents"
SUBAGENTS_DIR = "subagents"
_META = "meta.json"

# Where a payload that is NOT a session lives (ticket 25.6). Reserved in
# build.RESERVED_LABELS, so walk_folders never yields its children as session
# folders; an unreserved name here would make `ccw archive --verify` report
# every file under it as a malformed session.
NOT_SESSIONS_LABEL = "_not-sessions"

# Non-sessions that arrived through `ccw import`, kept apart from the workflow
# journals so the tree says where each came from.
IMPORTED_DIR = "imported"
_ORPHAN_NOTE = "orphan.json"


@dataclass(frozen=True)
class SubagentResult:
    directory: Path
    jsonl: Path
    orphaned: bool = False
    replaced: bool = False
    refused_smaller: bool = False


def write_subagent(
    archive_root: Path,
    label: str,
    data: bytes,
    timezone: str,
    *,
    meta: bytes | None = None,
) -> SubagentResult:
    """Write one sub-agent transcript inside the session that spawned it.

        <label>/<stamp>_<parent-uuid>/subagents/<stamp>_<agentId>/
            <agentId>.jsonl
            meta.json

    A FOLDER per sub-agent rather than a loose file, and the reason is the
    principal's stated future: markdown and HTML for sub-agents. Loose files make
    that day a restructure of every session folder in a 13,829-folder archive;
    folders make it purely additive. The container costs nothing now.

    NO markdown or HTML is generated here. That is the default the principal set:
    sub-agents are archived, not rendered, with a flag for it recorded as future
    work.

    `meta.json` is Claude Code's companion file and it travels with the payload,
    because it is the only record of what the agent WAS (`agentType`,
    `description`). Losing it leaves folders nobody can tell apart.

    When the parent's folder does not exist the transcript is NOT dropped and NOT
    silently attached to something else: it goes to `<label>/_orphaned-subagents/`
    with a note naming the parent it is waiting for.
    """
    agent_id = agent_id_of(data)
    if agent_id is None:
        raise ValueError("payload is not a sub-agent transcript; use write_session_folder")

    meta_parsed = parse_session(data)
    parent = _parent_folder(archive_root, label, meta_parsed.session_uuid, timezone)
    orphaned = parent is None
    if parent is None:
        directory = (
            archive_root
            / build.component(ORPHAN_LABEL)
            / build.component(label)
            / build.subagent_folder_name(meta_parsed.first_ts, agent_id, timezone)
        )
    else:
        directory = parent / SUBAGENTS_DIR / build.subagent_folder_name(
            meta_parsed.first_ts, agent_id, timezone
        )
    directory.mkdir(parents=True, exist_ok=True)

    jsonl = directory / f"{agent_id}{_JSONL_SUFFIX}"
    replaced = refused = False
    if not jsonl.exists():
        store.atomic_write(jsonl, data)
    else:
        # R1 as amended: size answers "which of two payloads KNOWN to differ is
        # larger", never "are these the same bytes".
        existing = jsonl.stat().st_size
        if len(data) > existing:
            store.atomic_write(jsonl, data)
            replaced = True
        elif len(data) < existing:
            refused = True

    if meta is not None:
        store.atomic_write(directory / _META, meta)
    if orphaned:
        note = {
            "parent_session_uuid": meta_parsed.session_uuid,
            "agent_id": agent_id,
            "reason": "the parent session was not in the archive when this was written",
        }
        store.atomic_write(
            directory / _ORPHAN_NOTE,
            json.dumps(note, sort_keys=True, indent=2).encode("utf-8") + b"\n",
        )
    return SubagentResult(directory, jsonl, orphaned, replaced, refused)


def _parent_folder(
    archive_root: Path, label: str, parent_uuid: str | None, timezone: str
) -> Path | None:
    """The parent session's folder, or None when it is not in the archive.

    Found by SCANNING for the uuid suffix rather than computing the name,
    because the folder name encodes the parent's own start time and a sub-agent
    does not know it. Scoped to the one project directory, so this is a listing
    rather than a walk.
    """
    if not parent_uuid:
        return None
    project = archive_root / (build.component(label) or "_unlabeled")
    if not project.is_dir():
        return None
    suffix = f"_{parent_uuid}"
    for child in project.iterdir():
        if child.is_dir() and child.name.endswith(suffix):
            return child
    return None


def subagent_records(session_dir: Path) -> list[dict[str, object]]:
    """This session's sub-agents, as the manifest records them (ticket 21e).

    Without this a deleted sub-agent folder is UNDETECTABLE: verify would see
    five valid files, a matching source hash and a correct folder name, and
    report clean. That is the most dangerous kind of green.
    """
    subs = session_dir / SUBAGENTS_DIR
    if not subs.is_dir():
        return []
    out: list[dict[str, object]] = []
    for folder in sorted(p for p in subs.iterdir() if p.is_dir()):
        for jsonl in sorted(folder.glob(f"*{_JSONL_SUFFIX}")):
            payload = jsonl.read_bytes()
            out.append({
                "agent_id": jsonl.stem,
                "sha256": store.sha256_hex(payload),
                "bytes": len(payload),
            })
    return out


def read_payload(
    config: Config,
    *,
    label: str,
    first_ts: str | None,
    session_uuid: str | None,
    short: str,
    sha256: str,
) -> bytes:
    """One session's JSONL, preferring the archive over the store (slice 19l).

    THE reader. `store.get` was the read path in four places - render, build and
    share twice - so retiring `objects/` would have broken every one of them
    independently. A fence in tests/test_archive_reads.py keeps it at one.

    THE READ IS VERIFIED, NOT TRUSTED. The catalog names a session by sha256 and
    the archive holds a file; a file sitting in the right folder is not evidence
    that it IS that session. Serving it unchecked would be identity-by-location,
    the same class as F1's identity-by-size with a different cheap proxy. So the
    bytes are hashed against the hash the caller named, and a mismatch falls back
    to the store rather than being served.

    When the store cannot answer either, this RAISES. That is the conservative
    branch (R5/F7) and it matters most after `objects/` retires, when there is no
    fallback left: refusing is recoverable, serving the wrong session silently is
    the failure this project exists to prevent.
    """
    if config.archive_root is not None:
        stem = session_uuid or f"session-{short}"
        directory = build.archive_dir(
            config.archive_root,
            label,
            first_ts,
            session_uuid,
            config.archive_timezone,
            fallback_stem=f"session-{short}",
        )
        candidate = directory / f"{stem}{_JSONL_SUFFIX}"
        if candidate.is_file():
            data = candidate.read_bytes()
            if store.sha256_hex(data) == sha256:
                return data
            # Mismatch: the archive holds SOMETHING, but not the session asked
            # for. Fall through to the store, which is still authoritative while
            # it exists; once it does not, the get below raises and says so.
    return store.get(config.root, sha256)


def write_source(
    archive_root: Path,
    label: str,
    data: bytes,
    timezone: str,
    *,
    fallback_stem: str = "session",
) -> Path:
    """Write ONLY the session's JSONL into its archive folder, and nothing else.

    The durability half of write_session_folder, split out so the HOOK can run
    it synchronously before it returns (slice 19k). Rendering is left to the
    detached child, exactly as it is for a projection today: durable write
    first, rendering second.

    That split is what makes `objects/` retirable at all. While the archive got
    its JSONL from the render child, a child that never ran - a crash, a kill, a
    full disk, an OS that declined the spawn - would have meant a session that
    existed only in `~/.claude`. The content-addressed store is what makes the
    current design safe, so whatever replaces it has to take the same job on.
    """
    meta = parse_session(data)
    directory = build.archive_dir(
        archive_root, label, meta.first_ts, meta.session_uuid, timezone,
        fallback_stem=fallback_stem,
    )
    directory.mkdir(parents=True, exist_ok=True)
    jsonl = directory / f"{meta.session_uuid or fallback_stem}{_JSONL_SUFFIX}"
    if not jsonl.exists():
        store.atomic_write(jsonl, data)
        return jsonl
    # Same rule as write_session_folder: the LARGER payload wins, a smaller one
    # is refused, an equal one is left alone so re-capture does not churn the
    # mtime. Size here answers "which of two payloads known to differ is
    # larger", never "are these the same bytes" (R1 as amended 2026-08-02).
    if len(data) > jsonl.stat().st_size:
        store.atomic_write(jsonl, data)
    return jsonl


def write_not_a_session(archive_root: Path, data: bytes, *, stem: str) -> Path:
    """Rescue a payload that is NOT a session into the archive's reserved home.

    Ruling (a) as narrowed by ticket 21: a file is a session when it carries a
    `sessionId` and no `agentId`. The 7 workflow journals carry neither, and
    neither do the 2 Cursor transcripts measured in the legacy exporter tree on
    2026-08-04. They exist in exactly one place, so they are KEPT; they are not
    sessions, so they cannot be given a session folder, whose name is a pure
    function of a sessionId and a first timestamp that neither of them has. Two
    such payloads would otherwise both compute `undated_session/session.jsonl`
    and the larger would silently displace the smaller.

    The filename is CONTENT-ADDRESSED, which buys two properties at once: a
    re-import writes the same path rather than a second copy, and two unrelated
    payloads cannot collide. That is identity from BYTES, not from a path (F4);
    the trailing stem is decoration for whoever reads `ls`, and nothing reads it
    back.
    """
    directory = archive_root / NOT_SESSIONS_LABEL / IMPORTED_DIR
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{store.sha256_hex(data)[:12]}_{stem}{_JSONL_SUFFIX}"
    if not target.exists():
        store.atomic_write(target, data)
    return target


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
    if is_subagent(data):
        # REFUSED, loudly. This payload's sessionId is its PARENT'S, so writing
        # it here would name it `<parent-uuid>.jsonl` in the parent's own folder
        # and overwrite the parent whenever the sub-agent is larger - which is
        # the common case at a median 192 KB against 3.7 KB. Sub-agents have
        # their own writer; landing this "somewhere sensible" instead would still
        # put a sub-agent transcript where a session belongs (ticket 21a).
        raise ValueError(
            f"payload is a sub-agent transcript (agentId={agent_id_of(data)}),"
            " not a session; use write_subagent"
        )
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

    # STREAMED, one payload at a time. Holding all five at once cost 8.2 GB of
    # traced heap on a 100 MB session, 78x the payload; the real 114 MB object
    # survived the 2026-08-02 migration on a machine that happened to have the
    # RAM. See build.iter_projection_files.
    for name, payload in build.iter_projection_files(data, options):
        if name == _MANIFEST:
            # Written LAST-ish, and always with the sub-agent list, so a reader
            # can tell "none" from "this manifest predates the feature" (F6).
            payload = _with_subagents(payload, subagent_records(directory))
            if refused:
                payload = _with_refusal(payload, jsonl.stat().st_size, len(data))
        store.atomic_write(directory / name, payload)
    return FolderResult(directory, jsonl, True, replaced, refused)


def _with_subagents(manifest_bytes: bytes, records: list[dict[str, object]]) -> bytes:
    """Record this session's sub-agents in its manifest (ticket 21e)."""
    manifest = cast(dict[str, object], json.loads(manifest_bytes.decode("utf-8")))
    manifest["subagents"] = records
    return json.dumps(manifest, sort_keys=True, indent=2).encode("utf-8") + b"\n"


def _with_refusal(manifest_bytes: bytes, archived: int, offered: int) -> bytes:
    """Record a refused replacement IN the manifest. Never silent (F6): a
    truncated re-capture must not be able to leave the archive unchanged without
    saying why."""
    manifest = cast(dict[str, object], json.loads(manifest_bytes.decode("utf-8")))
    manifest["replace_refused"] = {
        "reason": "a re-captured payload was smaller than the archived one",
        "archived_bytes": archived,
        "offered_bytes": offered,
    }
    return json.dumps(manifest, sort_keys=True, indent=2).encode("utf-8") + b"\n"


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
    # R14. This was the ONLY write surface in the codebase taking no lock, while
    # build, capture, migrate, relocate and sweep all take one. The
    # replace-if-larger path stats a file and then writes it, so
    # identity-idempotence does NOT make two concurrent runs harmless, and R14's
    # own wording therefore requires a lock rather than permitting one.
    if not store.acquire_lock(warehouse_root, ARCHIVE_LOCK):
        report.lock_held = True
        return report
    try:
        return _migrate_locked(warehouse_root, archive_root, options, timezone, report, progress)
    finally:
        store.release_lock(warehouse_root, ARCHIVE_LOCK)


def _migrate_locked(
    warehouse_root: Path,
    archive_root: Path,
    options: render.RenderOptions,
    timezone: str,
    report: MigrationReport,
    progress: int,
) -> MigrationReport:
    """The migration body, with the lock already held."""
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
        problems.extend(_subagent_problems(directory, manifest_path))
    problems.extend(_name_problems(directory, meta, timezone))
    return problems


def _subagent_problems(directory: Path, manifest_path: Path) -> list[FolderProblem]:
    """Every sub-agent the manifest lists must still be present and unaltered.

    Without this a deleted sub-agent folder is invisible to verify: five valid
    files, a matching source hash and a correct folder name all still hold.
    """
    try:
        manifest = cast(dict[str, object], json.loads(manifest_path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return []
    listed = manifest.get("subagents")
    if not isinstance(listed, list):
        return []
    live = {str(r["agent_id"]): str(r["sha256"]) for r in subagent_records(directory)}
    out: list[FolderProblem] = []
    for raw in cast(list[object], listed):
        if not isinstance(raw, dict):
            continue
        rec = cast(dict[str, object], raw)
        agent_id = str(rec.get("agent_id", ""))
        want = str(rec.get("sha256", ""))
        if agent_id not in live:
            out.append(FolderProblem(directory, f"sub-agent {agent_id} is missing"))
        elif want and live[agent_id] != want:
            out.append(FolderProblem(directory, f"sub-agent {agent_id} does not match its hash"))
    return out


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
