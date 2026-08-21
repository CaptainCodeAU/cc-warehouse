"""Oracle tests: the BUILT ARTIFACT carries nothing the repository would not.

WHY THIS FILE EXISTS, and it is not hypothetical. On 2026-08-09 a pre-publication
audit scanned all 1417 git objects and found zero occurrences of the author's
account name. The sdist built from that same tree contained two. Four
`MEMORY/WORK/*/PRD.md` files rode into `uv build` output, because hatchling's
sdist default ships everything not excluded by the REPOSITORY's `.gitignore`, and
`MEMORY/` was ignored only by a global `~/.gitignore_global` that no build tool
reads. The repository was clean and the artifact was not, and the only thing that
caught it was a person deciding to look.

A build artifact is a SEPARATE PUBLICATION SURFACE from the repository. Auditing
the tree says nothing about the tarball, and PyPI cannot un-publish a release. So
the property is asserted here, on a real artifact, every time the suite runs.

TWO GUARDS AGAINST THIS FILE LYING, both learned the hard way in the same week:

1. `test_the_scan_detects_a_planted_violation` plants each forbidden shape and
   asserts the scan catches it. Without it, a typo in one pattern turns the file
   into a guaranteed pass that reports safety it never checked.
2. `test_the_artifact_is_not_empty` exists because an empty member list passes
   every other assertion here trivially. A scan of nothing is not a clean scan,
   and zero results read exactly like a negative result.

Contract: the CLAUDE.md hard rule that personal data is never committed, and
CHANGELOG 0.1.0's claim that the published artifact was audited. That claim is
only worth what re-checks it.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Any `/Users/<name>` or `/home/<name>` that is not one of the documented
# placeholders. Written as capture-then-allowlist rather than as a negative
# lookahead: a lookahead that is subtly wrong silently stops matching, and this
# file's whole purpose is to not fail open.
HOME_PATH = re.compile(r"/(?:Users|home)/([A-Za-z0-9._-]+)")
# Enumerated on purpose, so an unrecognised name FAILS rather than passing. The
# cost is that a new fixture placeholder must be added here; that cost is the
# feature. `a` and `x` are short forms already used in the suite.
PLACEHOLDER_NAMES = frozenset({"alice", "a", "x", "...", "youruser", "myuser", "you"})

# Secret shapes. Quantifiers are load-bearing: bare prefixes match this project's
# OWN redaction patterns in `share.py` and its test fixtures, which are not leaks.
SECRET_SHAPES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("aws key id", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("github token", re.compile(r"gh[pousr]_[A-Za-z0-9]{36}")),
    ("github pat", re.compile(r"github_pat_[A-Za-z0-9_]{22,}")),
    ("anthropic key", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("google api key", re.compile(r"AIza[0-9A-Za-z_-]{35}")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("session url", re.compile(r"claude\.ai/code/session_[A-Za-z0-9]{6,}")),
)

# Directories that must never reach the artifact. `MEMORY` is named first because
# it is the one that actually escaped. `plugins` and `.claude-plugin` are tracked
# and legitimate, but they are Claude Code assets: nothing installing this package
# from PyPI can use them, so the exclusion is asserted here rather than left to
# whoever last edited the hatch config. `tools` is scratch tooling (`ccstats`):
# tracked so it cannot be lost like `temp` can, but never shipped, since it is
# not subject to pyright strict or the oracle suite and ships nothing PyPI needs.
FORBIDDEN_DIRS: tuple[str, ...] = (
    "MEMORY",
    "Plans",
    "temp",
    "tools",
    ".claude",
    ".github",
    "plugins",
    ".claude-plugin",
)

# The one file the sdist legitimately holds that git does not track: the metadata
# the build backend generates. Anything else arrived by accident.
GENERATED_MEMBERS: frozenset[str] = frozenset({"PKG-INFO"})


def scan(members: dict[str, str]) -> list[str]:
    """One complaint per violation in `{member path: text}`.

    Separated from the build so the detector can be run against planted content.
    A scan only ever exercised on clean input is not a tested scan.
    """
    problems: list[str] = []
    for name in sorted(members):
        text = members[name]
        top = name.split("/", 1)[0]
        if top in FORBIDDEN_DIRS:
            problems.append(f"{name}: ships {top}/, which is working material")
        for owner in HOME_PATH.findall(text):
            if owner not in PLACEHOLDER_NAMES:
                problems.append(f"{name}: real home directory -> /.../{owner}")
        for label, pattern in SECRET_SHAPES:
            found = pattern.search(text)
            if found is not None:
                problems.append(f"{name}: {label} -> {found.group(0)!r}")
    return problems


def tracked_files() -> frozenset[str]:
    """Every path git tracks, named as the sdist names it."""
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return frozenset(line for line in result.stdout.splitlines() if line)


@pytest.fixture(scope="module")
def sdist_members(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    """Build a real sdist; return `{path below the root directory: text}`.

    SKIPS only when uv is absent, which is a genuine environment limitation. A
    build that RUNS and FAILS is allowed to fail the suite: a gate that excuses
    itself whenever anything goes wrong reports a safety it never established.
    """
    if shutil.which("uv") is None:
        pytest.skip("uv is not installed, so no artifact can be built to inspect")

    out_dir = tmp_path_factory.mktemp("sdist")
    subprocess.run(
        ["uv", "build", "--sdist", "--out-dir", str(out_dir)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    tarballs = sorted(out_dir.glob("*.tar.gz"))
    assert len(tarballs) == 1, f"expected exactly one sdist, got {tarballs}"

    members: dict[str, str] = {}
    with tarfile.open(tarballs[0], "r:gz") as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            handle = archive.extractfile(member)
            if handle is None:
                continue
            # Members are "<name>-<version>/<path>"; the prefix is not content.
            _, _, relative = member.name.partition("/")
            members[relative or member.name] = handle.read().decode(
                "utf-8", errors="replace"
            )
    return members


def test_the_artifact_is_not_empty(sdist_members: dict[str, str]) -> None:
    """An empty member list passes every other test here trivially.

    This is the control for the whole file. If the build silently produced
    nothing, or the extraction loop skipped every member, the scans below would
    report a clean artifact because they examined no artifact.
    """
    assert len(sdist_members) > 50, f"suspiciously small sdist: {len(sdist_members)}"
    assert "PKG-INFO" in sdist_members
    assert any(name.startswith("src/cc_warehouse/") for name in sdist_members)


def test_every_shipped_file_is_tracked_by_git(sdist_members: dict[str, str]) -> None:
    """The artifact ships the repository, plus generated metadata, and nothing else.

    This is the assertion that would have caught the MEMORY/ escape. It does not
    enumerate what is forbidden, it requires everything present to be accounted
    for, so a category nobody thought of still fails.
    """
    tracked = tracked_files()
    unexpected = sorted(set(sdist_members) - tracked - GENERATED_MEMBERS)
    assert unexpected == [], f"sdist ships files git does not track: {unexpected}"


def test_no_forbidden_content_in_the_artifact(sdist_members: dict[str, str]) -> None:
    assert scan(sdist_members) == []


# EVERY PLANTED VIOLATION IS ASSEMBLED AT RUNTIME, never written as a literal.
#
# This module ships inside the sdist it inspects, so a literal violation here
# would be a real violation there and this file would fail on itself. Its first
# run did exactly that. The same idiom is already used in `test_share.py`, which
# builds `"sk-ant-api03-" + "a1" * 20` for the same reason: a fixture that spells
# out the thing it is testing for becomes an instance of it.
#
# The concatenations below are therefore not stylistic. Collapsing any of them
# into a single string re-breaks the suite, and the failure will point here.
_USER = "real" + "person"
_PLANTS: tuple[tuple[str, str], ...] = (
    ("real home", "editable = /Users/" + _USER + "/code/thing"),
    ("linux home", "cwd: /home/" + _USER + "/projects"),
    ("aws key", "key = AKIA" + "IOSFODNN7EXAMPLE"),
    ("github token", "token = gh" + "p_" + "a1b2c3d4e5" * 3 + "abcdef"),
    ("anthropic key", "token = sk-" + "ant-api03-" + "a1" * 20),
    ("private key", "-----BEGIN " + "OPENSSH PRIVATE KEY-----"),
    ("session url", "see https://claude.ai/code/" + "session_" + "z" * 16),
)


@pytest.mark.parametrize(("label", "planted"), _PLANTS)
def test_the_scan_detects_a_planted_violation(label: str, planted: str) -> None:
    """The detector must be able to produce a positive, or its negatives mean nothing.

    Every pattern above is exercised against content that should trip it. A
    pattern that silently stopped matching would otherwise leave this file
    passing forever while checking nothing, which is the exact failure mode the
    module docstring describes.
    """
    problems = scan({"planted.txt": planted})
    assert problems != [], f"the scan failed to detect a planted {label}"


def test_the_scan_accepts_the_documented_placeholders() -> None:
    """Placeholders used throughout the tests and docs must not trip the scan.

    The counterpart to the planted-violation test: a detector that fires on
    everything is as useless as one that fires on nothing, and this project
    deliberately writes `/home/alice/projects/widget` in its fixtures.
    """
    assert scan({"a.py": 'CWD = "/home/alice/projects/widget"'}) == []
    assert scan({"b.py": 'path = "/Users/x/.local/share/uv"'}) == []


def test_forbidden_directories_are_caught_by_path_alone() -> None:
    """A working-material directory fails on its path, whatever it contains.

    MEMORY/ escaped with content that matched no secret pattern at all. The
    directory is the violation.
    """
    for directory in FORBIDDEN_DIRS:
        problems = scan({f"{directory}/anything.md": "entirely innocuous text"})
        assert problems != [], f"{directory}/ was not caught by path"
