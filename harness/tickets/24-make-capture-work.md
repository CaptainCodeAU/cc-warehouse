# Ticket 24: make capture work, and make it impossible to fail silently

DONE 2026-08-04 except 24.7, annotated 2026-08-05. **This ticket carried NO status
line at all for a day while its work was live and running**, which is how an audit
came to find it: a `grep DONE` over the ticket set skipped 24 entirely, and only
reading the file end to end showed there was nothing to skip. The three-way
agreement this project relies on (dated annotation + zero stubs + green tests) is
only as good as the annotation, and a missing one reads as "not started".

Verification is recorded at the end of this file.

## Why this ticket exists

Capture has never run automatically. Not once. All 13,836 stored sessions
arrived via manual `ccw sweep`.

    ccw / cc-warehouse references in ~/.claude/settings.json .......... 0
    SessionEnd hooks registered there ................................ 5, all PAI

A plugin was supposed to fill the slot: `claude-transcript-exporter@gz-claude-code-plugins`,
enabled, cache commit `3d7a85fe7065`, files byte-identical to their repo copies.
It delegates with:

    subprocess.run(["uv", "tool", "run", "claude-code-transcripts", "hook"],
                   stdin=sys.stdin, env=env, check=False)

**ROOT CAUSE, reproduced by execution 2026-08-03.** Two different programs share
the name `claude-code-transcripts`, both at version 0.6:

    the principal's fork   ~/.local/bin/…  editable install, argparse
                           verbs: local json web all render hook      HAS hook
    Simon Willison's       PyPI package,   Click
                           verbs: local all json web                  NO hook

`uv tool run` resolves the name from the index and builds an ephemeral
environment, so it lands on the PyPI package:

    $ uv tool run claude-code-transcripts hook
    Usage: claude-code-transcripts local [OPTIONS]
    Error: Got unexpected extra argument (hook)

`check=False` discards the non-zero exit. The hook returns 0, Claude Code is
satisfied, and nothing records that capture did not happen. Last successful
export 2026-07-24T05:21:13Z; 470 log entries then a hard stop.

INFERRED, NOT PROVEN: a uv upgrade changed `uv tool run`'s preference for an
installed tool. Editable cache entries for the fork stop at 2026-07-11; the PyPI
index cache for the package was refreshed 2026-07-27. Homebrew retains only the
current uv, so the prior version's date is unrecoverable from this machine.
Recorded as inference because it is one.

## Work order

- SLICE: capture that runs, and shouts when it does not
- GOAL: a session that ends lands in the archive without anyone asking, and a
  capture that fails is impossible to miss.

### 24.1  Repoint the wrapper at `ccw hook`

Env mapping is near 1:1 and frozen at `config.py:26-33`:

    TRANSCRIPT_EXPORT_DIR   -> CCW_ROOT
    TRANSCRIPT_VOICE_URL    -> CCW_VOICE_URL
    TRANSCRIPT_VOICE_ID     -> CCW_VOICE_ID
    TRANSCRIPT_OPEN_FOLDER  -> CCW_OPEN_FOLDER   (== "1")
    SKIP_SESSION_END_HOOK   -> CCW_SKIP_HOOK     (== "1", and REAL: the wrapper
                                                  documented the old one but
                                                  never read it)
    (none)                  -> CCW_WEBHOOKS

NOT settable by env, so `~/.config/cc-warehouse/config.toml` stays load bearing:
`archive_root`, `archive_timezone`, `keep_objects`, `keep_projections`,
`archive_subagents`.

### 24.2  Never resolve a bare package name in a hook

THE ACTUAL FIX. `uv tool run <name>` in a hook is banned. Call the installed
console script by an explicit path, or by PATH with the resolved path asserted.

The same trap is loaded for this project: `cc-warehouse` returns HTTP 404 on
PyPI, so the name is unclaimed. If anyone registers it, a hook written
`uv tool run cc-warehouse` would silently execute their code on every session
end with the session payload on stdin. Write the rule into the wrapper as a
comment naming this incident, so it is not undone by a later tidy-up.

**MEASURED 2026-08-03, immediately after installing `ccw` editable, and the
result is a trap rather than a reassurance.** The same command form resolves
differently for the two names:

    uv tool run cc-warehouse version              -> 0.1.0        OURS
    uv tool run claude-code-transcripts --version -> 0.6 (Click)  PyPI's
    uv tool run claude-code-transcripts hook      -> Error: unexpected extra
                                                     argument (hook)

Both are installed as editable uv tools. The observable difference is that
`claude-code-transcripts` exists on PyPI and `cc-warehouse` does not. The exact
uv rule is INFERRED (a warm ephemeral-environment cache for the first name is an
uncontrolled variable); what is PROVEN is that `uv tool run <name>` does not
reliably invoke a locally installed tool.

**So `uv tool run cc-warehouse` WORKS TODAY, and that is precisely why it must
not be used.** A form that works now and breaks silently the day someone
registers the name is worse than one that fails immediately, because it gets
adopted first. This is the same shape as the original defect, one step earlier.
Ties 28.18 (claim the name), which reduces but does not remove the exposure.

### 24.3  A failed capture must be loud

`check=False` goes. On non-zero: report through the channels the operator
already watches (notify / voice / a log the freshness check reads), and make
`ccw doctor` able to see it afterwards. The hook still exits 0, because SPEC 2.6
says the hook never raises and blocking session end is worse.

### 24.4  Fix the plugin README and SPEC

Both describe a fat script with its own project resolution, notifications and
JSONL logging. That script stopped existing on 2026-05-29 (`2c1a1ae`). The live
wrapper is 38 lines and logs nothing.

### 24.5  Schedule a daily `ccw sweep`

SessionEnd does not fire when a process is killed. A hook alone can only capture
sessions that end politely. Uses `--quiet` from ticket 23.

### 24.6  Decide the 16 legacy per-project hooks

Sixteen project `settings.json` files still register `export_transcript.sh`, and
all sixteen scripts still exist. They call the bare `claude-code-transcripts`
from PATH, which IS the fork, so they still work; one fired 2026-08-03 02:12.
They write to a third tree, `~/CODE/claude-code-transcripts` (224 MB).

MEASURED: of 68 session folders there, 1 is absent from `~/.claude` and 1 from
the archive, and ZERO are absent from both. They hold nothing unique.

They do one thing `ccw` does not: `export_transcript.sh:18-19` scrubs
`github_pat_` and `gh[posru]_` from every file it generates. `ccw` redaction
lives only in `share.py`; personal projections are written unscrubbed. That is
defensible but should be a decision, not an inheritance. Recorded as 28.2.

### 24.7  Session-start freshness signal

Built like the CI watch, which is the one alert shape that works on this
operator: in the existing attention path, ESCALATING (a rising count, not a
static banner), and clearing only by fixing. Reads ticket 23's gap figure.

## Oracle tests (write first)

- the wrapper invokes an explicit path, never `uv tool run` (assert the argv);
- a fence rejects the string `uv tool run` appearing in any hook wrapper;
- a non-zero child produces a REPORT, and the hook still exits 0;
- every `CCW_*` name the wrapper sets is in `config.ENV_VARS` (bijection, so a
  rename on either side fails the build);
- `CCW_SKIP_HOOK=1` skips, and is reported as skipped rather than silently;
- the freshness signal escalates: its output for 1 missing session differs from
  its output for 50.

## Contract excerpts

SPEC 2.6 (the hook never raises), DESIGN 4 (capture pipeline), DESIGN 8 (the six
env names, frozen), R9 (one implementation), R10, F6, F7.

## TOUCHES

The plugin repo wrapper + hooks.json + README + SPEC, `src/cc_warehouse/cli.py`
(`_run_hook` reporting), the freshness-check script, `contract/` where the env
bijection is asserted.

## Process

Standard loop. EXIT TEST: `ccw doctor` green, then end a real session and it is
still green.

---

## DONE 2026-08-04, except 24.7. Verified by execution 2026-08-05.

The exit test above is the right one and it PASSES: `ccw doctor` is green, and
real sessions have ended and been captured since.

    24.1  repoint the wrapper at `ccw hook`        DONE
    24.2  never resolve a bare package name        DONE
    24.3  a failed capture must be loud            DONE
    24.4  fix the plugin README and SPEC           DONE
    24.5  schedule a daily `ccw sweep`             DONE
    24.6  decide the 16 legacy per-project hooks   DECIDED: deferred, now 28.2
    24.7  session-start freshness signal           DONE 2026-08-23

**24.1 / 24.2.** The wrapper is `hooks/ccw-hook.py` in the plugin, and it resolves a
REAL EXECUTABLE: `CCW_BIN` if set, then `shutil.which("ccw")`, then the uv-tool
shim at `~/.local/bin/ccw`. `uv tool run` appears nowhere in it. The rule is
written into the file as a comment naming this incident, exactly as 24.2 asked,
so a later tidy-up cannot undo it without reading why.

**24.3.** `check=False` is still passed, but the return code is now READ: a
non-zero child writes a JSONL record to `~/.claude/logs/ccw-hook.log` and speaks
through the voice sink. The hook still exits 0 on every path (SPEC 2.6).

**24.4.** The plugin README describes ccw: 19 mentions of `ccw`/`cc-warehouse`
against 2 residual references to the tool it replaced.

**24.5.** `~/Library/LaunchAgents/com.captaincodeau.ccw-sweep.plist` exists, which
covers what a SessionEnd hook structurally cannot see (a killed process).

**THE EVIDENCE THAT CAPTURE ACTUALLY RUNS, which is the only claim that matters
here.** Three independent instruments, taken 2026-08-05, that cannot all be
wrong in the same direction:

    ~/.claude/logs/ccw-hook.log     6 entries, 6 ok, 0 error   (02:10 local)
    ccw doctor                      7 checks ok, "capture is working"
    ccw archive --verify            19,230 folders, 0 problems (02:30 local)

and they RECONCILE EXACTLY: ticket 26.1 verified 19,224 folders on 2026-08-04,
the hook had succeeded 6 times since, and 19,224 + 6 = 19,230. A count that
agrees with an independent count is worth more than either alone.

**STATE THE CLOCK WITH THE NUMBER, because both of these now MOVE.** The same log
read 9 entries (9 ok, 0 error) twenty minutes later, without anyone running
anything. That is the point of the ticket rather than a caveat on it: the archive
stopped being a thing built by hand and became a thing that grows. Any future
count here is a reading at an instant, not a constant, and a reconciliation that
does not name its clock will look broken the next time someone checks it.

## 24.7 IS THE ONE THING STILL OPEN, and it is the part that protects the rest

The freshness signal is not built. Measured 2026-08-05:

    ccw references in ~/.claude/settings.json ................. 0
    SessionStart commands registered there .................... 7, none ccw

The 0 is not the defect (the hook is registered by the PLUGIN, so settings.json
is the wrong place to look for it) but the absent SessionStart check is. Until
it exists, capture stopping again looks exactly like capture working: the failure
is silent at the one moment the operator is present and reading. That is the
failure mode this whole ticket was written about, one level up, and it is why
24.7 should not be quietly absorbed into "24 is done".

Build it like the CI watch: in the existing attention path, ESCALATING rather
than a static banner, and clearing only by fixing.

## NOT DONE, and deliberately so (until 24.7 closed it - see below)

The oracle tests this ticket names were not written. The work landed in the
PLUGIN repository, which has no suite; the fences it asks for (assert the argv,
reject the string `uv tool run` in any hook wrapper, assert the `CCW_*` env
bijection) belong in this repo and do not exist. Recorded here rather than
dropped: a rule enforced only by a comment is a rule until the next tidy-up.

## 24.7 DONE 2026-08-23

Two things shipped, one in each repo.

**cc-warehouse (`src/cc_warehouse/cli.py`, `_run_hook`).** `CCW_SKIP_HOOK=1`
used to return 0 with zero record anywhere - a silent skip indistinguishable
from a healthy no-op capture. It now reports `skipped_disabled` through the
same `notify.report` path `skipped_unchanged` already uses (log-only, does not
speak - `notify.SPEAKING_STATUSES` is unchanged). Oracle test:
`tests/test_capture.py::test_kill_switch_reports_skipped_rather_than_silently`,
proved red against the pre-fix code, green after.

**The plugin (`gz-claude-code-plugins`, a different repo).** A new
`SessionStart` hook, `ccw-freshness-check.py`, registered in `hooks.json`
alongside the existing `SessionEnd` capture hook.

A real design correction, found by running the first draft against this
machine's actual data rather than trusting the ticket's literal wording: "reads
ticket 23's gap figure" reads naturally as "alarm on the Uncaptured: N count",
and the first draft did exactly that with fixed thresholds. Run for real, it
printed ALERT on a perfectly healthy install, because that count sits at
250-350 here permanently (old sessions predating the archive, hidden/warmup
sessions) - `doctor.py` itself marks that line "ok", never a blocking failure,
and ticket 23's own file says the gap is "printed without being" [blocking].
A threshold on that number would have meant a false ALERT every single
session, forever - the opposite of "escalating, clearing only by fixing".

Shipped instead: the alarm is driven by `ccw doctor`'s own PASS/FAIL verdict
(its exit code - the same mechanism `ccw-watch`, ticket 28.22's external
consumer, already relies on), escalating on how many CONSECUTIVE
session-starts in a row that verdict has been broken, a streak persisted in
`~/.claude/logs/ccw-freshness-state.json`. The raw Uncaptured figure still
rides along in the message as context (so the ticket's "reads ticket 23's gap
figure" is honoured, just not as the trigger). Verified against real data:
298 chronic uncaptured sessions with a healthy doctor verdict prints nothing;
a simulated 6-session-start outage (via `CCW_BIN` pointed at a fake `ccw`
that fails) escalates mild -> WARNING (streak 2-4) -> ALERT (streak 5+), then
goes silent and resets to streak 0 the moment the fake doctor reports healthy
again.

**The "belongs in this repo" note above did not hold.** The wrapper files
physically live in `gz-claude-code-plugins`, a separate git repository on
disk; hardcoding that repo's local path into a cc-warehouse test would break
for anyone who clones this repo without that sibling checkout at that exact
path, which is the same class of problem this project's own "no personal
machine paths" rule exists to prevent. The oracle tests instead live in that
other repo, as its own first test file
(`gz-claude-code-plugins/tests/test_freshness_check.py`, stdlib `unittest`,
14 tests, no dependency added), scanning that repo's own `hooks/` directory
with relative paths. All 14 proved green; the `uv tool run` fence and the
`CCW_*` bijection check both scan real files rather than trusting a comment.
The `CCW_*` bijection is necessarily a hand-kept mirror of
`cc_warehouse.config.ENV_VARS` rather than a live cross-repo import - there is
no dependency between the two repos to make it otherwise - so it catches a
wrapper-side typo but not a rename made only on the cc-warehouse side.

Full suite re-confirmed green in cc-warehouse after the fix: 1,138 tests,
ruff clean, pyright 0 errors.

## Why there is a `ticket-24` tag on a docs commit

Because that is where every other ticket tag on this track sits: `ticket-23`,
`ticket-25` and `ticket-26` all point at that ticket's closing `docs(harness):`
commit rather than at code. Most of 24's code is not in this repository at all.
