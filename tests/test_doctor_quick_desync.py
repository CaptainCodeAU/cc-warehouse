"""Oracle tests: doctor's desync check is a QUICK check, `ccw repair` keeps the full one
(open item W-20260929-A74; ruling: Gavin, 2026-09-29, option 1).

THE FAILURE THIS EXISTS FOR. Measured 2026-09-29 on the real machine: `ccw doctor`
took 47 s and 48 s with no batch job running, and `doctor._desync` alone 16 to 44 s.
The SessionStart freshness hook gives doctor 45 s and counts a timeout as a failure.
The cost was `archive.verify_folder` reading and sha256-hashing every byte of the 25
sampled folders (118 MB in 557 opens over SMB on Wi-Fi) and parsing each JSONL.

THE RULING. At SessionStart doctor confirms each file the manifest lists is PRESENT
and the RIGHT SIZE, using sizes already recorded (each manifest record's `bytes`; the
catalog's `size_bytes` for the main payload, `hidden` and `first_ts` for the rest). No
hashing and no JSONL parsing on that path. The full fingerprint check keeps running in
`ccw repair` (daily) and `ccw archive --verify` (weekly).

WHAT IS PINNED HERE:

  1. doctor's desync path opens nothing under the archive except `manifest.json`,
     computes no sha256 and parses no JSONL, on a healthy folder that holds every
     kind of recorded file;
  2. a truncated or deleted file still FAILs doctor, for every kind of recorded file;
  3. THE ACCEPTED TRADE-OFF, both halves: a same-size byte change passes doctor and is
     caught by the full check `ccw repair` reads;
  4. `ccw repair` still hashes: a hash-only corruption makes it act and report;
  5. a record written before `bytes` existed is still checked (by hash), never skipped;
  6. a hidden session is judged by the catalog's `hidden`, with no parse.
"""

import builtins
import hashlib
import io
import json
import os
import sqlite3
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from cc_warehouse import archive, doctor, parser, store
from cc_warehouse.config import Config
from conftest import (
    basic_session,
    claude_projects,
    entry,
    jsonl,
    mark_archive,
    run_ccw,
    run_cli,
    subagent_meta,
    subagent_session,
    warehouse_root,
    write_transcript,
)

ZONE = "Australia/Melbourne"
UUID_A = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
UUID_W = "dddddddd-4444-4444-8444-dddddddddddd"
TOOL_RESULT = "toolu_01stdout.txt"
AGENT_ID = "agent-sub1"
TITLE = b'{"customTitle":"quick check"}\n'
PROMPTS = b'{"display":"hello","sessionId":"' + UUID_A.encode() + b'"}\n'


def configure(env: dict[str, str], archive_root: Path) -> None:
    cfg = Path(env["HOME"]) / ".config" / "cc-warehouse"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "config.toml").write_text(
        f'root = "{warehouse_root(env)}"\n'
        f'archive_timezone = "{ZONE}"\n'
        f'archive_root = "{archive_root}"\n',
        encoding="utf-8",
    )
    env["XDG_CONFIG_HOME"] = str(cfg.parent)
    mark_archive(archive_root, ZONE)


def age_capture(env: dict[str, str], uuid: str) -> None:
    """Move the catalog's `captured_at` an hour back so no pending grace applies:
    every problem in these tests must be judged as a real one."""
    stamp = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    conn = sqlite3.connect(warehouse_root(env) / "catalog.sqlite")
    try:
        with conn:
            conn.execute(
                "UPDATE session SET captured_at = ? WHERE session_uuid = ?", (stamp, uuid)
            )
    finally:
        conn.close()


def manifest_of(folder: Path) -> dict[str, object]:
    return cast(dict[str, object], json.loads((folder / "manifest.json").read_text("utf-8")))


def rich_folder(env: dict[str, str], tmp_path: Path) -> tuple[Config, Path]:
    """One archived session holding EVERY kind of file a manifest records: the
    payload, a sub-agent, a tool result, `prompts.jsonl` and `custom-title.json`."""
    archive_root = tmp_path / "archive"
    configure(env, archive_root)
    transcript = write_transcript(env, basic_session(session_id=UUID_A), session_id=UUID_A)
    beside = claude_projects(env) / transcript.parent.name / UUID_A
    (beside / "subagents").mkdir(parents=True)
    (beside / "subagents" / f"{AGENT_ID}.jsonl").write_bytes(
        subagent_session(parent_uuid=UUID_A)
    )
    (beside / "subagents" / f"{AGENT_ID}.meta.json").write_bytes(subagent_meta())
    (beside / "tool-results").mkdir()
    (beside / "tool-results" / TOOL_RESULT).write_bytes(b"line one\nline two\n")
    assert run_ccw(["sweep", "--quiet"], env).code == 0
    folders = list(archive.walk_folders(archive_root))
    assert len(folders) == 1, folders
    folder = folders[0]
    archive.write_prompts(folder, PROMPTS)
    archive.write_custom_title(folder, TITLE)
    assert run_ccw(["build"], env).code == 0
    manifest = manifest_of(folder)
    # Control: the fixture really carries every recorded kind, each with a size.
    assert cast(list[dict[str, object]], manifest["subagents"])[0]["bytes"]
    assert cast(list[dict[str, object]], manifest["tool_results"])[0]["bytes"]
    assert cast(dict[str, object], manifest["prompts"])["bytes"]
    assert cast(dict[str, object], manifest["custom_title"])["bytes"]
    age_capture(env, UUID_A)
    config = Config(root=warehouse_root(env), archive_root=archive_root, archive_timezone=ZONE)
    assert doctor._desync(config)[1] == 0, "fixture precondition: healthy"  # pyright: ignore[reportPrivateUsage]
    return config, folder


def targets(folder: Path) -> dict[str, Path]:
    # The product's own locator: a bare `*.jsonl` glob also matches prompts.jsonl.
    payload = archive.sole_jsonl(folder)
    assert payload is not None and payload.name != archive.PROMPTS_FILE, payload
    return {
        "payload": payload,
        "sub-agent": next((folder / "subagents").glob("*/*.jsonl")),
        "tool-result": folder / "tool-results" / TOOL_RESULT,
        "prompts": folder / archive.PROMPTS_FILE,
        "custom-title": folder / archive.CUSTOM_TITLE_FILE,
    }


KINDS = ("payload", "sub-agent", "tool-result", "prompts", "custom-title")


# One word of CONTENT in each kind of file. Flipping a byte in a JSON key instead
# (say "user" -> "usEr") can make the payload parse as hidden, and the full check
# then skips it; that would be a test of the hidden rule, not of the hash.
CONTENT_WORDS = (b"flux", b"reviewer", b"line", b"hello", b"quick")


def flip_one_byte(path: Path) -> None:
    """A same-size change: the length is untouched, the content is not."""
    data = bytearray(path.read_bytes())
    index = next(data.find(word) for word in CONTENT_WORDS if data.find(word) >= 0)
    data[index] = ord(chr(data[index]).upper())
    path.write_bytes(bytes(data))


class Reads:
    """Every archive path opened, and every sha256 and JSONL parse, while active."""

    def __init__(self, root: Path) -> None:
        self.root = str(root)
        self.opened: list[str] = []
        self.hashes = 0
        self.parses = 0

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        real_open = builtins.open

        def wrapped_open(file: object, *args: object, **kwargs: object) -> object:
            if isinstance(file, (str, os.PathLike)):
                text = os.fspath(cast("str | os.PathLike[str]", file))
                if text.startswith(self.root):
                    self.opened.append(text)
            return real_open(file, *args, **kwargs)  # type: ignore[arg-type]

        # pathlib's read_bytes/read_text go through io.open, the rest through builtins.
        monkeypatch.setattr(builtins, "open", wrapped_open)
        monkeypatch.setattr(io, "open", wrapped_open)

        real_hex = store.sha256_hex

        def counted_hex(data: bytes) -> str:
            self.hashes += 1
            return real_hex(data)

        monkeypatch.setattr(store, "sha256_hex", counted_hex)
        real_sha = hashlib.sha256

        def counted_sha(*args: object, **kwargs: object) -> object:
            self.hashes += 1
            return real_sha(*args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(hashlib, "sha256", counted_sha)
        real_parse = parser.parse_session

        def counted_parse(data: bytes) -> object:
            self.parses += 1
            return real_parse(data)

        monkeypatch.setattr(archive, "parse_session", counted_parse)


# ---------------------------------------------------------------------------
# 1. the quick path reads manifests only, hashes nothing, parses nothing
# ---------------------------------------------------------------------------


def test_doctor_desync_opens_only_manifests_and_hashes_nothing_when_healthy(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, folder = rich_folder(ccw_env, tmp_path)
    for kind, path in targets(folder).items():
        assert path.is_file(), f"fixture lacks the {kind} file"
    reads = Reads(folder)
    reads.install(monkeypatch)

    checked, problems, pending, first = doctor._desync(config)  # pyright: ignore[reportPrivateUsage]

    assert (checked, problems, pending, first) == (1, 0, 0, None)
    # Control: the wrapper sees reads at all (the manifest must be one of them).
    assert str(folder / "manifest.json") in reads.opened, reads.opened
    others = sorted({p for p in reads.opened if Path(p).name != "manifest.json"})
    assert others == [], f"doctor's desync path read file contents: {others}"
    assert reads.hashes == 0, f"doctor's desync path computed {reads.hashes} sha256(s)"
    assert reads.parses == 0, f"doctor's desync path parsed {reads.parses} JSONL payload(s)"


def test_the_full_check_repair_reads_still_opens_hashes_and_parses(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The control for the test above, on the SAME fixture and wrapper: if the
    wrapper could not see these reads, the zero above would prove nothing."""
    config, folder = rich_folder(ccw_env, tmp_path)
    reads = Reads(folder)
    reads.install(monkeypatch)

    _folders, broken = doctor.desync_detail(config)

    assert broken == []
    opened = {Path(p).name for p in reads.opened}
    assert {TOOL_RESULT, archive.PROMPTS_FILE, archive.CUSTOM_TITLE_FILE} <= opened, opened
    assert reads.hashes >= len(KINDS)
    assert reads.parses >= 1


# ---------------------------------------------------------------------------
# 2. a truncated or deleted file still FAILs doctor
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", KINDS)
def test_a_truncated_file_fails_doctor(
    ccw_env: dict[str, str], tmp_path: Path, kind: str
) -> None:
    config, folder = rich_folder(ccw_env, tmp_path)
    path = targets(folder)[kind]
    path.write_bytes(path.read_bytes()[:-3])

    _checked, problems, pending, first = doctor._desync(config)  # pyright: ignore[reportPrivateUsage]

    assert problems >= 1, f"a truncated {kind} file passed doctor"
    assert pending == 0
    assert first is not None and folder.name in first


@pytest.mark.parametrize("kind", KINDS)
def test_a_deleted_file_fails_doctor(ccw_env: dict[str, str], tmp_path: Path, kind: str) -> None:
    config, folder = rich_folder(ccw_env, tmp_path)
    targets(folder)[kind].unlink()

    _checked, problems, _pending, first = doctor._desync(config)  # pyright: ignore[reportPrivateUsage]

    assert problems >= 1, f"a deleted {kind} file passed doctor"
    assert first is not None and folder.name in first


def test_a_truncated_file_fails_the_real_doctor_verb(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """End to end through the process boundary: the exit code moves."""
    _config, folder = rich_folder(ccw_env, tmp_path)
    path = targets(folder)["tool-result"]
    path.write_bytes(path.read_bytes()[:-1])
    result = run_ccw(["doctor"], ccw_env)
    assert result.code != 0, result.out
    assert folder.name in result.out, result.out


# ---------------------------------------------------------------------------
# 3. THE ACCEPTED TRADE-OFF: a same-size change passes doctor, the full check sees it
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", KINDS)
def test_a_same_size_change_passes_doctor_but_the_full_check_catches_it(
    ccw_env: dict[str, str], tmp_path: Path, kind: str
) -> None:
    config, folder = rich_folder(ccw_env, tmp_path)
    path = targets(folder)[kind]
    before = path.stat().st_size
    flip_one_byte(path)
    assert path.stat().st_size == before

    _checked, problems, _pending, _first = doctor._desync(config)  # pyright: ignore[reportPrivateUsage]
    assert problems == 0, "doctor caught a same-size change: the quick path is hashing again"

    _folders, broken = doctor.desync_detail(config)
    shapes = [p.problem for _f, found in broken for p in found]
    assert any("does not match" in s for s in shapes), (
        f"the full check `ccw repair` reads missed a same-size change to the {kind}: {shapes}"
    )


# ---------------------------------------------------------------------------
# 4. `ccw repair` still hashes
# ---------------------------------------------------------------------------


def test_repair_acts_on_a_hash_only_corruption(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The render repair would run is replaced by a recorded failure, so the test
    pins DETECTION: repair names the folder and exits non-zero."""
    _config, folder = rich_folder(ccw_env, tmp_path)
    flip_one_byte(targets(folder)["tool-result"])
    renders: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        renders.append(args)
        return subprocess.CompletedProcess(args, 1, "", "render refused (test)")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_cli(["repair"])

    assert len(renders) == 1, f"repair did not act on a hash-only corruption: {result.out!r}"
    assert result.code != 0
    assert folder.name in result.out + result.err


def test_repair_is_quiet_about_a_healthy_rich_folder(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Control for the test above: the same fixture untouched gives repair nothing to do."""
    rich_folder(ccw_env, tmp_path)
    renders: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        renders.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_cli(["repair"])
    assert result.code == 0, result.err
    assert renders == []


# ---------------------------------------------------------------------------
# 5. a record with no recorded size is still checked, by hash
# ---------------------------------------------------------------------------


def strip_bytes(folder: Path) -> None:
    """A manifest written before records carried `bytes`."""
    manifest = manifest_of(folder)
    for key in ("subagents", "tool_results"):
        for record in cast(list[dict[str, object]], manifest[key]):
            del record["bytes"]
    for key in ("prompts", "custom_title"):
        del cast(dict[str, object], manifest[key])["bytes"]
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def test_a_record_without_a_size_passes_when_healthy(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    config, folder = rich_folder(ccw_env, tmp_path)
    strip_bytes(folder)
    assert doctor._desync(config)[1] == 0, "a healthy folder with an older manifest FAILed"  # pyright: ignore[reportPrivateUsage]


@pytest.mark.parametrize("kind", ("sub-agent", "tool-result", "prompts", "custom-title"))
def test_a_record_without_a_size_is_hashed_not_skipped(
    ccw_env: dict[str, str], tmp_path: Path, kind: str
) -> None:
    config, folder = rich_folder(ccw_env, tmp_path)
    strip_bytes(folder)
    flip_one_byte(targets(folder)[kind])
    assert doctor._desync(config)[1] >= 1, (  # pyright: ignore[reportPrivateUsage]
        f"a {kind} record with no size was skipped instead of hashed"
    )


def test_a_payload_the_catalog_has_no_size_for_is_hashed_not_skipped(tmp_path: Path) -> None:
    """The main payload's size comes from the catalog row whose hash the manifest
    names. With no such row the quick check falls back to the hash."""
    from cc_warehouse.render import RenderOptions

    folder = archive.write_session_folder(
        tmp_path, "widget", basic_session(session_id=UUID_A), RenderOptions(), ZONE
    ).directory
    payload = archive.sole_jsonl(folder)
    assert payload is not None
    meta = parser.parse_session(payload.read_bytes())
    known = archive.KnownPayload(meta.session_uuid, meta.first_ts, meta.hidden, {})
    assert archive.verify_folder(folder, ZONE, known=known) == []
    flip_one_byte(payload)
    shapes = [p.problem for p in archive.verify_folder(folder, ZONE, known=known)]
    assert "JSONL does not match manifest source_hash" in shapes, shapes


# ---------------------------------------------------------------------------
# 6. hidden: the catalog's flag, no parse
# ---------------------------------------------------------------------------


def warmup_session(session_id: str) -> bytes:
    return jsonl(
        entry("user", "Warmup", "2026-01-05T10:00:00.000Z", session_id=session_id),
        entry("assistant", "ok", "2026-01-05T10:00:05.000Z", session_id=session_id),
    )


def test_a_hidden_session_is_judged_by_the_catalog_without_a_parse(
    ccw_env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive_root = tmp_path / "archive"
    configure(ccw_env, archive_root)
    write_transcript(ccw_env, warmup_session(UUID_W), session_id=UUID_W)
    assert run_ccw(["sweep", "--quiet"], ccw_env).code == 0
    folder = next(archive.walk_folders(archive_root))
    assert not (folder / "manifest.json").exists(), "fixture precondition: hidden, unrendered"
    age_capture(ccw_env, UUID_W)
    config = Config(
        root=warehouse_root(ccw_env), archive_root=archive_root, archive_timezone=ZONE
    )
    reads = Reads(folder)
    reads.install(monkeypatch)
    assert doctor._desync(config) == (1, 0, 0, None)  # pyright: ignore[reportPrivateUsage]
    assert reads.parses == 0 and reads.hashes == 0 and reads.opened == []

