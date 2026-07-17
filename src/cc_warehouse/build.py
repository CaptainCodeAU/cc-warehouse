"""Projection build/rebuild orchestration (slice 8).

With share.py, the ONLY module sanctioned to delete files, and only inside the
projections directory (DESIGN R4): superseded-version dirs and label-rename moves.
"""

from cc_warehouse.config import Config
from cc_warehouse.reports import BatchReport


def build(config: Config, *, rebuild: bool = False, include_hidden: bool = False) -> BatchReport:
    """Incremental by catalog diff; --rebuild regenerates everything from objects + catalog."""
    raise NotImplementedError
