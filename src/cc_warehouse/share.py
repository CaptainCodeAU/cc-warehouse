"""ccw share: sanitized static-site export (slice 11). DESIGN section 9.

Sanitization runs on COPIES at share time; the store and personal projections stay
full fidelity. With build.py, the only module sanctioned to delete files, and only
inside the shares directory (R4).
"""

from dataclasses import dataclass
from pathlib import Path

from cc_warehouse.config import Config


@dataclass(frozen=True)
class RedactionHit:
    pattern: str
    file: str
    line: int
    replacement: str


@dataclass(frozen=True)
class ShareReport:
    out_dir: Path
    hits: tuple[RedactionHit, ...]
    findings: tuple[RedactionHit, ...]  # secret-shaped detections; abort unless allowed


def share(
    config: Config,
    sessions: tuple[str, ...],
    out_dir: Path,
    *,
    allow_findings: bool = False,
) -> ShareReport:
    """Build the share site for the given s:<hash> keys; multi-session gets one index."""
    raise NotImplementedError
