---
name: architecture
description: Regenerate cc-warehouse's architecture-review board HTML (cc-warehouse-architecture/index.html) from its canonical source (cc-warehouse-architecture/SOURCE.md). The HTML is the rich, visual, dark-first review board - Tailwind + Mermaid, per-candidate strength badges + state chips + evidence tiers, the verified-healthy panel, the top recommendation, a plain-English line per section. Renders ONLY what SOURCE.md holds - never invents a candidate or a verdict. A fresh REVIEW runs via /mattpocock-skills:improve-codebase-architecture; its verified findings are folded into SOURCE.md FIRST, then this command renders. Manual only.
argument-hint: "[ (blank = confirm-gate then regen) | status | add | regen (skip the gate) | artifact (inline for publishing) ]"
disable-model-invocation: true
allowed-tools: Bash, Read, Edit, Write
---

# /architecture - regenerate cc-warehouse's architecture-review board

You maintain **cc-warehouse's code-architecture REVIEW BOARD** - the deepening candidates, their
verdicts, and the verified-healthy findings. Two files, one folder:

- **`cc-warehouse-architecture/SOURCE.md`** - the canonical board record (the TRUTH). Every
  candidate and cleared finding lives here with its **state**, **strength**, **evidence tier**,
  and its contract/ticket ties. **This is what you edit.**
- **`cc-warehouse-architecture/index.html`** - the human-facing VIEW, RENDERED from SOURCE.md by
  this command. Never hand-author findings into the HTML; it is generated.

**Scope guard (the locked contract):** the contract docs (`contract/BRAINSTORM.md`, `SPEC.md`,
`DESIGN.md`, `FINDINGS.md`, `HARNESS.md`) are LOCKED. This command NEVER edits them and never
relitigates their decisions. A candidate that needs a contract change carries an amber contract
callout naming the open item (the C8 pattern: DESIGN section 15 item 8) and waits for the
principal's ruling.

**Golden rule - the HTML renders SOURCE.md, nothing more.** Every candidate, badge, line-ref, and
verdict in the HTML traces to SOURCE.md. New review findings get folded into SOURCE.md FIRST
(with their evidence verified per the census discipline: bounded surface, triangulate, inspect,
tag verified/agent-reported/assumed), then rendered.

**Mode = `$ARGUMENTS`** (default = the confirm-gate then regenerate):

- **blank** - run the CONFIRM-GATE (below), then regenerate `index.html` from SOURCE.md.
- **`status`** - print the board ledger (candidates by state: PROPOSED / GRILLING /
  TICKETED-<nn> / BUILT / REJECTED; evidence tiers; the snapshot commit + review date) and any
  drift vs the live repo (a ticket absorbed a candidate; a cited src file moved). NO edits, NO
  regeneration.
- **`add`** - fold new information into SOURCE.md (a fresh review's verified findings, a grilling
  outcome, a ticket absorbing a candidate, a slice landing), correct state + evidence tier + a
  dated change-log line - then run the gate.
- **`regen`** - skip the gate and render now (only when the operator just said "just render it").
- **`artifact`** - an INLINED, CDN-free variant for publishing as a claude.ai Artifact (CSP
  blocks CDNs): inline the needed CSS as plain styles, use Artifact-native mermaid fences or
  pre-rendered SVG. The default output stays CDN-based for local viewing.

---

## THE CONFIRM-GATE (mandatory - never render half-informed)

Findings arrive in parts (a review lands, then grilling verdicts, then tickets absorb or close
candidates). Before rendering:

1. Read `SOURCE.md`; compute the ledger (candidates by state + evidence tier; the snapshot SHA).
2. **Ticket/contract drift check:** for every candidate, grep `harness/tickets/*.md`, DESIGN
   section 15's decided entries, and CLAUDE.md's phase prose for changes that touch it - a ticket
   newly listing a candidate's finding (the C10/12b precedent), a slice landing a candidate's
   surface, a new principal ruling. A hit means SOURCE.md is stale: fold the change in FIRST
   (`add` behavior) with a dated change-log line.
3. **Line-ref decay check:** SOURCE.md pins file:line evidence at a named commit. If src changed
   since (`git -C <repo> diff --name-only <snapshot-sha>..HEAD -- src/`) in the cited files, mark
   the affected refs "line refs may have drifted" in the render (do NOT silently re-derive - a
   fresh review re-verifies, this command only renders). A DIRECT-BUILD burst (Guardrail 7) moves
   many cited files at once, so decay after one is LARGE and BROAD across cards; that breadth is
   the signal a fresh review is due, not a rendering fault. Report it plainly and offer the review.
4. **Ask the operator whether anything is pending** (an unfolded grilling outcome, a candidate
   verdict, new review results) - one short question, not a pop-up. Only then render. `regen` is
   the sole bypass.

## Generation procedure (after the gate)

1. Fold any just-given info into `SOURCE.md` FIRST (state + tier + dated change-log line).
2. Read the WHOLE of SOURCE.md - the only input. Map: header notes -> banner; each candidate ->
   a card; the cleared list -> the healthy panel; the not-on-board list -> the scheduled strip;
   the ranking -> the top-recommendation section.
3. Write `cc-warehouse-architecture/index.html` per the HTML spec below.
4. **Validate:** extract every `<pre class="mermaid">` block and render each with mmdc
   (`PUPPETEER_SKIP_DOWNLOAD=1`, system Chrome) - a failed block is a BLOCKING finding, never
   shipped. If mmdc is unavailable on this machine, record "mermaid: browser-render only" in the
   SOURCE.md change log honestly - never claim a validation that did not run. Confirm every
   SOURCE.md candidate is represented with its state + tier carried through.
5. **Hygiene gate (public repo):** grep the changed files for em-dashes (the repo bans them in
   authored text) and personal data (real username, machine names, personal paths) - both must
   come back clean before any commit.
6. **Commit `SOURCE.md` + `index.html` BY NAME** (never `git add -A`) under the GitHub noreply
   identity (`git -c user.name='CaptainCodeAU' -c user.email='69835039+CaptainCodeAU@users.noreply.github.com'`),
   append the `Claude-Session:` line, and push per the frequent-push practice unless told
   `--no-push`.

## HTML spec (dark-first . visual . plain-English)

Built on the mattpocock HTML-REPORT pattern, cc-warehouse-fitted:

- **Libraries:** Tailwind via `https://cdn.tailwindcss.com`; Mermaid via
  `https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs` (`theme:"dark"`).
  **Dark-first** (the operator's standing preference): `bg-slate-950` body.
- **Header:** title, review date + the snapshot SHA, the build-state line (which slices landed,
  what is next), the legend (module / seam / leakage / deep module / contract callout), and the
  state+tier chip key.
- **Per-candidate card:** title (C-number) . state chip (violet PROPOSED / indigo TICKETED-<nn> /
  emerald BUILT / slate REJECTED) . strength badge (`Strong` emerald, `Worth exploring` amber,
  `Speculative` slate) . dependency-category tag . files (mono) . before/after visual (Mermaid
  for graph-shaped, hand-built divs for mass/cross-section; every visual container gets
  `overflow-x-auto`) . Problem (cited file:line) . Solution (plain English, NO interface
  signatures - grilling owns those) . Wins bullets (glossary terms: locality / leverage / depth /
  seam) . an amber contract callout where the candidate touches an open DESIGN 15 item or an
  R-rule . the evidence tier line.
- **Healthy panel:** the cleared findings, emerald-framed.
- **Scheduled strip:** the not-on-board items with their owning tickets.
- **Top recommendation:** one larger card, the pick + why, anchored.
- **Vocabulary:** module . interface . implementation . depth . seam . adapter . leverage .
  locality (the /codebase-design glossary) - never component/service/API/boundary.
- **Every section carries a plain-English line** (the operator's standing rule), visually
  distinct (sky-tinted box, "In plain English." lead).
- **No em-dashes anywhere** (repo rule; use hyphens, middots, commas). No personal data (public
  repo; repo-relative paths only).

## Guardrails (non-negotiable)

1. **Render SOURCE.md, never invent.** A finding not in SOURCE.md does not exist in the HTML.
2. **Evidence discipline travels:** every candidate keeps its tier (VERIFIED at a named commit /
   CONTRACT / AGENT-REPORTED). Never silently upgrade a tier - only a fresh first-hand
   verification (recorded in SOURCE.md, dated) does that. Expressed confidence never exceeds
   verification coverage.
3. **States are earned:** PROPOSED -> GRILLING -> TICKETED-<nn> (the ticket is the claim) ->
   BUILT (tests + the HARNESS changelog are the proof) or REJECTED (record why, so future
   reviews stop re-suggesting it). This command records state; it never advances one on its own.
4. **Single ownership:** this command owns `cc-warehouse-architecture/` currency. `/refresh`'s
   docs slice enumerates CLAUDE.md, README, the contract/ status tier, and harness/tickets - this
   folder is deliberately outside that scope; staleness here is caught by THIS command's gate
   (ticket/contract drift + line-ref decay).
5. **Stage by name; never `git add -A`.** Never commit warehouse data, scratchpads, or memory.
   The C- trailers auto-stamp; keep appending the `Claude-Session:` line; never hand-add a C-
   trailer.
6. **Judgment calls go to the principal** as one short question with a recommendation, never an
   auto-decision.
7. **The direct-build era (2026-07-23).** The principal may direct work built directly and OUT OF
   the DESIGN section 16 order, so the build-state line reflects what actually LANDED, not the
   linear slice order: slice 13 landed while relocate 12a/12b are still open, and the render was
   reworked to the full exporter-v8.10.1 chrome plus entry-type coverage (parser + render) without
   a ticket of its own. Consequences for this board: (a) the snapshot commit in SOURCE.md can fall
   far behind HEAD in one burst, so line-ref decay is broad, not a bug; (b) a candidate's cited
   surface may have moved even though no ticket "landed" it (the render rework touched C1/C5/C7's
   files, cli.py cards C2/C6, the config surface); (c) that breadth is the standing signal to run a
   fresh `/mattpocock-skills:improve-codebase-architecture` review and re-verify before re-ranking.
   This command still never advances a state or re-derives a ref on its own.

## File map

- `cc-warehouse-architecture/SOURCE.md` - canonical board record (edit this).
- `cc-warehouse-architecture/index.html` - generated view (this command writes it).
- `cc-warehouse-architecture/README.md` - orientation.
- A fresh review = `/mattpocock-skills:improve-codebase-architecture` (Explore lens agents ->
  first-hand verification of every load-bearing claim -> fold into SOURCE.md via `add`).
