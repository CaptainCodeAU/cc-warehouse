"""Project registry: stable IDs, time-stamped path aliases, mutable labels.

Slice 2. DESIGN section 2; rules R3, R4; FINDINGS F4.
"""

import re
import sqlite3
from dataclasses import dataclass
from typing import cast

# One transaction discipline for the slice: registry mutations share catalog's
# BEGIN IMMEDIATE / COMMIT helper so read-decide-write is never unlocked (R14/F8).
from cc_warehouse.catalog import writing

# SPEC section 3 skip list, kept only for the default label suggestion.
_SKIP_DIRS = {"projects", "code", "repos", "src", "dev", "work", "documents"}
_PREFIX_DIRS = {"home", "users"}


def _present(value: str | None) -> str | None:
    """Normalize a resolution key: an empty or whitespace-only cwd/encoded_dir
    counts as absent, so a blank key never creates a catch-all label-'' project
    that would swallow every cwd-less session (F4)."""
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


@dataclass(frozen=True)
class ResolvedProject:
    project_id: int
    created: bool


def derive_label(path: str) -> str:
    """Default display label suggested for a newly seen project path (SPEC section 3)."""
    parts = [p for p in path.split("/") if p]
    segments = list(parts)
    if [s.lower() for s in segments[:3]] == ["mnt", "c", "users"]:
        segments = segments[3:]
    elif segments and segments[0].lower() in _PREFIX_DIRS:
        segments = segments[1:]
    if len(segments) >= 2 and segments[1].lower() in _SKIP_DIRS:
        segments = segments[1:]
    segments = [s for s in segments if s.lower() not in _SKIP_DIRS]
    if segments:
        return "-".join(segments)
    return parts[-1] if parts else path


def _alias_project(conn: sqlite3.Connection, path: str, kind: str) -> int | None:
    row = conn.execute(
        "SELECT project_id FROM project_alias WHERE path = ? AND kind = ?",
        (path, kind),
    ).fetchone()
    if row is None:
        return None
    return cast(int, cast(tuple[object, ...], row)[0])


def _stamp_claims(
    conn: sqlite3.Connection,
    project_id: int,
    cwd: str | None,
    encoded_dir: str | None,
    now: str,
) -> None:
    """Record the provided paths as claims of project_id. A (path, kind) already
    claimed elsewhere is left alone (R5): collisions never repoint a claim."""
    for path, kind in ((cwd, "cwd"), (encoded_dir, "encoded_dir")):
        if path is None:
            continue
        conn.execute(
            "INSERT OR IGNORE INTO project_alias (project_id, path, kind, first_seen, last_seen)"
            " VALUES (?, ?, ?, ?, ?)",
            (project_id, path, kind, now, now),
        )
        conn.execute(
            "UPDATE project_alias SET last_seen = ?"
            " WHERE project_id = ? AND path = ? AND kind = ?",
            (now, project_id, path, kind),
        )


def resolve_project(
    conn: sqlite3.Connection, *, cwd: str | None, encoded_dir: str | None, now: str
) -> ResolvedProject:
    """Alias lookup; on miss creates a project (label from derive_label) plus alias rows.

    When a cwd is present it is the only resolution key, so distinct cwds never
    merge through a shared encoded_dir (F4). With no cwd the encoded_dir is a
    best-effort key (SPEC section 3): two different original cwds that encoded to
    one string do resolve together, an accepted loss for lossy input that
    resolution_source records and a later registry edit can split.
    """
    cwd = _present(cwd)
    encoded_dir = _present(encoded_dir)
    if cwd is None and encoded_dir is None:
        raise ValueError("resolve_project requires a cwd or an encoded_dir")
    with writing(conn):
        if cwd is not None:
            hit = _alias_project(conn, cwd, "cwd")
        else:
            hit = _alias_project(conn, cast(str, encoded_dir), "encoded_dir")
        if hit is not None:
            _stamp_claims(conn, hit, cwd, encoded_dir, now)
            return ResolvedProject(project_id=hit, created=False)
        if cwd is not None:
            label = derive_label(cwd)
        else:
            label = derive_label(cast(str, encoded_dir).replace("-", "/"))
        row = conn.execute(
            "INSERT INTO project (label, created_at) VALUES (?, ?) RETURNING id",
            (label, now),
        ).fetchone()
        project_id = cast(int, cast(tuple[object, ...], row)[0])
        _stamp_claims(conn, project_id, cwd, encoded_dir, now)
        return ResolvedProject(project_id=project_id, created=True)


def rename_project(conn: sqlite3.Connection, project_id: int, label: str) -> None:
    """Label edit only; nothing on disk moves."""
    with writing(conn):
        conn.execute("UPDATE project SET label = ? WHERE id = ?", (label, project_id))


def project_for_path(conn: sqlite3.Connection, path: str, kind: str) -> int | None:
    """The project claiming `path` under `kind`, or None. The one alias-resolution
    implementation (R9); callers outside the registry use this instead of their own SQL."""
    return _alias_project(conn, path, kind)


def cwds_for_encoded_dir(conn: sqlite3.Connection, encoded_name: str) -> tuple[str, ...]:
    """EVERY cwd claim of whichever project owns `encoded_name` (possibly empty).

    Lets a caller tell a repo SUBDIRECTORY's encoded dir from an unrelated SIBLING repo's:
    the encoding collapses `/`, `_` and `.` to `-`, so the names alone are ambiguous (F4).
    Returns all claims, never one arbitrary row: a project that has been relocated keeps
    its previous cwd alias (claims are append-only, R4), so picking a single row would
    hand back a stale path and mislabel the project that owns it.
    """
    rows = cast(
        list[tuple[object, ...]],
        conn.execute(
            "SELECT cwd.path FROM project_alias enc"
            " JOIN project_alias cwd ON cwd.project_id = enc.project_id AND cwd.kind = 'cwd'"
            " WHERE enc.path = ? AND enc.kind = 'encoded_dir'",
            (encoded_name,),
        ).fetchall(),
    )
    return tuple(cast(str, row[0]) for row in rows)


def encode_cwd(path: str) -> str:
    """Claude Code's cwd -> encoded-dir-name mapping: `/`, `_`, `.` become `-`.

    SPEC section 3. The one implementation of this encoding (R9); relocate reuses it
    for boundary-guarded encoded-dir matching.
    """
    return re.sub(r"[/_.]", "-", path)


def move_project(
    conn: sqlite3.Connection, project_id: int, old_path: str, new_path: str, now: str
) -> None:
    """Record a cwd move as alias rows; zero file rewrites.

    Refuses rather than silently recording nothing (R5): old_path must be this
    project's cwd claim, and new_path must be free or already this project's, so
    a move onto another project's claim raises instead of no-op'ing on the
    UNIQUE(path, kind) index. Also claims the ENCODED form of new_path (slice 12),
    so a project first captured without a cwd still resolves after the move instead
    of matching a stale encoded_dir alias (F4).
    """
    with writing(conn):
        if _alias_project(conn, old_path, "cwd") != project_id:
            raise ValueError(
                f"old_path {old_path!r} is not a cwd claim of project {project_id}"
            )
        new_owner = _alias_project(conn, new_path, "cwd")
        if new_owner is not None and new_owner != project_id:
            raise ValueError(
                f"new_path {new_path!r} is already a cwd claim of project {new_owner}"
            )
        conn.execute(
            "UPDATE project_alias SET last_seen = ?"
            " WHERE project_id = ? AND path = ? AND kind = 'cwd'",
            (now, project_id, old_path),
        )
        conn.execute(
            "INSERT OR IGNORE INTO project_alias (project_id, path, kind, first_seen, last_seen)"
            " VALUES (?, ?, 'cwd', ?, ?)",
            (project_id, new_path, now, now),
        )
        conn.execute(
            "UPDATE project_alias SET last_seen = ?"
            " WHERE project_id = ? AND path = ? AND kind = 'cwd'",
            (now, project_id, new_path),
        )
        encoded = encode_cwd(new_path)
        encoded_owner = _alias_project(conn, encoded, "encoded_dir")
        if encoded_owner is not None and encoded_owner != project_id:
            # Two different cwds can encode identically (`my_repo` and `my.repo` both
            # become `my-repo`), so refuse rather than let INSERT OR IGNORE silently do
            # nothing while the caller reports the claim as made (F4/F6).
            raise ValueError(
                f"encoded form {encoded!r} is already a claim of project {encoded_owner}"
            )
        conn.execute(
            "INSERT OR IGNORE INTO project_alias (project_id, path, kind, first_seen, last_seen)"
            " VALUES (?, ?, 'encoded_dir', ?, ?)",
            (project_id, encoded, now, now),
        )
        conn.execute(
            "UPDATE project_alias SET last_seen = ?"
            " WHERE project_id = ? AND path = ? AND kind = 'encoded_dir'",
            (now, project_id, encoded),
        )


def merge_projects(conn: sqlite3.Connection, keep_id: int, merge_id: int) -> None:
    """Repoint the merged project's sessions and claims onto keep, then soft-retire it.

    Validates first (R5): the ids must differ, both projects must exist, and keep
    must not itself be retired. Sessions, then the merged project's alias claims,
    then the retire flag all commit in one transaction, so a future capture at a
    merged path resolves to keep, never back to the retired row (F4).
    """
    if keep_id == merge_id:
        raise ValueError(f"cannot merge project {keep_id} into itself")
    with writing(conn):
        keep = conn.execute("SELECT retired FROM project WHERE id = ?", (keep_id,)).fetchone()
        merge = conn.execute("SELECT id FROM project WHERE id = ?", (merge_id,)).fetchone()
        if keep is None:
            raise ValueError(f"keep project {keep_id} does not exist")
        if merge is None:
            raise ValueError(f"merge project {merge_id} does not exist")
        if cast(int, cast(tuple[object, ...], keep)[0]):
            raise ValueError(f"keep project {keep_id} is retired")
        conn.execute(
            "UPDATE session SET project_id = ? WHERE project_id = ?", (keep_id, merge_id)
        )
        conn.execute(
            "UPDATE project_alias SET project_id = ? WHERE project_id = ?",
            (keep_id, merge_id),
        )
        conn.execute("UPDATE project SET retired = 1 WHERE id = ?", (merge_id,))
