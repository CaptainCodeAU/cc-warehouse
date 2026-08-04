# Ticket 28: backlog, recorded so nothing is silently dropped

Not a slice. A register of everything named during the 2026-08-03 investigation
that is real but not on the ticket 22-27 critical path. Items graduate out of
here into their own ticket when they are taken up.

## Worth doing, small

- **28.1  `--open`.** Open the generated HTML in a browser. `notify.py:132`
  `open_folder` reveals the FOLDER; there is no equivalent for the page. The
  specimen had `--open` on four verbs. This is the difference between handing
  someone a directory and handing them their transcript.

- **28.2  Optional secret redaction on personal projections.** `ccw` redaction
  lives only in `share.py`; `build.py`, `render.py` and `capture.py` contain
  none, so personal projections are written unscrubbed. The retired
  `export_transcript.sh:18-19` scrubbed `github_pat_` and `gh[posru]_` from
  every file it generated. Defensible either way; currently inherited rather
  than decided.

- **28.3  `--limit` on sweep.** Useful for exercising a slice of a large import.

## Recorded, low value, not planned

- **28.4  `--repo` override.** `parser.detect_github_repo` auto-detects and has
  not failed. The specimen exposed a manual override.
- **28.5  Interactive session picker (`local`).** `ccw status` lists and
  `ccw render --session` renders; nothing joins them.
- **28.6  URL as input.** `ccw render <path>` takes a local path only. Low value
  while `web` is deferred.
- **28.7  `--gist`.** Deliberately NOT wanted: `ccw share` is the better
  replacement, with redaction and a self-contained page. Recorded only because
  it was in the specimen. (A 2026-08-03 report that `ccw` might already have
  gist support was wrong: the grep was matching re-GIST-ry.)
- **28.8  `web` / claude.ai import.** Excluded from this cut by the principal.
  DESIGN names claude.ai exports as a source, so this is deferred, not dropped.

## Known defects and debts

- **28.21  `project.json` is written by ONE verb, so the disposable-index
  guarantee has silently lapsed for 33 of 90 projects.** Measured 2026-08-05
  against the real archive, through the product's own reader rather than a
  filesystem guess:

        label dirs on disk ............ 90
        read_projects recovers ........  57      <- unchanged since 2026-08-02
        aliases recovered ............. 114      <- unchanged since 2026-08-02
        INVISIBLE to a rebuild ........  33

  MECHANISM, found in code rather than inferred: `archive.write_project_files`
  has exactly ONE caller, `cli.py` in the `ccw archive` verb. The capture path
  (`_archive_source`) and `ccw import` both create label folders and neither
  writes a sidecar, and `archive.read_projects` SKIPS a folder that has none
  (`archive.py`, "A folder with no sidecar ... is SKIPPED rather than fatal").
  So every project folder born since the last bulk `ccw archive` run is invisible
  to a catalog rebuild. The 57 and the 114 are exactly the figures ticket 19f
  recorded at migration, which is the tell: nothing has been added since.

  WHY IT MATTERS AND WHY IT IS NOT URGENT. `write_project_files`' own docstring
  says the sidecar is "what makes the catalog a DISPOSABLE INDEX rather than a
  load-bearing database", and that until it exists the rebuild claim is "a claim
  the product cannot honour, and an unhonoured guarantee is the F6 class this
  project exists to ban". That is exactly the state 33 projects are in. But NO
  DATA IS AT RISK: the sessions, their JSONL and their projections are all on
  disk, and the LABEL survives because the label is the folder name. What would
  be lost on a rebuild is `project_alias`, so a renamed project would split in
  two on the next capture.

  THE CHEAP FIX IS NOT THE RIGHT FIX. Re-running `ccw archive --to` regenerates
  all 90 sidecars and is proven idempotent, but it also re-renders 19k folders
  and leaves the hole open for the next import. The fix is to write the sidecar
  on the path that creates the folder. Ties 28.10, which already lists
  "rename-then-rebuild for `project.json`" as a test gap.

  FOUND BY AUDIT, NOT BY A FAILURE, which is the argument for auditing: every
  gate was green, `ccw archive --verify` reported 0 problems over the whole tree,
  and the verify does not ask this question.

- **28.20  `ccw build` is O(everything) even when nothing changed.** Measured
  2026-08-04 on the real corpus: 14,246 sessions, 0 failed, **5:55 the first
  time and 6:04 the second**, back to back with nothing changed in between. Its
  docstring promises incremental ("a session whose files already hold the
  current bytes is left mtime-stable"), and that holds for the WRITE, but every
  head is still read from the store and fully re-rendered in order to compare.
  Since ticket 25 wired `build` into the end of `ccw sweep`, this is now the
  cost of every sweep that captures anything: about six minutes of CPU on the
  daily job. Tolerable at Background/LowPriorityIO, wasteful, and it will only
  grow with the corpus. A cheap skip (source hash plus render-options hash
  recorded in the manifest) would turn it into a stat walk.

  I ESTIMATED THIS WRONG TWICE, which is why it is written down with numbers:
  first "considerably slower", then "roughly a doubling, about 50 seconds". The
  real figure is a full re-render per build, unchanged on repeat.

- **28.9  `render_html` costs 74x the payload** and emits about 6.3x its size
  (a 100 MB session projects to a 633 MB page, 7.26 GiB peak). Latent: the
  largest real page is 17.7 MiB. Measured per stage; the earlier attribution to
  a dict holding five payloads was wrong, streaming recovered 0.4 GB of 8.2.
  Documented today only in a test comment. Needs its own ticket.

- **28.10  Test gaps still open:** symlinked archive root; folder-name
  collision; ENOSPC mid-write; cross-tree reconciliation as a TEST rather than
  a hand-check; rename-then-rebuild for `project.json`.

- **28.11  Markdown and HTML for sub-agents.** Purely additive now that each
  sub-agent has its own folder: a config key, a flag, and the files appear
  beside the JSONL.

- **28.12  Re-homing an orphaned sub-agent when its parent arrives.**
  Unreachable today (0 orphans) and it collides with R4 as amended: moving a
  JSONL means deleting one. It would have to join R4's closed list.

- **28.13  Architecture board 41+ commits stale**, pinned at `1517bba`. `src/`
  has gained a module since, so its line refs have drifted. `/architecture`
  owns it.

- **28.14  `prefers-color-scheme` for shared pages.** Named v1.1 candidate
  (DESIGN 15, 2026-07-24). Needs a light palette designed and the highlight.js
  token colours re-checked for contrast.

- **28.15  SSH key drops out of the agent repeatedly** (twice on 2026-08-03).
  Worth making survive a lock.

## If the repository goes public

Separate track, not on the ticket 22-27 path. Audit run 2026-08-03: the working
tree is clean (0 hits for the username, no personal paths, no emails, no
secret-shaped strings, no data files tracked, 127 files).

- **28.16  The root commit carries a personal email.** `063a499` "Initial
  Commit", `<redacted>`, an ancestor of master; the other 156
  commits use the noreply identity. A 2026-07-20 principal ruling left it,
  reasoning that "the address is already public in the remote's records so a
  rewrite cannot un-publish it". THAT PREMISE IS NOW FALSE: the repo returns
  HTTP 404 unauthenticated, so it is not public and going public would expose
  the address for the first time. The ruling deserves re-taking on the corrected
  fact. Not re-proposing the rewrite; reporting that its basis changed.

- **28.17  Session trailers become public.** 156 commits carry `C-Sess-Id` and
  `C-Web-Id`: 15 distinct session UUIDs and 16 distinct `claude.ai/code/session_…`
  URLs. The URLs need the owner's login, so this is not a data leak, but it does
  publish a map from commits to private sessions. `C-Wt-Path` uses the tilde
  form and leaks no username.

- **28.18  Claim the PyPI name.** `cc-warehouse` returns HTTP 404 on PyPI, so it
  is unclaimed. Claiming it also closes the squatting risk behind ticket 24.2:
  today a hook written `uv tool run cc-warehouse` would fail loudly, but if
  someone registers the name it would silently run their code with the session
  payload on stdin. This is the exact failure that hit the old plugin, where the
  colliding package happened to be harmless.

- **28.19  Move the plugin into this repo.** `plugins/<name>/` plus a root
  `.claude-plugin/marketplace.json`. Documented and normal: Anthropic's own
  `anthropics/claude-code` carries a marketplace manifest at its root while
  being a software project. Removes the cross-repo drift that caused the
  ten-day outage. Note the plugin name is an immutable slug once published, so
  the final name must be chosen before the first publish, and PolyForm
  Noncommercial may sit awkwardly with a community-marketplace submission.
