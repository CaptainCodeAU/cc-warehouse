"""Contract-derived regression tests for the store write primitive.

Surfaced by the slice-12 relocate loop and decided by the principal on 2026-07-19:
`atomic_write` replaces the target inode (mkstemp + os.replace), and mkstemp creates
its file 0600, so overwriting silently changed an existing file's permissions. Relocate
rewrites arbitrary user files under the configured roots, which made the loss visible
(an executable helper lost +x, a group-readable memory file became owner-only), but the
primitive is shared by every slice, so the guarantee is pinned here.
"""

import stat
from pathlib import Path

from cc_warehouse import store


def test_overwrite_preserves_the_targets_mode(tmp_path: Path) -> None:
    """R2: the one sanctioned write primitive must not change an existing file's mode."""
    target = tmp_path / "memory.md"
    target.write_text("before\n")
    target.chmod(0o644)
    store.atomic_write(target, b"after\n")
    assert target.read_bytes() == b"after\n"
    assert stat.S_IMODE(target.stat().st_mode) == 0o644, "overwrite changed the file mode"


def test_overwrite_preserves_the_executable_bit(tmp_path: Path) -> None:
    """An executable rewritten in place must still be executable afterwards."""
    script = tmp_path / "hook.sh"
    script.write_text("#!/bin/sh\necho old\n")
    script.chmod(0o755)
    store.atomic_write(script, b"#!/bin/sh\necho new\n")
    assert stat.S_IMODE(script.stat().st_mode) == 0o755
    assert script.stat().st_mode & stat.S_IXUSR, "the executable bit was lost on rewrite"


def test_a_new_file_keeps_the_restrictive_default(tmp_path: Path) -> None:
    """Only an EXISTING target's mode is carried over; a fresh file stays owner-only, so
    preserving modes never widens permissions on something the store just created."""
    fresh = tmp_path / "new.json"
    store.atomic_write(fresh, b"{}\n")
    assert fresh.read_bytes() == b"{}\n"
    assert not stat.S_IMODE(fresh.stat().st_mode) & (stat.S_IRGRP | stat.S_IROTH)
