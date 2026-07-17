"""Capture pipeline shared verbatim by the hook, sweep, and migrate (DESIGN section 4, R9).

Slice 4 (hook + notify wiring; the render child stays a stub until slice 8).
"""

from dataclasses import dataclass
from pathlib import Path

from cc_warehouse.config import Config


@dataclass(frozen=True)
class CaptureResult:
    sha256: str
    short: str
    action: str  # stored | skipped_unchanged | superseded | duplicate-invocation | error
    project_id: int | None
    elapsed_ms: int
    detail: str


def capture_transcript(
    config: Config, transcript_path: Path, *, session_id: str | None, cwd: str | None
) -> CaptureResult:
    """Hash-first, identity-idempotent capture of one transcript into the store + catalog."""
    raise NotImplementedError
