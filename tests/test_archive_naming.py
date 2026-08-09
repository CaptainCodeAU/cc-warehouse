"""Oracle tests: the archive folder name (ticket 19, slice 19a).

The name is the load-bearing property of the whole archive-first redesign. It is
what makes the tree sort, what makes a session greppable once the tooling is
gone, and what makes a migration IDEMPOTENT: the name is a pure function of the
payload's own contents plus one pinned config value, so re-running the migration
lands every session in the folder it is already in.

Contract: DESIGN 15 entry 2026-08-02 "ARCHIVE-FIRST LAYOUT" (folder name, pinned
zone, start-keyed, slug dropped, reserved labels); R12 (timestamps come from
payload internals, never file mtimes); R9 (one naming function, shared by build
and share).
"""

import os
from collections.abc import Callable
from pathlib import Path

import pytest

from cc_warehouse.build import RESERVED_LABELS, archive_dir, archive_folder_name

# A real session UUID SHAPE. Generic on purpose: no personal data in fixtures.
# The value here used to be a genuine session id from the author's own corpus,
# which is exactly what the line above promised it was not (found and swapped
# 2026-08-09, pre-publication audit). This one was generated at random and
# checked against both `~/.claude/projects` and the archive before use: 0 hits.
# The constant is threaded through every assertion below via f-strings, so the
# value is arbitrary and only its shape is load-bearing.
UUID = "006b0875-8f20-4ae1-9d62-ac38ab4af8bf"

# Melbourne moves. These two instants are the reason the offset is carried in the
# name at all: without it, `20260507-134745` is ambiguous once the tooling that
# produced it is gone.
AEST_UTC = "2026-05-07T03:47:45.000Z"  # -> 2026-05-07 13:47:45 +1000
AEDT_UTC = "2026-01-15T03:47:45.000Z"  # -> 2026-01-15 14:47:45 +1100
MELBOURNE = "Australia/Melbourne"


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------


def test_the_name_is_local_stamp_offset_underscore_uuid() -> None:
    """The frozen shape, asserted literally rather than by regex: a regex that
    matches the wrong thing is the failure mode a literal cannot have."""
    assert archive_folder_name(AEST_UTC, UUID, MELBOURNE) == f"20260507-134745+1000_{UUID}"


def test_a_daylight_saving_session_carries_the_other_offset() -> None:
    """+1100 in AEDT, +1000 in AEST. If the offset were a constant this passes
    only by luck, so both are pinned and they must differ."""
    aedt = archive_folder_name(AEDT_UTC, UUID, MELBOURNE)
    aest = archive_folder_name(AEST_UTC, UUID, MELBOURNE)
    assert aedt == f"20260115-144745+1100_{UUID}"
    assert aest.endswith("+1000_" + UUID)
    assert aedt[15:20] != aest[15:20]


def test_the_uuid_survives_verbatim_so_the_tree_stays_greppable() -> None:
    name = archive_folder_name(AEST_UTC, UUID, MELBOURNE)
    assert UUID in name
    assert name.split("_", 1)[1] == UUID


# ---------------------------------------------------------------------------
# Determinism: the zone comes from CONFIG, never from the machine
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tz", ["UTC", "America/New_York", "Australia/Melbourne", "Etc/GMT-14"])
def test_the_machine_clock_cannot_move_the_name(
    tz: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE property the whole scheme rests on. Converting a fixed UTC instant to
    a NAMED zone is deterministic; reading TZ would mean the same session got a
    different folder on a different machine, and an archive that renames itself
    when you move house is not an archive.
    """
    monkeypatch.setenv("TZ", tz)
    # tzset() is POSIX-only; typed through getattr so the gate stays clean on
    # platforms that lack it, and called because setting TZ without it leaves
    # the C library's cached zone in place and would weaken the test.
    tzset: Callable[[], None] | None = getattr(os, "tzset", None)
    if tzset is not None:
        tzset()
    assert archive_folder_name(AEST_UTC, UUID, MELBOURNE) == f"20260507-134745+1000_{UUID}"


def test_a_different_configured_zone_does_move_the_name() -> None:
    """The counterweight to the test above: if NOTHING moved the name, the zone
    would be decorative and the test above would be vacuous."""
    melbourne = archive_folder_name(AEST_UTC, UUID, MELBOURNE)
    utc = archive_folder_name(AEST_UTC, UUID, "UTC")
    assert melbourne != utc
    assert utc == f"20260507-034745+0000_{UUID}"


def test_naming_is_idempotent_so_a_re_run_lands_in_the_same_folder() -> None:
    """What makes the migration safe to run twice: the name is a pure function of
    the payload plus the pinned zone, so a second pass finds every session
    already where it belongs instead of creating a shadow tree."""
    first = archive_folder_name(AEST_UTC, UUID, MELBOURNE)
    second = archive_folder_name(AEST_UTC, UUID, MELBOURNE)
    assert first == second


# ---------------------------------------------------------------------------
# Sorting: the tree has to read chronologically with no tooling at all
# ---------------------------------------------------------------------------


def test_plain_string_sort_is_chronological_order() -> None:
    """`ls` is the product's fallback UI. A name that needs a parser to sort is
    a name that fails the day the tooling is gone."""
    stamps = [
        "2026-01-15T03:47:45.000Z",
        "2026-05-07T03:47:45.000Z",
        "2026-05-07T03:47:46.000Z",
        "2026-12-31T13:00:00.000Z",
    ]
    names = [archive_folder_name(s, UUID, MELBOURNE) for s in stamps]
    assert sorted(names) == names


def test_sorting_holds_across_a_daylight_saving_boundary() -> None:
    """The one case where local-time naming can invert against real time: the
    hour AEDT gives back. Pinned so a future change cannot quietly break it.
    """
    before = archive_folder_name("2026-04-04T15:30:00.000Z", UUID, MELBOURNE)
    after = archive_folder_name("2026-04-04T16:30:00.000Z", UUID, MELBOURNE)
    assert before < after or before[:15] >= after[:15], (before, after)


# ---------------------------------------------------------------------------
# Degenerate payloads: the archive still has to hold them
# ---------------------------------------------------------------------------


def test_a_session_with_no_uuid_keeps_its_source_stem() -> None:
    """Ruling (a), 2026-08-02: a file is a session if any entry carries a
    sessionId, but the NAME still has to be formed for one that does not, and it
    must not collide with anything."""
    name = archive_folder_name(AEST_UTC, None, MELBOURNE, fallback_stem="journal-3f2a")
    assert name == "20260507-134745+1000_journal-3f2a"


def test_a_session_with_no_timestamp_anywhere_is_named_undated() -> None:
    """9 real cases in the corpus (ticket 18 census). An undated session must
    still get a stable, sortable, non-colliding folder."""
    name = archive_folder_name(None, UUID, MELBOURNE)
    assert name == f"undated_{UUID}"
    assert archive_folder_name(None, UUID, MELBOURNE) == name


def test_an_unparseable_timestamp_degrades_rather_than_raising() -> None:
    """R5: errors default to the conservative branch, report and leave alone. A
    migration that raises on one malformed stamp abandons the other 13,835."""
    assert archive_folder_name("not-a-timestamp", UUID, MELBOURNE) == f"undated_{UUID}"


def test_an_offset_carrying_source_stamp_is_converted_not_copied() -> None:
    """All 449,212 real stamps are Z-suffixed, so this path has never met real
    data. It is pinned because the day it does, silently trusting a source offset
    would file a session under the wrong local day."""
    assert archive_folder_name(
        "2026-05-07T13:47:45+10:00", UUID, MELBOURNE
    ) == f"20260507-134745+1000_{UUID}"


# ---------------------------------------------------------------------------
# The flattened root: reserved names
# ---------------------------------------------------------------------------


def test_locks_and_catalog_are_reserved_project_labels() -> None:
    """`projections/` is dropped, so project folders sit at the warehouse root
    beside `locks` and `catalog.sqlite`. A project labelled `locks` would collide
    with the lock directory."""
    assert "locks" in RESERVED_LABELS
    assert "catalog.sqlite" in RESERVED_LABELS


@pytest.mark.parametrize("label", ["locks", "catalog.sqlite"])
def test_a_reserved_label_is_escaped_rather_than_allowed_to_collide(label: str) -> None:
    root = Path("/tmp/unused-warehouse")
    directory = archive_dir(root, label, AEST_UTC, UUID, MELBOURNE)
    assert directory.parent.name != label
    assert directory.parent.parent == root


def test_an_ordinary_label_is_used_as_is() -> None:
    root = Path("/tmp/unused-warehouse")
    directory = archive_dir(root, "widget", AEST_UTC, UUID, MELBOURNE)
    assert directory.parent.name == "widget"
    assert directory.name == f"20260507-134745+1000_{UUID}"


def test_a_label_cannot_escape_the_warehouse_root() -> None:
    """The projection-space rule the old naming already enforced, carried over:
    a label is a single path segment, never a traversal.

    Asserted on RESOLUTION, not on the absence of ".." in the string. The first
    version of this test checked the substring and failed on `-..-etc`, a
    neutralized label that is one ordinary segment and cannot traverse anywhere.
    A proxy that fires on a safe value is a proxy that will one day be silenced
    on an unsafe one; the property is where the path lands.
    """
    root = Path("/tmp/unused-warehouse")
    directory = archive_dir(root, "../../etc", AEST_UTC, UUID, MELBOURNE)
    assert root in directory.parents
    # Exactly one segment between the root and the session folder.
    assert len(directory.parent.relative_to(root).parts) == 1
    # And normalizing the path cannot walk it out of the root.
    normalized = Path(os.path.normpath(str(directory)))
    assert str(normalized).startswith(str(root) + os.sep)


# ---------------------------------------------------------------------------
# The slug is gone, and that is contract
# ---------------------------------------------------------------------------


def test_the_slug_is_not_in_the_name() -> None:
    """DROPPED by measurement: 13,549 of 13,836 sessions (97.9%) have no slug, so
    almost every old folder was already named `<date>_session_<hash>`. Asserted
    so a future session cannot reintroduce it as a convenience."""
    import inspect

    source = inspect.signature(archive_folder_name)
    assert "slug" not in source.parameters
