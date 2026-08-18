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

- **28.22  Fence `ccw doctor`'s text output.** Recorded 2026-08-18 (ticket 30's
  Appendix, deployment facts from outside this repo). `~/.local/bin/ccw-watch`
  (a different repo, `fifty-shades-of-dotfiles`) runs `ccw doctor` at every
  Claude Code SessionStart on this machine and parses it with a regex: the
  `hook` line's wording, and the `Uncaptured: N session(s)` figure. Nothing in
  this repo's own suite protects that shape today, so a reformat would break
  an external consumer with no test here going red to say so. An oracle test
  pinning the exact substrings a known-external parser depends on (not the
  whole output, which would over-constrain wording changes that do not touch
  the parsed parts) turns that into a fence instead of a surprise.

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

- **28.21  DONE 2026-08-05. The sidecar is now written by whatever CREATES the
  folder, so 27.4's prerequisite is met.** `capture._archive_project_file`
  refreshes the one project's `project.json` after its session lands, which
  covers the hook, `ccw sweep` and `ccw import` in one place because all three
  route through `capture.capture_transcript` (verified by running each, not
  assumed). `archive.write_project_files` keeps its behaviour and now LOOPS over
  the same single-project writer, so there is one sidecar renderer rather than
  two (R9/F8).

  THE SKIP IS LOAD BEARING, NOT TIDINESS. An unchanged sidecar is not rewritten,
  compared on CONTENT and never on existence, or a 4,756-payload import would
  rewrite one project's sidecar thousands of times. Cost measured on the real
  catalog rather than asserted, against the worst case (1,449 aliases, a 137 KB
  sidecar): `project_record` 0.89 ms, `write_project_file` no-op 0.70 ms, so
  about **1.6 ms added to a capture** whose hook timeout is 40 s.

  A SIDECAR FAILURE NEVER COSTS A CAPTURE, and that is the opposite of the
  payload write beside it. `_archive_source` raises when `keep_objects` is false
  because then nothing else holds the session; a sidecar is an index aid, so it
  gets its own try and is never re-raised (DESIGN 12). There is a test that
  makes the write fail and asserts the session still lands.

  THE PROOF IS THE ROUND TRIP THAT COULD NOT PASS BEFORE: capture only, `ccw
  archive` never run, delete the catalog, `ccw reindex`, and both labels and
  aliases come back. The fixture asserts it stored aliases FIRST, because a
  round trip over an empty set passes for the wrong reason (19f's lesson).

  A THIRD FENCE FIRED. R8's `test_guarantee_words_cite_their_proving_test`
  caught "byte-identical" in the new docstring. The word is load bearing (it is
  what the skip rests on) and it IS proven, so the proof registry gained an
  entry naming the test rather than the docstring being reworded to dodge the
  check. The registry's own comment says it "grows when a guarantee is added".

  **THE LIVE ARCHIVE WAS BROUGHT UP TO DATE THE SAME DAY** (principal's word),
  by calling `write_project_files` directly rather than re-running the bulk verb.
  57 sidecars became 90; exactly 45 files were written and 0 non-sidecar files
  were touched; `ccw archive --verify` reads 19,235 folders, 0 problems. The
  rebuild now recovers **4,906 of 4,913 aliases, 99.9%, up from 2.3%**, and the
  7 that do not come back are the 7 workflow journals, which have no project
  folder because they are not sessions. Full figures on ticket 27 beside the
  27.2 proof they update.

  The original finding, kept for the record:

- **28.21 (as first written)  `project.json` is written by ONE verb, so the
  disposable-index guarantee has silently lapsed for 33 of 90 projects.**
  Measured 2026-08-05
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

  **UPGRADED 2026-08-05 FROM BACKLOG ITEM TO PREREQUISITE OF 27.4, and the
  number is far worse than "33 of 90 projects".** Ticket 27.2's rebuild of the
  real archive recovered **114 of 4,913 aliases, 2.3%**. The project COUNT
  understated it badly: the 33 sidecar-less folders are not 33/90 of the aliases,
  because almost every alias learned since the 2026-08-02 bulk run lives only in
  the database. Sessions and labels round trip perfectly (19,233 of 19,233
  hashes, 90 of 90 labels); aliases do not. 27.4 deletes `objects/` on the
  argument that the archive is a complete substitute, and on aliases it is not.
  The measurement is in ticket 27 beside the rest of the 27.2 proof.

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

  **STILL OPEN, but the pattern it proposed now exists elsewhere: see ticket 30
  (2026-08-18).** `archive.folder_is_current` is exactly the "source hash plus
  render-options hash recorded in the manifest" skip suggested here, built for
  the ANALOGOUS but distinct cost on `ccw archive`'s tree (measured there:
  20779 folders, ~40 minutes, every run). It also had to check a renderer
  fingerprint and the sub-agent list, not just source hash and config - see
  that ticket if this one is picked up, both for the predicate shape and for a
  regression it found live: a naive "manifest still matches" check alone let a
  DELETED sibling file (e.g. `transcript.md`) go unrestored, which is directly
  relevant here since `build()`'s OWN per-head loop (`_read` then
  `write_projection`) is what THIS item is about and is UNCHANGED by ticket 30 -
  it still reads and fully re-renders every head, every run. `_mirror`'s call
  into `archive.write_session_folder` is now cheap when `archive_root` is
  configured; the `projections/` half this item describes is not.

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

**RESOLVED 2026-08-10. The repository IS public.** 28.16, 28.17 and 28.18 are
closed; what follows records how, and one residual the principal accepted with
its measurement, so nobody re-discovers it as a surprise.

- **28.16 CLOSED.** `git filter-repo --mailmap` rewrote the root commit's author
  and committer to the noreply identity. All 209 commits, all messages and all
  32 annotated tags survived; the HEAD tree hash was byte-identical before and
  after, which is the proof no file content moved.
- **28.17 CLOSED, then reopened by design, then closed properly.** The trailers
  were stripped, and then REGREW, because the harness stamps them on every commit
  made from a session. Proved twice by execution within minutes. The durable fix
  is not a repeated rewrite: it is `git config trailers.disable true` in this
  clone, a knob the dotfiles owner added on request, which also strips the
  appended `Claude-Session:` line. Machine-local config, so a fresh clone
  re-enables stamping and must set it again.
- **28.18 CLOSED.** `cc-warehouse` 0.1.0 published 2026-08-09, 0.1.1 on 08-10.
  The squat named below is closed: the name now serves this code.

- **28.20  RESOLVED 2026-08-10 by deleting and re-creating the repository.** The
  entry below is kept as written, because the reasoning that led to accepting the
  residual is worth reading even though the decision was reversed. WHAT CHANGED:
  the accept was taken on figures this entry gave as "one session UUID and one
  URL". Measured properly afterwards, an anonymous fetch of a single old SHA
  pulled the whole ancestry, **1804 objects**, recovering 19 distinct session
  UUIDs, 19 session URLs, the personal email 8 times, the drive name 13 times and
  the real session UUID 14 times. Both prior history rewrites had bought nothing
  against anyone holding a SHA. The "not enumerable" claim was false too: of 76
  candidate SHAs quoted in the public tree, one resolved, and it was the one this
  very entry had published.

  The repository was deleted and re-created, which destroys the server-side
  object store. Verified afterwards with the same three-way control: the current
  HEAD and its parent fetch, a bogus SHA does not, and the root commit,
  pre-rewrite-1 HEAD, pre-strip HEAD and session-start HEAD are all **gone**.
  The re-created repository reports **1474 objects, reachable == total**, so it
  holds no unreachable objects at all. One old SHA still fetches, `ad71fd4`, and
  that is correct: it is an ancestor of HEAD, whose SHA survived the trailer
  rewrite because it carried no trailer and its parents were unchanged.

  **THE DURABLE LESSON, which outlives this ticket.** A force-push does not
  delete objects; only destroying the object store does. Every verification that
  used a CLONE was true and irrelevant, because a clone fetches reachable objects
  and the problem was in the unreachable ones. The instrument could not see the
  place the problem was. Check reachability with `git fetch origin <sha>` and a
  bogus-SHA control, never with a clone.

  --- the original entry, superseded, kept for its reasoning ---

  **ACCEPTED RESIDUAL: pre-rewrite commits survive on GitHub.**
  A force-push does NOT delete the old objects. Measured 2026-08-10 with a
  three-way probe (`git fetch origin <sha>` into a scratch bare repo): the
  current HEAD fetched, a bogus SHA was refused, and the pre-strip commit
  FETCHED. The two controls disagreed, so the probe distinguishes present from
  absent; without them it proves nothing, and two earlier attempts at this
  measurement were broken instruments that looked conclusive.

  **THE PRE-STRIP SHA IS NOT WRITTEN HERE, and the first version of this entry
  got that wrong.** It quoted the full 40 characters two lines above the sentence
  arguing the risk is bounded BECAUSE an attacker would have to know them, which
  published the key beside the lock. Caught by scanning the public clone for the
  SHA and finding one hit: this file. Anyone who needs the value has the backup
  bundles, where `git bundle list-heads` prints it; it does not need to be in a
  public document to be recoverable by the person entitled to it.

  Removing it here does not remove it from this repository's history, because the
  commit that introduced it is already public. That is accepted rather than
  chased: a rewrite to erase it would leave its own unreachable-but-fetchable
  object, which is the very condition this entry documents, so the fix would
  recreate the problem one level down. What the removal does buy is that the
  current tree no longer hands the pointer to a casual reader.

  A fresh clone cannot see these, because a clone fetches only REACHABLE objects.
  That is why the "209 commits, 0 trailers" verification is true and beside the
  point, and it is the same shape of blind spot as a `git log --pretty=%(trailers:only)`
  check that reads ordinary prose as a trailer.

  **WHAT IS EXPOSED:** one session UUID and one `claude.ai/code/session_…` URL,
  in `C-Sess-Id` / `C-Web-Id` trailers across 7 pre-strip commits and one
  superseded tag object. Not credentials. Nothing to rotate. The URL requires the
  owner's login to follow. Reachable only by someone who already knows the
  40-character SHA, so not enumerable.

  **THE FIX THAT WAS AVAILABLE AND DECLINED:** delete and re-create the GitHub
  repository, which gives a new server-side object store and keeps the same URL.
  All four preconditions held at the time (private, not a fork, 0 forks, no pull
  requests, 1 collaborator) and a verified bundle of the clean history existed.
  Principal ruling 2026-08-10: accept the exposure and flip. Recorded rather than
  left unwritten, because a residual nobody wrote down becomes a surprise.

  **IF THIS IS EVER REVISITED**, deleting and re-creating still works and is
  still about two minutes, but only while the four preconditions hold. A fork or
  a pull request referencing an old SHA makes it much harder, and neither is
  under this project's control once the repository is public.

Prior audit, superseded and kept for its baseline: run 2026-08-03, the working
tree was clean (0 hits for the username, no personal paths, no emails, no
secret-shaped strings, no data files tracked, 127 files).

- **28.16  The root commit carries a personal email.** `063a499` "Initial
  Commit", a personal address rather than the GitHub noreply, in BOTH the author
  and committer fields, an ancestor of master; every other commit uses the
  noreply identity. THE ADDRESS IS NOT REPEATED HERE ON PURPOSE (redacted
  2026-08-09): this file is tracked, so writing it out published to the tree the
  exact string the ticket exists to keep out of it. Read it off the commit with
  `git log --format='%ae' 063a499` when the fix is run. A 2026-07-20 principal
  ruling left it, reasoning that "the address is already public in the remote's records so a
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
