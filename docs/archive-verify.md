# What `ccw archive --to <dir> --verify` proves, and what it does not

Written 2026-11-28 against the code at that date. Each claim names the function it rests
on; if the code has moved, re-read those functions before trusting this page.

## Short answer

`--verify` proves that **each session folder that is in the tree agrees with its own
manifest**: the session JSONL hashes to the `source_hash` the manifest recorded, the
generated files are present, every file the manifest lists is present with its recorded
hash, and the folder's name matches the session's own uuid and start time.

It does **not** compare the archive against anything outside the tree. It does not count
sessions against the local catalog or vault, it does not compare hashes against the local
store or against `~/.claude`, and it cannot see a session folder that is missing
altogether. So it does not, today, prove the archive holds the same content as the
machine it came from.

## What it checks

The verb is `cli._run_archive`, which hands `--verify` to `cli._archive_verify`.

1. **The target must be a directory, and must hold at least one session folder.** A
   missing target exits 2 ("no archive at ..."); a tree with no session folders exits 2
   ("no session folders under ..."). Verifying nothing is never reported as a pass.
2. **Which folders it reads.** `archive.walk_folders`: exactly two levels,
   `<root>/<label>/<session>/`. Label names in `build.RESERVED_LABELS` (such as
   `_not-sessions`, `_orphaned-subagents` and the marker file) are skipped, and so are
   `_memory` and `_memory-history` inside a label (`build.RESERVED_IN_LABEL`).
3. **Each folder gets the full check**, `archive.verify_folder` with no `known` argument:
   every recorded file is read and sha256-hashed, never judged by size alone (the size
   shortcut, `archive._size_matches`, is used only by `ccw doctor`'s quick check).
   - A folder with no `*.jsonl` is a problem ("no session JSONL in the folder").
   - The JSONL is parsed for its hidden flag, uuid and first timestamp
     (`parse_session`).
   - **A hidden session** (archived on purpose without rendered pages) has only its
     folder name checked (`archive._name_problems`); nothing else in it is checked.
   - Otherwise each of the 5 generated files must exist (`archive.GENERATED_NAMES`:
     `transcript.md`, `transcript.compact.md`, `conversation.html`,
     `conversation.compact.html`, `manifest.json`).
   - The JSONL's sha256 must equal the manifest's `source_hash`.
   - Every sub-agent the manifest lists must be present and match its sha256
     (`archive._subagent_problems`).
   - Every file the manifest lists under `tool_results`, `workflows`, `file_history`,
     `todos` and `pastes` must be present and match its sha256
     (`archive._companion_problems`, over `archive.COMPANION_MANIFEST_KEYS`).
   - `prompts.jsonl` and `custom-title.json` must match their manifest records, and must
     not exist when the manifest says there is none (`archive._single_file_problems`).
   - The folder name must equal the name the session's uuid and first timestamp give in
     the zone in use (`archive._name_problems`, `build.archive_folder_name`).
4. **A folder that cannot be read** is reported as one problem and the rest are still
   checked (`cli._archive_verify`, the `read.error` branch).
5. **Exit codes**: 0 when every folder passed, 1 when any problem was found, 2 for the
   two refusals in item 1, for an unknown `--zone`, and for `--init` given with
   `--verify` (`cli._run_archive`). The last line reads `archive: <N> folders checked, <M>
   problems`.
6. **It writes nothing**, not even a marker. Pinned by
   `tests/test_archive_cli.py::test_verify_writes_nothing` and
   `tests/test_archive_root_marker.py::test_archive_verify_is_unchanged_on_an_unmarked_tree`.

## What it does not check

- **Nothing outside the tree.** No count of sessions against the local catalog, no
  hash comparison against the local vault (`objects/`) or against the source
  transcripts in `~/.claude`. `cli._archive_verify` takes only the target and a zone.
- **A missing session folder.** The walk visits only folders that exist, so a session
  that was never written, or whose whole folder was removed, is not reported.
- **A consistent rewrite.** The JSONL is checked against the manifest in the same
  folder. If both were rewritten together (for example, by a faulty writer that wrote a
  wrong payload and its matching manifest), the folder passes.
- **The content of the rendered pages.** The 4 markdown and HTML files are checked for
  presence only, not hashed.
- **Files the manifest does not list.** An extra file in a sidecar folder is not
  reported; only `prompts.jsonl` and `custom-title.json` are checked in that direction.
  A manifest that predates a companion key yields no check for that key at all.
- **Hidden sessions' companions.** Only the name of a hidden session's folder is checked,
  so its sub-agents and sidecar files are never hash-verified.
- **A folder with more than one JSONL.** The first in sorted order is taken as the
  session (`archive._sole_jsonl`); the others are not checked.
- **`project.json`, `_not-sessions/`, `_orphaned-subagents/`, `_memory/` and
  `_memory-history/`.** All are skipped by the walk (item 2 above).
- **The root marker.** `--verify` does not read `_archive-root.json`. The zone comes from
  `--zone`, or else from the config's `archive_timezone`, never from the marker
  (`cli._run_archive`). Run it with the wrong zone and every folder name is reported as a
  problem.

## Related checks that are not `--verify`

- `ccw verify` with no arguments checks the archive only when `keep_objects = false`
  and `archive_root` is set (`cli._run_verify`). With `keep_objects = true`, as on a
  machine whose archive is on a share mounted only during its sweep, it checks the vault
  and the catalog instead (`status.verify`), and not the archive.
- `ccw doctor`'s desync check runs the quick depth of the same function on the 25
  catalog heads with the latest session start times (not capture times), and fails on a
  catalog row whose folder is missing (`doctor.py`'s sample, and
  `tests/test_archive_root_marker.py::
  test_doctor_fails_on_a_catalog_row_whose_folder_is_missing`). `ccw repair` runs the
  same sample at full depth and re-renders what it finds. These two are the only checks
  that report from the catalog towards the archive, and only for those 25.
- `ccw archive --to <dir>` and `ccw build` do compare every catalog row with its folder,
  but only to decide what to write; they fix a gap rather than report it.

## What proving content would take (not built)

To show the archive holds what the machine holds, a check would compare the local
catalog's heads (each session uuid and its payload sha256) with the archive: one folder
per head, and each folder's `source_hash` equal to the head's sha256. It would report
heads with no folder and folders whose hash differs. Nothing in `ccw` does this whole-tree
comparison today.
