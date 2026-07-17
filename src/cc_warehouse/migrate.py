"""ccw migrate: one-shot legacy archive import (slice 10). DESIGN section 10.

The source tree is read-only forever; `retire` performs the single sanctioned
old-world write (one rename).
"""

from pathlib import Path

from cc_warehouse.config import Config
from cc_warehouse.reports import BatchReport


def migrate(config: Config, source_root: Path) -> BatchReport:
    """Import every session payload under source_root via the shared capture routine;
    hash dedupe collapses duplicate copies; every source file is accounted for."""
    raise NotImplementedError


def retire(source_root: Path, *, year_month: str) -> Path:
    """Rename source_root to _RETIRED_<YYYY-MM>_<name>; returns the new path."""
    raise NotImplementedError
