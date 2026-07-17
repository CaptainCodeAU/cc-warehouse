"""Command-line entry point for ccw / cc-warehouse (DESIGN section 7).

Stub: Phase 2 freezes the surface; the build slices implement it.
"""

import sys
from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch one ccw invocation; returns the process exit code."""
    _ = argv if argv is not None else sys.argv[1:]
    print("Error: not implemented", file=sys.stderr)
    return 1
