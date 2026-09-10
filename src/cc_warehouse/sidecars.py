"""What may sit beside a session transcript, and what nobody is copying yet.

Ticket 38. THE DEFECT THIS CLOSES is not "tool-results was not archived"; it is
that nothing in the product ever ENUMERATED what sits beside a transcript.
`capture.py` asked for `subagents/` by name and ignored the rest of the
directory, so Claude Code could start writing a new sibling and the archive would
quietly stop being complete. It did: `tool-results/` appeared on 2026-05-08 and
was found four months later, 1,067 dirs and 135.7 MB, 65.4 MB of it held nowhere
else. `workflows/` appeared too, unnoticed for the same reason.

So this module holds the ONE list of known names, and a fence in
tests/test_sidecar_archive.py asserts that `archive.COPIERS` covers exactly it.
A name cannot be acknowledged here without a copier, and a copier cannot exist
for a name that is not here. Anything else beside a transcript is reported as an
anomaly by the callers, so the next new sibling announces itself on the day it
appears rather than in four months.

RULING (c), 2026-09-06, sidecar identity. A `.txt` under `tool-results/` carries
no `sessionId`, so ruling (a) - identity from content - cannot reach it. Its
parent is therefore the session whose transcript sits BESIDE its dir. The
transcript's own identity is still decided from content; the DIR is located by
that content uuid first and by the file stem only as a fallback. The dir name is
a source-layout FILTER, the same exemption `sweep.py` already has for the
`agent-` prefix under the F4 fence. It is never used to file a sidecar whose
transcript is absent as if it were a session.

A LEAF MODULE, deliberately: `archive`, `capture`, `sweep`, `doctor` and
`status` all need this answer, so it may import none of them (R9). Stdlib only.

THREE LEVELS of stranger, because they are found by different walks and cost
different amounts:

  A  a child of `<uuid>/` that is not a known sidecar name       per capture and sweep
  B  a child of the PROJECT dir that is not a transcript,
     a session dir, `memory/` or an ignored name                 `ccw doctor` only
  C  a child of `subagents/` that is not one of the four
     shapes Claude Code actually writes there                    per capture and sweep

Names INSIDE `tool-results/` are deliberately NOT judged. The copier mirrors the
whole tree, so a new file shape is archived rather than lost, and flagging one
would be permanent noise - the ticket 24.7 lesson (an alert that fires on a
healthy machine trains the operator to stop reading it). The one rule instead is
that the copier recurses: the real `pdf-<uuid>/page-NN.jpg` nesting proves a
top-level listing is not enough.
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path

SUBAGENTS_DIR = "subagents"
TOOL_RESULTS_DIR = "tool-results"
WORKFLOWS_DIR = "workflows"
# Claude Code started writing this beside a transcript's `<uuid>/` dir at some
# point after the 2026-09-06 measurement below - a single flat FILE holding a
# renamed session's title (`{"customTitle": "..."}`), not a directory. Found
# 2026-09-10 when it fired the level-A anomaly alert this module exists to
# raise. It gets the SUBAGENTS_DIR treatment (its own dedicated copier,
# `archive.write_custom_title`), never `copy_companion_dir`, because that
# copier mirrors a directory tree and this is one small file.
CUSTOM_TITLE_FILE = "custom-title.json"

# Measured 2026-09-06 over all 1,196 real `<uuid>/` dirs: these three plus
# `.DS_Store` were the only children that existed THEN. `CUSTOM_TITLE_FILE`
# is a fourth, confirmed real on 2026-09-10 - the measurement above is
# historical, not a claim that nothing has been added since.
SESSION_SIDECARS = frozenset({SUBAGENTS_DIR, TOOL_RESULTS_DIR, WORKFLOWS_DIR, CUSTOM_TITLE_FILE})

# Skipped at EVERY depth, by the scan and by the copier alike. Finder writes one
# of these into any folder a human browses, and the archive already holds 125 of
# them inside session folders from before this rule existed.
IGNORED = frozenset({".DS_Store"})

# Project-dir children that are neither transcripts nor session sidecar dirs and
# are still expected. `memory/` is Claude Code's per-project memory directory;
# ticket 40 owns whether it gets archived, and until then reporting it as a
# stranger every single run would be a permanent false positive.
PROJECT_KNOWN = frozenset({"memory"})

_JSONL_SUFFIX = ".jsonl"

# What Claude Code really writes inside `subagents/`, measured 2026-09-06: the
# transcripts, their `.meta.json`, the two forked-skill companions, and a
# `workflows/` dir holding Workflow-tool sub-agents.
#
# F4 NOTE, because this looks like the banned shape and is not. The fence
# `test_no_module_identifies_a_subagent_by_filename` rejects the exact string
# constants "agent-" and "agent-*" outside `sweep.py`. This is a different
# constant, and more importantly a different JOB: it classifies a directory
# entry as EXPECTED or ANOMALOUS. It never decides what a payload IS - that
# stays `archive.is_subagent`, reading content. If the fence's rule is ever
# widened to patterns, exempt this module by name on that ground.
_SUBAGENT_CHILD_RE = re.compile(
    r"^agent-[A-Za-z0-9_.-]+\.(?:jsonl|meta\.json|forked-skill(?:\.marker)?\.json)$"
    rf"|^{WORKFLOWS_DIR}$"
)


@dataclass(frozen=True)
class SidecarScan:
    """What sits beside one transcript, sorted into what we handle and what we do not.

    `sidecar_dir` is None when the session has no `<uuid>/` dir at all, which is
    the common case (1,196 dirs against ~28,000 transcripts) and is not an
    anomaly. `known` is what a copier exists for; `unknown` is level A; and
    `unknown_inside_subagents` is level C, kept as its own field because
    `subagents` itself reads as known and a stranger nested inside it would
    otherwise ride along invisibly.
    """

    sidecar_dir: Path | None
    known: tuple[str, ...]
    unknown: tuple[str, ...]
    unknown_inside_subagents: tuple[str, ...]

    @property
    def has_anomaly(self) -> bool:
        return bool(self.unknown or self.unknown_inside_subagents)


def locate(transcript_path: Path, session_uuid: str | None) -> Path | None:
    """This transcript's sidecar dir, by content uuid first and file stem second.

    Ruling (c). The order matters for exactly one real file shape and it exists:
    `<uuid>.orphaned-<n>-<hash>.jsonl`, whose stem is not the bare uuid, so a
    stem-keyed lookup misses its `<uuid>/` dir entirely. `capture.py` has carried
    that gap since ticket 21. The stem fallback is still needed for a payload
    whose content carries no uuid at all.
    """
    parent = transcript_path.parent
    for name in (session_uuid, transcript_path.stem):
        if not name:
            continue
        candidate = parent / name
        if candidate.is_dir():
            return candidate
    return None


def _entries(directory: Path) -> list[os.DirEntry[str]]:
    """Directory entries, or nothing at all if the directory cannot be listed.

    NEVER RAISES, and never opens a file (F5). This runs on the capture hook's
    critical path and once per session on a ~24,000-file sweep, so it answers
    from directory entries alone. An unreadable directory reads as empty: the
    signal must not be the thing that fails a capture (DESIGN 12), and reporting
    no anomaly is safer than inventing one.
    """
    try:
        with os.scandir(directory) as it:
            return list(it)
    except OSError:
        return []


def scan(transcript_path: Path, session_uuid: str | None) -> SidecarScan:
    """Sort this session's sidecar children into known, level A and level C."""
    directory = locate(transcript_path, session_uuid)
    if directory is None:
        return SidecarScan(None, (), (), ())

    known: list[str] = []
    unknown: list[str] = []
    for entry in _entries(directory):
        if entry.name in IGNORED:
            continue
        (known if entry.name in SESSION_SIDECARS else unknown).append(entry.name)

    nested: list[str] = []
    if SUBAGENTS_DIR in known:
        nested = [
            entry.name
            for entry in _entries(directory / SUBAGENTS_DIR)
            if entry.name not in IGNORED and not _SUBAGENT_CHILD_RE.match(entry.name)
        ]

    return SidecarScan(
        directory, tuple(sorted(known)), tuple(sorted(unknown)), tuple(sorted(nested))
    )


def scan_project_dir(project_dir: Path) -> tuple[str, ...]:
    """LEVEL B: children of a project dir that are neither a transcript nor a
    directory nor an expected name.

    Directories are ALWAYS fine here: every one is either a session's sidecar dir
    or `memory/`, and a directory with no transcript beside it is a different
    question with a different answer (`stranded_dirs`). So this reports stray
    FILES only. Nothing in the live tree trips it today, which is the point - it
    is the instrument that says when that changes.
    """
    strangers = [
        entry.name
        for entry in _entries(project_dir)
        if not entry.is_dir()
        and entry.name not in IGNORED
        and entry.name not in PROJECT_KNOWN
        and not entry.name.endswith(_JSONL_SUFFIX)
    ]
    return tuple(sorted(strangers))


def stranded_dirs(project_dir: Path) -> tuple[Path, ...]:
    """Sidecar dirs whose transcript is not beside them (ruling (d)).

    91 exist in the live source tree and 39 hold `tool-results/`. Nothing carries
    them into the archive, because the archive is organised by session and the
    session is not here. Ruling (d) copies them under `_not-sessions/` with the
    dir name recorded as a LABEL rather than claimed as identity - a directory
    name is not a session (F4), and the whole reason they are stranded is that
    the file that would have proved otherwise is absent.
    """
    out = [
        Path(entry.path)
        for entry in _entries(project_dir)
        if entry.is_dir()
        and entry.name not in IGNORED
        and entry.name not in PROJECT_KNOWN
        and not (project_dir / f"{entry.name}{_JSONL_SUFFIX}").is_file()
    ]
    return tuple(sorted(out))
