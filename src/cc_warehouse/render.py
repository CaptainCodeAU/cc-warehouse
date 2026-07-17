"""The 4-file projection emitters (slices 6-7). DESIGN section 6; SPEC sections 6-7.

One parser-produced conversation model feeds all emitters; the emitters take the raw
payload so tests stay black-box.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class RenderOptions:
    reminders_full: str = "collapse"  # collapse | strip | show (personal override only)
    reminders_compact: str = "strip"
    breadcrumbs: bool = False


def render_markdown(data: bytes, options: RenderOptions) -> tuple[str, str]:
    """Return (transcript.md, transcript.compact.md) contents."""
    raise NotImplementedError


def render_html(data: bytes, options: RenderOptions) -> tuple[str, str]:
    """Return (conversation.html, conversation.compact.html) contents."""
    raise NotImplementedError


def build_manifest(data: bytes, options: RenderOptions) -> dict[str, object]:
    """Per-session render manifest: config used, counts, loss telemetry, source hash."""
    raise NotImplementedError
