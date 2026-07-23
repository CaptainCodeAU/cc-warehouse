# Changelog

All notable changes to cc-warehouse.

**There have been no releases yet.** `cc-warehouse` is not published, and the version in
`pyproject.toml` is still `0.1.0`. The entries below are BUILD MILESTONES, recorded as
annotated git tags (`slice-01` .. `slice-13`, including `slice-12a` and `slice-12b`), not
versions anyone could install. The first release entry will appear here when the PyPI name
is confirmed (`contract/DESIGN.md` section 15 item 6).

Each tag's own annotation carries the full record; `git show <tag>` is the primary source.
The per-slice retros live in `contract/HARNESS.md` section 8, and the decisions in
`contract/DESIGN.md` section 15.

---

## Unreleased

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

| Tag | Date | What landed |
|---|---|---|
| `slice-01` | 2026-07-18 | store module (the harness trial run) |
| `slice-02` | 2026-07-18 | catalog + registry: transactional catalog, claims-based registry |
| `slice-03` | 2026-07-18 | parser + conversation model |
| `slice-04` | 2026-07-18 | capture hook + notify |
| `slice-05` | 2026-07-18 | sweep: capture what the hook missed, orphan adoption |
| `slice-06` | 2026-07-18 | transcript.md emitters, full and compact |
| `slice-07` | 2026-07-19 | HTML emitters, full and compact, plus the manifest |
| `slice-08` | 2026-07-19 | build/render orchestration; un-stubs the render child |
| `slice-09` | 2026-07-19 | status and `ccw verify` |
| `slice-10` | 2026-07-19 | migrate and retire |
| `slice-11` | 2026-07-19 | share and redaction |
| `slice-12a` | 2026-07-23 | relocate containers and registry claims |
| `slice-13` | 2026-07-23 | config layering, CLI/help surface, content flags, `--EXPOSED` |
| `slice-12b` | 2026-07-24 | relocate content rewriting |

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
