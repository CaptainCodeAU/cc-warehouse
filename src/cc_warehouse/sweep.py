"""ccw sweep: import anything the hook missed (slice 5). DESIGN section 4; R10, R14."""

from pathlib import Path

from cc_warehouse.config import Config
from cc_warehouse.reports import BatchReport


def sweep(config: Config, source: Path | None = None) -> BatchReport:
    """Scan the source tree for payloads the catalog lacks; capture each via the shared
    routine under a locks/sweep O_EXCL lock; continue past item failures."""
    raise NotImplementedError
