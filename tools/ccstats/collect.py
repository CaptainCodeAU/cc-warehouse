#!/usr/bin/env python3
"""Collect Claude Code session statistics into a queryable SQLite dataset.

READ-ONLY over every source tree. The ONLY directory this script writes to is
the resolved output root (`~/.cc-warehouse/stats` by default; see `--out`
below). It contains no delete primitive at all. `sessions.sqlite` is published
by building into a temp file beside it and `os.replace`-ing it onto the target,
so a re-run never leaves a stale copy and a crash mid-build never corrupts the
live database.

Run:  uv run python3 tools/ccstats/collect.py
Flags: --limit N    scan only N transcripts (smoke test)
       --quiet      suppress per-stage progress
       --out DIR    write here instead of the default (or set CCSTATS_OUT)
       --no-cache   ignore the scan cache and rescan every transcript

Most transcripts never change once a session ends, so a full run re-reads and
re-parses ~25k files it already scanned last time. `scan-cache.sqlite` (beside
`sessions.sqlite`, in the same output directory) remembers each file's own
scan result keyed by its path + size + mtime; an unchanged file is served from
the cache instead of being re-read. A `--limit` smoke-test run reads the cache
but never overwrites it (it only ever sees a slice of the corpus, and writing
that slice back would evict every other session's cached entry). The cache is
purely an optimisation: delete it, pass `--no-cache`, or feed it garbage, and
the next run just falls back to a full, correct scan (R5/R10) - nothing here
is a second copy of session data (R1), only of numbers already derived from it.

Read `tools/ccstats/README.md` for what every column means and the caveats that
come with the dollar figures.
"""

from __future__ import annotations

import csv
import json
import os
import sqlite3
import sys
import tempfile
import time
import tomllib
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, tzinfo
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

sys.path.insert(0, str(Path(__file__).parent))

from common import (  # noqa: E402
    ARCHIVE,
    DAY_SECONDS,
    HOME,
    LIVE,
    BadOut,
    Out,
    cost_note,
    publish_text,
    resolve_out,
)
from common import IDLE_GAP_SECONDS as _IDLE_GAP  # noqa: E402

# ---------------------------------------------------------------- locations

# Archive root entries that are not project folders (build.RESERVED_LABELS).
ARCHIVE_SKIP = {"locks", "catalog.sqlite", "_orphaned-subagents", "_not-sessions"}

# A pause longer than this splits "engaged" time from idle time. Defined in
# common.py so the code and the docs that describe it quote the same number.
_IDLE_GAP_SECONDS = _IDLE_GAP

# ------------------------------------------------------------------ pricing
# USD per 1,000,000 tokens, first-party Anthropic API list prices.
# RE-CHECKED 2026-08-23 against the live pricing page (platform.claude.com/
# docs/en/about-claude/models/overview) - every rate below still matches what
# was cached 2026-06-24, with one deliberate exception (see claude-sonnet-5).
# THIS IS NOT A BILL. See README.md "What the dollar column is not".

PRICES_READ_ON = "2026-08-23"

PRICES: dict[str, tuple[float, float]] = {
    "claude-fable-5": (10.00, 50.00),
    "claude-mythos-5": (10.00, 50.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-opus-4-7": (5.00, 25.00),
    "claude-opus-4-6": (5.00, 25.00),
    "claude-opus-4-5": (5.00, 25.00),
    # The live page currently shows $2.00/$10.00 - an introductory rate that
    # runs through 2026-08-31 (checked 2026-08-23, still in effect). Kept at
    # the post-intro steady-state rate deliberately (operator's choice): this
    # is the rate that will actually apply for most of the model's deployed
    # life. Re-check after 2026-08-31 to confirm the live page has settled on
    # $3.00/$15.00 as expected, rather than assuming it.
    "claude-sonnet-5": (3.00, 15.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-sonnet-4-5": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
}

# Fast mode is a research preview on Opus 5 / Opus 4.8 only, at premium rates.
PRICES_FAST: dict[str, tuple[float, float]] = {
    "claude-opus-5": (10.00, 50.00),
    "claude-opus-4-8": (10.00, 50.00),
}

# Multipliers applied to the model's own INPUT rate.
CACHE_WRITE_5M = 1.25
CACHE_WRITE_1H = 2.00
CACHE_READ = 0.10

# Model ids that are known non-billable sentinels, not missing prices.
KNOWN_FREE = {"<synthetic>"}

# Bump whenever `scan_transcript` (or anything it calls) changes what it
# derives from a transcript's bytes - a new/changed column, a fixed formula,
# a different tool-name normalisation, anything. This is the manual half of
# cache invalidation; `PRICES_READ_ON` and the detected local timezone are the
# automatic half (see `_cache_fingerprint` below) because those two change the
# meaning of an old row WITHOUT anyone touching this function.
CACHE_SCHEMA_VERSION = 2

_UNPRICED: Counter[str] = Counter()
_PRICE_CACHE: dict[tuple[str, str], tuple[float, float] | None] = {}


def rates_for(model: str | None, speed: str | None) -> tuple[float, float] | None:
    """(input, output) USD per 1M for a model id, by longest known prefix.

    Returns None for an unknown id so the caller can record it instead of
    silently charging zero. `claude-haiku-4-5-20251001` resolves to the
    `claude-haiku-4-5` row; a model released after PRICES_READ_ON does not
    resolve at all, which is the point.
    """
    if not model:
        return None
    key = (model, speed or "")
    if key in _PRICE_CACHE:
        return _PRICE_CACHE[key]
    table = PRICES_FAST if speed == "fast" else PRICES
    best: str | None = None
    for known in table:
        if model.startswith(known) and (best is None or len(known) > len(best)):
            best = known
    if best is None and speed == "fast":
        # Fast mode on a model with no fast rate: fall back to standard rates.
        for known in PRICES:
            if model.startswith(known) and (best is None or len(known) > len(best)):
                best = known
        table = PRICES
    result = table[best] if best is not None else None
    _PRICE_CACHE[key] = result
    return result


def turn_cost(
    model: str | None,
    speed: str | None,
    tin: int,
    tout: int,
    cw5: int,
    cw1h: int,
    cread: int,
) -> tuple[float, float, float, float]:
    """(input, output, cache_write, cache_read) USD for one assistant turn."""
    rates = rates_for(model, speed)
    if rates is None:
        if model and model not in KNOWN_FREE:
            _UNPRICED[model] += 1
        return (0.0, 0.0, 0.0, 0.0)
    r_in, r_out = rates
    m = 1e-6
    return (
        tin * r_in * m,
        tout * r_out * m,
        (cw5 * CACHE_WRITE_5M + cw1h * CACHE_WRITE_1H) * r_in * m,
        cread * CACHE_READ * r_in * m,
    )


# --------------------------------------------------------- project identity
# Matches registry.derive_label (src/cc_warehouse/registry.py:36) exactly, so
# `project_label` here is the same string `ccw project list` shows.

_SKIP_DIRS = {"projects", "code", "repos", "src", "dev", "work", "documents"}
_PREFIX_DIRS = {"home", "users"}

_WORKTREE_DIRS = (".worktree", ".worktrees")
_WORKTREE_PREFIX = ".worktree-"


def derive_label(path: str) -> str:
    """Default display label for a project path (SPEC section 3)."""
    parts = [p for p in path.split("/") if p]
    segments = list(parts)
    if [s.lower() for s in segments[:3]] == ["mnt", "c", "users"]:
        segments = segments[3:]
    elif segments and segments[0].lower() in _PREFIX_DIRS:
        segments = segments[1:]
    if len(segments) >= 2 and segments[1].lower() in _SKIP_DIRS:
        segments = segments[1:]
    segments = [s for s in segments if s.lower() not in _SKIP_DIRS]
    if segments:
        return "-".join(segments)
    return parts[-1] if parts else path


_REPO_CACHE: dict[str, tuple[str, int, str | None]] = {}


def project_shape(cwd: str | None) -> tuple[str | None, int, str | None]:
    """(repo_root, is_worktree, worktree_name) derived from a cwd.

    Three real worktree layouts appear in this corpus and all three are handled:
    `<repo>/.worktree/<branch>`, `<repo>/.worktrees/<name>` and
    `<repo>/.worktree-<name>`. A checkout that still exists on disk also gets
    its repo root confirmed by walking up to a `.git`; one that has been moved
    or deleted degrades to the path-derived answer rather than raising.
    """
    if not cwd:
        return (None, 0, None)
    if cwd in _REPO_CACHE:
        return _REPO_CACHE[cwd]

    parts = [p for p in cwd.split("/") if p]
    root: str | None = None
    is_wt = 0
    wt_name: str | None = None

    for i, seg in enumerate(parts):
        if seg in _WORKTREE_DIRS:
            root = "/" + "/".join(parts[:i])
            wt_name = parts[i + 1] if i + 1 < len(parts) else seg
            is_wt = 1
            break
        if seg.startswith(_WORKTREE_PREFIX):
            root = "/" + "/".join(parts[:i])
            wt_name = seg[len(_WORKTREE_PREFIX) :] or seg
            is_wt = 1
            break

    if root is None:
        # Not a worktree path. Confirm the repo root from disk when we still can.
        probe = Path(cwd)
        found: str | None = None
        try:
            if probe.is_dir():
                for candidate in [probe, *probe.parents]:
                    if (candidate / ".git").exists():
                        found = str(candidate)
                        break
        except OSError:
            found = None
        root = found or cwd

    answer = (root, is_wt, wt_name)
    _REPO_CACHE[cwd] = answer
    return answer


# ------------------------------------------------------------------- timing

def _config_timezone() -> tuple[str | None, str]:
    """`archive_timezone` from cc-warehouse's own config, and where it came from.

    THE CONFIG IS THE AUTHORITY, not the machine clock. `config.toml` says so in
    its own words: the zone is "PINNED here rather than read from the machine
    clock, so the same session yields the same folder name on any machine
    forever". The archive tree is already named in that zone, so deriving these
    columns from anything else would put the statistics and the folder names in
    two different times on any machine whose clock disagrees.

    Precedence mirrors config.load_config: XDG config, then the data root's own
    config.toml. An unreadable file or an unknown zone is IGNORED rather than
    raised, matching `_archive_timezone`'s rule that a typo must never stop the
    run (R5).
    """
    candidates: list[Path] = []
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else HOME / ".config"
    candidates.append(base / "cc-warehouse" / "config.toml")
    root = os.environ.get("CCW_ROOT")
    candidates.append((Path(root) if root else HOME / "cc-warehouse-data") / "config.toml")

    for path in candidates:
        try:
            with path.open("rb") as handle:
                data = tomllib.load(handle)
        except (OSError, tomllib.TOMLDecodeError):
            continue
        value = data.get("archive_timezone")
        if not isinstance(value, str) or not value.strip():
            continue
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            # Same rule config.py uses: record nothing, keep looking, never raise.
            continue
        return value, f"config ({path})"
    return None, ""


def _detect_local_zone() -> tuple[tzinfo, str, str]:
    """(zone, name, source) for every `local_*` column.

    Order: the cc-warehouse config, then the machine's IANA zone, then a
    fixed offset as a last resort.

    `datetime.now().astimezone().tzinfo` returns a FIXED-OFFSET object frozen at
    whatever the offset happens to be when the script runs, so applying it to
    historical timestamps silently ignores daylight saving. Found by a reviewer
    on 2026-08-21: this machine is Australia/Melbourne, the script ran in August
    (AEST +10), and every session before Melbourne left AEDT on 2026-04-05 was
    bucketed an hour early. 577 sessions had the wrong local_hour and 45 the
    wrong local_date and weekday. A real ZoneInfo knows its own DST history.
    """
    override = os.environ.get("CCSTATS_TZ")
    if override:
        try:
            return ZoneInfo(override), override, "CCSTATS_TZ env"
        except (ZoneInfoNotFoundError, ValueError):
            pass

    name, source = _config_timezone()
    if name is not None:
        return ZoneInfo(name), name, source

    try:
        parts = Path("/etc/localtime").resolve().parts
        if "zoneinfo" in parts:
            index = len(parts) - 1 - parts[::-1].index("zoneinfo")
            key = "/".join(parts[index + 1 :])
            return ZoneInfo(key), key, "machine (/etc/localtime)"
    except (OSError, ZoneInfoNotFoundError, ValueError):
        pass

    fallback = datetime.now().astimezone().tzinfo
    assert fallback is not None
    return fallback, str(fallback), "machine clock offset (NOT DST-aware)"


_LOCAL_TZ, _LOCAL_TZ_NAME, _LOCAL_TZ_SOURCE = _detect_local_zone()


def parse_ts(raw: str | None) -> datetime | None:
    """An ISO-8601 payload timestamp as an aware datetime, or None."""
    if not raw:
        return None
    try:
        moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment


def local_parts(moment: datetime | None) -> tuple[str | None, int | None, int | None, str | None]:
    """(YYYY-MM-DD, hour, weekday, utc-offset) in the machine's local zone.

    Local rather than UTC because the question these feed is "when do I work",
    and that is a wall-clock question. Weekday is 0=Monday.
    """
    if moment is None:
        return (None, None, None, None)
    local = moment.astimezone(_LOCAL_TZ)
    return (
        local.strftime("%Y-%m-%d"),
        local.hour,
        local.weekday(),
        local.strftime("%z"),
    )


def as_str(value: object) -> str | None:
    """A non-empty string, or None. Mirrors parser._as_nonempty_str."""
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


# ------------------------------------------------------------ the one pass

ATTRIBUTION_KEYS = {
    "attributionSkill": "skill",
    "attributionPlugin": "plugin",
    "attributionAgent": "agent",
    "attributionMcpServer": "mcp_server",
    "attributionMcpTool": "mcp_tool",
}

INTERRUPT_MARKERS = ("[Request interrupted by user", "[Request interrupted by")


@dataclass(frozen=True)
class Usage:
    """One assistant turn's token counters, normalised.

    Pulled out of `scan_transcript` so the two rules that are easiest to get
    wrong can be asserted on their own, without building a transcript:

      * `thinking` is a SUBSET of `output` and is clamped to it, never added.
      * the 5m/1h cache split must reconcile with the declared total, because
        the tiers are priced differently (1.25x vs 2x the input rate).
    """

    input: int = 0
    output: int = 0
    cache_write_5m: int = 0
    cache_write_1h: int = 0
    cache_read: int = 0
    thinking: int = 0
    declared_cache_write: int = 0
    service_tier: str | None = None
    speed: str | None = None
    web_search: int = 0
    web_fetch: int = 0

    @property
    def cache_write(self) -> int:
        return self.cache_write_5m + self.cache_write_1h


def read_usage(raw: object) -> Usage:
    """A `message.usage` block as a `Usage`. Anything unexpected reads as zero."""
    if not isinstance(raw, dict):
        return Usage()
    usage = cast(dict[str, object], raw)

    def num(key: str, source: dict[str, object] | None = None) -> int:
        value = (source if source is not None else usage).get(key)
        return int(value) if isinstance(value, (int, float)) else 0

    output = num("output_tokens")
    declared = num("cache_creation_input_tokens")

    cache = usage.get("cache_creation")
    if isinstance(cache, dict):
        cache_map = cast(dict[str, object], cache)
        cw5 = num("ephemeral_5m_input_tokens", cache_map)
        cw1h = num("ephemeral_1h_input_tokens", cache_map)
    else:
        # No TTL breakdown on this payload version. Attribute the whole cache
        # write to the 5m tier, the CHEAPER rate, so an unknown can never
        # inflate the cost estimate.
        cw5, cw1h = declared, 0
    if cw5 + cw1h != declared:
        # The split must reconcile. It did on every turn measured; if a payload
        # ever disagrees, the declared total wins.
        cw5, cw1h = declared, 0

    thinking = 0
    details = usage.get("output_tokens_details")
    if isinstance(details, dict):
        thinking = min(num("thinking_tokens", cast(dict[str, object], details)), output)

    server = usage.get("server_tool_use")
    server_map = cast(dict[str, object], server) if isinstance(server, dict) else {}

    return Usage(
        input=num("input_tokens"),
        output=output,
        cache_write_5m=cw5,
        cache_write_1h=cw1h,
        cache_read=num("cache_read_input_tokens"),
        thinking=thinking,
        declared_cache_write=declared,
        service_tier=as_str(usage.get("service_tier")),
        speed=as_str(usage.get("speed")),
        web_search=num("web_search_requests", server_map),
        web_fetch=num("web_fetch_requests", server_map),
    )


class Scan:
    """Everything one transcript yields. One object, one pass over the file."""

    __slots__ = ("session", "turns", "tools", "attrs")

    def __init__(self) -> None:
        self.session: dict[str, object] = {}
        self.turns: list[tuple[object, ...]] = []
        self.tools: list[tuple[object, ...]] = []
        self.attrs: list[tuple[object, ...]] = []


@dataclass(frozen=True)
class AssistantTurnStats:
    """Everything one assistant entry contributes, computed once so
    `scan_transcript`'s loop only has to add it up. Same reason `Usage` is
    pulled out above: the per-turn rules (thinking count, refusal category,
    tool-use names, cost) can be read and asserted on their own."""

    model: str | None
    effort: str | None
    usage: Usage
    cost_input: float
    cost_output: float
    cost_cache_write: float
    cost_cache_read: float
    stop_reason: str | None
    refusal_category: str | None
    n_thinking_blocks: int
    tool_use_names: list[str]


def _scan_assistant_entry(
    entry: dict[str, object], message: dict[str, object]
) -> AssistantTurnStats:
    """Derive every per-turn statistic from one assistant entry's message."""
    model = as_str(message.get("model"))
    usage = read_usage(message.get("usage"))
    k_in, k_out, k_cw, k_cr = turn_cost(
        model, usage.speed, usage.input, usage.output,
        usage.cache_write_5m, usage.cache_write_1h, usage.cache_read,
    )

    stop = as_str(message.get("stop_reason"))
    refusal_category = None
    if stop == "refusal":
        details = message.get("stop_details")
        if isinstance(details, dict):
            refusal_category = as_str(cast(dict[str, object], details).get("category"))

    n_thinking = 0
    tool_use_names: list[str] = []
    content = message.get("content")
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "thinking":
                n_thinking += 1
            elif btype == "tool_use":
                tool_use_names.append(as_str(block.get("name")) or "(unnamed)")

    return AssistantTurnStats(
        model=model,
        effort=as_str(entry.get("effort")),
        usage=usage,
        cost_input=k_in,
        cost_output=k_out,
        cost_cache_write=k_cw,
        cost_cache_read=k_cr,
        stop_reason=stop,
        refusal_category=refusal_category,
        n_thinking_blocks=n_thinking,
        tool_use_names=tool_use_names,
    )


@dataclass(frozen=True)
class UserTurnStats:
    """Everything one user entry contributes, computed once. Same shape as
    `AssistantTurnStats` above."""

    text: str
    has_text: bool
    n_tool_results: int
    error_tool_uses: int


def _scan_user_entry(content: object) -> UserTurnStats:
    """Derive per-entry statistics from one user entry's message content."""
    if isinstance(content, str):
        return UserTurnStats(text=content, has_text=True, n_tool_results=0, error_tool_uses=0)
    text = ""
    has_text = False
    n_tool_results = 0
    error_tool_uses = 0
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                has_text = True
                text += str(block.get("text") or "")
            elif btype == "tool_result":
                n_tool_results += 1
                if block.get("is_error"):
                    error_tool_uses += 1
    return UserTurnStats(
        text=text, has_text=has_text, n_tool_results=n_tool_results, error_tool_uses=error_tool_uses
    )


def _engaged_seconds(stamps: list[datetime]) -> float:
    """Sum of gaps between consecutive timestamps no longer than the idle
    threshold - active time, with long pauses excluded."""
    ordered = sorted(stamps)
    engaged = 0.0
    for prev, nxt in zip(ordered, ordered[1:], strict=False):
        gap = (nxt - prev).total_seconds()
        if 0.0 <= gap <= _IDLE_GAP_SECONDS:
            engaged += gap
    return engaged


def scan_transcript(
    path: Path,
    *,
    source_tree: str,
    container: str,
    is_subagent: bool,
    parent_uuid: str | None,
) -> Scan | None:
    """Read one JSONL transcript and derive every statistic from it.

    Malformed lines are counted, never fatal: one bad line must not cost the
    other 20,000 sessions (the project's own R10/F6 discipline).
    """
    try:
        raw = path.read_bytes()
    except OSError:
        return None

    out = Scan()

    session_uuid = cwd = git_branch = slug = version = None
    entrypoint = user_type = None
    ai_title = custom_title = None
    first_prompt: str | None = None
    is_sidechain = 0
    agent_id = agent_name = None

    n_lines = n_bad = 0
    first_ts_raw: str | None = None
    last_ts_raw: str | None = None
    stamps: list[datetime] = []

    types: Counter[str] = Counter()
    models: Counter[str] = Counter()
    versions: Counter[str] = Counter()
    efforts: Counter[str] = Counter()
    tiers: Counter[str] = Counter()
    speeds: Counter[str] = Counter()
    modes: Counter[str] = Counter()
    psources: Counter[str] = Counter()
    refusal_cats: Counter[str] = Counter()
    attrs: Counter[tuple[str, str]] = Counter()

    n_user_prompts = n_assistant = n_tool_use = n_tool_result = 0
    n_thinking = n_attachment = n_api_err = n_interrupt = n_refusal = 0
    n_turn_events = 0
    prompt_ids: set[str] = set()
    active_ms = 0
    shutdown = 0

    tok_in = tok_out = tok_cw5 = tok_cw1h = tok_cr = tok_think = 0
    cw_declared = 0
    web_search = web_fetch = 0
    c_in = c_out = c_cw = c_cr = 0.0
    ordinal = 0

    for line in raw.split(b"\n"):
        if not line.strip():
            continue
        n_lines += 1
        try:
            entry = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            n_bad += 1
            continue
        if not isinstance(entry, dict):
            n_bad += 1
            continue

        etype = as_str(entry.get("type")) or "(none)"
        types[etype] += 1

        session_uuid = session_uuid or as_str(entry.get("sessionId"))
        cwd = cwd or as_str(entry.get("cwd"))
        git_branch = git_branch or as_str(entry.get("gitBranch"))
        slug = slug or as_str(entry.get("slug"))
        version = version or as_str(entry.get("version"))
        entrypoint = entrypoint or as_str(entry.get("entrypoint"))
        user_type = user_type or as_str(entry.get("userType"))
        agent_id = agent_id or as_str(entry.get("agentId"))
        agent_name = agent_name or as_str(entry.get("agentName"))
        if entry.get("isSidechain"):
            is_sidechain = 1
        if entry.get("interruptedByShutdown"):
            shutdown = 1
        if entry.get("isApiErrorMessage"):
            n_api_err += 1

        if (v := as_str(entry.get("version"))) is not None:
            versions[v] += 1
        if (v := as_str(entry.get("effort"))) is not None:
            efforts[v] += 1
        if (v := as_str(entry.get("permissionMode"))) is not None:
            modes[v] += 1
        if (v := as_str(entry.get("promptSource"))) is not None:
            psources[v] += 1
        if (v := as_str(entry.get("promptId"))) is not None:
            prompt_ids.add(v)
        if (v := as_str(entry.get("apiRefusalCategory"))) is not None:
            refusal_cats[v] += 1

        for key, kind in ATTRIBUTION_KEYS.items():
            if (v := as_str(entry.get(key))) is not None:
                attrs[(kind, v)] += 1

        # Last-wins titles, matching parser.parse_session.
        if etype == "ai-title":
            ai_title = as_str(entry.get("aiTitle")) or ai_title
        elif etype == "custom-title":
            custom_title = as_str(entry.get("customTitle")) or custom_title
        elif etype == "attachment":
            n_attachment += 1
        elif etype == "system" and entry.get("subtype") == "turn_duration":
            n_turn_events += 1
            dur = entry.get("durationMs")
            if isinstance(dur, int):
                active_ms += dur

        ts_raw = as_str(entry.get("timestamp"))
        if ts_raw is not None:
            if first_ts_raw is None:
                first_ts_raw = ts_raw
            last_ts_raw = ts_raw
            if (moment := parse_ts(ts_raw)) is not None:
                stamps.append(moment)

        message = entry.get("message")
        if not isinstance(message, dict):
            continue
        content = message.get("content")

        if etype == "assistant":
            n_assistant += 1
            a = _scan_assistant_entry(entry, message)
            if a.model:
                models[a.model] += 1
            if a.usage.service_tier:
                tiers[a.usage.service_tier] += 1
            if a.usage.speed:
                speeds[a.usage.speed] += 1
            cw_declared += a.usage.declared_cache_write
            web_search += a.usage.web_search
            web_fetch += a.usage.web_fetch

            c_in += a.cost_input
            c_out += a.cost_output
            c_cw += a.cost_cache_write
            c_cr += a.cost_cache_read

            tok_in += a.usage.input
            tok_out += a.usage.output
            tok_cw5 += a.usage.cache_write_5m
            tok_cw1h += a.usage.cache_write_1h
            tok_cr += a.usage.cache_read
            tok_think += a.usage.thinking

            if a.stop_reason == "refusal":
                n_refusal += 1
                if a.refusal_category is not None:
                    refusal_cats[a.refusal_category] += 1

            ordinal += 1
            out.turns.append(
                (
                    None,  # session key, filled by the caller
                    ordinal,
                    ts_raw,
                    a.model,
                    a.effort,
                    a.usage.service_tier,
                    a.usage.speed,
                    a.stop_reason,
                    a.usage.input,
                    a.usage.output,
                    a.usage.cache_write_5m,
                    a.usage.cache_write_1h,
                    a.usage.cache_read,
                    a.usage.thinking,
                    a.usage.web_search,
                    a.usage.web_fetch,
                    round(a.cost_input + a.cost_output + a.cost_cache_write + a.cost_cache_read, 8),
                )
            )

            n_thinking += a.n_thinking_blocks
            for name in a.tool_use_names:
                n_tool_use += 1
                out.tools.append((None, ts_raw, name, 0))

        elif etype == "user":
            u = _scan_user_entry(content)
            n_tool_result += u.n_tool_results
            for _ in range(u.error_tool_uses):
                out.tools.append((None, ts_raw, "(error-result)", 1))
            if any(marker in u.text for marker in INTERRUPT_MARKERS):
                n_interrupt += 1
            elif u.has_text and not entry.get("isMeta"):
                n_user_prompts += 1
                if first_prompt is None and u.text.strip():
                    first_prompt = u.text.strip()[:300]

    if n_lines == 0:
        return None

    first_dt = parse_ts(first_ts_raw)
    last_dt = parse_ts(last_ts_raw)
    wall = (last_dt - first_dt).total_seconds() if first_dt and last_dt else 0.0

    engaged = _engaged_seconds(stamps)

    l_date, l_hour, l_wday, l_off = local_parts(first_dt)
    label = derive_label(cwd) if cwd else None
    repo_root, is_wt, wt_name = project_shape(cwd)
    primary = models.most_common(1)[0][0] if models else None

    out.session = {
        "session_uuid": session_uuid,
        "source_tree": source_tree,
        "source_path": str(path),
        "container_name": container,
        "size_bytes": len(raw),
        "line_count": n_lines,
        "is_subagent": int(is_subagent),
        "parent_session_uuid": parent_uuid,
        "agent_id": agent_id or (path.stem if is_subagent else None),
        "agent_name": agent_name,
        "cwd": cwd,
        "project_label": label,
        "repo_root": repo_root,
        "is_worktree": is_wt,
        "worktree_name": wt_name,
        "git_branch": git_branch,
        "first_ts": first_ts_raw,
        "last_ts": last_ts_raw,
        "wall_seconds": round(wall, 3),
        "active_seconds": round(active_ms / 1000.0, 3),
        "engaged_seconds": round(engaged, 3),
        "idle_seconds": round(max(0.0, wall - engaged), 3),
        "local_date": l_date,
        "local_hour": l_hour,
        "local_weekday": l_wday,
        "tz_offset": l_off,
        "n_user_prompts": n_user_prompts,
        "n_prompt_ids": len(prompt_ids),
        "n_assistant_turns": n_assistant,
        "n_tool_uses": n_tool_use,
        "n_tool_results": n_tool_result,
        "n_thinking_blocks": n_thinking,
        "n_attachments": n_attachment,
        "n_turn_duration_events": n_turn_events,
        "tok_input": tok_in,
        "tok_output": tok_out,
        "tok_cache_write_5m": tok_cw5,
        "tok_cache_write_1h": tok_cw1h,
        "tok_cache_write": tok_cw5 + tok_cw1h,
        "tok_cache_write_declared": cw_declared,
        "tok_cache_read": tok_cr,
        "tok_thinking": tok_think,
        "tok_billable_total": tok_in + tok_out + tok_cw5 + tok_cw1h,
        "tok_context_total": tok_in + tok_cr + tok_cw5 + tok_cw1h,
        "cost_input_usd": round(c_in, 8),
        "cost_output_usd": round(c_out, 8),
        "cost_cache_write_usd": round(c_cw, 8),
        "cost_cache_read_usd": round(c_cr, 8),
        "cost_usd": round(c_in + c_out + c_cw + c_cr, 8),
        "primary_model": primary,
        "models_json": json.dumps(dict(models.most_common()), sort_keys=True),
        "cc_versions_json": json.dumps(dict(versions.most_common()), sort_keys=True),
        "effort_json": json.dumps(dict(efforts.most_common()), sort_keys=True),
        "service_tiers_json": json.dumps(dict(tiers.most_common()), sort_keys=True),
        "speeds_json": json.dumps(dict(speeds.most_common()), sort_keys=True),
        "permission_modes_json": json.dumps(dict(modes.most_common()), sort_keys=True),
        "prompt_sources_json": json.dumps(dict(psources.most_common()), sort_keys=True),
        "entry_types_json": json.dumps(dict(types.most_common()), sort_keys=True),
        "entrypoint": entrypoint,
        "user_type": user_type,
        "is_sidechain": is_sidechain,
        "cc_version": version,
        "is_real": int(n_assistant > 0),
        "has_usage": int(tok_in + tok_out + tok_cw5 + tok_cw1h + tok_cr > 0),
        "n_api_errors": n_api_err,
        "n_interrupts": n_interrupt,
        "n_refusals": n_refusal,
        "refusal_categories_json": json.dumps(dict(refusal_cats.most_common()), sort_keys=True),
        "interrupted_by_shutdown": shutdown,
        "n_malformed_lines": n_bad,
        "web_search_requests": web_search,
        "web_fetch_requests": web_fetch,
        "ai_title": ai_title,
        "custom_title": custom_title,
        "slug_title": slug,
        "first_prompt_preview": first_prompt,
    }
    out.attrs = [(None, kind, name, count) for (kind, name), count in attrs.items()]
    return out


# ------------------------------------------------------------- source trees


class Source:
    """One transcript to scan, with where it came from."""

    __slots__ = ("path", "tree", "container", "is_subagent", "parent")

    def __init__(
        self, path: Path, tree: str, container: str, is_subagent: bool, parent: str | None
    ) -> None:
        self.path = path
        self.tree = tree
        self.container = container
        self.is_subagent = is_subagent
        self.parent = parent


def discover_archive() -> list[Source]:
    """`<root>/<label>/<stamp>_<uuid>/` folders, plus their `subagents/` trees."""
    found: list[Source] = []
    if not ARCHIVE.is_dir():
        return found
    for label in sorted(ARCHIVE.iterdir()):
        if not label.is_dir() or label.name in ARCHIVE_SKIP or label.name.startswith("_"):
            continue
        for folder in sorted(label.iterdir()):
            if not folder.is_dir():
                continue
            parent_uuid = folder.name.split("_", 1)[-1] if "_" in folder.name else None
            for jsonl in sorted(folder.glob("*.jsonl")):
                found.append(Source(jsonl, "archive", label.name, False, None))
            subs = folder / "subagents"
            if subs.is_dir():
                for agent in sorted(subs.rglob("*.jsonl")):
                    found.append(Source(agent, "archive", label.name, True, parent_uuid))
    return found


def discover_live() -> list[Source]:
    """`~/.claude/projects/<slug>/<uuid>.jsonl`, plus nested `subagents/`."""
    found: list[Source] = []
    if not LIVE.is_dir():
        return found
    for slug in sorted(LIVE.iterdir()):
        if not slug.is_dir():
            continue
        for jsonl in sorted(slug.glob("*.jsonl")):
            found.append(Source(jsonl, "live", slug.name, False, None))
        for session_dir in sorted(slug.iterdir()):
            if not session_dir.is_dir():
                continue
            subs = session_dir / "subagents"
            if subs.is_dir():
                for agent in sorted(subs.rglob("*.jsonl")):
                    found.append(Source(agent, "live", slug.name, True, session_dir.name))
    return found


# ------------------------------------------------------------------- schema

SESSION_COLUMNS: tuple[str, ...] = (
    "key", "session_uuid", "source_tree", "source_path", "container_name",
    "size_bytes", "line_count", "is_subagent", "parent_session_uuid", "agent_id",
    "agent_name", "cwd", "project_label", "repo_root", "is_worktree",
    "worktree_name", "git_branch", "first_ts", "last_ts", "wall_seconds",
    "active_seconds", "engaged_seconds", "idle_seconds", "local_date",
    "local_hour", "local_weekday", "tz_offset", "n_user_prompts", "n_prompt_ids",
    "n_assistant_turns", "n_tool_uses", "n_tool_results", "n_thinking_blocks",
    "n_attachments", "n_turn_duration_events", "tok_input", "tok_output",
    "tok_cache_write_5m", "tok_cache_write_1h", "tok_cache_write",
    "tok_cache_write_declared", "tok_cache_read", "tok_thinking",
    "tok_billable_total", "tok_context_total", "cost_input_usd",
    "cost_output_usd", "cost_cache_write_usd", "cost_cache_read_usd", "cost_usd",
    "primary_model", "models_json", "cc_versions_json", "effort_json",
    "service_tiers_json", "speeds_json", "permission_modes_json",
    "prompt_sources_json", "entry_types_json", "entrypoint", "user_type",
    "is_sidechain", "cc_version", "is_real", "has_usage", "n_api_errors",
    "n_interrupts", "n_refusals", "refusal_categories_json",
    "interrupted_by_shutdown", "n_malformed_lines", "web_search_requests",
    "web_fetch_requests", "ai_title", "custom_title", "slug_title",
    "first_prompt_preview",
)

_INT_COLS = {
    "size_bytes", "line_count", "is_subagent", "is_worktree", "local_hour",
    "local_weekday", "n_user_prompts", "n_prompt_ids", "n_assistant_turns",
    "n_tool_uses", "n_tool_results", "n_thinking_blocks", "n_attachments",
    "n_turn_duration_events", "tok_input", "tok_output", "tok_cache_write_5m",
    "tok_cache_write_1h", "tok_cache_write", "tok_cache_write_declared",
    "tok_cache_read", "tok_thinking", "tok_billable_total", "tok_context_total",
    "is_sidechain", "is_real", "has_usage", "n_api_errors", "n_interrupts",
    "n_refusals", "interrupted_by_shutdown", "n_malformed_lines",
    "web_search_requests", "web_fetch_requests",
}
_REAL_COLS = {
    "wall_seconds", "active_seconds", "engaged_seconds", "idle_seconds",
    "cost_input_usd", "cost_output_usd", "cost_cache_write_usd",
    "cost_cache_read_usd", "cost_usd",
}


def session_ddl() -> str:
    cols = []
    for name in SESSION_COLUMNS:
        if name == "key":
            cols.append("key TEXT PRIMARY KEY")
        elif name in _INT_COLS:
            cols.append(f"{name} INTEGER")
        elif name in _REAL_COLS:
            cols.append(f"{name} REAL")
        else:
            cols.append(f"{name} TEXT")
    return "CREATE TABLE session (\n  " + ",\n  ".join(cols) + "\n)"


VIEWS = """
CREATE VIEW v_project AS
SELECT
  COALESCE(repo_root, cwd, '(unknown)')      AS repo_root,
  COALESCE(project_label, '(unknown)')       AS project_label,
  COUNT(*)                                   AS files_total,
  SUM(is_real)                               AS sessions_real,
  SUM(is_subagent)                           AS subagent_files,
  SUM(is_worktree)                           AS worktree_files,
  ROUND(SUM(wall_seconds)   / 3600.0, 2)     AS wall_hours,
  ROUND(SUM(engaged_seconds)/ 3600.0, 2)     AS engaged_hours,
  ROUND(SUM(active_seconds) / 3600.0, 2)     AS active_hours,
  SUM(tok_input)                             AS tok_input,
  SUM(tok_output)                            AS tok_output,
  SUM(tok_cache_write)                       AS tok_cache_write,
  SUM(tok_cache_read)                        AS tok_cache_read,
  SUM(tok_billable_total)                    AS tok_billable_total,
  ROUND(SUM(cost_usd), 2)                    AS cost_usd,
  MIN(first_ts)                              AS first_seen,
  MAX(last_ts)                               AS last_seen
FROM session
GROUP BY 1, 2
ORDER BY cost_usd DESC;

CREATE VIEW v_daily AS
SELECT
  local_date,
  COUNT(*)                                   AS files_total,
  SUM(is_real)                               AS sessions_real,
  COUNT(DISTINCT repo_root)                  AS projects_touched,
  ROUND(SUM(wall_seconds)   / 3600.0, 2)     AS wall_hours,
  ROUND(SUM(engaged_seconds)/ 3600.0, 2)     AS engaged_hours,
  ROUND(SUM(active_seconds) / 3600.0, 2)     AS active_hours,
  SUM(n_user_prompts)                        AS prompts,
  SUM(n_tool_uses)                           AS tool_calls,
  SUM(tok_input + tok_output + tok_cache_write) AS tok_billable,
  SUM(tok_cache_read)                        AS tok_cache_read,
  ROUND(SUM(cost_usd), 2)                    AS cost_usd
FROM session
WHERE local_date IS NOT NULL
GROUP BY local_date
ORDER BY local_date;

CREATE VIEW v_hourly AS
SELECT
  local_weekday,
  local_hour,
  COUNT(*)                                   AS files_total,
  SUM(is_real)                               AS sessions_real,
  ROUND(SUM(engaged_seconds)/ 3600.0, 2)     AS engaged_hours,
  ROUND(SUM(cost_usd), 2)                    AS cost_usd
FROM session
WHERE local_hour IS NOT NULL
GROUP BY local_weekday, local_hour
ORDER BY local_weekday, local_hour;

CREATE VIEW v_model AS
SELECT
  model,
  COUNT(*)                                   AS turns,
  COUNT(DISTINCT session_key)                AS sessions,
  SUM(input_tokens)                          AS tok_input,
  SUM(output_tokens)                         AS tok_output,
  SUM(thinking_tokens)                       AS tok_thinking,
  SUM(cache_write_5m + cache_write_1h)       AS tok_cache_write,
  SUM(cache_read)                            AS tok_cache_read,
  ROUND(SUM(cost_usd), 2)                    AS cost_usd
FROM turn
GROUP BY model
ORDER BY cost_usd DESC;

CREATE VIEW v_tool AS
SELECT tool_name, COUNT(*) AS calls, SUM(is_error) AS errors,
       COUNT(DISTINCT session_key) AS sessions
FROM tool_call GROUP BY tool_name ORDER BY calls DESC;

CREATE VIEW v_attribution AS
SELECT kind, name, SUM(count) AS uses, COUNT(DISTINCT session_key) AS sessions
FROM attribution GROUP BY kind, name ORDER BY uses DESC;
"""


def build_overlap(conn: sqlite3.Connection) -> None:
    """Per local day: real clock hours, summed hours, and peak concurrency.

    EVERY session interval is CLIPPED TO EACH CALENDAR DAY IT TOUCHES, then the
    day's clipped intervals are merged. Without the clip a session that ran from
    2026-06-01 to 2026-07-04 contributed its whole 804-hour span to 2026-06-01,
    which produced 814 "elapsed hours" in a 24-hour day. That defect was found by
    a reviewer on 2026-08-21: 73 of 153 days read over 24 h and 87.6% of the
    corpus total sat on physically impossible days.

    After clipping, `elapsed_hours` cannot exceed 24 and `test` asserts it.

    Note `summed_hours` is still a SUM across parallel sessions, so it may well
    exceed 24 on a day when several ran at once. That is not an error: it is what
    running 26 sessions simultaneously means. Only `elapsed_hours` is clock time.
    """
    conn.execute(
        "CREATE TABLE overlap_day ("
        "  local_date TEXT PRIMARY KEY,"
        "  sessions_active INTEGER,"
        "  sessions_started INTEGER,"
        "  summed_hours REAL,"
        "  elapsed_hours REAL,"
        "  concurrency REAL,"
        "  max_concurrent INTEGER)"
    )
    rows = conn.execute(
        "SELECT first_ts, last_ts FROM session "
        "WHERE is_real = 1 AND first_ts IS NOT NULL AND last_ts IS NOT NULL"
    ).fetchall()
    conn.executemany(
        "INSERT INTO overlap_day VALUES (?, ?, ?, ?, ?, ?, ?)",
        overlap_rows(rows, _LOCAL_TZ),
    )


def overlap_rows(rows: list[tuple[str, str]], tz: tzinfo) -> list[tuple[object, ...]]:
    """`overlap_day` rows for whatever `(first_ts, last_ts)` pairs it is given.

    SPLIT OUT OF `build_overlap` SO IT CAN BE ASKED ABOUT A SUBSET. `overlap_day`
    is pre-aggregated per day across EVERY project and carries no `project_label`
    column, so the eight clock-time and concurrency figures in `facts.compute`
    could not be filtered by project at all. They can now, because `facts.py`
    calls this over the selected sessions instead of reading the table.

    ONE implementation, deliberately. The clipping below is a hard-won fix and
    reimplementing it beside a filter would be the same bug twice: see
    `build_overlap`'s docstring, and the eight tests in `tests/test_overlap.py`
    which now exercise this function through it.

    THE ZONE IS AN ARGUMENT, not this module's `_LOCAL_TZ` global. Which day a
    session falls on depends on it, and the process RECOMPUTING a subset is not
    the process that COLLECTED the corpus: `_LOCAL_TZ` is detected at import
    from config and environment, so a config change between the two would have
    bucketed the recomputed days into a different calendar from the stored ones,
    silently. `facts.py` passes the zone the collector actually recorded, from
    `meta.local_timezone` in the database itself.
    """
    day_seconds = DAY_SECONDS
    per_day: dict[str, list[tuple[float, float]]] = {}
    started: Counter[str] = Counter()

    for first_ts, last_ts in rows:
        begin = parse_ts(first_ts)
        finish = parse_ts(last_ts)
        if begin is None or finish is None or finish < begin:
            continue

        # Walk the session forward one local day at a time, clipping as we go.
        # The start day is derived HERE from the same timestamp the clipping
        # uses, not read from the stored local_date column. Two sources for one
        # fact meant `sessions_started` could silently count zero for a day the
        # clip had bucketed differently.
        local_begin = begin.astimezone(_LOCAL_TZ)
        started[local_begin.strftime("%Y-%m-%d")] += 1
        cursor = begin.timestamp()
        stop = finish.timestamp()
        midnight = local_begin.replace(hour=0, minute=0, second=0, microsecond=0)
        boundary = midnight.timestamp() + day_seconds
        day = local_begin
        guard = 0
        while cursor <= stop and guard < 4000:
            guard += 1
            slice_end = min(stop, boundary)
            key = day.strftime("%Y-%m-%d")
            per_day.setdefault(key, []).append((cursor, slice_end))
            if slice_end >= stop:
                break
            cursor = slice_end
            boundary += day_seconds
            day = datetime.fromtimestamp(cursor + 1, tz=_LOCAL_TZ)

    out: list[tuple[object, ...]] = []
    for local_date, spans in per_day.items():
        spans.sort()
        summed = sum(e - s for s, e in spans)

        merged_total = 0.0
        cur_s, cur_e = spans[0]
        for s, e in spans[1:]:
            if s <= cur_e:
                cur_e = max(cur_e, e)
            else:
                merged_total += cur_e - cur_s
                cur_s, cur_e = s, e
        merged_total += cur_e - cur_s

        events: list[tuple[float, int]] = []
        for s, e in spans:
            events.append((s, 1))
            events.append((e, -1))
        events.sort()
        live = peak = 0
        for _, delta in events:
            live += delta
            peak = max(peak, live)

        # Floating point can put the merge a hair over a full day; clamp so the
        # invariant holds exactly rather than by luck.
        merged_total = min(merged_total, day_seconds)

        out.append(
            (
                local_date,
                len(spans),
                started.get(local_date, 0),
                round(summed / 3600.0, 3),
                round(merged_total / 3600.0, 3),
                round(summed / merged_total, 3) if merged_total > 0 else None,
                peak,
            )
        )

    return out


def export_csv(conn: sqlite3.Connection, note: str, out: Out) -> list[str]:
    """Flat exports for plotting. Every file gets the not-a-bill note on line 1."""
    written: list[str] = []
    targets = {
        "sessions.csv": "SELECT * FROM session ORDER BY first_ts",
        "turns.csv": "SELECT * FROM turn ORDER BY session_key, ordinal",
        "projects.csv": "SELECT * FROM v_project",
        "daily.csv": "SELECT * FROM v_daily",
        "hourly.csv": "SELECT * FROM v_hourly",
        "models.csv": "SELECT * FROM v_model",
        "tools.csv": "SELECT * FROM v_tool",
        "attribution.csv": "SELECT * FROM v_attribution",
        "overlap.csv": "SELECT * FROM overlap_day ORDER BY local_date",
    }
    for name, sql in targets.items():
        cur = conn.execute(sql)
        headers = [d[0] for d in cur.description]
        path = out.root / name
        with path.open("w", newline="", encoding="utf-8") as handle:
            handle.write(f"# {note}\n")
            writer = csv.writer(handle)
            writer.writerow(headers)
            writer.writerows(cur)
        written.append(name)
    return written





# --------------------------------------------------------------- scan cache
# `sessions.sqlite` is always rebuilt from scratch (R2's temp-file + replace
# idiom), but the EXPENSIVE step is reading and parsing 25k JSONL files, not
# writing SQLite rows. Almost none of those files change between two runs -
# a session's transcript only grows while it is live, then sits untouched
# forever - so `scan_transcript`'s own result for an unchanged file is cached
# in a sibling database, keyed by that file's own path + size + mtime.
#
# A cache miss (new file, changed file, no cache, wrong fingerprint, a
# corrupted row) always falls back to a full re-scan. Nothing here can make a
# result WRONGER than a full scan would - only slower - which is the whole
# point of treating it as an optimisation rather than a dependency (R5/R10).


def _cache_fingerprint() -> str:
    """Everything besides a transcript's own bytes that can change what a
    cached row means. A cached session row bakes in `cost_usd` (from the
    price table) and `local_date`/`local_hour` (from the detected timezone);
    if either changes, an old row for an untouched file would keep reporting
    numbers that were only ever true under the OLD prices or the OLD zone.
    Mismatched against the stored fingerprint, the whole cache is treated as
    empty - simplest possible invalidation, and correct by construction."""
    return f"{CACHE_SCHEMA_VERSION}|{PRICES_READ_ON}|{_LOCAL_TZ_NAME}"


def _open_cache_ro(path: Path) -> sqlite3.Connection | None:
    """A read-only handle to the previous run's cache, or None if there is
    nothing usable to read from it. Point lookups only, by design: the whole
    cache is never loaded into memory at once, so peak memory stays flat with
    corpus size the same way the existing batched scan already is."""
    if not path.is_file():
        return None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        row = conn.execute("SELECT value FROM meta WHERE key = 'fingerprint'").fetchone()
    except sqlite3.Error:
        return None
    if row is None or row[0] != _cache_fingerprint():
        conn.close()
        return None
    return conn


def _cache_lookup(
    cache_ro: sqlite3.Connection | None, key: str, path: Path, size: int, mtime_ns: int
) -> Scan | None:
    """The cached `Scan` for `key` if the cache still describes this exact
    file (same path, size and mtime), else None.

    Measured, not assumed: reusing the row's own raw JSON text on a hit
    (skipping the decode-then-re-encode when writing the new cache) was tried
    and made no measurable difference against the real archive - the SQL
    lookups and JSON decode dominate, not the encode - so the simpler,
    symmetric form (always re-encode) is what shipped."""
    if cache_ro is None:
        return None
    try:
        row = cache_ro.execute(
            "SELECT source_path, size_bytes, mtime_ns, session_json, turns_json,"
            " tools_json, attrs_json FROM cache WHERE key = ?",
            (key,),
        ).fetchone()
    except sqlite3.Error:
        return None
    if row is None:
        return None
    src_path, cached_size, cached_mtime, session_json, turns_json, tools_json, attrs_json = row
    if src_path != str(path) or cached_size != size or cached_mtime != mtime_ns:
        return None
    try:
        out = Scan()
        out.session = json.loads(session_json)
        out.turns = [tuple(r) for r in json.loads(turns_json)]
        out.tools = [tuple(r) for r in json.loads(tools_json)]
        out.attrs = [tuple(r) for r in json.loads(attrs_json)]
    except (ValueError, TypeError):
        return None
    return out


def main() -> int:
    argv = sys.argv[1:]
    quiet = "--quiet" in argv
    no_cache = "--no-cache" in argv
    limit = 0
    if "--limit" in argv:
        limit = int(argv[argv.index("--limit") + 1])

    def say(message: str) -> None:
        if not quiet:
            print(message, flush=True)

    try:
        out = resolve_out(argv)
    except BadOut as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    # Write-root self check. The only path this process may create is out.root.
    out.ensure()
    if not out.root.is_dir():
        print(f"cannot use output directory: {out.root}", file=sys.stderr)
        return 2

    started = time.time()
    say(f"scanning\n  archive: {ARCHIVE}\n  live:    {LIVE}")
    say(f"  zone:    {_LOCAL_TZ_NAME}  <- {_LOCAL_TZ_SOURCE}")

    sources = discover_archive() + discover_live()
    say(f"found {len(sources):,} transcript files")
    if limit:
        sources = sources[:limit]
        say(f"--limit {limit}: scanning {len(sources):,}")

    # ---------------------------------------------------------- dedupe first
    # Pick the winner per identity BEFORE parsing, using file size as the
    # ordering key. This is an ORDERING comparison only, never an equality
    # test (DESIGN R1/R12): between two captures of one session the larger
    # file is the more complete one, because a short capture is a byte prefix
    # of the long one. Deciding first means each session is parsed once and
    # nothing but the winner list is held in memory.
    winners: dict[str, tuple[Source, int, int]] = {}
    superseded = 0
    for src in sources:
        try:
            stat = src.path.stat()
        except OSError:
            continue
        size = stat.st_size
        if src.is_subagent:
            # The archive names a sub-agent transcript by its bare agent id
            # (`<id>.jsonl`); the live tree keeps Claude Code's own filename,
            # which carries an `agent-` prefix (`agent-<id>.jsonl`). Without
            # normalising, the same sub-agent gets two different keys - one
            # per tree - and is scanned and counted TWICE (measured on this
            # machine's real corpus: 1,908 sub-agents, +US$5,750, +119
            # engaged hours). Strip the prefix so both trees collapse to one
            # identity, same as a top-level session's `<uuid>.jsonl` already
            # does on both trees.
            stem = src.path.stem
            if stem.startswith("agent-"):
                stem = stem[len("agent-") :]
            key = f"agent:{stem}"
        else:
            key = src.path.stem
        prior = winners.get(key)
        if prior is None:
            winners[key] = (src, size, stat.st_mtime_ns)
            continue
        superseded += 1
        prior_src, prior_size, _prior_mtime = prior
        if size > prior_size or (size == prior_size and src.tree == "archive"):
            winners[key] = (src, size, stat.st_mtime_ns)

    say(f"{len(winners):,} distinct sessions ({superseded:,} duplicate payloads collapsed)")

    # A --limit run only ever sees a slice of the corpus. Writing that slice
    # back as "the cache" would evict every session outside the slice, so a
    # smoke test still READS the cache (useful for testing the cache itself)
    # but never overwrites it.
    write_cache = limit == 0
    cache_ro = None if no_cache else _open_cache_ro(out.cache)
    if no_cache:
        say("--no-cache: rescanning every transcript")
    elif cache_ro is None:
        say("no usable scan cache found; scanning every transcript")

    # ------------------------------------------------------------ write out
    # Publish via mkstemp + os.replace (DESIGN R2's idiom): build into a fresh
    # temp file beside the target, then rename it over in one atomic step. This
    # replaces a real leak: the previous approach renamed `sessions.sqlite`
    # aside to `sessions.sqlite.prev` on every run and never removed it, which
    # left two full copies of a 137 MB file on disk forever. It also means a
    # crash mid-build can no longer corrupt the live database: the live file is
    # only ever replaced by a complete build.
    stale = sorted(out.root.glob("*.sqlite.building"))
    if stale:
        say(f"note: {len(stale)} stale build file(s) from an earlier interrupted"
            " run (left alone; remove by hand if not needed):")
        for path in stale:
            say(f"      {path}")

    building_fd, building_name = tempfile.mkstemp(
        dir=out.root, prefix="sessions.", suffix=".sqlite.building"
    )
    os.close(building_fd)
    building_path = Path(building_name)
    conn = sqlite3.connect(building_path)
    # OFF, not WAL: this file is throwaway on any crash (never published unless
    # the build finishes and closes cleanly) and single-writer, so a rollback
    # journal buys nothing and would only leave orphan -wal/-shm files behind.
    conn.execute("PRAGMA journal_mode = OFF")
    conn.execute("PRAGMA synchronous = OFF")
    conn.execute(session_ddl())
    conn.execute(
        "CREATE TABLE turn ("
        " session_key TEXT, ordinal INTEGER, ts TEXT, model TEXT, effort TEXT,"
        " service_tier TEXT, speed TEXT, stop_reason TEXT, input_tokens INTEGER,"
        " output_tokens INTEGER, cache_write_5m INTEGER, cache_write_1h INTEGER,"
        " cache_read INTEGER, thinking_tokens INTEGER, web_search_requests INTEGER,"
        " web_fetch_requests INTEGER, cost_usd REAL)"
    )
    conn.execute(
        "CREATE TABLE tool_call ("
        " session_key TEXT, ts TEXT, tool_name TEXT, is_error INTEGER)"
    )
    conn.execute(
        "CREATE TABLE attribution ("
        " session_key TEXT, kind TEXT, name TEXT, count INTEGER)"
    )
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")

    # The new cache, built the exact same way (temp file + os.replace) and for
    # the exact same reason: a crash mid-run must leave the last good cache
    # untouched rather than a half-written one that would be silently trusted
    # next time.
    cache_building_path: Path | None = None
    cache_conn: sqlite3.Connection | None = None
    if write_cache:
        cache_fd, cache_name = tempfile.mkstemp(
            dir=out.root, prefix="scan-cache.", suffix=".sqlite.building"
        )
        os.close(cache_fd)
        cache_building_path = Path(cache_name)
        cache_conn = sqlite3.connect(cache_building_path)
        cache_conn.execute("PRAGMA journal_mode = OFF")
        cache_conn.execute("PRAGMA synchronous = OFF")
        cache_conn.execute(
            "CREATE TABLE cache (key TEXT PRIMARY KEY, source_path TEXT,"
            " size_bytes INTEGER, mtime_ns INTEGER, session_json TEXT,"
            " turns_json TEXT, tools_json TEXT, attrs_json TEXT)"
        )
        cache_conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")

    placeholders = ", ".join("?" for _ in SESSION_COLUMNS)
    insert_session = f"INSERT INTO session VALUES ({placeholders})"

    # Parse and flush in batches so peak memory stays flat regardless of corpus
    # size. This machine runs several Claude Code sessions at once; a collector
    # that grows to gigabytes would starve them.
    BATCH = 500
    sess_rows: list[tuple[object, ...]] = []
    turn_rows: list[tuple[object, ...]] = []
    tool_rows: list[tuple[object, ...]] = []
    attr_rows: list[tuple[object, ...]] = []
    cache_rows: list[tuple[object, ...]] = []
    scanned = unreadable = cache_hits = cache_misses = 0
    n_rows = {"session": 0, "turn": 0, "tool_call": 0, "attribution": 0}

    def flush() -> None:
        if sess_rows:
            conn.executemany(insert_session, sess_rows)
            n_rows["session"] += len(sess_rows)
            sess_rows.clear()
        if turn_rows:
            conn.executemany(
                "INSERT INTO turn VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", turn_rows
            )
            n_rows["turn"] += len(turn_rows)
            turn_rows.clear()
        if tool_rows:
            conn.executemany("INSERT INTO tool_call VALUES (?,?,?,?)", tool_rows)
            n_rows["tool_call"] += len(tool_rows)
            tool_rows.clear()
        if attr_rows:
            conn.executemany("INSERT INTO attribution VALUES (?,?,?,?)", attr_rows)
            n_rows["attribution"] += len(attr_rows)
            attr_rows.clear()
        conn.commit()
        if cache_conn is not None and cache_rows:
            cache_conn.executemany(
                "INSERT OR REPLACE INTO cache VALUES (?,?,?,?,?,?,?,?)", cache_rows
            )
            cache_rows.clear()
            cache_conn.commit()

    for key, (src, size, mtime_ns) in winners.items():
        result = _cache_lookup(cache_ro, key, src.path, size, mtime_ns)
        if result is not None:
            cache_hits += 1
        else:
            result = scan_transcript(
                src.path,
                source_tree=src.tree,
                container=src.container,
                is_subagent=src.is_subagent,
                parent_uuid=src.parent,
            )
            cache_misses += 1
        if result is None:
            unreadable += 1
            continue
        scanned += 1
        result.session["key"] = key
        sess_rows.append(tuple(result.session.get(col) for col in SESSION_COLUMNS))
        turn_rows.extend((key, *row[1:]) for row in result.turns)
        tool_rows.extend((key, *row[1:]) for row in result.tools)
        attr_rows.extend((key, *row[1:]) for row in result.attrs)
        if cache_conn is not None:
            cache_rows.append((
                key, str(src.path), size, mtime_ns,
                json.dumps(result.session), json.dumps(result.turns),
                json.dumps(result.tools), json.dumps(result.attrs),
            ))
        if len(sess_rows) >= BATCH:
            flush()
            if not quiet and scanned % 5000 < BATCH:
                say(f"  ... {scanned:,} / {len(winners):,} parsed ({cache_hits:,} cached)")
    flush()
    if cache_ro is not None:
        cache_ro.close()

    say(f"parsed {scanned:,} sessions ({unreadable:,} unreadable,"
        f" {cache_hits:,} from cache, {cache_misses:,} rescanned)")

    for stmt in (
        "CREATE INDEX idx_session_date ON session(local_date)",
        "CREATE INDEX idx_session_repo ON session(repo_root)",
        "CREATE INDEX idx_session_real ON session(is_real)",
        "CREATE INDEX idx_turn_session ON turn(session_key)",
        "CREATE INDEX idx_turn_model ON turn(model)",
        "CREATE INDEX idx_tool_session ON tool_call(session_key)",
    ):
        conn.execute(stmt)

    conn.executescript(VIEWS)
    build_overlap(conn)

    for k, v in (
        ("generated_at", datetime.now(UTC).isoformat()),
        ("prices_read_on", PRICES_READ_ON),
        ("cost_note", cost_note(PRICES_READ_ON)),
        ("idle_gap_seconds", str(_IDLE_GAP_SECONDS)),
        ("local_timezone", _LOCAL_TZ_NAME),
        ("local_timezone_source", _LOCAL_TZ_SOURCE),
        ("local_timezone_dst_aware", "yes" if isinstance(_LOCAL_TZ, ZoneInfo) else "NO"),
        ("archive_root", str(ARCHIVE)),
        ("live_root", str(LIVE)),
    ):
        conn.execute("INSERT INTO meta VALUES (?, ?)", (k, v))

    conn.commit()
    files = export_csv(conn, cost_note(PRICES_READ_ON), out)

    # --------------------------------------------------------- self checks
    checks: dict[str, object] = {}
    checks["turns_where_thinking_exceeds_output"] = conn.execute(
        "SELECT COUNT(*) FROM turn WHERE thinking_tokens > output_tokens"
    ).fetchone()[0]
    checks["sessions_where_cache_split_disagrees"] = conn.execute(
        "SELECT COUNT(*) FROM session WHERE tok_cache_write <> tok_cache_write_declared"
    ).fetchone()[0]
    # `<synthetic>` turns are placeholders Claude Code writes locally (an
    # interrupted or cancelled reply). No API call happened, so no usage object
    # exists and none should. Measured 2026-08-21: all 34 such sessions in the
    # corpus carry exactly {"<synthetic>": 1}. Excluding them is what makes this
    # check mean "a real model turn lost its token data".
    checks["real_turns_missing_usage"] = conn.execute(
        "SELECT COUNT(*) FROM session WHERE has_usage = 0"
        " AND n_assistant_turns > 0 AND models_json <> '{\"<synthetic>\": 1}'"
    ).fetchone()[0]
    checks["synthetic_only_sessions"] = conn.execute(
        "SELECT COUNT(*) FROM session WHERE models_json = '{\"<synthetic>\": 1}'"
    ).fetchone()[0]
    # A day cannot hold more than 24 hours of clock time. This check exists
    # because it did not, and 73 days read over 24 h before the clip landed.
    checks["days_with_impossible_elapsed_hours"] = conn.execute(
        "SELECT COUNT(*) FROM overlap_day WHERE elapsed_hours > 24.001"
    ).fetchone()[0]
    # A fixed-offset zone silently mis-buckets every session recorded under a
    # different offset. That happened: 577 sessions landed an hour early.
    checks["local_zone_is_dst_aware"] = isinstance(_LOCAL_TZ, ZoneInfo)
    checks["local_zone_from_config"] = _LOCAL_TZ_SOURCE.startswith("config")
    checks["distinct_utc_offsets_in_corpus"] = len(
        {row[0] for row in conn.execute("SELECT DISTINCT tz_offset FROM session")}
    )
    checks["session_cost_vs_turn_cost_delta_usd"] = round(
        (conn.execute("SELECT COALESCE(SUM(cost_usd),0) FROM session").fetchone()[0] or 0.0)
        - (conn.execute("SELECT COALESCE(SUM(cost_usd),0) FROM turn").fetchone()[0] or 0.0),
        4,
    )

    totals = conn.execute(
        "SELECT COUNT(*), SUM(is_real), SUM(is_subagent),"
        " ROUND(SUM(wall_seconds)/3600.0,1), ROUND(SUM(engaged_seconds)/3600.0,1),"
        " ROUND(SUM(active_seconds)/3600.0,1),"
        " SUM(tok_input), SUM(tok_output), SUM(tok_cache_write), SUM(tok_cache_read),"
        " ROUND(SUM(cost_usd),2) FROM session"
    ).fetchone()
    elapsed_h = conn.execute(
        "SELECT ROUND(SUM(elapsed_hours),1), ROUND(SUM(summed_hours),1) FROM overlap_day"
    ).fetchone()

    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "elapsed_seconds": round(time.time() - started, 2),
        "transcript_files_found": len(sources),
        "distinct_sessions": len(winners),
        "sessions_parsed": scanned,
        "duplicate_payloads_collapsed": superseded,
        "unreadable_files": unreadable,
        "cache_hits": cache_hits,
        "cache_rescanned": cache_misses,
        "cache_written": cache_conn is not None,
        "rows": dict(n_rows),
        "totals": {
            "files": totals[0],
            "real_sessions": totals[1],
            "subagent_files": totals[2],
            "wall_hours_summed": totals[3],
            "engaged_hours_summed": totals[4],
            "active_hours_turn_duration": totals[5],
            "real_elapsed_hours_deduped": elapsed_h[0],
            "summed_hours_for_comparison": elapsed_h[1],
            "tok_input": totals[6],
            "tok_output": totals[7],
            "tok_cache_write": totals[8],
            "tok_cache_read": totals[9],
            "cost_usd_api_list_price": totals[10],
        },
        "self_checks": checks,
        "unpriced_models": dict(_UNPRICED),
        "stale_building_files": [str(p) for p in stale],
        "local_timezone": _LOCAL_TZ_NAME,
        "local_timezone_source": _LOCAL_TZ_SOURCE,
        "prices_read_on": PRICES_READ_ON,
        "cost_note": cost_note(PRICES_READ_ON),
        "outputs": [str(out.db), *[str(out.root / f) for f in files]],
    }
    publish_text(json.dumps(report, indent=2, sort_keys=True) + "\n", out.report)
    conn.close()
    os.replace(building_path, out.db)

    if cache_conn is not None and cache_building_path is not None:
        cache_conn.execute(
            "INSERT INTO meta VALUES ('fingerprint', ?)", (_cache_fingerprint(),)
        )
        cache_conn.commit()
        cache_conn.close()
        os.replace(cache_building_path, out.cache)

    say("")
    say(json.dumps(report["totals"], indent=2))
    say("")
    say(f"self checks: {json.dumps(checks)}")
    if _UNPRICED:
        say(f"UNPRICED MODELS (cost counted as 0): {dict(_UNPRICED)}")
    say(f"\nwrote {out.db}")
    say(f"      {out.report}")
    say(f"      {len(files)} csv files in {out.root}")
    if cache_conn is not None:
        say(f"      {out.cache}  ({cache_hits:,} cached, {cache_misses:,} rescanned)")
    elif limit:
        say(f"      {out.cache} left untouched (--limit run)")
    else:
        say(f"      {out.cache} left untouched")
    say(f"done in {report['elapsed_seconds']}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
