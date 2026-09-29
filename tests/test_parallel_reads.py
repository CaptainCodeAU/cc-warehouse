"""Oracle tests: the read-only share checks run in a bounded thread pool.

Open item W-20260929-A91, ticket 46 option A step 1 (ruling: Gavin, 2026-09-29).
With the archive on SMB over Wi-Fi, one small file costs 50 to 64 ms to open and
read cold, and the daily sweep spent 4h30m waiting on the share with 16 minutes of
CPU. Reads that overlap cost far less per file (21 / 11 / 7 ms at 8 / 16 / 32
threads, measured). So the READ-ONLY questions go through a bounded pool:

- the build's per-head "is this folder current" check (results used directly);
- the sweep's per-item read-backs (a read-ahead that warms the share's client
  cache just before the unchanged serial writers re-read the same files);
- the coverage pass, the full desync verify `ccw repair` uses, and `ccw archive
  --verify`.

WRITES STAY EXACTLY AS THEY ARE: same order, same writers, main thread only.

The oracles, one group each:

1. The parallel run's outcomes and every byte it writes equal the serial run's.
2. The pool is bounded: never more than `READ_WORKERS` reads at once.
3. A read that raises in a worker becomes that item's failure (R10), never an
   aborted batch; a warm-up that raises changes nothing at all.
4. No write happens off the main thread.
5. The build checks at most one chunk ahead of where it acts, so the
   check-then-act window stays short (and the A58 re-check still runs first).
6. The single-session hook path never starts a pool.
"""

import json
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import cast

import pytest

from cc_warehouse import archive, build, capture, doctor, parallel, status, store, sweep
from cc_warehouse.config import Config, load_config
from cc_warehouse.reports import BatchReport
from conftest import (
    basic_session,
    entry,
    jsonl,
    mark_archive,
    run_cli,
    subagent_meta,
    subagent_session,
    tree_snapshot,
)

ZONE = "UTC"
ENCODED = "-home-alice-projects-widget"
CWD = "/home/alice/projects/widget"
UUIDS = [f"a{i}a{i}a{i}a{i}-0000-4000-8000-00000000000{i}" for i in range(6)]
AGENTS = {0: "a0000000000000000", 1: "a1111111111111111", 2: "a2222222222222222"}


# ---------------------------------------------------------------------------
# A small, deterministic corpus that reaches every parallelised read
# ---------------------------------------------------------------------------


def _session(i: int) -> bytes:
    return basic_session(cwd=CWD, session_id=UUIDS[i], prompt=f"Please fix widget number {i}")


def _sandbox(base: Path, monkeypatch: pytest.MonkeyPatch, *, live_like: bool) -> Config:
    """A fresh HOME, warehouse and archive under `base`, and its loaded config.

    `live_like` mirrors the operator's real config (no vault, no projections);
    otherwise the shipped defaults keep both, so `pages_are_current` is reached too.
    """
    home = base / "home"
    (home / ".claude" / "projects").mkdir(parents=True)
    archive_root = base / "archive"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CCW_ROOT", str(base / "warehouse"))
    monkeypatch.setenv("CCW_DESKTOP_ALERTS", "0")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("CCW_SKIP_HOOK", raising=False)
    cfg = home / ".config" / "cc-warehouse"
    cfg.mkdir(parents=True)
    lines = [
        f'root = "{base / "warehouse"}"',
        f'archive_root = "{archive_root}"',
        f'archive_timezone = "{ZONE}"',
    ]
    if live_like:
        lines += ["keep_objects = false", "keep_projections = false"]
    (cfg / "config.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    mark_archive(archive_root, ZONE)
    return load_config()


def _claude(config: Config) -> Path:
    return Path.home() / ".claude"


def _project(config: Config) -> Path:
    return _claude(config) / "projects" / ENCODED


def _plant(config: Config) -> None:
    project = _project(config)
    project.mkdir(parents=True, exist_ok=True)
    for i in range(len(UUIDS)):
        (project / f"{UUIDS[i]}.jsonl").write_bytes(_session(i))
    for i, agent in AGENTS.items():
        sub = project / UUIDS[i] / "subagents"
        sub.mkdir(parents=True, exist_ok=True)
        (sub / f"agent-{agent}.jsonl").write_bytes(
            subagent_session(agent_id=agent, parent_uuid=UUIDS[i], cwd=CWD)
        )
        (sub / f"agent-{agent}.meta.json").write_bytes(subagent_meta())
    for i in (0, 3):
        results = project / UUIDS[i] / "tool-results"
        results.mkdir(parents=True, exist_ok=True)
        (results / f"toolu_{i}.txt").write_bytes(f"tool output {i}\n".encode())
    history = _claude(config) / "file-history" / UUIDS[1]
    history.mkdir(parents=True)
    (history / "0123abcd@v1").write_bytes(b"old file contents\n")
    todos = _claude(config) / "todos"
    todos.mkdir(parents=True)
    (todos / f"{UUIDS[2]}-agent-{UUIDS[2]}.json").write_bytes(b'[{"content": "x"}]\n')
    pastes = _claude(config) / "paste-cache"
    pastes.mkdir(parents=True)
    (pastes / "hash0.txt").write_bytes(b"pasted text\n")
    (pastes / "hash1.txt").write_bytes(b"more pasted text\n")
    rows: list[dict[str, object]] = [
        {"display": f"prompt {i}", "sessionId": UUIDS[i], "timestamp": 1000 + i}
        for i in range(4)
    ]
    rows.extend(
        {
            "display": "with paste",
            "sessionId": UUIDS[i],
            "pastedContents": {"1": {"id": 1, "type": "text", "contentHash": f"hash{i}"}},
        }
        for i in (0, 1)
    )
    (_claude(config) / "history.jsonl").write_bytes(
        b"".join(json.dumps(row).encode() + b"\n" for row in rows)
    )


def _folder(config: Config, i: int) -> Path:
    assert config.archive_root is not None
    found = sorted(config.archive_root.glob(f"*/*_{UUIDS[i]}"))
    assert len(found) == 1, found
    return found[0]


def _mutate(config: Config) -> None:
    """One of each kind of change a real day brings, between two sweeps."""
    project = _project(config)
    (project / UUIDS[0] / "tool-results" / "toolu_new.txt").write_bytes(b"a new result\n")
    grown = project / UUIDS[1] / "subagents" / f"agent-{AGENTS[1]}.jsonl"
    grown.write_bytes(
        grown.read_bytes()
        + jsonl(entry("user", "one more turn", "2026-01-05T11:00:00.000Z", session_id=UUIDS[1]))
    )
    shrunk = project / UUIDS[2] / "subagents" / f"agent-{AGENTS[2]}.jsonl"
    shrunk.write_bytes(shrunk.read_bytes()[:-40] + b"\n")
    (_folder(config, 4) / "transcript.md").unlink()
    (_folder(config, 3) / "tool-results" / "toolu_3.txt").write_bytes(b"changed in the archive\n")
    with (_claude(config) / "history.jsonl").open("ab") as fh:
        fh.write(json.dumps({"display": "later", "sessionId": UUIDS[1]}).encode() + b"\n")


def _normal(report: BatchReport, base: Path) -> list[tuple[str, str, str]]:
    return [
        (o.item, o.action, o.detail.replace(str(base), "<SANDBOX>")) for o in report.outcomes
    ]


def _scenario(config: Config, base: Path) -> dict[str, object]:
    """Sweep, build, cover; change things; do it again; then every read-only check."""
    assert config.archive_root is not None
    source = _claude(config) / "projects"
    _plant(config)
    seen: dict[str, object] = {}
    seen["sweep1"] = _normal(sweep.sweep(config, source), base)
    seen["build1"] = _normal(build.build(config), base)
    _mutate(config)
    seen["sweep2"] = _normal(sweep.sweep(config, source), base)
    seen["build2"] = _normal(build.build(config), base)
    seen["build3"] = _normal(build.build(config), base)
    status.write_coverage(config, source)
    coverage = json.loads(status.coverage_path(config).read_text(encoding="utf-8"))
    del coverage["at"]
    seen["coverage"] = coverage
    recent, broken = doctor.desync_detail(config)
    seen["desync"] = (
        [str(p).replace(str(base), "<SANDBOX>") for p in recent],
        [
            (str(p).replace(str(base), "<SANDBOX>"), [x.problem for x in problems])
            for p, problems in broken
        ],
    )
    verify = run_cli(["archive", "--to", str(config.archive_root), "--verify"])
    seen["verify"] = (verify.code, verify.out, verify.err.replace(str(base), "<SANDBOX>"))
    tree = tree_snapshot(config.archive_root)
    # The root marker records when and where it was made, so it differs between
    # any two sandboxes; nothing this change touches writes it.
    del tree[archive.ROOT_MARKER]
    seen["tree"] = tree
    if config.keep_projections:
        seen["projections"] = tree_snapshot(config.root / "projections")
    return seen


def _serial(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(parallel, "READ_WORKERS", 1)


def _pooled(monkeypatch: pytest.MonkeyPatch, workers: int = 4, chunk: int = 2) -> None:
    monkeypatch.setattr(parallel, "READ_WORKERS", workers)
    monkeypatch.setattr(parallel, "READ_CHUNK", chunk)


# ---------------------------------------------------------------------------
# 1. Same outcomes, same bytes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("live_like", [True, False], ids=["live-config", "defaults"])
def test_the_pooled_run_matches_the_serial_run_exactly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, live_like: bool
) -> None:
    _serial(monkeypatch)
    serial = _scenario(_sandbox(tmp_path / "s", monkeypatch, live_like=live_like), tmp_path / "s")
    _pooled(monkeypatch)
    pooled = _scenario(_sandbox(tmp_path / "p", monkeypatch, live_like=live_like), tmp_path / "p")

    # The control: the scenario really exercised writes, refusals and failures of
    # the verify, so equality below is not two empty reports agreeing.
    actions = {a for _i, a, _d in cast(list[tuple[str, str, str]], serial["sweep2"])}
    assert {"archived-sidecars", "refused-sidecar", "refused-subagent"} <= actions, actions
    assert any(a == "built" for _i, a, _d in cast(list[tuple[str, str, str]], serial["build2"]))

    for key in serial:
        assert pooled[key] == serial[key], key


def test_a_warm_up_that_raises_changes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The sweep's read-ahead is an optimisation and nothing else: when every
    warm-up raises, the serial writers meet the same world and do the same thing."""
    _serial(monkeypatch)
    serial = _scenario(_sandbox(tmp_path / "s", monkeypatch, live_like=True), tmp_path / "s")
    _pooled(monkeypatch)
    raised: list[str] = []

    def broken(*_args: object) -> None:
        raised.append(threading.current_thread().name)
        raise OSError("the share went away")

    for name in ("_warm_subagent", "_warm_sidecars", "_warm_history"):
        monkeypatch.setattr(sweep, name, broken)
    pooled = _scenario(_sandbox(tmp_path / "p", monkeypatch, live_like=True), tmp_path / "p")

    assert raised, "control: no warm-up ran, so nothing was tested"
    for key in serial:
        assert pooled[key] == serial[key], key


# ---------------------------------------------------------------------------
# 2. Bounded
# ---------------------------------------------------------------------------


class _Gauge:
    """Counts how many wrapped calls are in flight at once, and on which threads."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.now = 0
        self.peak = 0
        self.calls = 0
        self.off_main = 0

    def wrap[**P, R](self, fn: Callable[P, R], delay: float = 0.03) -> Callable[P, R]:
        def inner(*args: P.args, **kwargs: P.kwargs) -> R:
            with self.lock:
                self.now += 1
                self.calls += 1
                self.peak = max(self.peak, self.now)
                if threading.current_thread() is not threading.main_thread():
                    self.off_main += 1
            try:
                time.sleep(delay)
                return fn(*args, **kwargs)
            finally:
                with self.lock:
                    self.now -= 1

        return inner


def _built(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    config = _sandbox(tmp_path / "w", monkeypatch, live_like=True)
    _plant(config)
    sweep.sweep(config, _claude(config) / "projects")
    build.build(config)
    return config


def test_build_currency_checks_run_in_a_bounded_pool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _built(tmp_path, monkeypatch)
    _pooled(monkeypatch, workers=3, chunk=6)
    gauge = _Gauge()
    monkeypatch.setattr(archive, "folder_is_current", gauge.wrap(archive.folder_is_current))

    report = build.build(config)

    assert {o.action for o in report.outcomes} == {build.UNCHANGED}
    assert gauge.calls == len(UUIDS)
    assert 2 <= gauge.peak <= 3, gauge.peak
    assert gauge.off_main == gauge.calls


def test_sweep_read_ahead_runs_in_a_bounded_pool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _built(tmp_path, monkeypatch)
    _pooled(monkeypatch, workers=2, chunk=8)
    gauges = {name: _Gauge() for name in ("_warm_subagent", "_warm_sidecars", "_warm_history")}
    for name, gauge in gauges.items():
        monkeypatch.setattr(sweep, name, gauge.wrap(getattr(sweep, name)))

    sweep.sweep(config, _claude(config) / "projects")

    for name, gauge in gauges.items():
        assert gauge.calls >= 2, (name, gauge.calls)
        assert gauge.peak == 2, (name, gauge.peak)
        assert gauge.off_main == gauge.calls, name


def test_desync_verify_and_coverage_read_in_a_bounded_pool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _built(tmp_path, monkeypatch)
    _pooled(monkeypatch, workers=3, chunk=4)
    verify = _Gauge()
    notice = _Gauge()
    manifest = _Gauge()
    monkeypatch.setattr(archive, "verify_folder", verify.wrap(archive.verify_folder))
    monkeypatch.setattr(archive, "read_sidecar_notice", notice.wrap(archive.read_sidecar_notice))
    monkeypatch.setattr(status, "_read_manifest", manifest.wrap(status._read_manifest))  # pyright: ignore[reportPrivateUsage]

    doctor.desync_detail(config)
    status.write_coverage(config, _claude(config) / "projects")

    for gauge in (verify, notice, manifest):
        assert gauge.calls == len(UUIDS)
        assert 2 <= gauge.peak <= 3, gauge.peak
        assert gauge.off_main == gauge.calls


def test_archive_verify_reads_in_a_bounded_pool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _built(tmp_path, monkeypatch)
    assert config.archive_root is not None
    _pooled(monkeypatch, workers=3, chunk=4)
    gauge = _Gauge()
    monkeypatch.setattr(archive, "verify_folder", gauge.wrap(archive.verify_folder))

    result = run_cli(["archive", "--to", str(config.archive_root), "--verify"])

    assert result.code == 0, result.err
    assert f"{len(UUIDS)} folders checked, 0 problems" in result.out
    assert 2 <= gauge.peak <= 3, gauge.peak


def test_the_read_ahead_covers_every_read_back_the_writers_make(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pins what the warm-up is FOR: on a steady-state sweep, every archive file
    a serial writer reads back was already read by a worker, so on the share it
    comes out of the client cache. A warm-up that warms nothing passes every
    other test here; it fails this one."""
    config = _built(tmp_path, monkeypatch)
    assert config.archive_root is not None
    _pooled(monkeypatch, workers=4, chunk=8)
    archive_root = str(config.archive_root)
    lock = threading.Lock()
    warmed: set[str] = set()
    cold: list[str] = []
    real = Path.read_bytes

    def recording(self: Path) -> bytes:
        name = str(self)
        if name.startswith(archive_root):
            with lock:
                if threading.current_thread() is not threading.main_thread():
                    warmed.add(name)
                elif name not in warmed:
                    cold.append(name)
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", recording)
    sweep.sweep(config, _claude(config) / "projects")

    assert len(warmed) >= 8, f"control: only {len(warmed)} files were warmed"
    assert cold == []


# ---------------------------------------------------------------------------
# 3. A raise in a worker is one item's failure
# ---------------------------------------------------------------------------


def test_a_currency_check_that_raises_in_a_worker_fails_only_its_own_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The share dropping mid-run: several workers raise OSError at once."""
    config = _built(tmp_path, monkeypatch)
    _pooled(monkeypatch, workers=4, chunk=6)
    real = archive.folder_is_current
    doomed = {UUIDS[1], UUIDS[4]}
    threads: list[bool] = []

    def flaky(directory: Path, source_hash: str, options: object) -> bool:
        if directory.name.split("_", 1)[1] in doomed:
            threads.append(threading.current_thread() is threading.main_thread())
            raise OSError("Host is down")
        return real(directory, source_hash, options)  # type: ignore[arg-type]

    monkeypatch.setattr(archive, "folder_is_current", flaky)
    report = build.build(config)

    failed = {o.item for o in report.outcomes if o.action == "error"}
    assert len(failed) == 2, report.outcomes
    assert all(o.detail == "OSError: Host is down" for o in report.failures)
    assert sum(o.action == build.UNCHANGED for o in report.outcomes) == len(UUIDS) - 2
    assert threads == [False, False], "the raise did not happen in a worker thread"


def test_archive_verify_names_a_folder_it_could_not_read_and_checks_the_rest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _built(tmp_path, monkeypatch)
    assert config.archive_root is not None
    _pooled(monkeypatch, workers=3, chunk=4)
    real = archive.verify_folder
    doomed = _folder(config, 2)

    def flaky(directory: Path, timezone: str, **kwargs: object) -> list[archive.FolderProblem]:
        if directory == doomed:
            raise OSError("Host is down")
        return real(directory, timezone, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(archive, "verify_folder", flaky)
    result = run_cli(["archive", "--to", str(config.archive_root), "--verify"])

    assert result.code == 1
    assert f"{len(UUIDS)} folders checked, 1 problems" in result.out
    assert f"{doomed.name}: could not be verified: OSError: Host is down" in result.err


# ---------------------------------------------------------------------------
# 4. Writes stay on the main thread
# ---------------------------------------------------------------------------


def test_no_write_happens_off_the_main_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pooled(monkeypatch)
    config = _sandbox(tmp_path / "w", monkeypatch, live_like=False)
    off_main: list[str] = []
    reads = _Gauge()

    def main_only[**P, R](name: str, fn: Callable[P, R]) -> Callable[P, R]:
        def inner(*args: P.args, **kwargs: P.kwargs) -> R:
            if threading.current_thread() is not threading.main_thread():
                off_main.append(f"{name}{args[:1]}")
            return fn(*args, **kwargs)

        return inner

    for name in ("atomic_write", "write_if_changed", "write_if_absent"):
        monkeypatch.setattr(store, name, main_only(name, getattr(store, name)))
    monkeypatch.setattr(Path, "mkdir", main_only("mkdir", Path.mkdir))
    monkeypatch.setattr(archive, "folder_is_current", reads.wrap(archive.folder_is_current, 0))

    _scenario(config, tmp_path / "w")

    assert reads.off_main > 0, "control: no read ran in a worker, so nothing was tested"
    assert off_main == []


# ---------------------------------------------------------------------------
# 5. The check-then-act window is one chunk
# ---------------------------------------------------------------------------


def test_the_build_checks_at_most_one_chunk_ahead_of_acting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _built(tmp_path, monkeypatch)
    for i in range(len(UUIDS)):
        (_folder(config, i) / "transcript.md").unlink()  # every head needs a build
    _pooled(monkeypatch, workers=2, chunk=2)
    lock = threading.Lock()
    events: list[str] = []
    real_current = archive.folder_is_current
    real_superseded = build._superseded_by  # pyright: ignore[reportPrivateUsage]

    def current(directory: Path, source_hash: str, options: object) -> bool:
        # Only the pool's checks: the writer runs its own on the main thread.
        if threading.current_thread() is not threading.main_thread():
            with lock:
                events.append("check")
        return real_current(directory, source_hash, options)  # type: ignore[arg-type]

    def superseded(conn: object, head: object) -> str | None:
        with lock:
            events.append("act")
        return real_superseded(conn, head)  # type: ignore[arg-type]

    monkeypatch.setattr(archive, "folder_is_current", current)
    monkeypatch.setattr(build, "_superseded_by", superseded)
    report = build.build(config)

    assert [o.action for o in report.outcomes] == ["built"] * len(UUIDS)
    ahead = 0
    for event in events:
        ahead += 1 if event == "check" else -1
        assert ahead <= 2, events
    assert events.count("check") == events.count("act") == len(UUIDS)


# ---------------------------------------------------------------------------
# 6. The hook path is serial
# ---------------------------------------------------------------------------


def test_the_hook_path_starts_no_pool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _pooled(monkeypatch)
    config = _sandbox(tmp_path / "w", monkeypatch, live_like=True)
    _plant(config)
    pools: list[int] = []
    real_init = ThreadPoolExecutor.__init__

    def counting(self: object, *args: object, **kwargs: object) -> None:
        pools.append(1)
        real_init(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(ThreadPoolExecutor, "__init__", counting)
    for uuid in UUIDS:
        transcript = _project(config) / f"{uuid}.jsonl"
        result = capture.capture_transcript(config, transcript, session_id=uuid, cwd=CWD)
        assert result.action == "stored", result
    assert pools == []

    build.build(config)
    assert pools, "control: the batch build started no pool, so the counter is blind"


# ---------------------------------------------------------------------------
# The primitive itself
# ---------------------------------------------------------------------------


def test_map_reads_keeps_order_and_captures_each_error() -> None:
    def fn(n: int) -> int:
        if n % 3 == 0:
            raise ValueError(f"bad {n}")
        return n * 10

    results = parallel.map_reads(fn, list(range(1, 8)), workers=3)

    assert [r.error is None for r in results] == [True, True, False, True, True, False, True]
    assert [r.get() for r in results if r.error is None] == [10, 20, 40, 50, 70]
    with pytest.raises(ValueError, match="bad 6"):
        results[5].get()


def test_one_worker_means_no_thread_at_all(monkeypatch: pytest.MonkeyPatch) -> None:
    pools: list[int] = []
    real_init = ThreadPoolExecutor.__init__

    def counting(self: object, *args: object, **kwargs: object) -> None:
        pools.append(1)
        real_init(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(ThreadPoolExecutor, "__init__", counting)
    seen: list[bool] = []

    def fn(n: int) -> int:
        seen.append(threading.current_thread() is threading.main_thread())
        return n

    assert [r.get() for r in parallel.map_reads(fn, [1, 2, 3], workers=1)] == [1, 2, 3]
    warmed: list[int] = []
    assert list(parallel.read_ahead([1, 2, 3], warmed.append, workers=1)) == [1, 2, 3]
    assert pools == [] and seen == [True, True, True] and warmed == []


def test_read_ahead_yields_every_item_in_order_after_warming_its_chunk() -> None:
    lock = threading.Lock()
    log: list[str] = []

    def warm(n: int) -> None:
        with lock:
            log.append(f"w{n}")

    def consume(count: int) -> Iterator[int]:
        for n in parallel.read_ahead(list(range(count)), warm, chunk=2, workers=2):
            log.append(f"y{n}")
            yield n

    assert list(consume(6)) == [0, 1, 2, 3, 4, 5]
    for n in range(6):
        assert log.index(f"w{n}") < log.index(f"y{n}")
    # Chunk 2 is warmed only after chunk 1 has been consumed.
    assert log.index("w2") > log.index("y1")
    # A chunk of one is yielded unwarmed: warming it inline only doubles the read.
    log.clear()
    assert list(consume(3)) == [0, 1, 2]
    assert "w2" not in log and "y2" in log
