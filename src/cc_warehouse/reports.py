"""Batch outcome reporting shared by sweep, build, migrate, relocate, share (rule R10)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ItemOutcome:
    item: str
    action: str
    detail: str


@dataclass(frozen=True)
class BatchReport:
    outcomes: tuple[ItemOutcome, ...]

    @property
    def failures(self) -> tuple[ItemOutcome, ...]:
        return tuple(o for o in self.outcomes if o.action == "error")
