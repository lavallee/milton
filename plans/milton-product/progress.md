# Milton product implementation progress

This is the execution ledger for
[`itemized-plan.md`](itemized-plan.md). The itemized plan remains the scope and
dependency authority; this file records implementation state, proof, and
adjustments learned while executing it.

## Status meanings

- `pending`: no implementation claim.
- `in progress`: the task is the current bounded implementation slice.
- `implemented`: code and focused tests exist, but any required live checkpoint
  or cross-repository acceptance has not yet passed.
- `complete`: every acceptance criterion has reproducible evidence.
- `narrowed`: an explicit checkpoint selected a smaller supported contract and
  recorded why.

## Task ledger

| Task | Status | Evidence / next proof |
| --- | --- | --- |
| A-0.1 Typed directed relation records | complete | `relations.py`, SQLite append/refute history, public exports, and `tests/test_relations.py`; quality suite passes. |
| A-0.2 Relation traversal and explanation | complete | Directed/depth-bounded traversal, activity schema v2, `relations show`, refutation tests, and George→Fab→Somm CLI proof. |
| A-0.3 Finding action state from receipts | complete | Exact-revision action projection validates receipts; tests cover missing receipts, source loss, action/refutation separation, and retained history. |
| A-0.4 Finding review CLI primitives | complete | Create/list/show/revise/refute/relate/unrelate/export; deterministic export re-read through public APIs. |
| A-0.5 Trust-contract live checkpoint | complete | 35-event metadata-only live store; direct Fab→Somm and reachable George→Fab→Git proofs; redacted reproducible report. |
| A-1.1 Attribution states and conservation | complete | Three exclusive buckets, reason codes, single-allocation precedence, and property-style conservation tests. |
| A-1.2 Exact attribution paths | complete | Current relation/crosswalk graph records all event/link/relation revision IDs; precedence and competing outcomes abstain deterministically. |
| A-1.3 `cost --per-outcome` | complete | Time/type filters, text/JSON, embedded accounting reconciliation, denominators, source provenance, and explicit reported/computed semantics. |
| A-1.4 Outcome regression fixtures | complete | Landed/failed/reverted/abandoned/runner/ambiguous/missing paths, rollup/dedup/kind, replay/refutation/window, and host-shaped ingest coverage. |
| A-1.5 Ten-trace outcome checkpoint | complete | Ten live observations across Somm/OpenCode/Hermes: exact conservation, one directed Fab outcome, nine explicit abstentions; conservative projection graduates with named producer-contract dependency. |
| A-2.1 Normalize George gate evidence | complete | Typed mint/consult/decision/disposition events keep canonical coordinates and mint IDs separate; live July scan found 42 mints, 39 keyed, one 12-mint family, and later human resolutions with consultation unknown. |
| A-2.2 Deterministic gate detectors | complete | Three versioned rules have positive/negative/ambiguous/stale fixtures, exact evidence manifests, stable dry runs, lead-only output, and idempotent append/replay. |
| A-2.3 Finding generation/evaluation CLI | complete | Public evaluate, dry-run, gated append, list, and show flow; append requires a surface-approved held-out result and cannot emit corroborated findings. |
| A-2.4 Labeled gate corpus | complete | Frozen five-case tuning and nine-case disjoint held-out corpus; all held-out expectations exact, all rules explicitly offline because positive precision is unavailable. |
| A-2.5 Export to George intake | complete | Versioned advisory export, taint, George service/CLI intake, disposition receipts, idempotent replay, conflict closure, and dependency-free simulated round trip all pass. |
| A-2.6 Live acted-on checkpoint | narrowed | George refused one obsolete tuning-only lead through the live contract; Milton derives one valid/current refutation, but zero gates were removed and review burden increased, so B2 remains offline. |
| A-3.1 Execute Somm accounting-integrity commission | complete | Somm schema v22 records gold/judge custody and provider ids; OTLP native replay attaches exactly once and foreign imports are non-policy observations. Full suite: 806 passed, 1 optional skip. |
| A-3.2 Expand Somm evidence adapter | complete | Host-shaped v22 fixture selects exactly production + gold + judge, excludes campaign rollups, and traces eval/campaign/decision/recommendation/late-update evidence through activity. |
| A-3.3 Execute Fab identity-receipts commission | complete | `fab.execution-receipt/v1` persists source custody, attempt correlation, native ids, terminal/delivery semantics, verifier proofs, artifacts, and child-keyed non-counting rollups. Fab suite: 469 passed. |
| A-3.4 Ingest stable Fab verifier and artifact receipts | complete | Receipt-first adapter traces George→job→attempt→Somm/session→outcome/verifier/artifact without stdout matching; safe disposable proof selects/attributes `$0.25` once and excludes two Fab rollups. Milton suite: 76 passed. |
| A-3.5 Execute George disposition commission | complete | George intake/disposition service and CLI, idempotent receipt replay, conflict closure, and one live refutation are accepted; dash-main deployment still lacks the new route. |
| A-3.6 Reconcile Somm overlap and export tuple evidence | complete | Milton exports exact implementation/profile/model/harness outcome snapshots; Somm consumes versioned JSON as evidence only and keeps policy changes explicit. Milton: 80 passed. Somm: 812 passed, 1 optional skip. |
| A-4.1 Finding-quality evaluation harness | complete | Generator-neutral immutable result envelope binds generator/model/harness/parameters/source; partitions fail closed, calibration is append-only, and gate CLI consumes measured precision/recurrence/aggregation decisions. Suite: 83 passed. |
| A-4.2 Direct analysis versus facet clustering | complete | Equal-budget local Qwen/Ollama comparison selected direct bounded synthesis: 1.00 precision, 0.889 recall, 1.00 stability versus facet-only 1.00/0.333/1.00; all counterexamples retained, no runtime dependency adopted. |
| A-4.3 Failure-motif and drift findings | complete | Metadata-only exact failure fingerprints, source receipts, independent recurrence, privacy floors, tuple-bound synthesis, candidate maximum, expiry, and public CLI. Live 7-day scan: 211,216 events, one 24-session candidate, 1.00/1.00 bounded precision/recall. |
| A-4.4 Audit two memory systems | complete | Read-only native and decision adapters distinguish inventory/loaded/retrieved/referenced/applied/unknown. Live: 3 native + 29 decision items, all access unknown; fixture proves keep/retire and simulated action receipt without source mutation. |
| A-4.5 Export idempotent Chip procedure candidates | complete | Stable finding/candidate/revision identity, unique-reference tallying, counterexample/fixture/source-limit custody, public receipt-only adapter, and actual Milton→Chip replay→Milton contract test. Milton: 92 passed. Chip: 197 passed, 4 optional skips. |
| A-4.6 Close one procedure promotion outcome loop | complete | Actual local Qwen/Ollama loop: Spindle held-out delta +0.475 and owned bind/promotion; Fab/Somm preserved both exact tuples and paired native calls; Milton appended `improvement` calibration. Replay added no calls/receipts. |

## Baseline already present

Before execution of the itemized plan, Milton had a normalized event store,
identity crosswalk, accounting projection, activity view, adapter framework,
finding ledger library, CLI foundation, and a passing local quality suite. Those
are foundations, not evidence that any task above is complete.

Baseline verification on 2026-07-17: `pytest`, `ruff check`, `ruff format
--check`, strict `mypy`, and package build all passed with 38 tests.

## Adjustments log

- 2026-07-17: Added this execution ledger so implementation state is not
  inferred from roadmap prose or code presence.
- 2026-07-17: Realigned the A-3 progress rows to the canonical itemized plan.
  Accepted A-3.1/A-3.2 after Somm's 806-test suite and Milton's normal-adapter
  cardinality fixture proved exact request accounting and non-counting
  rollups. Marked the already-accepted George commission A-3.5 complete while
  retaining its dash-main deployment gap.
- 2026-07-17: Completed A-3.3/A-3.4. Fab now distinguishes its chronological
  ledger from stable producer receipts and passes deterministic attempt ids as
  correlation. Milton prefers those receipts, keeps legacy stdout/ledger
  fallback, and prevents duplicate relation ownership by leaving current
  attempt→call direction to Fab while retaining legacy Somm job→call
  projection. The disposable checkpoint traversed seven identities, selected
  and attributed `$0.25` once, and excluded two Fab rollups. See
  `reports/fab-receipt-checkpoint-2026-07-17.md`.
- 2026-07-17: Completed A-3.6. Milton now exports coverage-declared outcome
  evidence for one exact implementation/profile/served-model/harness tuple;
  Somm validates the versioned JSON without importing Milton or changing
  policy automatically. Disposable cross-repository controls covered ready,
  stale, sparse, confounded, and unavailable states. Full verification: Milton
  80 tests; Somm 812 passed with one optional OpenTelemetry skip. See
  `reports/somm-overlap-tuple-checkpoint-2026-07-17.md`.
- 2026-07-17: Completed A-4.1. The stale-gate evaluator now adapts into the
  shared `milton.finding-evaluation/v1` harness. Result identity covers the
  generator/model/harness/parameter/source tuple, corpus, predictions, and
  floors; tuning/held-out/calibration leakage fails closed; and append-only
  reviewed calibration cannot rewrite or promote an old result. Promotion
  also fails when recurrence or aggregation floors fail despite perfect
  precision. Full suite: 83 passed plus Ruff, format, sdist, and wheel.
- 2026-07-17: Completed A-4.2. A frozen metadata-only corpus compared direct
  synthesis with Milton-owned deterministic facets followed by clustering,
  using the same held-out cases, local Apache-2.0 Qwen blob, Ollama harness,
  seeds, and one-call 1,600-token cap. Direct synthesis retained 1.00 precision,
  0.889 recall, 0.667 operator-family coverage, and 1.00 stability; facet-only
  clustering retained precision but fell to 0.333 recall/operator value. The
  direct seam wins behind deterministic hard gates; no model or engine enters
  Milton's runtime dependencies. See
  `reports/failure-motif-method-2026-07-17.md`.
- 2026-07-17: Completed A-4.3. The direct synthesis receipt now names and
  describes a motif while deterministic metadata-only facets own membership.
  Redacted input hashes prove exact repeats; every member needs a native
  failure/outcome receipt; independent recurrence and aggregation/privacy
  floors cannot be weakened; and the maximum self-issued grade is candidate
  with expiry. A 24-hour live scan abstained at one exact session. The widened
  seven-day scan covered 211,216 events and produced one 24-session retry-storm
  candidate with six negative controls, 1.00 live precision/recall, and no
  source mutation. See `reports/failure-motif-live-checkpoint-2026-07-17.md`.
- 2026-07-17: Completed A-4.4. Two read-only adapters inventory native
  files/rules/skills and decision memories and optionally ingest explicit host
  access rows. Loaded, retrieved, referenced, and applied remain independent;
  absent signals stay unknown. The live audit found 3 native and 29 decision
  items with no trustworthy access stages and emitted no recommendations. A
  source-shaped fixture proved evidence-supported keep/retire grades and linked
  one retire revision to a simulated human action receipt without modifying
  the source. See `reports/memory-audit-checkpoint-2026-07-17.md`.
- 2026-07-17: Completed A-4.5. Milton emits a deterministic Chip candidate
  projection with stable candidate/source/revision identity and preserves
  occurrence, counterexample, negative/exception fixture, coverage, expiry,
  snapshot, and privacy limits. Chip owns idempotent commissioning and a
  content-addressed public receipt; repeated commissioning appends neither a
  row nor a receipt, and tallies union occurrences across later revisions.
  Milton ingests only the public receipt and records exact origin/custody
  relations. The contract test invokes the real sibling Chip package twice and
  closes the loop without reading its private candidate ledger. See
  `reports/chip-candidate-checkpoint-2026-07-17.md`.
- 2026-07-17: Completed A-4.6. A source-derived procedure candidate retained
  exact Milton/Chip custody, while Spindle independently evaluated the pinned
  local Qwen/Ollama tuple and owned the eligible bind and promotion. Frozen
  held-out means were 0.525 baseline and 1.000 variant. A fresh operational
  case then ran through two native Somm calls; Fab preserved the promoted call
  and origin, Somm preserved both baseline and promoted call IDs, and Milton
  appended an `improvement` calibration for 0.30 to 1.00. Replay issued no
  additional calls or receipts. Reported and computed dollar cost are both
  unavailable; local usage is `included` and `local-included-unpriced`, never
  silently `$0`. This validates the
  narrow policy-adherence loop, not general production efficacy. See
  `reports/procedure-promotion-pilot-2026-07-17.md`.
- 2026-07-17: Kept Forge feedback in a separate ledger to avoid broadening
  Milton acceptance criteria with tooling-maintenance work.
- 2026-07-17: Completed A-0.1 and A-0.2. Activity schema v2 adds directed
  `relations` while retaining identity `links` as a separate surface. Focused
  and full verification: 44 tests plus Ruff and strict mypy.
- 2026-07-17: Completed A-0.3 and A-0.4. Receipt validity and freshness are
  separate, finding refutation remains adjudication rather than acted-on, and
  deterministic custody export includes both append-only histories. Full
  verification: 49 tests, Ruff, strict mypy, sdist, and wheel build.
- 2026-07-17: Completed A-0.5. Exact Somm/George source coordinates now emit
  source-receipt relations alongside crosswalks. Added exclusive `--until`
  ingestion after a seven-day scan selected roughly 322,000 Somm calls. The
  final 35-event live proof and gaps are in
  `reports/trust-contract-live-checkpoint-2026-07-17.md`.
- 2026-07-17: Completed A-1.1 through A-1.4. Accounting selection now feeds a
  conservative outcome projection with exact precedence, conservation,
  explicit ambiguity/unallocated reasons, rollup exclusion, source provenance,
  and `milton cost --per-outcome`. Full verification: 63 tests plus Ruff,
  format, and strict mypy.
- 2026-07-17: Completed A-1.5. The retained ten-trace store selects five Somm,
  four OpenCode, and one Hermes observations. One zero-dollar Somm observation
  reaches a successful Fab job; nine abstain with `no-outcome-path`; all native
  amounts match and `$0.02910777` conserves exactly. The projection graduates,
  but shared billable dedup and broad coverage remain gated on the named Somm
  and Fab producer contracts. See
  `reports/cost-per-outcome-pilot-2026-07-17.md`.
- 2026-07-17: Completed A-2.1. Added a typed gate-evidence payload and exact
  George gate relations while retaining ordinary George entry outcomes. A
  host-shaped ingest fixture proves repeated mints, explicit consultation,
  human resolution, and unavailable read evidence. The bounded live inventory
  retained in `.milton/a2-gates-inventory-2026-07-17.db` contains 42 mints (39
  keyed), three human decision receipts, and one coordinate minted 12 times
  before a later resolution. Full verification: 64 tests plus Ruff, format,
  and strict mypy.
- 2026-07-17: Completed A-2.2 through A-2.4. The versioned generator keeps
  resolved-condition, re-mint, and old/unconsulted claims separate; exact mint
  targets can resolve to canonical coordinates, while unavailable coordinates,
  consultation, or source freshness abstain. The public CLI supports evaluate,
  dry-run, precision-gated append, stable replay, list, and show, with `lead` as
  the maximum generated grade. The frozen live corpus has five tuning and nine
  disjoint held-out cases. All nine held-out expectations match, but there are
  no independent held-out positives, so precision is unavailable, every rule
  remains offline, and append fails closed. See
  `reports/george-gate-finding-eval-2026-07-17.md`.
- 2026-07-17: Completed A-2.5 and narrowed A-2.6. Milton now emits immutable
  `milton.finding-candidate/v1` advisory documents with explicit taint; George
  owns versioned, deduplicated intake and accept/refute/defer/act receipts over
  its service and CLI, with no Python dependency in either direction. The live
  pilot sent one exact but explicitly tuning-only stale-gate lead. George
  refused it as already reconciled and not surface-approved; replay appended no
  duplicates. Re-ingest derives exactly one valid/current `refutes` relation.
  The contract loop graduates, but B2 does not: zero gates were removed and one
  review was added. See `reports/stale-gate-pilot-2026-07-17.md`.
