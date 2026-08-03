"""Projection build/rebuild orchestration (slice 8).

With share.py, the ONLY module sanctioned to delete files, and only inside the
projections directory (DESIGN R4): superseded-version dirs and label-rename moves.

One dir-path function (projection_dir) and one projection-writing routine
(write_projection) serve build (per session), `ccw render --session`, and
`ccw render <path>` alike, so there is a single projection implementation, not
three (R9/F8). Selection reads the catalog only, never a raw payload scan (R6);
projection dir names carry the payload-internal date, never a file mtime (R12).
"""

import json
import shutil
import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cc_warehouse import catalog, render, store
from cc_warehouse.config import Config
from cc_warehouse.reports import BatchReport, ItemOutcome

# The five files a projection dir holds (DESIGN section 1/6). The manifest is
# serialized deterministically so an unchanged session re-projects to the same
# bytes and the incremental compare skips it (mtime-stable).
_TRANSCRIPT_FULL = "transcript.md"
_TRANSCRIPT_COMPACT = "transcript.compact.md"
_CONVERSATION_FULL = "conversation.html"
_CONVERSATION_COMPACT = "conversation.compact.html"
_MANIFEST = "manifest.json"


@dataclass(frozen=True)
class _Head:
    """One session to project: the latest version of its uuid, plus its label."""

    hash: str
    short: str
    label: str
    first_ts: str | None
    slug: str | None
    # Carried since slice 19l so every consumer can locate this session's
    # archive folder without a second query per head. The alternative was an
    # N+1 lookup in three modules.
    #
    # NO DEFAULT, deliberately. It had one for exactly one slice, and in that
    # slice `head_for_short` selected the column and forgot to pass it - so
    # `ccw render --session` looked for the wrong archive filename, missed, and
    # fell back to the vault. Silently, and correctly, right up until the vault
    # would have been deleted. A required field turns that into a TypeError at
    # the construction site.
    session_uuid: str | None


def render_options(config: Config) -> render.RenderOptions:
    """The RenderOptions every emitter uses, from the personal render config keys
    (the Group-A content toggles land here from config + flags, DESIGN section 8).

    The `_compact` half is the per-variant matrix (DESIGN 15, 2026-08-01): the
    same five content classes for the compact variant, defaulting OFF. The
    chrome half is block 2: page-level initial states, variant-agnostic."""
    return render.RenderOptions(
        reminders_full=config.render_reminders_full,
        reminders_compact=config.render_reminders_compact,
        breadcrumbs=config.render_breadcrumbs,
        subagents=config.render_subagents,
        attachments=config.render_attachments,
        commands=config.render_commands,
        extras=config.render_extras,
        toolresult_diff=config.render_tool_output,
        subagents_compact=config.render_subagents_compact,
        attachments_compact=config.render_attachments_compact,
        commands_compact=config.render_commands_compact,
        extras_compact=config.render_extras_compact,
        tool_output_compact=config.render_tool_output_compact,
        html_width=config.render_html_width,
        html_font=config.render_html_font,
        html_turns=config.render_html_turns,
        details=config.render_details,
        html_dates=config.render_html_dates,
        thinking_withheld=config.render_thinking_withheld,
        tool_output_max_chars=config.render_tool_output_max_chars,
    )


def component(value: str | None) -> str:
    """Public alias of the path-segment sanitizer.

    archive.py needs the SAME label-to-folder mapping `archive_dir` uses when it
    writes a project's sidecar, and a second copy of the sanitizing rules would
    be the F8 class: two implementations of one truth, drifting apart the first
    time either is touched.
    """
    return _component(value)


def _component(value: str | None) -> str:
    """A single safe path segment for a projection dir name.

    A path separator, a NUL, or a leading/trailing dot is neutralized so a label
    or slug can never escape projections/ or spill across a directory boundary;
    the catalog, not the dir name, remains the source of every mapping (F4).
    """
    if not value:
        return ""
    cleaned = value.replace("/", "-").replace("\\", "-").replace("\x00", "")
    return cleaned.strip().strip(".")


def projection_dir(
    projections: Path, label: str, first_ts: str | None, slug: str | None, short: str
) -> Path:
    """projections/<label>/<YYYY-MM-DD>_<slug>_s-<short>/.

    date is the payload-internal first timestamp (R12, never a file mtime); a
    missing slug or date falls back to a stable placeholder rather than crashing.
    """
    date = (first_ts or "")[:10] or "undated"
    slug_part = _component(slug) or "session"
    label_part = _component(label) or "_unlabeled"
    return projections / label_part / f"{date}_{slug_part}_s-{short}"


# Names the flattened archive root cannot give to a project folder. `projections/`
# is dropped by the archive-first layout, so project folders sit at the warehouse
# root beside these two (DESIGN 15, 2026-08-02).
RESERVED_LABELS = frozenset({"locks", "catalog.sqlite"})

_UNDATED = "undated"


def archive_folder_name(
    first_ts: str | None,
    session_uuid: str | None,
    timezone: str,
    *,
    fallback_stem: str = "session",
) -> str:
    """`<YYYYMMDD-HHMMSS><offset>_<uuid>` for one session (DESIGN 15, 2026-08-02).

    Local wall time in a zone PINNED IN CONFIG, never read from the machine
    clock: converting a fixed UTC instant to a NAMED zone is deterministic, so
    the same session yields the same folder name on any machine forever, which
    reading `TZ` would not. That determinism is what makes the migration
    idempotent, because the name is then a pure function of the payload's own
    contents plus one config value.

    The OFFSET is carried because zones move (Melbourne is +1100 AEDT and +1000
    AEST), and without it a folder name is ambiguous once the tooling that
    produced it is gone. Keyed on the session START (R12, payload-internal, never
    a file mtime) because a start-keyed name is IMMUTABLE: an end-keyed one is
    only final when the session is truly dead, so a session already backed up
    could sprout a second folder later.

    No slug: measured at 13,549 of 13,836 sessions (97.9%) having none, so it
    cost length and delivered nothing.
    """
    stamp = _local_stamp(first_ts, timezone)
    return f"{stamp}_{session_uuid or fallback_stem}"


def _local_stamp(first_ts: str | None, timezone: str) -> str:
    """`YYYYMMDD-HHMMSS±HHMM` in the pinned zone, or `undated`.

    A missing or unparseable stamp degrades to a stable placeholder rather than
    raising (R5): a migration that dies on one malformed timestamp abandons the
    other 13,835 sessions, and 9 real payloads carry no timestamp at all.
    """
    if not first_ts:
        return _UNDATED
    try:
        moment = datetime.fromisoformat(first_ts.replace("Z", "+00:00"))
        zone = ZoneInfo(timezone)
    except (ValueError, ZoneInfoNotFoundError):
        return _UNDATED
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    local = moment.astimezone(zone)
    return local.strftime("%Y%m%d-%H%M%S%z")


def archive_dir(
    root: Path,
    label: str,
    first_ts: str | None,
    session_uuid: str | None,
    timezone: str,
    *,
    fallback_stem: str = "session",
) -> Path:
    """`<root>/<label>/<name>/`, the one directory-naming function (R9).

    `ccw share` calls this too, so a shared bundle looks exactly like the archive
    it came from. A reserved or unsafe label is neutralized rather than refused,
    because refusing would drop a real session on the floor over a folder name.
    """
    part = _component(label) or "_unlabeled"
    if part in RESERVED_LABELS:
        part = f"_{part}"
    name = archive_folder_name(first_ts, session_uuid, timezone, fallback_stem=fallback_stem)
    return root / part / name


def iter_projection_files(
    data: bytes, options: render.RenderOptions
) -> Iterator[tuple[str, bytes]]:
    """The five projection payloads, ONE AT A TIME (R9: the single assembly).

    Streams rather than returning a dict, and the reason is measured. The dict
    version held four large strings AND their four encoded copies at once, so a
    100 MB session peaked at 8.2 GB of traced heap - 78x the payload, against
    9x for the render path alone. The real 114 MB object survived the 2026-08-02
    migration on a machine with enough RAM, which is luck rather than design;
    nothing had ever pinned the archive write path's cost, so nothing noticed.

    Each payload is released before the next is built. The emitters return their
    full and compact variants in pairs, so two documents is the floor without
    changing them, and that is where this stops.
    """
    full_md, compact_md = render.render_markdown(data, options)
    encoded = full_md.encode("utf-8")
    del full_md
    yield _TRANSCRIPT_FULL, encoded
    del encoded
    encoded = compact_md.encode("utf-8")
    del compact_md
    yield _TRANSCRIPT_COMPACT, encoded
    del encoded

    full_html, compact_html = render.render_html(data, options)
    encoded = full_html.encode("utf-8")
    del full_html
    yield _CONVERSATION_FULL, encoded
    del encoded
    encoded = compact_html.encode("utf-8")
    del compact_html
    yield _CONVERSATION_COMPACT, encoded
    del encoded

    manifest = render.build_manifest(data, options)
    yield _MANIFEST, json.dumps(manifest, sort_keys=True, indent=2).encode("utf-8") + b"\n"


def _write_if_changed(path: Path, data: bytes, *, force: bool) -> None:
    """Write via the store's sanctioned writer, skipping when the target already
    holds the same bytes so an unchanged file stays mtime-stable (incremental).

    The compare reads the full file bytes, never a size or mtime proxy (F1). A
    force pass always writes.
    """
    if not force:
        try:
            if path.read_bytes() == data:
                return
        except OSError:
            pass
    store.atomic_write(path, data)


def write_projection(
    directory: Path, data: bytes, options: render.RenderOptions, *, force: bool
) -> None:
    """Render the 4 files + manifest for one payload into `directory`.

    Reused verbatim by build (per session), `ccw render --session`, and ad-hoc
    `ccw render <path>`. Each file goes through the store writer; without force,
    a file whose current bytes already match is left untouched (incremental).
    """
    directory.mkdir(parents=True, exist_ok=True)
    for name, payload in iter_projection_files(data, options):
        _write_if_changed(directory / name, payload, force=force)


def _heads(conn: sqlite3.Connection, include_hidden: bool) -> list[_Head]:
    """The head session of every version chain, from the catalog alone (R6).

    A head is a row no other row supersedes; each uuid's chain is linear, so this
    is exactly one browsable version per session (DESIGN section 6). Hidden rows
    (warmup / no-summary) are excluded unless include_hidden.
    """
    sql = (
        "SELECT s.hash, s.short, p.label, s.first_ts, s.slug, s.session_uuid"
        " FROM session s JOIN project p ON p.id = s.project_id"
        " WHERE s.hash NOT IN (SELECT supersedes FROM session WHERE supersedes IS NOT NULL)"
    )
    if not include_hidden:
        sql += " AND s.hidden = 0"
    heads: list[_Head] = []
    for row in cast(list[tuple[object, ...]], conn.execute(sql).fetchall()):
        hash_ = cast(str, row[0])
        short = cast(str, row[1])
        label = cast(str, row[2])
        first_ts = cast("str | None", row[3])
        slug = cast("str | None", row[4])
        session_uuid = cast("str | None", row[5])
        heads.append(
            _Head(
                hash=hash_, short=short, label=label, first_ts=first_ts,
                slug=slug, session_uuid=session_uuid,
            )
        )
    return heads


def heads_for_window(
    conn: sqlite3.Connection, keep: Callable[[str | None], bool]
) -> list[_Head]:
    """Every current, visible head whose R12 first timestamp satisfies `keep`.

    Shares _heads' join and head predicate (R9), so a windowed `ccw share`
    selects among exactly the sessions a build would project - never a second
    notion of what a session is.
    """
    return [head for head in _heads(conn, include_hidden=False) if keep(head.first_ts)]


def head_for_short(conn: sqlite3.Connection, short: str) -> _Head | None:
    """The _Head named by `short` when it is a current, visible head, else None.

    Shares _heads' join and head predicate (one owner, R9): a row that another
    version supersedes, or a hidden row, is not a head. `ccw render --session`
    projects only a current head through this, so a superseded or hidden short
    lays down no dir the next build would immediately prune (R9/F8). A `short`
    with no row at all also returns None; the CLI distinguishes the two.
    """
    sql = (
        "SELECT s.hash, s.short, p.label, s.first_ts, s.slug, s.session_uuid"
        " FROM session s JOIN project p ON p.id = s.project_id"
        " WHERE s.short = ? AND s.hidden = 0"
        " AND s.hash NOT IN (SELECT supersedes FROM session WHERE supersedes IS NOT NULL)"
    )
    row = cast("tuple[object, ...] | None", conn.execute(sql, (short,)).fetchone())
    if row is None:
        return None
    return _Head(
        hash=cast(str, row[0]),
        short=cast(str, row[1]),
        label=cast(str, row[2]),
        first_ts=cast("str | None", row[3]),
        slug=cast("str | None", row[4]),
        session_uuid=cast("str | None", row[5]),
    )


def _read(config: Config, head: _Head) -> bytes:
    """This session's payload, through the ONE reader (R9, slice 19l).

    Lazy import: archive.py imports build.py, so the archive layer sits above
    this one and a module-level import would be a cycle.
    """
    from cc_warehouse import archive

    return archive.read_payload(
        config,
        label=head.label,
        first_ts=head.first_ts,
        session_uuid=head.session_uuid,
        short=head.short,
        sha256=head.hash,
    )
def _mirror(
    config: Config, label: str, short: str, data: bytes, options: render.RenderOptions
) -> None:
    """Refresh this session's archive folder, when an archive is configured.

    Imported lazily because archive.py imports build.py: the archive layer sits
    ABOVE this one and a module-level import would be a cycle. Never fatal, for
    the same reason the capture path's mirror is not - the item is already
    stored and already reported.
    """
    if config.archive_root is None:
        return
    from cc_warehouse import archive

    try:
        archive.write_session_folder(
            config.archive_root,
            label,
            data,
            options,
            config.archive_timezone,
            fallback_stem=f"session-{short}",
        )
    except Exception:
        return


def _prune(projections: Path, expected: set[Path]) -> None:
    """Remove every projection dir not in the expected set, then any label dir it
    emptied (sanctioned in-projections deletion, R4).

    This one mechanism retires a superseded version's old-hash dir and a renamed
    project's old-label dir, and clears the emptied old label folder. It walks
    only projections/*/* and touches nothing outside projections/.

    Best-effort per dir (R5/R10): a session or label dir that vanished under us
    or cannot be removed (a concurrent writer, a permission error) is skipped so
    a filesystem error on one dir never crashes the whole build.
    """
    if not projections.is_dir():
        return
    for label_dir in sorted(projections.iterdir()):
        if not label_dir.is_dir():
            continue
        for session_dir in sorted(label_dir.iterdir()):
            if session_dir.is_dir() and session_dir not in expected:
                try:
                    shutil.rmtree(session_dir)
                except OSError:
                    continue
    for label_dir in sorted(projections.iterdir()):
        if not label_dir.is_dir():
            continue
        try:
            if not any(label_dir.iterdir()):
                label_dir.rmdir()
        except OSError:
            continue


# DESIGN section 13 / R14: build is a two-writer surface (a second concurrent
# build; the hook's detached render child), so it runs under a locks/build
# O_EXCL lock. A dead-PID lock is taken over by acquire_lock; a live holder makes
# build refuse.
_BUILD_LOCK = "build"

# A live lock holder is reported as one named item (its lock path token) so the
# CLI end report and exit code can name the refusal (R10), mirroring sweep.
_LOCK_HELD_ITEM = "locks/build"

# The lock-held outcome carries this DISTINCT action (not "error") so the CLI can
# refuse with a distinct line and a non-zero exit WITHOUT counting a no-op that
# built nothing as a built item. Public: the CLI end report keys on it.
BUILD_LOCK_HELD = "lock-held"


def build(config: Config, *, rebuild: bool = False, include_hidden: bool = False) -> BatchReport:
    """Project the catalog head sessions; --rebuild regenerates every file.

    Runs under a locks/build O_EXCL lock (R14/DESIGN section 13): a live holder
    makes build a no-op that projects nothing and returns a single lock-held
    outcome for the CLI to refuse on; a dead-PID lock is taken over. Incremental
    by default: a session whose files already hold the current bytes is left
    mtime-stable; --rebuild writes unconditionally. Retired dirs (superseded
    versions, relocated labels) are pruned ONLY after a fully-successful build;
    a build with any failed head keeps the last-good projections instead so a
    render failure never strands a session with zero projections (F7/F9), and a
    later clean build reconciles the tree. Item failures are reported and the
    batch continues (R10); nothing outside projections/ moves.
    """
    root = config.root
    projections = root / "projections"
    options = render_options(config)
    if not store.acquire_lock(root, _BUILD_LOCK):
        return BatchReport(
            (ItemOutcome(_LOCK_HELD_ITEM, BUILD_LOCK_HELD, "build lock held by a live holder"),)
        )
    try:
        conn = catalog.open_catalog(root)
        try:
            heads = _heads(conn, include_hidden)
        finally:
            conn.close()

        outcomes: list[ItemOutcome] = []
        expected: set[Path] = set()
        for head in heads:
            directory = projection_dir(
                projections, head.label, head.first_ts, head.slug, head.short
            )
            expected.add(directory)
            try:
                data = _read(config, head)
                if config.keep_projections:
                    write_projection(directory, data, options, force=rebuild)
                # `ccw build` has to keep meaning something once the old tree is
                # retired: it is the verb that rebuilds after a render change,
                # so it rebuilds whichever tree still exists (slice 19j).
                _mirror(config, head.label, head.short, data, options)
                outcomes.append(ItemOutcome(head.short, "built", ""))
            except Exception as exc:  # report and continue past a bad item (R10)
                outcomes.append(
                    ItemOutcome(head.short, "error", f"{type(exc).__name__}: {exc}")
                )
        # Prune retired dirs ONLY on a fully-successful build. If any head errored
        # the new tree is incomplete, so keeping the last-good projections is the
        # conservative branch (F7/F9); the next clean build reconciles.
        if config.keep_projections and not any(
            outcome.action == "error" for outcome in outcomes
        ):
            _prune(projections, expected)
        return BatchReport(tuple(outcomes))
    finally:
        store.release_lock(root, _BUILD_LOCK)
