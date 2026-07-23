"""ccw relocate: repair the external world after a repo move (slice 12).

DESIGN section 11 (the riskiest surface; FINDINGS F2/F7/F9 apply doubly): PLAN ->
BACKUP -> APPLY -> VERIFY -> REPORT; dry-run is the default; contents are rewritten
BEFORE containers are renamed; encoded-dir matching is boundary-guarded.

Safety posture (every clause below is a refusal or a named report, never a silent skip):
- Pre-flight validates everything it can before any mutation and refuses having changed
  NOTHING (R5/F7): same device, source is a real directory (not a symlink), source and
  target are not nested in one another, every rename target is free, every directory to
  be written is writable, and the registry move is legal.
- Cross-device relocate is refused: os.rename cannot cross filesystems and R4 forbids the
  delete-half of a copy+delete, so there is no sanctioned cross-device move.
- The warehouse root is never a content-rewrite target: rewriting a stored object would
  break its content address (R4/F9). Symlinks are never written through, and a file that
  cannot be read or decoded is REPORTED as unrepaired rather than silently skipped.
- Backup reads each file once and both stores that pre-image and rewrites from it, so a
  backup always matches the bytes that were transformed. The repo and encoded dirs are
  MOVED same-device (a rename recorded in the run's journal), not copied.
- Every write (backup, content, journal, manifest) goes through store.atomic_write (R2).
  Nothing is deleted (R4/F9). A manifest is written on every path that mutated anything.
"""

import json
import os
import re
import sqlite3
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from cc_warehouse import catalog, registry, store
from cc_warehouse.config import Config
from cc_warehouse.reports import BatchReport, ItemOutcome

RELOCATE_LOCK = "relocate"
LOCK_HELD_ACTION = "lock-held"
_LOCK_HELD_ITEM = "relocate"
# A path/name continuation char. A boundary is anything else, so `/x/widget` matches
# `/x/widget/src` but never the different directories `/x/widget-two` or `/x/widget.bak`.
_NAME_CHARS = r"[A-Za-z0-9_.-]"
_MAX_CONTENT_BYTES = 8 * 1024 * 1024  # a bigger file is reported, never slurped (F5)


@dataclass(frozen=True)
class RelocateEdit:
    kind: str  # alias | encoded_dir | memory_file | inventory_file
    target: Path
    detail: str
    # True when this entry records something the run REFUSED to touch. A skip belongs in
    # the report by name (R10) and out of every total: counting refusals as work inflates
    # the blast radius before consent and overstates what happened after it (F6). Typed
    # rather than sniffed from the detail string, so a reworded message cannot silently
    # change a count.
    skipped: bool = False


@dataclass(frozen=True)
class RelocatePlan:
    repo_path: Path
    new_path: Path
    edits: tuple[RelocateEdit, ...]


# The outcome actions that represent a real change to the world. Shared by the success
# line and the halted-run report so the two can never disagree about what counts (R9).
CHANGE_ACTIONS = ("rewritten", "moved", "renamed", "alias")


def planned_changes(plan: RelocatePlan) -> tuple[RelocateEdit, ...]:
    """The plan entries a run would actually MAKE; skips are shown but never counted."""
    return tuple(edit for edit in plan.edits if not edit.skipped)


def applied_changes(report: BatchReport) -> tuple[ItemOutcome, ...]:
    """The outcomes that changed something; refusals and skips are not changes."""
    return tuple(o for o in report.outcomes if o.action in CHANGE_ACTIONS)


@dataclass(frozen=True)
class _Scan:
    """What a content scan found: rewritable targets plus everything it could not."""

    targets: tuple[Path, ...]
    skipped: tuple[tuple[Path, str], ...]
    config_error: str | None


def _now() -> str:
    return datetime.now(UTC).isoformat()


HOME_UNSET_ERROR = (
    "HOME is not set: relocate cannot locate ~/.claude/projects, so the encoded-dir"
    " renames and the source-transcript guard would both be inert while the content scan"
    " still reaches the real home through pwd. Refusing rather than half-relocating."
    " Set HOME and re-run."
)


def home_error() -> str | None:
    """The refusal reason when HOME is unset, else None (ticket 12a).

    Under cron or launchd there is frequently no HOME. `os.path.expanduser` still finds
    the account's home through the `pwd` database, so the content scan reaches the real
    tree, but `_claude_projects` reads the environment and returns None: no encoded dir is
    ever a candidate, and the source-transcript exclusion silently protects nothing. That
    asymmetry produces a half-relocated world that reports success. The absence of the
    context needed to do the job is the conservative branch, exactly like the absence of a
    human (R5/F7, and F10 in spirit).
    One implementation, called by both the CLI (before planning) and _preflight (before
    any mutation), so neither the dry-run nor the public module API can slip past it (R9).
    Proven by tests/test_relocate_regressions.py::
    test_home_unset_is_refused_rather_than_running_with_guards_inert.
    """
    return None if os.environ.get("HOME") else HOME_UNSET_ERROR


def _claude_projects() -> Path | None:
    home = os.environ.get("HOME")
    return Path(home) / ".claude" / "projects" if home else None


def _absolute(path: Path) -> Path:
    """Absolutize WITHOUT resolving symlinks (a symlinked source is refused, not followed)."""
    return Path(os.path.abspath(path.expanduser()))


def _resolved(path: Path) -> Path:
    """Fully resolve a path for EXCLUSION comparisons only (ticket 12a).

    The scan enumerates files by their real paths, so an exclusion holding a symlink path
    never compares equal to them and silently protects nothing. A symlinked `CCW_ROOT` (an
    external disk) or a symlinked `~/.claude` (any dotfile-managed account) therefore let
    relocate string-edit an immutable stored object or a captured transcript, breaking
    R4/F9 and the locked "source transcripts are never modified by anything, ever" rule.
    Both sides of every exclusion comparison are resolved so the guard cannot be defeated
    by a link. A resolution failure (a symlink loop, a vanished parent) falls back to the
    unresolved path rather than raising: the conservative branch keeps the candidate under
    whichever comparison still works, it never opens the guard (R5/F7).
    Proven by tests/test_relocate_regressions.py::test_stored_objects_survive_a_symlinked
    _warehouse_root and ::test_source_transcripts_survive_a_symlinked_claude_dir.
    """
    try:
        return path.resolve()
    except OSError:
        return path


def _relocate_roots(root: Path) -> tuple[tuple[Path, ...], str | None]:
    """Read [relocate].roots from <root>/config.toml; returns (roots, parse_error).

    An ABSENT file or section legitimately means no inventory to repair. A file that
    fails to parse is NOT the same thing: it is reported so a typo can never masquerade
    as "nothing to rewrite" while the containers are renamed anyway (R5/F7). The full
    config layering that folds this into load_config lands in slice 13.
    """
    config_path = root / "config.toml"
    if not config_path.exists():
        return (), None
    try:
        with open(config_path, "rb") as fh:
            data = cast(dict[str, object], tomllib.load(fh))
    except OSError as exc:
        return (), f"config.toml unreadable: {exc}"
    except tomllib.TOMLDecodeError as exc:
        return (), f"config.toml is malformed: {exc}"
    section = data.get("relocate")
    if not isinstance(section, dict):
        return (), None
    roots_raw = cast(dict[str, object], section).get("roots")
    if roots_raw is None:
        return (), None
    if not isinstance(roots_raw, list):
        return (), "[relocate].roots is not a list"
    items = cast(list[object], roots_raw)
    return tuple(_absolute(Path(i)) for i in items if isinstance(i, str) and i), None


def _form_patterns(
    old_repo: str, new_repo: str, extra: list[tuple[str, str]] | None = None
) -> list[tuple[re.Pattern[str], str]]:
    """Boundary-guarded (old_form -> new_form) rewrites for absolute/tilde/encoded paths.

    A match must sit at a path boundary (neither neighbour is a name char), so the repo
    path is never rewritten inside a different directory like `.../widget-two` or
    `.../widget.bak`. The tilde form is emitted whenever the OLD path is under $HOME,
    even when the new one is not, so a `~/...` reference is never left stale.
    """
    pairs: list[tuple[str, str]] = [(old_repo, new_repo)]
    home = os.environ.get("HOME")
    if home and old_repo.startswith(home + "/"):
        new_form = "~" + new_repo[len(home) :] if new_repo.startswith(home + "/") else new_repo
        pairs.append(("~" + old_repo[len(home) :], new_form))
    pairs.append((registry.encode_cwd(old_repo), registry.encode_cwd(new_repo)))
    # One literal pair per encoded dir this run actually renames. The generic encoded
    # pattern is boundary-guarded and `-` is a name char, so it matches only the exact
    # dir; without these, a reference to a renamed SUBPROJECT dir would be left dangling
    # by the very run that renamed it. Only renamed dirs are listed, so a reference to a
    # dir we deliberately did not touch is never rewritten either.
    pairs.extend(extra or [])
    compiled: list[tuple[re.Pattern[str], str]] = []
    for old_form, new_form in pairs:
        pat = re.compile(rf"(?<!{_NAME_CHARS}){re.escape(old_form)}(?!{_NAME_CHARS})")
        compiled.append((pat, new_form))
    return compiled


def _sub_text(text: str, patterns: list[tuple[re.Pattern[str], str]]) -> str:
    for pat, repl in patterns:
        text = pat.sub(lambda _m, r=repl: r, text)  # lambda: treat repl as a literal
    return text


def _sub_tree(node: object, patterns: list[tuple[re.Pattern[str], str]]) -> object:
    """Rewrite every string in a decoded JSON structure, KEYS INCLUDED.

    Real memory/config files are keyed BY absolute project path (`{"projects": {"/old":
    ...}}`), so skipping keys would leave the file stale in exactly the field that
    resolves a project, and the verify pass would then re-match it and report a failure
    on a run that actually succeeded. The boundary guard means only a whole path
    component is ever replaced, so a structural key that merely contains the text is safe.
    """
    if isinstance(node, str):
        return _sub_text(node, patterns)
    if isinstance(node, list):
        return [_sub_tree(item, patterns) for item in cast(list[object], node)]
    if isinstance(node, dict):
        return {
            _sub_text(key, patterns): _sub_tree(val, patterns)
            for key, val in cast(dict[str, object], node).items()
        }
    return node


def _rewrite_bytes(path: Path, original: str, patterns: list[tuple[re.Pattern[str], str]]) -> bytes:
    """The rewritten bytes for a pre-image; JSON-aware for .json so the result re-parses."""
    if path.suffix == ".json":
        try:
            data = cast(object, json.loads(original))
        except json.JSONDecodeError:
            rewritten = _sub_text(original, patterns)
        else:
            rewritten = json.dumps(_sub_tree(data, patterns), ensure_ascii=False)
    else:
        rewritten = _sub_text(original, patterns)
    return rewritten.encode("utf-8")


def _scan_content(config: Config, patterns: list[tuple[re.Pattern[str], str]]) -> _Scan:
    """Find files under [relocate].roots that reference the old path.

    Excludes the warehouse root subtree entirely: a stored object is immutable and
    content-addressed, so rewriting one would break its address (R4/F9). Never descends
    or writes through a symlink, and never silently drops a file it cannot handle: an
    unreadable, undecodable, or oversized file is returned as a NAMED skip so the caller
    can report it as unrepaired instead of claiming a clean sweep (R5/F7).
    """
    roots, config_error = _relocate_roots(config.root)
    # RESOLVED on both sides (ticket 12a): the walk yields real paths, so an exclusion
    # holding a symlink path never matches one and protects nothing. See _resolved.
    warehouse = _resolved(_absolute(config.root))
    projects_link = _claude_projects()
    projects = _resolved(projects_link) if projects_link is not None else None
    targets: list[Path] = []
    skipped: list[tuple[Path, str]] = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            real = _resolved(path)
            if warehouse == real or warehouse in real.parents:
                continue  # never rewrite the warehouse (store objects are immutable)
            if projects is not None and (projects == real or projects in real.parents):
                # Captured transcripts are SOURCES: read-only forever (R4/F9). SPEC 10.2
                # keeps the specimen's rule that nothing outside the memory roots is ever
                # string-edited; the encoded dirs are renamed instead.
                continue
            if ".git" in path.parts:
                continue
            if path.is_symlink():
                skipped.append((path, "symlink not rewritten"))
                continue
            if not path.is_file():
                continue
            try:
                # A BOUNDED read, never a stat-size comparison (the F1 fence forbids
                # treating a size as meaningful): read one byte past the cap and refuse
                # anything bigger rather than slurping an unbounded file (F5).
                with path.open("rb") as handle:
                    raw = handle.read(_MAX_CONTENT_BYTES + 1)
            except OSError as exc:
                skipped.append((path, f"unreadable: {exc}"))
                continue
            if len(raw) > _MAX_CONTENT_BYTES:
                skipped.append((path, "file too large to rewrite"))
                continue
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                skipped.append((path, "not UTF-8 text"))
                continue
            if any(pat.search(text) for pat, _ in patterns):
                targets.append(path)
    return _Scan(tuple(targets), tuple(skipped), config_error)


def _encoded_candidates(old_repo: str, new_repo: str) -> list[tuple[Path, Path, str]]:
    """Encoded project dirs whose NAME matches, boundary-guarded (remainder empty or '-').

    The encoding collapses `/`, `_` and `.` to `-`, so a remainder starting with '-' is
    ambiguous between a SUBDIRECTORY of the repo and an unrelated SIBLING repo whose name
    merely contains a hyphen; the caller disambiguates against the catalog.
    """
    projects = _claude_projects()
    if projects is None or not projects.is_dir():
        return []
    prefix = registry.encode_cwd(old_repo)
    new_prefix = registry.encode_cwd(new_repo)
    out: list[tuple[Path, Path, str]] = []
    for entry in sorted(projects.iterdir()):
        if entry.is_symlink() or not entry.is_dir():
            continue
        name = entry.name
        if name != prefix and not (name.startswith(prefix) and name[len(prefix) :].startswith("-")):
            continue
        remainder = name[len(prefix) :]
        out.append((entry, projects / (new_prefix + remainder), remainder))
    return out


def _subdir_encodings(old_repo: Path) -> set[str]:
    """Every encoded name a REAL subdirectory of the repo would produce.

    Encoding forwards is exact; decoding a name backwards is not, because `/`, `_` and
    `.` all collapse to `-`. Comparing against this set therefore proves a candidate is
    a genuine subproject dir instead of guessing (F4).
    """
    names: set[str] = set()
    if not old_repo.is_dir():
        return names
    try:
        for path in old_repo.rglob("*"):
            if path.is_dir() and not path.is_symlink():
                names.add(registry.encode_cwd(str(path)))
    except OSError:
        pass  # an unreadable subtree just yields fewer proofs (R5)
    return names


def _rename_pairs(renames: list[tuple[Path, Path]]) -> list[tuple[str, str]]:
    """(old encoded name -> new encoded name) for every dir this run renames."""
    return [(old_dir.name, new_dir.name) for old_dir, new_dir in renames]


def _encoded_moves(
    root: Path, old_repo: Path, new_repo: str, *, claim_ambiguous: bool
) -> tuple[list[tuple[Path, Path]], list[tuple[Path, str]]]:
    """Split the name-matched candidates into (renames, skips).

    The exact match IS the repo's own dir. A hyphen-remainder candidate is renamed when
    it is PROVEN to belong to the repo, either because the catalog attributes it to a cwd
    at/under the repo or because a real subdirectory of the repo encodes to that exact
    name. Anything else may be an unrelated sibling (`/x/widget-two` encodes exactly like
    `/x/widget/two`), so by default it is left alone and NAMED rather than re-namespaced
    onto the relocated project (F4/F9); --claim-ambiguous opts into taking those too.
    """
    old_str = str(old_repo)
    prefix = old_str.rstrip("/") + "/"
    renames: list[tuple[Path, Path]] = []
    skipped: list[tuple[Path, str]] = []
    candidates = _encoded_candidates(old_str, new_repo)
    subdirs: set[str] = set()
    if any(remainder for _old, _new, remainder in candidates):
        subdirs = _subdir_encodings(old_repo)
    for old_dir, new_dir, remainder in candidates:
        if not remainder:
            renames.append((old_dir, new_dir))
            continue
        # Check EVERY cwd claim: a relocated project KEEPS its previous one (claims are
        # append-only, R4), so a single row could be a stale path for the right project.
        claims = _cwds_for_encoded(root, old_dir.name)
        attributed = any(c == old_str or c.startswith(prefix) for c in claims)
        foreign = bool(claims) and not attributed
        # A matching subdirectory is only a proof when no OTHER real directory encodes to
        # the same name: `/x/widget/two` and `/x/widget-two` both encode to
        # `-x-widget-two`, so a subdir match alone cannot rule the sibling out (F4).
        rival = Path(old_str + remainder)
        contested = rival.is_dir() or rival.is_symlink()
        if attributed or (old_dir.name in subdirs and not contested):
            renames.append((old_dir, new_dir))
        elif claim_ambiguous and not foreign:
            renames.append((old_dir, new_dir))
        else:
            reason = (
                "belongs to another project: not renamed"
                if foreign
                else "unproven encoded dir (possible sibling): not renamed"
                "; --claim-ambiguous takes it"
            )
            skipped.append((old_dir, reason))
    return renames, skipped


def _catalog_conn(root: Path) -> sqlite3.Connection | None:
    """Open the catalog only when it already exists, so a dry-run creates nothing."""
    if not (root / "catalog.sqlite").exists():
        return None
    return catalog.open_catalog(root)


def _cwds_for_encoded(root: Path, encoded_name: str) -> tuple[str, ...]:
    conn = _catalog_conn(root)
    if conn is None:
        return ()
    try:
        return registry.cwds_for_encoded_dir(conn, encoded_name)
    finally:
        conn.close()


def _project_for_cwd(root: Path, cwd: str) -> int | None:
    conn = _catalog_conn(root)
    if conn is None:
        return None
    try:
        return registry.project_for_path(conn, cwd, "cwd")
    finally:
        conn.close()


@dataclass(frozen=True)
class _Computed:
    """One pass over the world: the internals apply needs AND the edits a plan shows.

    Both `plan_relocate` and the apply path derive from this single function, so the set
    the operator consents to and the set apply executes are produced by one implementation
    rather than two that can drift apart (R9/F8, ticket 12a finding 4).
    """

    renames: list[tuple[Path, Path]]
    ambiguous: list[tuple[Path, str]]
    patterns: list[tuple[re.Pattern[str], str]]
    scan: _Scan
    project_id: int | None
    edits: tuple[RelocateEdit, ...]


def _compute(
    config: Config, repo_path: Path, new_path: Path, *, claim_ambiguous: bool
) -> _Computed:
    """Enumerate every edit and the internals behind it, without touching anything."""
    # The encoded renames are decided FIRST so the content patterns can carry one pair
    # per dir this run will actually rename (A2-4: otherwise the rename creates its own
    # dangling references, which the verify pass is blind to by construction).
    renames, ambiguous = _encoded_moves(
        config.root, repo_path, str(new_path), claim_ambiguous=claim_ambiguous
    )
    patterns = _form_patterns(str(repo_path), str(new_path), _rename_pairs(renames))
    scan = _scan_content(config, patterns)
    project_id = _project_for_cwd(config.root, str(repo_path))
    edits: list[RelocateEdit] = []
    # Surfaced as a plan entry, exactly like a malformed config below: a caller that
    # enumerates a plan with HOME unset must SEE why the plan is not honourable, rather
    # than read a short edit list as "not much to do" (R8 - the docstring on home_error
    # promises the module API cannot slip past the guard, so it must not).
    home_problem = home_error()
    if home_problem:
        edits.append(RelocateEdit("inventory_file", config.root, home_problem))
    if scan.config_error:
        edits.append(RelocateEdit("inventory_file", config.root, scan.config_error))
    for target in scan.targets:
        edits.append(RelocateEdit("memory_file", target, f"rewrite path refs -> {new_path}"))
    for path, reason in scan.skipped:
        edits.append(RelocateEdit("inventory_file", path, f"SKIPPED: {reason}", skipped=True))
    for old_dir, new_dir in renames:
        edits.append(RelocateEdit("encoded_dir", old_dir, f"rename -> {new_dir}"))
    for path, reason in ambiguous:
        edits.append(RelocateEdit("encoded_dir", path, f"SKIPPED: {reason}", skipped=True))
    if project_id is not None:
        edits.append(RelocateEdit("alias", new_path, f"claim {new_path} (cwd + encoded)"))
    return _Computed(renames, ambiguous, patterns, scan, project_id, tuple(edits))


def _drift_detail(
    planned: tuple[RelocateEdit, ...], current: tuple[RelocateEdit, ...]
) -> str:
    """Name what changed between the plan the operator saw and the world apply found."""
    added = sorted(f"{e.kind} {e.target}" for e in set(current) - set(planned))
    gone = sorted(f"{e.kind} {e.target}" for e in set(planned) - set(current))
    parts: list[str] = []
    if added:
        parts.append("new since the plan: " + ", ".join(added))
    if gone:
        parts.append("gone since the plan: " + ", ".join(gone))
    return (
        "the world changed after the plan was shown, so the consent given no longer"
        " covers this run; nothing was changed. Re-run to re-plan and re-consent. "
        + "; ".join(parts)
    )


def plan_relocate(
    config: Config, repo_path: Path, new_path: Path, *, claim_ambiguous: bool = False
) -> RelocatePlan:
    """Enumerate every edit without touching anything (read-only; creates no catalog)."""
    repo_path, new_path = _absolute(repo_path), _absolute(new_path)
    computed = _compute(config, repo_path, new_path, claim_ambiguous=claim_ambiguous)
    return RelocatePlan(repo_path, new_path, computed.edits)


def _existing_parent(path: Path) -> Path:
    parent = path
    while not parent.exists():
        parent = parent.parent
    return parent


def _uncreatable_parent(new_repo: Path) -> str | None:
    """Why `--to`'s parent cannot be created as a directory, or None (ticket 12a).

    `_existing_parent` walks up until something EXISTS, and both failure shapes below slip
    through that test, so pre-flight approved a target the container phase could never
    produce. By then the contents had already been rewritten to point at it: a
    half-repaired world, which is precisely what the plan/backup/apply order exists to
    prevent. Pre-flight must PROVE the parent is, or can become, a directory (R5/F7).

    - a REGULAR FILE reports exists() == True, so the walk stopped there and every later
      check (st_dev, os.access) answered about the file;
    - a DANGLING SYMLINK reports exists() == False, so the walk stepped straight past it
      to a real ancestor, and `mkdir(parents=True, exist_ok=True)` then raises EEXIST on
      the link.

    Proven by tests/test_relocate_regressions.py::
    test_to_parent_that_is_a_regular_file_is_refused_before_any_rewrite and
    ::test_to_parent_that_is_a_dangling_symlink_is_refused_before_any_rewrite.
    """
    parent = new_repo.parent
    while not parent.exists():
        if parent.is_symlink():
            return f"target parent is a dangling symlink: {parent}"
        if parent == parent.parent:  # walked off the top without finding anything real
            return f"target parent has no existing ancestor: {new_repo.parent}"
        parent = parent.parent
    if not parent.is_dir():
        return f"target parent is not a directory: {parent}"
    return None


def _is_nested(inner: Path, outer: Path) -> bool:
    return inner == outer or outer in inner.parents


def _preflight(
    config: Config,
    old_repo: Path,
    new_repo: Path,
    scan: _Scan,
    encoded: list[tuple[Path, Path]],
    project_id: int | None,
    backup_dir: Path,
) -> list[ItemOutcome]:
    """Validate everything checkable BEFORE any mutation; any error changes nothing."""
    errors: list[ItemOutcome] = []
    home_problem = home_error()
    if home_problem:  # the CLI refuses earlier; this guards the public module API too
        errors.append(ItemOutcome(str(old_repo), "error", home_problem))
    if scan.config_error:
        errors.append(ItemOutcome(str(config.root / "config.toml"), "error", scan.config_error))
    if old_repo.is_symlink():
        errors.append(ItemOutcome(str(old_repo), "error", "source is a symlink"))
    if not old_repo.exists() and new_repo.exists():
        # An interrupted run leaves exactly this shape. Say so and point at the record
        # rather than reporting a bare "source is not a directory" the operator cannot
        # act on; there is no automatic undo (DESIGN section 11 specifies a report).
        errors.append(
            ItemOutcome(
                str(old_repo),
                "error",
                "source is gone but the target exists: a previous relocate may have been"
                f" interrupted. Its journal and originals are under {backup_dir.parent},"
                " newest run last; finish or reverse it by hand before re-running",
            )
        )
    elif not old_repo.is_dir():
        errors.append(ItemOutcome(str(old_repo), "error", "source is not a directory"))
    if old_repo == new_repo:
        errors.append(ItemOutcome(str(new_repo), "error", "source and target are the same path"))
    elif _is_nested(new_repo, old_repo) or _is_nested(old_repo, new_repo):
        errors.append(ItemOutcome(str(new_repo), "error", "source and target are nested"))
    if new_repo.exists() or new_repo.is_symlink():
        errors.append(ItemOutcome(str(new_repo), "error", "target already exists"))
    parent_problem = _uncreatable_parent(new_repo)
    if parent_problem:
        errors.append(ItemOutcome(str(new_repo), "error", parent_problem))
    try:
        if os.stat(old_repo).st_dev != os.stat(_existing_parent(new_repo.parent)).st_dev:
            errors.append(
                ItemOutcome(str(new_repo), "error", "cross-device relocate not supported")
            )
    except OSError as exc:
        errors.append(ItemOutcome(str(old_repo), "error", f"stat failed: {exc}"))
    for _old_dir, new_dir in encoded:
        if new_dir.exists() or new_dir.is_symlink():
            errors.append(ItemOutcome(str(new_dir), "error", "encoded target already exists"))
    if project_id is not None:
        owner = _project_for_cwd(config.root, str(new_repo))
        if owner is not None and owner != project_id:
            errors.append(
                ItemOutcome(str(new_repo), "error", "new path claimed by another project")
            )
        encoded_owner = _encoded_owner(config.root, registry.encode_cwd(str(new_repo)))
        if encoded_owner is not None and encoded_owner != project_id:
            errors.append(
                ItemOutcome(str(new_repo), "error", "encoded form claimed by another project")
            )
    # Every directory this run will write into or rename within must be writable now.
    writable: list[tuple[Path, str]] = [
        (_existing_parent(backup_dir), "backup dir not writable"),
        (old_repo.parent, "source parent not writable"),
        (_existing_parent(new_repo.parent), "target parent not writable"),
    ]
    projects = _claude_projects()
    if encoded and projects is not None:
        writable.append((projects, "~/.claude/projects not writable"))
    for directory, message in writable:
        if not os.access(directory, os.W_OK):
            errors.append(ItemOutcome(str(directory), "error", message))
    # Name the FILE, not just its directory: the operator needs to know which memory
    # file cannot be repaired, not only which folder is read-only (R10 named items).
    for path in scan.targets:
        if not os.access(path.parent, os.W_OK):
            errors.append(ItemOutcome(str(path), "error", "target dir not writable"))
    return errors


def _encoded_owner(root: Path, encoded_name: str) -> int | None:
    conn = _catalog_conn(root)
    if conn is None:
        return None
    try:
        return registry.project_for_path(conn, encoded_name, "encoded_dir")
    finally:
        conn.close()


def _write_json(target: Path, payload: object) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    store.atomic_write(target, body.encode("utf-8"))


def _manifest(backup_dir: Path, outcomes: list[ItemOutcome]) -> None:
    """Persist what actually happened on EVERY path that mutated anything, into the run's
    own backup dir so a later run can never overwrite an interrupted run's record."""
    _write_json(
        backup_dir / "relocate-manifest.json",
        [{"item": o.item, "action": o.action, "detail": o.detail} for o in outcomes],
    )


def _verify(
    targets: tuple[Path, ...],
    patterns: list[tuple[re.Pattern[str], str]],
    old_repo: Path,
    new_repo: Path,
    encoded: list[tuple[Path, Path]],
) -> list[ItemOutcome]:
    """Re-read exactly the files this run rewrote (not the whole tree again).

    A target that lived UNDER the repo has moved with it, so it is verified at its new
    location: reading the pre-move path would manufacture a failure report on a run where
    every step actually succeeded.
    """
    outcomes: list[ItemOutcome] = []
    for original in targets:
        path = original
        if original == old_repo or old_repo in original.parents:
            path = new_repo / original.relative_to(old_repo)
        try:
            text = path.read_text()
        except (OSError, UnicodeDecodeError) as exc:
            outcomes.append(ItemOutcome(str(path), "error", f"unverifiable after rewrite: {exc}"))
            continue
        if any(pat.search(text) for pat, _ in patterns):
            outcomes.append(ItemOutcome(str(path), "error", "old path still present after rewrite"))
    if not new_repo.exists():
        outcomes.append(ItemOutcome(str(new_repo), "error", "repo missing at new path"))
    for _old_dir, new_dir in encoded:
        if not new_dir.is_dir():
            outcomes.append(ItemOutcome(str(new_dir), "error", "encoded dir missing after rename"))
    return outcomes


def _apply_locked(
    config: Config, plan: RelocatePlan, backup_dir: Path, claim_ambiguous: bool
) -> BatchReport:
    root = config.root
    old_repo, new_repo = _absolute(plan.repo_path), _absolute(plan.new_path)
    # RECOMPUTE at the point of action (the frozen slice-12 decision keeps this re-check),
    # then require it to MATCH the plan the operator consented to. Consent is given for a
    # specific set of edits (R13); silently applying a different set is not consent, and
    # blindly replaying a stale plan would under-repair a world that has since changed.
    # Divergence is therefore a refusal, not a merge (R5/F7), and the operator re-plans.
    computed = _compute(config, old_repo, new_repo, claim_ambiguous=claim_ambiguous)
    if computed.edits != plan.edits:
        return BatchReport(
            (ItemOutcome(str(new_repo), "error", _drift_detail(plan.edits, computed.edits)),)
        )
    encoded, ambiguous = computed.renames, computed.ambiguous
    patterns, scan, project_id = computed.patterns, computed.scan, computed.project_id

    errors = _preflight(config, old_repo, new_repo, scan, encoded, project_id, backup_dir)
    if errors:
        return BatchReport(tuple(errors))  # changed nothing

    noted: list[tuple[Path, str]] = list(scan.skipped) + ambiguous
    outcomes: list[ItemOutcome] = [
        ItemOutcome(str(path), "skipped", reason) for path, reason in noted
    ]

    # BACKUP: read each file ONCE and keep that pre-image, so the backup is exactly the
    # bytes the rewrite transforms (no read-modify-write drift between the two).
    pre_images: list[tuple[Path, str]] = []
    for path in scan.targets:
        try:
            original = path.read_text()
            dest = backup_dir / path.relative_to(path.anchor)
            dest.parent.mkdir(parents=True, exist_ok=True)
            store.atomic_write(dest, original.encode("utf-8"))
        except (OSError, UnicodeDecodeError) as exc:
            outcomes.append(ItemOutcome(str(path), "error", f"backup failed: {exc}"))
            _manifest(backup_dir, outcomes)
            return BatchReport(tuple(outcomes))
        pre_images.append((path, original))

    _write_json(
        backup_dir / "relocate-journal.json",
        {
            "repo": {"old": str(old_repo), "new": str(new_repo)},
            "encoded": [{"old": str(o), "new": str(n)} for o, n in encoded],
        },
    )

    content_failed = False
    for path, original in pre_images:
        try:
            store.atomic_write(path, _rewrite_bytes(path, original, patterns))
            outcomes.append(ItemOutcome(str(path), "rewritten", str(new_repo)))
        except OSError as exc:
            outcomes.append(ItemOutcome(str(path), "error", f"rewrite failed: {exc}"))
            content_failed = True
    if content_failed:  # contents before containers: a content failure halts the move
        _manifest(backup_dir, outcomes)
        return BatchReport(tuple(outcomes))

    # CONTAINERS: guarded, so a late filesystem refusal is a named report, never a
    # traceback over a half-rewritten world. Targets are re-checked at the point of
    # action to narrow the pre-flight window (the residual race is documented).
    try:
        new_repo.parent.mkdir(parents=True, exist_ok=True)
        if new_repo.exists() or new_repo.is_symlink():
            raise FileExistsError(f"target appeared before the move: {new_repo}")
        os.rename(old_repo, new_repo)
        outcomes.append(ItemOutcome(str(old_repo), "moved", str(new_repo)))
        for old_dir, new_dir in encoded:
            if new_dir.exists() or new_dir.is_symlink():
                raise FileExistsError(f"encoded target appeared before the rename: {new_dir}")
            os.rename(old_dir, new_dir)
            outcomes.append(ItemOutcome(str(old_dir), "renamed", str(new_dir)))
        if project_id is not None:
            conn = catalog.open_catalog(root)
            try:
                registry.move_project(conn, project_id, str(old_repo), str(new_repo), _now())
            finally:
                conn.close()
            outcomes.append(ItemOutcome(str(new_repo), "alias", "cwd + encoded claim"))
    except (OSError, ValueError, sqlite3.Error) as exc:
        outcomes.append(ItemOutcome(str(new_repo), "error", f"container phase failed: {exc}"))
        _manifest(backup_dir, outcomes)
        return BatchReport(tuple(outcomes))

    outcomes.extend(_verify(scan.targets, patterns, old_repo, new_repo, encoded))
    _manifest(backup_dir, outcomes)
    return BatchReport(tuple(outcomes))


def apply_relocate(
    config: Config, plan: RelocatePlan, *, backup_dir: Path, claim_ambiguous: bool = False
) -> BatchReport:
    """Backup every file to be touched, then apply item by item, verify, report.

    Holds a locks/relocate O_EXCL lock for the whole apply (R14); a live holder makes the
    apply refuse without touching anything, mirroring migrate. The journal and manifest
    land in the run's own backup dir; nothing here consumes them automatically, so they
    are a record for the operator, not an automatic undo.
    """
    if not store.acquire_lock(config.root, RELOCATE_LOCK):
        return BatchReport(
            (ItemOutcome(_LOCK_HELD_ITEM, LOCK_HELD_ACTION, "relocate lock held by a live holder"),)
        )
    try:
        return _apply_locked(config, plan, backup_dir, claim_ambiguous)
    finally:
        store.release_lock(config.root, RELOCATE_LOCK)
