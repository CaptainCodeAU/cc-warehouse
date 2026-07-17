"""ccw relocate: repair the external world after a repo move (slice 12).

DESIGN section 11: PLAN -> BACKUP -> APPLY -> VERIFY -> REPORT; dry-run is the
default; contents are rewritten before containers are renamed; encoded-dir matching
is boundary-guarded. FINDINGS F2/F7/F9/F10 apply doubly.
"""

from dataclasses import dataclass
from pathlib import Path

from cc_warehouse.config import Config
from cc_warehouse.reports import BatchReport


@dataclass(frozen=True)
class RelocateEdit:
    kind: str  # alias | encoded_dir | memory_file | inventory_file
    target: Path
    detail: str


@dataclass(frozen=True)
class RelocatePlan:
    repo_path: Path
    new_path: Path
    edits: tuple[RelocateEdit, ...]


def plan_relocate(config: Config, repo_path: Path, new_path: Path) -> RelocatePlan:
    """Enumerate every edit without touching anything."""
    raise NotImplementedError


def apply_relocate(config: Config, plan: RelocatePlan, *, backup_dir: Path) -> BatchReport:
    """Backup every file to be touched, then apply atomically per item, verify, report."""
    raise NotImplementedError
