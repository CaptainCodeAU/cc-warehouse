"""Oracle tests: page drawing has its own version number (record #1646).

Contract: DESIGN section 15, "2026-11-22 - page drawing gets its own version"
(principal's ruling, cc-warehouse-main Q8: A: "Give page drawing its own version
number, changed only when pages change; a new release then redraws nothing.").

Before this, a folder's `renderer_version` was the PACKAGE version, so every
release made every archive folder look stale and the next build redrew all of
them, page output changed or not. Now `render_version.RENDER_VERSION` is a
hand-set literal, and the fence below is what stops it being forgotten: if the
pinned page output moves while the number does not, the suite fails.

What the fence sees, stated so nobody reads it as more: the four files of the
matrix anchor (`tests/golden/matrix-anchor`, the full and compact markdown and
HTML, which move only by a recorded ruling in `tests/test_matrix.py`) plus the
manifest `render.build_manifest` writes for the anchor's own session, minus its
`renderer_version` key. It does NOT see the manifest keys `archive.py` adds
beside a folder (sub-agents, sidecars, prompts) or output only non-default
options reach. A change there that should redraw folders still needs a hand bump.
"""

import hashlib
import json
from pathlib import Path

import pytest

import cc_warehouse
from cc_warehouse import archive, render, render_version, store
from cc_warehouse.render import RenderOptions
from conftest import matrix_session

GOLDEN = Path(__file__).resolve().parent / "golden" / "matrix-anchor"
ANCHOR_FILES = (
    "transcript.md",
    "transcript.compact.md",
    "conversation.html",
    "conversation.compact.html",
)

# Re-record BOTH values together, and only when page output changed on purpose:
# bump RENDER_VERSION in src/cc_warehouse/render_version.py, then paste the new
# digest the failing test prints. Recording a new digest without a new number
# is the one thing this pin exists to stop.
RECORDED_RENDER_VERSION = "0.1.4"
RECORDED_PAGE_DIGEST = "8c5776868a3e27da1c9050c1b755826b051bb10e25a6ea33c9d945491aac0ee9"


def page_digest() -> str:
    """sha256 over the anchor's four files and its manifest minus the version key."""
    digest = hashlib.sha256()
    for name in ANCHOR_FILES:
        digest.update(name.encode() + b"\0" + (GOLDEN / name).read_bytes() + b"\0")
    manifest = render.build_manifest(matrix_session(), RenderOptions())
    manifest.pop("renderer_version")
    digest.update(json.dumps(manifest, sort_keys=True).encode())
    return digest.hexdigest()


def test_page_output_and_render_version_move_together() -> None:
    produced = page_digest()
    if produced == RECORDED_PAGE_DIGEST:
        assert render_version.RENDER_VERSION == RECORDED_RENDER_VERSION, (
            "RENDER_VERSION moved but page output did not: every archive folder "
            "would be redrawn for nothing. Put RENDER_VERSION back."
        )
        return
    assert render_version.RENDER_VERSION != RECORDED_RENDER_VERSION, (
        "page output changed: bump RENDER_VERSION and re-record the fingerprint "
        f"(new digest {produced})"
    )
    pytest.fail(
        "RENDER_VERSION was bumped; now re-record RECORDED_RENDER_VERSION = "
        f"{render_version.RENDER_VERSION!r} and RECORDED_PAGE_DIGEST = {produced!r}"
    )


def test_the_first_render_version_is_the_installed_release() -> None:
    """Every live folder was drawn by 0.1.4 and is stamped "0.1.4". Starting
    the new number anywhere else would redraw all of them on the first run,
    which is the exact cost the ruling removes."""
    assert render_version.RENDER_VERSION == "0.1.4"


def test_render_version_is_a_literal_not_the_package_version() -> None:
    source = Path(render_version.__file__).read_text(encoding="utf-8")
    assert "__version__" not in source
    assert "import" not in source
    assert isinstance(render_version.RENDER_VERSION, str)


def test_manifest_stamps_the_render_version() -> None:
    manifest = render.build_manifest(matrix_session(), RenderOptions())
    assert manifest["renderer_version"] == render_version.RENDER_VERSION


def test_a_new_package_version_alone_leaves_folders_current(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ruling's point: a release that draws pages the same redraws nothing."""
    data = matrix_session()
    result = archive.write_session_folder(
        tmp_path, "widget", data, RenderOptions(), "Australia/Melbourne",
        fallback_stem="session",
    )
    for module in (cc_warehouse, render, archive):
        monkeypatch.setattr(module, "__version__", "9.9.9", raising=False)
    assert archive.folder_is_current(result.directory, store.sha256_hex(data), RenderOptions())
    assert archive.pages_are_current(result.directory, store.sha256_hex(data), RenderOptions())


def test_a_new_render_version_makes_folders_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = matrix_session()
    result = archive.write_session_folder(
        tmp_path, "widget", data, RenderOptions(), "Australia/Melbourne",
        fallback_stem="session",
    )
    monkeypatch.setattr(render_version, "RENDER_VERSION", "0.1.5")
    assert not archive.folder_is_current(
        result.directory, store.sha256_hex(data), RenderOptions()
    )
