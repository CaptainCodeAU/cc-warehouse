"""Contract-derived regression tests for status/verify (slice 9, post-review). NOT
the frozen oracle (tests/test_status_verify.py); these pin the reviewer clusters the
oracle did not cover. Cited in ticket 09.

- RT-VERIFY-CRASH (F7/R5): verify must REPORT a malformed / NULL catalog hash and keep
  going, never crash -- a poisoned catalog row must not suppress the real findings.
  [C-VERIFY-CRASH]
- RT-UNREADABLE-LABEL: an unreadable stored object is labeled "unreadable", not
  "does not match its content address". [C-UNREADABLE-LABEL]
"""

import hashlib
import stat

from cc_warehouse import catalog, status
from cc_warehouse.config import Config
from conftest import (
    basic_session,
    hook_payload,
    run_ccw,
    run_cli,
    warehouse_root,
    write_transcript,
)


def _capture_one(env: dict[str, str]) -> bytes:
    data = basic_session()
    transcript = write_transcript(env, data)
    result = run_ccw(["hook"], env, stdin=hook_payload(transcript))
    assert result.code == 0, result.err
    return data


def _insert_raw_row(env: dict[str, str], hash_val: object, short: str) -> None:
    conn = catalog.open_catalog(warehouse_root(env))
    conn.execute(
        "INSERT INTO session (hash, short, source_kind, captured_at, hidden)"
        " VALUES (?, ?, 'claude_code', '2026-01-05T12:00:00Z', 0)",
        (hash_val, short),
    )
    conn.commit()
    conn.close()


def test_verify_reports_a_non_hex_catalog_hash_without_crashing(ccw_env: dict[str, str]) -> None:
    """C-VERIFY-CRASH: a non-64-hex session.hash must be reported, not crash verify, and
    it must not suppress a genuine corrupted-object finding."""
    data = _capture_one(ccw_env)
    digest = hashlib.sha256(data).hexdigest()
    stored = warehouse_root(ccw_env) / "objects" / digest[:2] / f"{digest}.jsonl"
    stored.write_bytes(b"CORRUPTED")
    _insert_raw_row(ccw_env, "notavalidhexstring", "badshort00001")

    report = status.verify(Config(root=warehouse_root(ccw_env)))  # must not raise
    assert len(report.outcomes) >= 2  # the corrupted object AND the malformed row

    result = run_cli(["verify"])
    assert result.code != 0
    assert digest[:12] in result.out + result.err  # the real finding is not suppressed


def test_verify_reports_a_null_catalog_hash_without_crashing(ccw_env: dict[str, str]) -> None:
    """C-VERIFY-CRASH: a NULL session.hash must not crash verify's sort/lookup."""
    _capture_one(ccw_env)
    _insert_raw_row(ccw_env, None, "badshort00002")
    report = status.verify(Config(root=warehouse_root(ccw_env)))  # must not raise
    assert any(o.action in {"malformed", "missing"} for o in report.outcomes)
    result = run_cli(["verify"])
    assert result.code != 0


def test_verify_labels_an_unreadable_object(ccw_env: dict[str, str]) -> None:
    """C-UNREADABLE-LABEL: an unreadable object is named 'unreadable', not a content
    mismatch."""
    data = _capture_one(ccw_env)
    digest = hashlib.sha256(data).hexdigest()
    stored = warehouse_root(ccw_env) / "objects" / digest[:2] / f"{digest}.jsonl"
    stored.chmod(0)
    try:
        result = run_cli(["verify"])
        assert result.code != 0
        assert "unreadable" in (result.out + result.err).lower()
    finally:
        stored.chmod(stat.S_IRUSR | stat.S_IWUSR)
