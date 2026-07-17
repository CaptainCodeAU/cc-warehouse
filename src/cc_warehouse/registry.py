"""Project registry: stable IDs, time-stamped path aliases, mutable labels.

Slice 2. DESIGN section 2; rules R3, R4; FINDINGS F4.
"""

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class ResolvedProject:
    project_id: int
    created: bool


def derive_label(path: str) -> str:
    """Default display label suggested for a newly seen project path (SPEC section 3)."""
    raise NotImplementedError


def resolve_project(
    conn: sqlite3.Connection, *, cwd: str | None, encoded_dir: str | None, now: str
) -> ResolvedProject:
    """Alias lookup; on miss creates a project (label from derive_label) plus alias rows."""
    raise NotImplementedError


def rename_project(conn: sqlite3.Connection, project_id: int, label: str) -> None:
    """Label edit only; nothing on disk moves."""
    raise NotImplementedError


def move_project(
    conn: sqlite3.Connection, project_id: int, old_path: str, new_path: str, now: str
) -> None:
    """Record a path move as alias rows; zero file rewrites."""
    raise NotImplementedError


def merge_projects(conn: sqlite3.Connection, keep_id: int, merge_id: int) -> None:
    raise NotImplementedError
