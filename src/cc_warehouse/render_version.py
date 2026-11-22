"""The version of page drawing, kept apart from the package version.

Every archive folder's `manifest.json` carries this as `renderer_version`, and
`archive.folder_is_current` redraws a folder whose stamp differs. It used to be
the package version, so every release redrew every folder, pages changed or not.
Principal's ruling, 2026-11-22 (cc-warehouse-main Q8: A): "Give page drawing its
own version number, changed only when pages change; a new release then redraws
nothing." DESIGN section 15 has the entry.

Bump it by hand when, and only when, page output changes on purpose.
`tests/test_render_version.py` fails when the pinned page output moves and this
number does not. It started at "0.1.4", the release that drew every live folder,
so no folder redraws because of this change.

Leaf module on purpose: it holds one literal and nothing else.
"""

RENDER_VERSION = "0.1.4"
