"""ccw doctor: is capture actually working, and if not, since when.

Ticket 23, slice 23c. DESIGN section 7 (`ccw doctor` row) and section 15 entry
"`ccw doctor`, AND WHY IT IS A VERB".

THE FAILURE THIS EXISTS FOR. Capture stopped on 2026-07-24 and nobody found out
for ten days. Every link an operator would check looked healthy: the plugin was
enabled, its cached files matched what its repo held, and the CLI it delegated to
existed and still exposed the verb being called. The break was one layer below
all of that, and the wrapper discarded the child's non-zero exit.

Nothing in the product could have said so. `ccw status` reads the catalog, so a
hook that never runs writes no row and raises no error; silence and idleness are
the same shape. The question "is the machinery working" had no owner.

READ-ONLY BY CONSTRUCTION, which is not a nicety here: doctor runs when things
are broken, so it must not materialise a warehouse that was never there. It
opens the catalog read-only and never through catalog.open_catalog, whose
docstring says "creating if needed".
"""

import json
import re
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import cc_warehouse
from cc_warehouse import archive, parser, status, store, sweep
from cc_warehouse.config import Config

# How far behind the rest of the corpus a session may fall before it counts as
# missed rather than merely pending.
_OVERDUE_SECONDS = 24 * 60 * 60

# Ticket 34: how long a just-captured folder gets before a missing render file
# counts as a real problem rather than "still queued". Covers the live hook's
# own single-session detached render child, which holds no lock at all, so
# `_BATCH_LOCK_NAMES` below cannot see it. Deliberately short: a normal
# single-session render finishes in well under a minute; this is headroom for
# process-start jitter, not a render budget. The much longer bulk-batch case
# (hundreds of sessions queued behind `ccw sweep`'s call to `build.build()`,
# measured 2026-09-01 at over 7 minutes for one item) is NOT covered by this
# window on purpose -- it is covered by the lock check instead, which lasts
# exactly as long as the batch actually takes rather than guessing a number.
_PENDING_GRACE_SECONDS = 120

# The lock names `sweep.py` (`_SWEEP_LOCK`) and `build.py` (`_BUILD_LOCK`)
# acquire for their entire run. Repeated here as literals rather than
# importing those private module constants across a peer boundary: the
# shared truth this module actually depends on is store.py's lock file
# FORMAT (`lock_is_held`), not sweep/build's own private naming choice, and a
# renamed lock constant over there would need a matching rename here either
# way. A test pins both names against their source of truth so this cannot
# drift silently.
_BATCH_LOCK_NAMES = ("sweep", "build")

# A hook that mentions either console script is ours; the plugin wrapper and a
# settings.json entry both end up as a command string containing one of these.
_OUR_COMMANDS = ("ccw", "cc-warehouse")

# A hook wrapper is a small script. Anything larger is not one, and reading it
# would turn a diagnosis into an unbounded file read.
_WRAPPER_READ_LIMIT = 64 * 1024

# Ticket 31.5: how many of the MOST RECENT archive folders to verify. A desync from an
# in-flight capture failure shows up in sessions just captured, not one archived months
# ago, so a small bounded sample catches the failure mode `verify_folder` exists for
# without reintroducing the O(everything) cost ticket 31 exists to remove elsewhere. An
# older, long-standing desync outside the sample is NOT caught here -- `ccw archive
# --verify` over the full tree is still the complete answer, run by hand or by the
# weekly job (deliberate scope decision, recorded rather than defaulting to "check
# everything").
_DESYNC_SAMPLE = 25


@dataclass(frozen=True)
class Check:
    """One diagnosis. `blocking` marks the ones that decide the exit code, so a
    figure can be reported without being an alarm."""

    name: str
    ok: bool
    detail: str
    blocking: bool = True


@dataclass(frozen=True)
class Report:
    checks: tuple[Check, ...]

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks if check.blocking)


def install_mode(module_file: Path) -> str:
    """`frozen` or `editable`, from where the code was ACTUALLY loaded.

    `pyproject.toml` can pin the mode, but a pin is a REQUEST: advisory, honoured
    only by the operator's own shell functions, inert on another machine, and
    overridable by an explicit flag. It says what should be installed, never what
    is. This says what is running.

    THE IMPORT PATH RATHER THAN PEP 610, deliberately. `direct_url.json` is the
    standard record of how a distribution was installed, and it is the right
    answer to a different question; it also sits four levels down under a
    version-stamped `.dist-info`, so a lookup can MISS. A miss returns nothing,
    nothing reads as "no editable flag", and that reads as FROZEN, which is the
    dangerous wrong answer delivered silently. I shipped exactly that bug in a
    documented command on 2026-08-03 and it printed empty for an hour without
    anyone noticing. `__file__` cannot miss.
    """
    parts = set(module_file.parts)
    return "frozen" if {"site-packages", "dist-packages"} & parts else "editable"


def _mentions_ccw(command: str, plugin_root: Path | None) -> bool:
    """Whether this hook command runs OUR capture, following one level of wrapper.

    A plugin registers its hook as `python3 ${CLAUDE_PLUGIN_ROOT}/hooks/ccw-hook.py`,
    so the word `ccw` can be absent from the command entirely while the script it
    names calls nothing else. Matching only the command string reported NO HOOK
    REGISTERED while capture worked, and an instrument that cries wolf is ignored,
    which is the same as not having one.

    ONE level, and only files that already exist: this is a diagnosis, not an
    interpreter, and it must stay read-only and bounded (F9).
    """
    if any(name in command for name in _OUR_COMMANDS):
        return True
    for token in command.split():
        if plugin_root is not None:
            token = token.replace("${CLAUDE_PLUGIN_ROOT}", str(plugin_root))
        candidate = Path(token)
        if candidate.suffix not in {".py", ".sh", ".ts", ".js"} or not candidate.is_file():
            continue
        try:
            # R1 (as amended): size here is a RESOURCE BOUND, never identity and
            # never a version ordering. Nothing about this file is decided by how
            # big it is; the comparison only refuses to slurp something that is
            # not a hook wrapper, so a diagnosis cannot be turned into an
            # unbounded read by a path that happens to end in .py. Identity in
            # this function is decided by the CONTENT that follows (F1/F4).
            if candidate.stat().st_size > _WRAPPER_READ_LIMIT:
                continue
            body = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if any(name in body for name in _OUR_COMMANDS):
            return True
    return False


def _enabled_plugins(home: Path) -> dict[str, bool]:
    """The `plugin@marketplace` keys Claude Code has explicitly enabled or
    disabled, from `~/.claude/settings.json`'s `enabledPlugins`.

    Best-effort: a missing or unreadable settings file yields an empty map, so
    `_hook_commands` then treats every plugin-sourced hook as unconfirmed
    (excluded) rather than guessing. That is the safe default here: doctor's
    whole purpose is to not claim capture works when it might not."""
    path = home / ".claude" / "settings.json"
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(loaded, dict):
        return {}
    enabled = cast(dict[str, object], loaded).get("enabledPlugins")
    if not isinstance(enabled, dict):
        return {}
    return {k: v is True for k, v in cast(dict[str, object], enabled).items()}


def _hook_commands(home: Path) -> list[tuple[str, Path | None, str | None]]:
    """Every SessionEnd hook command Claude Code would ACTUALLY run, paired
    with its plugin root and a human-readable `plugin@marketplace` source
    label (None for a non-plugin, settings.json-level hook).

    Both places a capture hook can legitimately live: settings files, and an
    installed plugin's hooks.json. Checking only settings.json would report "no
    hook" for a correctly installed PLUGIN, which is exactly how ticket 24
    delivers it. The plugin root travels alongside so `${CLAUDE_PLUGIN_ROOT}` can
    be resolved.

    SCOPED TO SessionEnd, deliberately. This used to walk every event key in
    `hooks{}` and let `diagnose()` label whatever it found FIRST as "the
    SessionEnd capture hook" -- so an unrelated SessionStart command that merely
    CONTAINS "ccw" (a monitoring script named `ccw-watch`, say) outranked the
    real plugin-registered SessionEnd hook, because settings.json is scanned
    before plugin hooks.json. Doctor would then say "ok" for the wrong hook,
    which survives the real one being removed entirely (found 2026-08-18).

    ALSO GATED ON `enabledPlugins` (found 2026-08-23, a real mistake made while
    building ticket 24.7): a plugin's cache directory can outlive its removal
    from Claude Code entirely. `claude-transcript-exporter@gz-claude-code-
    plugins` was retired when ticket 28.19 moved capture into
    `cc-capture@cc-warehouse`, but its OLD cached hooks.json could still sit on
    disk, glob-matched here, a perfectly ordinary-looking hooks.json. Without
    this check doctor would report a hook Claude Code will never invoke. A
    plugin-sourced candidate only counts when `enabledPlugins` says `true` for
    its exact `plugin@marketplace` key; absent or `false` both exclude it. A
    non-plugin (settings.json-level) command is unaffected: it needs no
    enablement key to be real.
    """
    found: list[tuple[str, Path | None, str | None]] = []
    candidates = [home / ".claude" / "settings.json", home / ".claude" / "settings.local.json"]
    cache = home / ".claude" / "plugins" / "cache"
    if cache.is_dir():
        candidates.extend(sorted(cache.glob("*/*/*/hooks/hooks.json")))
    enabled = _enabled_plugins(home)
    for path in candidates:
        if not path.is_file():
            continue
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(loaded, dict):
            continue
        hooks = cast(dict[str, object], loaded).get("hooks")
        if not isinstance(hooks, dict):
            continue
        groups = cast(dict[str, object], hooks).get("SessionEnd")
        if not isinstance(groups, list):
            continue
        is_plugin = path.parent.name == "hooks"
        source: str | None = None
        if is_plugin:
            # cache/<marketplace>/<plugin>/<version>/hooks/hooks.json
            marketplace = path.parent.parent.parent.parent.name
            plugin_name = path.parent.parent.parent.name
            source = f"{plugin_name}@{marketplace}"
            if not enabled.get(source, False):
                continue
        root = path.parent.parent if is_plugin else None
        for group in cast(list[object], groups):
            if not isinstance(group, dict):
                continue
            inner = cast(dict[str, object], group).get("hooks")
            if not isinstance(inner, list):
                continue
            for hook in cast(list[object], inner):
                if isinstance(hook, dict):
                    command = cast(dict[str, object], hook).get("command")
                    if isinstance(command, str):
                        found.append((command, root, source))
    return found


def _last_capture(root: Path) -> str | None:
    """When capture last ran, from the catalog, WITHOUT creating it.

    None means it has never run: no catalog, or no capture_event rows. That
    distinction is the whole point of this check. On 2026-07-24 the failure
    looked like "fired, but not recently" and was in fact "never fired here".
    """
    path = root / "catalog.sqlite"
    if not path.is_file():
        return None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        row = cast(
            tuple[str | None] | None,
            conn.execute("SELECT MAX(at) FROM capture_event").fetchone(),
        )
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    return row[0] if row and row[0] else None


def _last_activity(path: Path) -> str | None:
    """The payload's own final timestamp (R12), never a file mtime."""
    try:
        return parser.parse_session(path.read_bytes()).last_ts
    except (OSError, ValueError):
        return None


def _moment(stamp: str | None) -> datetime | None:
    """An ISO payload timestamp as an aware datetime, or None if unusable."""
    if not stamp:
        return None
    try:
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _folder_moment(name: str) -> datetime | None:
    """The session start encoded in an archive folder name, `YYYYMMDD-HHMMSS+ZZZZ_<uuid>`.

    Payload-derived (archive.py builds it from the payload's first timestamp in
    the pinned zone), so it is a legitimate R12 source and costs only the
    directory listing this function already does.
    """
    stamp = name.partition("_")[0]
    match = re.match(r"^(\d{8})-(\d{6})([+-]\d{4})$", stamp)
    if not match:
        return None
    try:
        return datetime.strptime("".join(match.groups()), "%Y%m%d%H%M%S%z")
    except ValueError:
        return None


def _recent_archive_folders(archive_root: Path, limit: int) -> list[Path]:
    """The `limit` most-recently-STARTED archive folders, newest first.

    Ordered by the payload-derived start time encoded in the folder name (R12), never by
    mtime: an untouched folder still sorts by when its session happened, not by when this
    check last ran. `archive.walk_folders` sorts by label then name, which is only
    chronological WITHIN one label, so the moments are collected and re-sorted globally
    here rather than trusting that order directly."""
    dated: list[tuple[datetime, Path]] = []
    for folder in archive.walk_folders(archive_root):
        moment = _folder_moment(folder.name)
        if moment is not None:
            dated.append((moment, folder))
    dated.sort(key=lambda pair: pair[0], reverse=True)
    return [folder for _, folder in dated[:limit]]


def desync_detail(
    config: Config,
) -> tuple[list[Path], list[tuple[Path, list[archive.FolderProblem]]]]:
    """The most recent `_DESYNC_SAMPLE` archive folders, and which of them
    `archive.verify_folder` flags (ticket 31.5 / ticket 32). The one place the
    recency scan actually runs; `_desync` (doctor's own summary) and `ccw
    repair` (the write-side companion, cli.py `_run_repair`) both read this
    rather than re-walking the archive a second time (R9). PUBLIC, deliberately
    (unlike most of this module): it is the one thing outside doctor.py that
    legitimately needs doctor's own recency scan rather than a second copy of it."""
    if config.archive_root is None or not config.archive_root.is_dir():
        return [], []
    folders = _recent_archive_folders(config.archive_root, _DESYNC_SAMPLE)
    broken = [
        (folder, problems)
        for folder in folders
        if (problems := archive.verify_folder(folder, config.archive_timezone))
    ]
    return folders, broken


def _batch_render_in_progress(root: Path) -> bool:
    """True while `ccw sweep` or `ccw build` is actively running against this
    warehouse (ticket 34). A pure read (`store.lock_is_held`), so this keeps
    doctor read-only by construction. `build.build()` holds its lock for its
    entire per-head loop (acquire before the loop, release in a `finally`
    after), so this stays true for exactly as long as a sweep-triggered batch
    is still rendering -- unlike a fixed timer, it cannot expire mid-batch."""
    return any(store.lock_is_held(root, name) for name in _BATCH_LOCK_NAMES)


def _desync(config: Config) -> tuple[int, int, int, str | None]:
    """Verify the most recently captured archive folders against their own manifests
    (ticket 31.5). Returns (checked, problems, pending, first problem description or
    None) -- `problems` is what blocks `report.ok`; `pending` never does.

    BOUNDED, DELIBERATELY (see `_DESYNC_SAMPLE`): `archive.verify_folder` reads and
    re-hashes each folder's JSONL, so a full pass over a 21,000+ folder tree is not
    SessionStart-cheap -- that cost is exactly what ticket 31 exists to remove elsewhere.

    PENDING VS. PROBLEM (ticket 34). A folder missing its generated files is not
    always broken: `ccw sweep` can capture hundreds of sessions in under two
    minutes and then render them afterward through `build.build()`, which takes
    real wall-clock time (measured 2026-09-01: one ordinary session took 7m14s
    from capture to fully rendered, inside a 446-session batch). Sampling mid-batch
    used to report every still-queued folder as broken -- confirmed as the real
    mechanism behind a live false alarm the same day (`ccw-watch`'s RED banner
    fired 24 seconds after one such folder was captured).

    NARROW ON PURPOSE: a folder reclassifies as PENDING only when EVERY one of
    its problems is a missing-generated-file problem (`FolderProblem.problem`
    starting with "missing ", the one shape `archive.verify_folder` produces for
    a not-yet-rendered file -- see `GENERATED_NAMES`) AND either a sweep/build
    batch is currently running (`_batch_render_in_progress`, covering the bulk
    case for as long as it actually takes) or the folder was captured within
    `_PENDING_GRACE_SECONDS` of now (covering the live hook's own single-session
    detached render child, which holds no lock at all). Any OTHER problem shape
    on a folder -- a hash mismatch, an unreadable manifest, a missing/altered
    sub-agent, a name that disagrees with its own payload -- always counts as a
    real problem regardless of timing, because none of those describe "still
    queued"; they describe something actually wrong. A folder with a mix (some
    missing files AND, say, a hash mismatch) is real too, for the same reason.
    Pending folders are still counted and still surfaced in the detail text -- a
    genuinely stuck pending item does not become invisible, it just does not
    trip the alarm on its own.
    """
    folders, broken = desync_detail(config)
    if not broken:
        return len(folders), 0, 0, None
    # broken is non-empty only when desync_detail actually walked a configured
    # archive, so config.root is a real warehouse to check locks against.
    batch_active = _batch_render_in_progress(config.root)
    now = datetime.now(UTC)
    problems: list[tuple[Path, list[archive.FolderProblem]]] = []
    pending_count = 0
    for folder, folder_problems in broken:
        only_missing_files = all(p.problem.startswith("missing ") for p in folder_problems)
        moment = _folder_moment(folder.name)
        within_grace = moment is not None and (now - moment) <= timedelta(
            seconds=_PENDING_GRACE_SECONDS
        )
        if only_missing_files and (batch_active or within_grace):
            # Counted the same unit as `problem_count` below (individual
            # FolderProblem entries, e.g. up to one per GENERATED_NAMES file),
            # not folders -- so "N problem(s)" and "M pending render(s)" stay
            # directly comparable in the detail text.
            pending_count += len(folder_problems)
        else:
            problems.append((folder, folder_problems))
    problem_count = sum(len(p) for _, p in problems)
    first = f"{problems[0][0].name}: {problems[0][1][0].problem}" if problems else None
    return len(folders), problem_count, pending_count, first


def _overdue(config: Config, walk_root: Path) -> tuple[int, str | None]:
    """Uncaptured sessions that the rest of the corpus has moved on without.

    RELATIVE TO THE CORPUS, not to the wall clock, and that is a deliberate
    choice rather than a convenience. A session still being written is not
    missed, so "older than N hours" would flag the session doctor is being run
    from. Comparing against the NEWEST activity anywhere in the source tree asks
    the question that actually matters: have other sessions ended since this one
    while it stayed uncaptured? It is also deterministic, so it can be tested
    without freezing a clock.
    """
    if config.archive_root is None:
        return 0, None
    archived: set[str] = set()
    newest_archived: datetime | None = None
    if config.archive_root.is_dir():
        for label_dir in config.archive_root.iterdir():
            if label_dir.is_dir():
                for session_dir in label_dir.iterdir():
                    if session_dir.is_dir():
                        _stamp, _sep, tail = session_dir.name.partition("_")
                        archived.add(tail)
                        moment = _folder_moment(session_dir.name)
                        if moment is not None and (
                            newest_archived is None or moment > newest_archived
                        ):
                            newest_archived = moment
    # ONLY THE UNCAPTURED ARE READ. The first version parsed every transcript in
    # the source tree to find the newest activity: 35 SECONDS on a 14,000-session
    # corpus. A health check nobody wants to wait for does not get run, which is
    # the crying-wolf failure wearing different clothes.
    #
    # THE ANCHOR STAYS IN PAYLOAD TIME. An earlier attempt used the catalog's
    # last capture, which is WALL-CLOCK, and comparing it to session timestamps
    # made January fixtures look overdue on an August machine. Archive folder
    # names carry the session's own start time in the pinned zone, so the newest
    # of them is a payload-derived anchor that costs a directory listing (R12).
    sessions, _subagents = sweep.source_transcripts(walk_root)
    stamps: dict[Path, datetime] = {}
    for path in sessions:
        if path.name.removesuffix(".jsonl") in archived:
            continue
        moment = _moment(_last_activity(path))
        if moment is not None:
            stamps[path] = moment
    if not stamps:
        return 0, None
    anchor = max([*stamps.values(), *filter(None, (newest_archived,))])
    cutoff = anchor - timedelta(seconds=_OVERDUE_SECONDS)
    overdue = [path for path, last in stamps.items() if last < cutoff]
    oldest = min((stamps[p] for p in overdue), default=None)
    return len(overdue), (oldest.isoformat() if oldest else None)


def diagnose(config: Config, home: Path | None = None, source: Path | None = None) -> Report:
    """Every check, in the order an operator would ask them."""
    where = home if home is not None else Path.home()
    walk_root = source if source is not None else where / ".claude" / "projects"
    checks: list[Check] = []

    resolved = shutil.which("ccw")
    checks.append(
        Check(
            "reachable",
            resolved is not None,
            f"ccw resolves to {resolved}" if resolved else "ccw is NOT on PATH",
            blocking=False,
        )
    )

    matches = [
        (c, hook_source)
        for c, root, hook_source in _hook_commands(where)
        if _mentions_ccw(c, root)
    ]
    if matches:
        command, hook_source = matches[0]
        detail = (
            f"SessionEnd capture hook found via {hook_source}: {command}"
            if hook_source
            else f"SessionEnd capture hook found: {command}"
        )
    else:
        detail = "NO capture hook is registered; sessions are not being captured"
    checks.append(Check("hook", bool(matches), detail))

    last = _last_capture(config.root)
    checks.append(
        Check(
            "fired",
            last is not None,
            f"last capture {last}" if last else "capture has NEVER fired on this machine",
        )
    )

    gap = status.uncaptured_gap(config, walk_root)
    checks.append(Check("uncaptured", True, status.gap_line(gap), blocking=False))

    count, oldest = _overdue(config, walk_root)
    checks.append(
        Check(
            "overdue",
            count == 0,
            "nothing overdue"
            if count == 0
            else f"{count} session(s) OVERDUE, oldest last active {oldest}",
        )
    )

    checked, problems, pending, first_problem = _desync(config)
    pending_suffix = f", {pending} pending render(s)" if pending else ""
    if config.archive_root is None:
        desync_detail = "no archive configured"
    elif checked == 0:
        desync_detail = "no archived sessions yet"
    elif problems == 0:
        desync_detail = (
            f"0 problems{pending_suffix} in the {checked} most recently captured folder(s)"
        )
    else:
        desync_detail = (
            f"{problems} problem(s){pending_suffix} in the {checked} most recently captured"
            f" folder(s), e.g. {first_problem}"
        )
    checks.append(Check("desync", problems == 0, desync_detail))

    module = Path(cc_warehouse.__file__).parent
    mode = install_mode(module)
    checks.append(
        Check(
            "install",
            True,
            f"{mode}: running from {module}"
            + (
                "  <- edits to this checkout ARE the capture path"
                if mode == "editable"
                else ""
            ),
            blocking=False,
        )
    )

    checks.append(
        Check(
            "config",
            True,
            f"root={config.root} archive_root={config.archive_root}"
            f" zone={config.archive_timezone} keep_objects={config.keep_objects}"
            f" keep_projections={config.keep_projections}",
            blocking=False,
        )
    )
    return Report(tuple(checks))


def report_text(report: Report) -> str:
    lines = [
        f"  {'ok ' if check.ok else 'FAIL' if check.blocking else '   '} "
        f"{check.name:<11} {check.detail}"
        for check in report.checks
    ]
    lines.append("")
    lines.append("doctor: capture is working" if report.ok else "doctor: capture is NOT working")
    return "\n".join(lines)
