# Boundaries: milton and its neighbors

Milton sits in an ecosystem with a gateway (Somm), a runner (Fab), an intent
and decision spine (George), an external-intelligence service (Projector), a
component contract (Chip), a binding system (Spindle), and whatever harnesses
people actually use. The boundaries below answer both “who is authoritative?”
and “what document crosses the boundary?”

## Canonical facts, associations, relations, and projections

Milton does not become a new canonical database for its neighbors:

- a **canonical fact** remains in its owning system, such as a Somm call, Fab
  terminal receipt, George disposition, Git commit, or Spindle promotion;
- an **identity association** says two external coordinates are explicitly
  connected and belongs in Milton's refutable crosswalk;
- a **directed relation** says one thing attempted, produced, verified, acted
  on, refuted, evaluated, or promoted another; it must not be inferred merely
  because identities share a connected component; and
- a **projection** is Milton's versioned answer over a declared source snapshot,
  such as selected accounting, cost-per-outcome, or finding activity.

Consumers receive schema-versioned projections and return authoritative
receipt ids. They do not read Milton's private SQLite store or copy its finding
ledger into an independently editable record.

## milton ↔ somm (the load-bearing boundary)

**Somm is authoritative for the mediated work it persists.** Its current audit
ledger is canonical for persisted calls, decisions, and eval receipts:
provider, model, tokens, the amount Somm recorded, outcome codes, and decision
rationale. Shadow-eval gold and judge requests now use the same first-class
call contract. A recorded amount is usually Somm's
token-times-price computation, not a provider bill. Milton preserves that
provenance and ingests Somm as the richest single adapter.

**Milton is the target owner for coverage-declared cross-source projections.**
A deliberate principle of these systems is that usage is never constrained to
our own tools: agents
run through Claude Code, Codex, Cursor, aider, hermes, and direct provider
APIs, and much of that traffic never touches a gateway. Only a
gateway-independent reader can do performance accounting, motif mining, or
memory auditing over *all* of it. Gateway ledgers are one adapter among
several — privileged in richness, not in scope.

**Division of labor:**

| Concern | Owner |
| --- | --- |
| In-flight routing, fallback, spend gates, plan pacing, model advice | Somm |
| Persisted mediated-call and first-class auxiliary-eval records | Somm |
| Model/workload evals, campaigns, and bounded routing actions | Somm |
| Quota learning, plan pacing, and source-local call/eval failure summaries | Somm |
| Cross-source normalization, identity, and directed relations | Milton |
| Cross-source historical reconciliation and cost-per-outcome | Milton |
| General motifs, drift, memory hygiene, and procedure candidates | Milton |
| Applying a Milton outcome-informed routing finding | Somm; returns an action receipt |

**Dependency direction.** Somm keeps its in-flight cost calculation, daily
budget gate, plan pacing, and per-call ledger. Those are hot-path gateway
responsibilities and must work without Milton. Milton owns historical
cross-source accounting, exact deduplication, and cost-per-outcome. A future
Somm retrospective command may optionally invoke Milton, but `somm-core` does
not take a required Milton dependency; doing so would put an offline projection
library on the routing path and invert the existing adapter boundary. The two
remain separately usable.

**Mutual awareness.** Somm's records carry correlation/session identifiers;
milton's crosswalk joins them to harness session ids, runner job ids, and
commits. Where identifiers are missing, that is a coverage-honesty finding,
not something to paper over.

Milton now exports `milton.outcome-tuple/v1` for exact
`(implementation, profile, served model, harness)` retrospective comparison.
The snapshot declares an exclusive source cutoff, coverage, selected sample,
path evidence, and unavailable/sparse/confounded uncertainty. Somm validates
the schema, exact tuple, freshness, sample floor, and ambiguity without a
Milton dependency. Ready means eligible for review only; policy action remains
null. Stale, sparse, confounded, unavailable, invalid, or tuple-mismatched
evidence falls back safely to Somm's existing local data and policy. Somm does
not create a parallel canonical Fab/George task-outcome table merely to power
historical routing.

**Producer integrity gate.** The
[Somm accounting-integrity commission](../plans/milton-product/commissions/somm-accounting-integrity.md)
is accepted: auxiliary provider requests are linked call rows, native OTLP
round trips attach to the existing `somm.call_id`, and foreign imports are
explicitly non-policy. Milton consumes that contract directly and still does
not use fuzzy duplicate suppression. Campaign and recommendation totals are
rollups over child facts, never new cost observations.

## milton ↔ Projector

The boundary is defined by corpus and decision:

- **Projector** interprets external developments, evaluates their relevance to
  the portfolio, recommends bounded experiments, and calibrates adoption from
  promotions and outcomes. Flip/Keel/Cistern remain canonical for its evidence
  and claims.
- **Milton** measures internal operational exhaust: sessions, attempts, costs,
  outcomes, failures, memory use, and repeated work shapes.

Projector can carry stable recommendation/experiment/promotion ids into
George/Fab. Milton can later return a versioned outcome or finding projection
for calibration. Projector does not build another session-log clusterer or
cross-source cost calculator; Milton does not copy Projector/Flip/Keel claims
or become an external technology scout.

## milton ↔ George

George owns intent, work hierarchy, decisions, gates, guarded actions, and
disposition. Milton currently reads George records and explicit identifiers.
The planned contract adds versioned finding intake and lets Milton later derive
`acted-on` or `refuted` from the stable receipt George returns.

Milton never closes or obviates a George gate directly. The first proof is the
stale/re-minted gate pilot: Milton supplies evidence and precision; George or a
human decides; George mutates canonical state; Milton re-ingests the receipt.
The contract is specified in the
[George finding-disposition commission](../plans/milton-product/commissions/george-finding-disposition.md).

## milton ↔ harnesses (Claude Code, Codex, Cursor, aider, hermes, …)

Adapters read each harness's native on-disk exhaust (JSONL transcripts,
session stores, history files) without requiring any change to the harness.
Adapter maintenance is acknowledged treadmill work — the price of the
no-lock-in principle — and each adapter declares what it can and cannot
recover (tokens, tool calls, models, timestamps) so coverage stays honest.
OpenTelemetry GenAI input is one optional adapter, not the foundation: the
conventions are still in development-status churn, and the highest-value
corpora are not OTel today.

## milton ↔ chip

`milton findings export FINDING --target chip` projects one exact finding
revision into Chip's candidate-ledger convention. It preserves occurrence,
counterexample, negative/exception fixture references, source snapshot,
coverage gaps, expiry, and other source limits. The candidate id is stable
across finding revisions; the source revision is exact. Chip's
`commission_candidate` owns the append-only candidate row and emits a stable
`chip.candidate-receipt/v1`. Re-exporting and re-commissioning the same finding
revision cannot add an occurrence or a receipt; Chip tallies commissioned rows
by unique occurrence reference across revisions.

Milton's `chip` adapter reads only `candidate-receipts.jsonl`, never Chip's
private candidate/fixture store. It records the exact finding-revision →
candidate origin and receipt → candidate verification relations. Candidate
capture is not called evaluation or promotion. The Milton finding remains
canonical; the Chip row is an interop projection.

## milton ↔ Spindle and Forge

Spindle owns package composition, held-out evaluation, distribution, and
binding. A procedure manifest carries the exact Milton/Chip origin and explicit
baseline/variant implementation/profile/model/harness tuples. Spindle refuses
ineligible evaluated binds and returns evaluation and promotion receipts tied
to the binding coordinate. A bound skill proves availability; the held-out
receipt supports promotion, while later Fab/Somm operational outcomes determine
post-promotion calibration.

Milton ingests those public receipts and can classify one exact comparison as
improvement, regression, or inconclusive. It cannot evaluate or bind the
procedure, and it cannot treat a binding or task closure as outcome evidence.

Forge supplies planning and interpretation procedures. It may consume Milton's
current reality, coverage gaps, and findings while shaping a commission. It is
not a runtime evidence store, recurrence counter, or promotion boundary.

## milton ↔ runners (fab and others)

Runner receipts (attempts, outcomes, verifier verdicts, chip receipts,
rollups) are the corroboration substrate: they turn transcript-derived
hypotheses into graded findings and provide the outcome side of
cost-per-outcome. Fab is the reference adapter; the receipt reader is
format-driven so other runners can implement the same surface.

Fab may retain cost rollups for operator convenience only when they reference
their child Somm/provider accounting keys and are typed as rollups. A rollup
without child keys remains a non-counting outcome observation. The stable
identity/evidence contract is accepted: `fab.execution-receipt/v1` persists
source commission custody, deterministic attempt correlation, terminal and
semantic delivery outcomes, verifier proof ids, and exact artifact/native
coordinates. Milton reads these receipts first and retains ledger/transcript
parsing only for legacy jobs. See the
[accepted Fab commission](../plans/milton-product/commissions/fab-identity-receipts.md).

## The grading ladder (cross-cutting)

Findings move `lead → candidate → corroborated`, in the style of
evidence-gated research notebooks: an LLM-extracted pattern is a lead; a
structural bar (recurrence count, multiple sources) makes it a candidate;
independent corroboration (a receipt, a matched outcome, a human
confirmation) promotes it. Refuted findings are retained with their
refutation — negative evidence is evidence.

`Acted-on` is not another grade. It is a derived relationship between an exact
finding revision and a valid authoritative action receipt. A current view shows
the latest disposition; historical `ever_acted_on` remains true after a valid
receipt unless that receipt or relation is explicitly refuted. Temporary source
unavailability qualifies freshness but does not erase history. A corroborated
finding may remain unacted; a lead may be explicitly refuted. Refutation counts
as adjudication and calibration, not as acted-on. Both facts remain visible.
