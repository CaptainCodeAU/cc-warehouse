"""Object store primitives: hashing, the write primitive, put/get/has, verify walk, locks.

Slice 1 (the trial run). DESIGN sections 1-2 and 13; rules R1, R2, R4, R14.
"""

import hashlib
import os
import re
import stat
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

# Address grammar (DESIGN section 1): objects/<hh>/<64-hex><ext>. Both address
# parts are validated before any path is built from them (F4/F9); nothing
# outside this grammar is ever treated as a stored object.
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_EXT_RE = re.compile(r"(?:\.[A-Za-z0-9]+)*")
_OBJECT_NAME_RE = re.compile(r"([0-9a-f]{64})(?:\.[A-Za-z0-9]+)*")
# Lock names are plain filename tokens (F9): no separators, no leading dot.
# The dot-prefixed namespace inside locks/ is reserved for acquire_lock's
# scratch and takeover files.
_LOCK_NAME_RE = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9._-]*")

# Bound on acquire_lock's contend-and-retry loop; when contention exhausts it,
# acquire refuses conservatively (R5) instead of spinning.
_ACQUIRE_ATTEMPTS = 8


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
    return hashlib.sha256(data).hexdigest()


def atomic_write(path: Path, data: bytes) -> None:
    """The one sanctioned file-write primitive: tmp file in the same dir, then os.replace.

    Overwriting PRESERVES the target's mode (decided 2026-07-19, principal): os.replace
    substitutes a new inode, and mkstemp creates it 0600, so without this an existing
    file silently changed permissions on every rewrite (an executable lost +x, a
    group-readable memory file became owner-only). A brand-new file keeps mkstemp's
    restrictive default; only an existing target's mode is carried over.
    """
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    try:
        os.chmod(tmp, stat.S_IMODE(os.stat(path).st_mode))
    except OSError:
        pass  # no existing target (or an unreadable one): keep the safe default
    os.replace(tmp, path)


def write_if_changed(path: Path, data: bytes) -> bool:
    """atomic_write, skipped when the target already holds the same bytes.

    Returns True when it wrote. The compare reads the full file, never a size
    or mtime proxy (F1); an unreadable target falls through to a write. One
    primitive rather than a copy per caller: ticket 37 found a third hand-
    rolled copy of this compare (write_subagent's meta.json), and the
    architecture board's C12 is exactly "one shared primitive, not three
    copies that drift". build.write_projection and archive's project sidecar
    and sub-agent writer all go through here.
    """
    try:
        if path.read_bytes() == data:
            return False
    except OSError:
        pass
    atomic_write(path, data)
    return True


def write_if_absent(path: Path, data: bytes) -> Literal["wrote", "unchanged", "refused"]:
    """Place COPIED SOURCE bytes at `path`, refusing to disturb anything already there.

    Ticket 38. The sibling of `write_if_changed`, and they differ in exactly one
    branch, on purpose. `write_if_changed` owns GENERATED files, so a target
    holding different bytes is stale and falls through to a write. This owns
    files copied out of `~/.claude` - a tool result, a workflow script - where a
    target holding different bytes means two different payloads claimed one name,
    and no rule in this project says which of them wins. Size cannot decide it
    either: a truncated capture and a full one are not "smaller and larger
    versions of a transcript", they are two files. So the conservative branch
    (R5) is the ONLY branch: keep what is there, write nothing, and return
    `refused` so the caller can record it (F6 - a refusal is never silent).

    An UNREADABLE target is also `refused`, the opposite direction from
    `write_if_changed`. There, "I cannot read it" resolves to "write a fresh
    one", which is right for a file that can be regenerated. Here the target may
    be the only copy of something, so "I cannot tell what is there" must never
    resolve to "overwrite it".

    The compare reads the full file, never a size or mtime proxy (F1). Directory
    creation is the caller's job: folding it in here would let a typo materialise
    a tree.
    """
    try:
        if path.read_bytes() == data:
            return "unchanged"
        return "refused"
    except FileNotFoundError:
        pass
    except OSError:
        return "refused"
    atomic_write(path, data)
    return "wrote"


def is_sha256_hex(value: str) -> bool:
    """True when value is exactly 64 lowercase hex chars (a sha256 digest).

    The one sha256-format check in the package (R9/F8): object_path and
    catalog.add_session both validate through this predicate, so identity never
    fractures on a case or length quirk (F1).
    """
    return _SHA256_RE.fullmatch(value) is not None


def object_path(root: Path, sha256: str, ext: str = ".jsonl") -> Path:
    """objects/<hh>/<sha256><ext> under the warehouse root.

    Both address parts are validated before the path is built: a malformed hash
    or ext raises ValueError rather than reaching the filesystem (F4/F9).
    """
    if not is_sha256_hex(sha256):
        raise ValueError(f"not a sha256 hex digest: {sha256!r}")
    if not _EXT_RE.fullmatch(ext):
        raise ValueError(f"not a valid object extension: {ext!r}")
    return root / "objects" / sha256[:2] / f"{sha256}{ext}"


def put(root: Path, data: bytes, ext: str = ".jsonl") -> PutResult:
    """Store a payload at its (sha256, ext) address; an address that already
    exists makes the put a no-op with created=False.

    Identity is the payload's own sha256 (R1). The ext is part of the address:
    the same bytes stored under a different ext occupy a distinct address.
    """
    digest = sha256_hex(data)
    path = object_path(root, digest, ext)
    if path.exists():
        return PutResult(digest, False, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, data)
    return PutResult(digest, True, path)


def has(root: Path, sha256: str, ext: str = ".jsonl") -> bool:
    return object_path(root, sha256, ext).exists()


def get(root: Path, sha256: str, ext: str = ".jsonl") -> bytes:
    """This object's bytes from the vault, addressed by its own hash.

    Raises a message NAMING THE HASH AND THE VAULT ROOT on any OSError (ticket
    37 Part B, slice 4a), not the bare `read_bytes()` failure. Still an OSError
    (constructed from the original's own errno, so Python still resolves it to
    the same concrete subclass -- e.g. FileNotFoundError) so the one caller
    that already catches OSError here (archive.py's `ccw archive` fallback)
    is unaffected.

    THE DEFECT THIS FIXES, traced 2026-09-09 to a real live incident (ticket
    37): the bare form's `repr()` drops the filename entirely
    (`FileNotFoundError(2, 'No such file or directory')`, confirmed by
    inspection -- only `str()` keeps it), and the one caller that surfaces
    this to an operator (`notify.report`'s error path, `cli.py`) formats with
    `repr()`. A `keep_objects=false` install with no `objects/` directory at
    all crashed a render with that bare, contextless message -- "something
    failed" with no way to tell what. A message built into the exception's own
    args survives either formatting.
    """
    path = object_path(root, sha256, ext)
    try:
        return path.read_bytes()
    except OSError as exc:
        detail = exc.strerror or str(exc)
        message = (
            f"no bytes for {sha256[:12]}{ext} in the vault at {root}"
            f" (objects/ {'missing' if not (root / 'objects').is_dir() else 'present'}: {detail})"
        )
        raise OSError(exc.errno, message) from exc


def verify_walk(root: Path) -> Iterator[VerifyResult]:
    """Re-hash every stored object against its address (the walk `ccw verify` wraps).

    Only files in the objects/<hh>/<64-hex><ext> layout are objects; anything
    else under objects/ (in-flight write tmp files, foreign litter) is skipped,
    not reported as corruption (F2/F7). An object that cannot be read is
    reported as a not-ok result and the walk continues (R5/R10).
    """
    objects = root / "objects"
    if not objects.is_dir():
        return
    for path in sorted(objects.rglob("*")):
        if not path.is_file():
            continue
        match = _OBJECT_NAME_RE.fullmatch(path.name)
        if match is None:
            continue
        expected = match.group(1)
        if path.parent.parent != objects or path.parent.name != expected[:2]:
            continue
        try:
            actual = sha256_hex(path.read_bytes())
        except OSError:
            yield VerifyResult(path=path, expected_sha256=expected, actual_sha256="", ok=False)
            continue
        yield VerifyResult(
            path=path,
            expected_sha256=expected,
            actual_sha256=actual,
            ok=actual == expected,
        )


def _validate_lock_name(name: str) -> None:
    """Reject lock names that are not plain filename tokens (F9): path
    separators, dot-relative segments, and the reserved dot prefix all raise."""
    if not _LOCK_NAME_RE.fullmatch(name):
        raise ValueError(f"not a valid lock name: {name!r}")


def _pid_is_alive(pid: int) -> bool:
    """Conservative liveness probe for a recorded holder PID (callers pass only
    validated positive PIDs): anything short of a definite ESRCH counts as alive."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _read_lock_holder(lock: Path) -> int | None:
    """The PID recorded in a lock file, or None when the content records no
    valid holder (empty, non-integer, non-ASCII, or non-positive).

    Lock creation publishes the file with its PID content in one atomic step,
    so a valid lock always parses; a file that does not parse was not created
    by this module and holds nothing. It is takeover-eligible rather than a
    permanently unbreakable lock (F2). OSError propagates to the caller.
    """
    try:
        text = lock.read_text(encoding="ascii")
    except UnicodeDecodeError:
        return None
    try:
        pid = int(text.strip())
    except ValueError:
        return None
    if pid <= 0:
        return None
    return pid


def acquire_lock(root: Path, name: str) -> bool:
    """Take locks/<name> with O_EXCL semantics; the file holds the holder's ASCII PID.

    Returns False while the recorded holder is alive; a lock whose recorded PID
    is dead, or whose content records no valid holder, is stale and taken over
    (DESIGN section 13). The lock file appears with its PID content in one
    atomic step: the PID is written to a scratch file first and os.link
    publishes it, failing when the lock already exists (O_EXCL semantics), so
    no crash can leave a PID-less lock behind (F2). Takeover is
    contention-losing (R14/F3): the stale file is renamed aside first, rename
    fails for every contender but one once the source is gone, and only the
    rename winner proceeds to re-contend the O_EXCL link.
    """
    _validate_lock_name(name)
    lock = root / "locks" / name
    lock.parent.mkdir(parents=True, exist_ok=True)
    pid = os.getpid()
    scratch = lock.parent / f".{name}.pid.{pid}"
    aside = lock.parent / f".{name}.stale.{pid}"
    atomic_write(scratch, str(pid).encode("ascii"))
    try:
        for _ in range(_ACQUIRE_ATTEMPTS):
            try:
                os.link(scratch, lock)
                return True
            except FileExistsError:
                pass
            try:
                holder = _read_lock_holder(lock)
            except FileNotFoundError:
                continue  # released or taken over since the link attempt; re-contend
            except OSError:
                return False  # unreadable: conservatively treat as held (R5)
            if holder is not None and _pid_is_alive(holder):
                return False
            # Stale (dead PID) or invalid (no recorded holder): rename it aside
            # so exactly one contender proceeds past this point.
            try:
                os.rename(lock, aside)
            except FileNotFoundError:
                continue  # another contender won the rename; re-contend
            except OSError:
                return False
            # Re-check what we actually renamed: if a fresh lock replaced the
            # stale one after our read, restore it and lose (R5).
            try:
                fresh_holder = _read_lock_holder(aside)
            except OSError:
                fresh_holder = None
            if fresh_holder is not None and _pid_is_alive(fresh_holder):
                try:
                    os.link(aside, lock)
                except OSError:
                    pass
                aside.unlink(missing_ok=True)
                return False
            aside.unlink(missing_ok=True)
        return False  # retry budget exhausted under contention: refuse (R5)
    finally:
        scratch.unlink(missing_ok=True)


def release_lock(root: Path, name: str) -> None:
    """Remove locks/<name> when this process is the recorded holder.

    Lock-file removal is on the sanctioned closed list (DESIGN section 13, R4).
    Releasing a lock that is already gone is a no-op; a lock recording a
    different holder, or unreadable content, is left in place (F3: only the
    acquire winner may release, and errors keep the lock, R5).
    """
    _validate_lock_name(name)
    lock = root / "locks" / name
    try:
        holder = _read_lock_holder(lock)
    except OSError:
        return
    if holder != os.getpid():
        return
    lock.unlink(missing_ok=True)


def lock_is_held(root: Path, name: str) -> bool:
    """True while `locks/<name>` names a live process (ticket 34).

    A pure read, unlike `acquire_lock`: never links, renames, or removes
    anything, so it is safe for a read-only caller (`ccw doctor`'s desync
    check) to ask "is a batch actively running right now" without racing an
    actual acquirer for the lock. A stale lock (dead PID, or content that does
    not parse) reads as NOT held, matching `acquire_lock`'s own definition of
    stale-and-takeover-eligible -- this function tells the truth about the
    SAME lock file `acquire_lock` would decide the same way about, it just
    never takes any action on what it finds.
    """
    _validate_lock_name(name)
    lock = root / "locks" / name
    try:
        holder = _read_lock_holder(lock)
    except (FileNotFoundError, OSError):
        return False
    return holder is not None and _pid_is_alive(holder)
