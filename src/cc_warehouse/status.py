"""ccw status and ccw verify surfaces (slice 9). Reads come from the catalog only (R6)."""

from dataclasses import dataclass

from cc_warehouse.config import Config
from cc_warehouse.reports import BatchReport


@dataclass(frozen=True)
class SessionListing:
    short: str
    label: str
    summary: str
    captured_at: str


def recent_sessions(config: Config, limit: int = 10) -> list[SessionListing]:
    """Recent captures from the catalog; opens zero stored payloads (FINDINGS F5)."""
    raise NotImplementedError


def status_text(config: Config) -> str:
    """Recent captures, counts, store size, last errors, from catalog + log only."""
    raise NotImplementedError


def verify(config: Config) -> BatchReport:
    """Wrap the slice-1 verify walk and cross-check catalog rows against objects."""
    raise NotImplementedError
