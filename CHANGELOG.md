# Changelog

All notable changes to cc-warehouse.

**THE "no releases" NOTE THAT STOOD HERE IS SUPERSEDED (2026-08-09).** It read "There
have been no releases, and none are planned for now" and "nothing is on PyPI", on a
2026-07-24 ruling. `cc-warehouse` 0.1.0 was published to PyPI on 2026-08-09 by a later
principal ruling, so both statements are now false and are replaced rather than left to
mislead the next reader.

This file therefore carries two kinds of entry, and they are not the same thing:

- **Releases**, below, are versions anyone can install with `uv tool install cc-warehouse`.
- **Build milestones** are annotated git tags (`slice-01` .. `slice-17`, `ticket-18` ..
  `ticket-26`) recording how the software was built. They are not installable versions.

Each tag's own annotation carries the full record; `git show <tag>` is the primary source.
The per-slice retros live in `contract/HARNESS.md` section 8, and the decisions in
`contract/DESIGN.md` section 15.

---

## Releases

### 0.1.2 - 2026-08-18

**Bug fix.** `ccw doctor`'s `hook` check could report the wrong hook as "the
SessionEnd capture hook" and say ok for it.

- `_hook_commands` walked every event key in `hooks{}`, not just `SessionEnd`,
  and `diagnose()` labelled whichever command it found FIRST. An unrelated
  SessionStart command that merely contains the substring "ccw" (a monitoring
  script named `ccw-watch`, say) outranked the real plugin-registered
  SessionEnd hook, because settings.json is scanned before plugin
  `hooks.json` files and its own key order can put SessionStart first. The
  `hook` check would then say ok for the wrong command -- a false green that
  survives the real capture hook being removed entirely. Found 2026-08-18,
  while adding an unrelated SessionStart watcher to a machine already running
  cc-warehouse. `_hook_commands` is now scoped to the `SessionEnd` key only,
  in both settings files and plugin `hooks.json` files. Regression test:
  `test_a_ccw_looking_command_in_another_event_is_not_claimed_as_the_hook`.

### 0.1.1 - 2026-08-09

**Metadata only. No behaviour changed, and no file under `src/` differs from 0.1.0.**
The sole reason this version exists is that PyPI freezes a project's description into
each release, so a rewritten README cannot reach the project page without a new version.

- The README is now written for a reader rather than for the build. It had accumulated
  into a build journal: slice numbers, milestone tags, an exit-review paragraph and a
  self-documented overclaim, with the reader's first question answered last. The build
  record was not deleted, it was left where it belongs, in this file and in `contract/`.
- README links are absolute GitHub URLs. The README doubles as the PyPI
  `long_description`, and PyPI does not resolve relative links, so `](LICENSE)` rendered
  as a dead link on the project page.
- Packaging metadata gained `urls`, `keywords` and classifiers. No `License ::`
  classifier is present on purpose: PEP 639 forbids pairing one with `License-Expression`,
  and `OSI Approved` would additionally be untrue of PolyForm Noncommercial.

### 0.1.0 - 2026-08-09

First publication. The distribution name was unclaimed until this release, which is
itself part of the point: `ccw hook` runs at session end with a transcript on stdin, so
an unclaimed name on a public index is a squatting target. Claiming it closes that.

The sdist ships the contract documents and the harness tickets alongside the code, which
is deliberate. Nothing in it is a credential, and a pre-publication audit of all 1417 git
objects plus the built artifact found no keys, no account name, no machine name and no
personal paths.

---

## Unreleased

### v1.1 flag groups, closed 2026-08-01

The four deferred flag groups, each landing the day it was defined: the per-variant
content matrix (`slice-14`), the HTML chrome initial states plus date locale
(`slice-15`), an opt-in truncation cap (`slice-16`), and a `--since`/`--until` window on
`share` and `sweep` (`slice-17`). Named one by one rather than as a range: the currency
sweep checks that every real tag is named here, and a range satisfies a reader while
leaving the probe correct to complain. A byte-for-byte regression
anchor at `tests/golden/matrix-anchor` pins the four projected files under default
options, so any slice that moves DEFAULT output breaks it on purpose; it has moved twice,
both times by a recorded ruling with the delta measured first.

### Real-data coverage, 2026-08-02 (`ticket-18`, `ticket-20`)

A census of a real 13,836-session corpus found that the suite had been proving the
product against inputs someone imagined rather than inputs that exist.

- **`ticket-18`** Eight entry types and three content-block types rendered nothing and
  incremented no counter: 62,577 entries with `loss: 0` recorded beside them. All of them
  now surface, `result` keeps a sub-agent's returned work in full, `custom-title` outranks
  the model's `ai-title`, and anything the parser does not name renders a marker AND
  increments a new top-level `unrecognised` manifest key. That last part is the durable
  half: the previous census ran once, and Claude Code's format kept moving after it.
- **`ticket-20`** 41,458 of 43,060 thinking blocks arrive empty, because the text stopped
  reaching the JSONL upstream at Claude Code v2.1.69 and it is a model property, not a
  date one. The count now folds into the phase caption the transcript already prints, a
  top-level `withheld` manifest key records it, and `--thinking-withheld` lets the
  operator overrule the display.

### Archive-first layout, 2026-08-02 (`slice-19d`, `slice-19f`)

Six of seven slices. One self-contained folder per session holding the raw JSONL beside
its projections, named `<YYYYMMDD-HHMMSS><offset>_<uuid>` in a config-pinned zone so the
same session yields the same folder on any machine and the migration is idempotent.
`ccw archive` builds or `--verify`s it; `project.json` per project makes the catalog a
genuinely disposable index. Run on the real corpus: 13,829 folders in six minutes, zero
failures, verified with zero problems. **Nothing has been swapped.**

### v1, closed 2026-07-24

Every slice in the `contract/DESIGN.md` section 16 build order landed and carries its
milestone tag. Gates: ruff clean, pyright strict 0 errors, 403 tests, zero stubs.

**Capture and storage**

- Content-addressed immutable object store; identity is sha256 of the payload, never a
  size, a path or a timestamp. Every write is tmp-file plus `os.replace`.
- SQLite catalog and a registry where projects are stable IDs and paths are time-stamped
  alias claims, so a repo move is a metadata edit rather than lost history.
- `ccw hook` (SessionEnd capture), `ccw sweep` (anything the hook missed), `ccw migrate`
  (one-shot legacy import, plus a separate consent-gated `--retire`).

**Rendering**

- Four files per session: `transcript.md`, `transcript.compact.md`, `conversation.html`,
  `conversation.compact.html`, plus a `manifest.json` recording the settings and counts
  that produced them.
- Full exporter-v8.10.1 chrome and complete Claude Code entry-type coverage: ai-title
  titles, sub-agent phases, attachments, slash commands, structured tool output and the
  informational extras, each an independent toggle.
- The HTML copy-as-markdown payloads are byte-equal to the markdown fragments, so the two
  exports cannot drift apart.

**Publishing**

- `ccw share` builds a sanitized static site from copies. Redaction runs on the decoded
  payload; secret-shaped strings abort the share rather than being silently mangled.
  See `docs/sharing-and-redaction.md`.
- Shared pages inline highlight.js and make **no third-party requests**; personal
  projections keep the CDN reference for exporter parity.
- `--EXPOSED` is the one sanctioned unscrubbed publish, gated by a scrubbed-versus-exposed
  comparison, a typed confirmation, and a non-TTY abort.

**Repair and inspection**

- `ccw relocate` repairs the external world after a repo move: plan, backup, apply, verify,
  report, with dry-run as the default.
- `ccw project` (list / show / rename / move / merge), `ccw status`, `ccw verify`,
  `ccw build`, `ccw render`.

**Configuration**

- Two-file layering (XDG then data-root), per-project sections keyed by registry ID,
  `CCW_*` environment variables, and CLI flags, in that precedence order.
  `--no-config` and `--config PATH` bypass the files.

### Build milestones

| Tag         | Date       | What landed                                                      |
| ----------- | ---------- | ---------------------------------------------------------------- |
| `slice-01`  | 2026-07-18 | store module (the harness trial run)                             |
| `slice-02`  | 2026-07-18 | catalog + registry: transactional catalog, claims-based registry |
| `slice-03`  | 2026-07-18 | parser + conversation model                                      |
| `slice-04`  | 2026-07-18 | capture hook + notify                                            |
| `slice-05`  | 2026-07-18 | sweep: capture what the hook missed, orphan adoption             |
| `slice-06`  | 2026-07-18 | transcript.md emitters, full and compact                         |
| `slice-07`  | 2026-07-19 | HTML emitters, full and compact, plus the manifest               |
| `slice-08`  | 2026-07-19 | build/render orchestration; un-stubs the render child            |
| `slice-09`  | 2026-07-19 | status and `ccw verify`                                          |
| `slice-10`  | 2026-07-19 | migrate and retire                                               |
| `slice-11`  | 2026-07-19 | share and redaction                                              |
| `slice-12a` | 2026-07-23 | relocate containers and registry claims                          |
| `slice-13`  | 2026-07-23 | config layering, CLI/help surface, content flags, `--EXPOSED`    |
| `slice-12b` | 2026-07-24 | relocate content rewriting                                       |

`slice-12` has no tag by design: it escalated on 2026-07-19 as the build's only
non-converging loop and was split into 12a and 12b. Its ticket is kept as SUPERSEDED for
the record.

### Notable during v1

- **The v1 exit review found two gaps no test could.** It reconciled the contract against
  the code rather than against the tickets: `ccw project` was implemented one subcommand of
  five (which silently broke per-project configuration, since that feature is keyed by an ID
  only `ccw project show` prints), and the dispatcher accepted an undocumented internal
  verb. Both fixed; the internal-verb concept is now sanctioned and documented.
- **Relocate was the one slice to escalate**, and closing it turned up defects worse than
  their tickets described: a symlinked warehouse or `~/.claude` let it rewrite an immutable
  stored object and a captured transcript, and its backups were produced by a
  locale-dependent, newline-translating read that corrupted a CRLF file and its own backup
  while reporting success. Backups are now proven byte-exact before an original is eligible
  to be touched.
- **A private config reader in three modules** meant `[relocate] roots` and
  `[share] redact_patterns` declared in the XDG tier were ignored. In share that was a
  publish-path leak: a redaction rule the operator set was silently dropped and the content
  it named was published.
