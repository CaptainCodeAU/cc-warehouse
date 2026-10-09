"""Batch outcome reporting shared by sweep, build, migrate, relocate, share (rule R10)."""

import traceback
from dataclasses import dataclass
from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parent


def describe_failure(exc: BaseException) -> str:
    """`<ExcType>: <message> (at <file>:<line> in <func>[, via <file>:<line> in <func>])`.

    W-20261006-A43: two nightly builds failed with a bare `OSError: [Errno 22]
    Invalid argument`, an fd-level error with no filename, and the record could
    not say which call raised it. The innermost frame is where it was raised;
    when that frame is outside this package (a stdlib call), the last frame
    inside it is the call site worth reading. The `<ExcType>: <message>` prefix
    is unchanged, so readers keyed on it still match."""
    text = f"{type(exc).__name__}: {exc}"
    frames = traceback.extract_tb(exc.__traceback__)
    if not frames:
        return text

    def where(frame: traceback.FrameSummary) -> str:
        return f"{Path(frame.filename).name}:{frame.lineno} in {frame.name}"

    def ours(frame: traceback.FrameSummary) -> bool:
        return Path(frame.filename).resolve().parent == _PACKAGE_DIR

    location = f"at {where(frames[-1])}"
    if not ours(frames[-1]):
        inside = [f for f in frames if ours(f)]
        if inside:
            location += f", via {where(inside[-1])}"
    return f"{text} ({location})"


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
