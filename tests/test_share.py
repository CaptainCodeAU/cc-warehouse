"""Oracle tests: ccw share static-site export (slice 11).

Contract: DESIGN section 9 (share-time sanitization on copies, redaction
report listing every hit, secret-shaped strings abort with findings unless
--allow-findings, personal overrides ignored, one renderer); rule R4 (store
and personal projections stay full fidelity).

Frozen here (Phase 2): the redaction report is <out>/redaction-report.json.
"""

import hashlib
import json
from pathlib import Path
from typing import cast

from conftest import (
    basic_session,
    catalog_rows,
    hook_payload,
    jsonl,
    rich_session,
    run_ccw,
    warehouse_root,
    write_transcript,
)


def capture_and_short(env: dict[str, str], data: bytes, **kwargs: str) -> str:
    transcript = write_transcript(env, data, **kwargs)  # type: ignore[arg-type]
    result = run_ccw(["hook"], env, stdin=hook_payload(transcript, cwd=None))
    assert result.code == 0, result.err
    digest = hashlib.sha256(data).hexdigest()
    rows = cast(
        list[tuple[object, ...]],
        catalog_rows(env, "SELECT short FROM session WHERE hash = ?", [digest]),
    )
    return f"s:{cast(str, rows[0][0])}"


def out_texts(out: Path) -> dict[Path, str]:
    return {
        p: p.read_text(errors="replace")
        for p in out.rglob("*")
        if p.is_file() and p.suffix in {".html", ".md"}
    }


def test_share_sanitizes_builtins_and_custom_patterns_on_copies_only(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    home = ccw_env["HOME"]
    root = warehouse_root(ccw_env)
    root.mkdir(parents=True, exist_ok=True)
    (root / "config.toml").write_text('[share]\nredact_patterns = ["SECRETPROJ"]\n')

    from conftest import entry

    data = jsonl(
        entry(
            "user",
            f"My files live in {home}/notes and I am alice@example.com on SECRETPROJ",
            "2026-01-05T10:00:00.000Z",
        ),
        entry("assistant", "Understood.", "2026-01-05T10:00:05.000Z"),
    )
    short = capture_and_short(ccw_env, data)
    assert run_ccw(["build"], ccw_env).code == 0

    out = tmp_path / "site"
    result = run_ccw(["share", short, "--out", str(out)], ccw_env)
    assert result.code == 0, result.err

    shared = out_texts(out)
    assert shared, "share produced no pages"
    for path, text in shared.items():
        assert home not in text, f"home dir leaked into {path}"
        assert "alice@example.com" not in text, f"email leaked into {path}"
        assert "SECRETPROJ" not in text, f"custom pattern leaked into {path}"

    report = cast(
        list[dict[str, object]], json.loads((out / "redaction-report.json").read_text())
    )
    assert report, "redaction report is empty despite hits"
    for hit in report:
        assert {"pattern", "file", "line", "replacement"} <= set(hit)

    # Full fidelity stays: the store object and the personal projections.
    digest = hashlib.sha256(data).hexdigest()
    stored = root / "objects" / digest[:2] / f"{digest}.jsonl"
    assert b"alice@example.com" in stored.read_bytes()
    personal = "".join(
        p.read_text(errors="replace")
        for p in (root / "projections").rglob("*.md")
    )
    assert "alice@example.com" in personal


def test_share_aborts_on_secret_shaped_strings(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """DESIGN section 9: secret-shaped strings are detected but never
    auto-redacted; they abort the share with findings, --allow-findings
    overrides and ships the string untouched."""
    from conftest import entry

    token = "sk-ant-api03-" + "a1" * 20
    data = jsonl(
        entry("user", f"my key is {token}", "2026-01-05T10:00:00.000Z"),
        entry("assistant", "Noted.", "2026-01-05T10:00:05.000Z"),
    )
    short = capture_and_short(ccw_env, data)
    out = tmp_path / "site"
    result = run_ccw(["share", short, "--out", str(out)], ccw_env)
    assert result.code != 0
    assert not out_texts(out), "share wrote pages despite secret findings"

    result = run_ccw(["share", short, "--out", str(out), "--allow-findings"], ccw_env)
    assert result.code == 0, result.err
    combined = "".join(out_texts(out).values())
    assert token in combined, "secret was auto-mangled; it must ship verbatim"


def test_share_ignores_personal_render_overrides(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    """DESIGN section 9: shared compact variants are always reminder-free and
    shared full variants always collapse reminders, regardless of config."""
    root = warehouse_root(ccw_env)
    root.mkdir(parents=True, exist_ok=True)
    (root / "config.toml").write_text(
        '[render]\nreminders_compact = "show"\nreminders_full = "show"\n'
    )
    short = capture_and_short(ccw_env, rich_session())
    out = tmp_path / "site"
    result = run_ccw(["share", short, "--out", str(out)], ccw_env)
    assert result.code == 0, result.err
    compacts = {
        p: t for p, t in out_texts(out).items() if "compact" in p.name
    }
    assert compacts, "share produced no compact variants"
    for path, text in compacts.items():
        assert "secret internal reminder text" not in text, f"reminder leaked into {path}"


def test_multi_session_share_gets_one_index(
    ccw_env: dict[str, str], tmp_path: Path
) -> None:
    uuid_b = "eeeeeeee-1111-2222-3333-444444444444"
    short_a = capture_and_short(ccw_env, basic_session())
    short_b = capture_and_short(
        ccw_env,
        basic_session(cwd="/home/alice/projects/gadget", session_id=uuid_b),
        encoded_dir="-home-alice-projects-gadget",
        session_id=uuid_b,
    )
    out = tmp_path / "site"
    result = run_ccw(["share", short_a, short_b, "--out", str(out)], ccw_env)
    assert result.code == 0, result.err
    assert (out / "index.html").exists()
