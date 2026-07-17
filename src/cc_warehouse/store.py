"""Object store primitives: hashing, the write primitive, put/get/has, verify walk, locks.

Slice 1 (the trial run). DESIGN sections 1-2 and 13; rules R1, R2, R4, R14.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PutResult:
    sha256: str
    created: bool
    path: Path


@dataclass(frozen=True)
class VerifyResult:
    path: Path
    expected_sha256: str
    actual_sha256: str
    ok: bool


def sha256_hex(data: bytes) -> str:
    raise NotImplementedError


def atomic_write(path: Path, data: bytes) -> None:
    """The one sanctioned file-write primitive: tmp file in the same dir, then os.replace."""
    raise NotImplementedError


def object_path(root: Path, sha256: str, ext: str = ".jsonl") -> Path:
    """objects/<hh>/<sha256><ext> under the warehouse root."""
    raise NotImplementedError


def put(root: Path, data: bytes, ext: str = ".jsonl") -> PutResult:
    """Store a payload by its own sha256; storing an existing hash is a no-op."""
    raise NotImplementedError


def has(root: Path, sha256: str) -> bool:
    raise NotImplementedError


def get(root: Path, sha256: str) -> bytes:
    raise NotImplementedError


def verify_walk(root: Path) -> Iterator[VerifyResult]:
    """Re-hash every stored object against its name (the walk `ccw verify` wraps)."""
    raise NotImplementedError


def acquire_lock(root: Path, name: str) -> bool:
    """Take locks/<name> with O_EXCL semantics; the file holds the holder's ASCII PID.

    Returns False when a live holder exists; a lock whose recorded PID is dead is stale
    and may be taken over (DESIGN section 13).
    """
    raise NotImplementedError


def release_lock(root: Path, name: str) -> None:
    raise NotImplementedError
