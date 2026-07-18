# Architecture: Milton Product

**Date:** 2026-07-17
**Mindset:** production
**Scale:** personal first, team-capable contracts
**Status:** Proposed architecture derived from the standing vision

---

## Technical Summary

Milton remains a local, dependency-light projection library over canonical
records held by native harnesses, Somm, Fab, George, Git/GitHub, memory stores,
and later Spindle/Chip/Projector. Current SQLite stores normalized events,
identity associations, and ingestion state. The target design adds directed-
relation indexes. Append-only JSONL stores finding revisions. Source bodies
remain in their owning systems.

The architecture below is the target design. Existing components are labeled
`existing`; `new`, `extended`, and `future` components are not implemented.

The next architecture adds two concepts that must not be conflated:

1. **identity association** says two external coordinates are explicitly
   associated in one work context; it does not assert object equivalence or
   workflow causality; and
2. **directed relation** says one record attempted, produced, verified, acted
   on, refuted, evaluated, or promoted another.

Cost-per-outcome is a deterministic projection over selected accounting
observations, identity associations, directed relations, and typed outcome
events. Findings use the same evidence spine but keep their append-only grading
history. `acted-on` is derived when an exact finding revision has a valid
directed relation to an authoritative external receipt.

Somm remains hot-path and independently operable. It produces mediated call
facts and consumes optional Milton projections. Before broader delegation,
Somm must close two accounting defects: shadow-eval auxiliary calls outside its
call ledger and non-idempotent OTLP round trips.

## Technology Stack

| Layer | Choice | Rationale |
| --- | --- | --- |
| Language | Python 3.12+ | Existing family and adapter implementation |
| Core | Standard library only | Safe local install; no service/network side effect |
| Event/graph index | SQLite | Existing scale is proven; transactions, indexes, and deterministic queries are sufficient |
| Finding history | Append-only JSONL | Reviewable immutable revisions and portable custody |
| CLI | `argparse`, JSON/text projections | Existing dependency-free contract |
| Model seam | Protocol/subprocess or optional Somm client extra | Keeps deterministic core and hot paths cycle-free |
| Tests | pytest, host-shaped fixtures, live bounded audits | Seam failures matter more than isolated algorithms |
| Distribution | hatchling/uv, PyPI package `milton-ai` | Broad AI-accounting scope; `milton` import retained |

## System Architecture

```text
native harnesses   Somm calls/evals   Fab receipts   George intent/actions
       │                  │                │                   │
       └──────── read-only adapters + source coverage [existing/extended] ─┘
                                  │
                                  v
                  normalized events (SQLite) [existing]
                                  │
                    ┌─────────────┴─────────────┐
                    v                           v
       identity crosswalk [existing]    directed relations [new]
         (explicit context)        (attempted/produced/acts_on/...)
                    │                           │
                    └─────────────┬─────────────┘
                                  v
                    deterministic projections
           accounting [existing] ─ outcome attribution [new]
                         activity [existing/extended]
                                  │
                    ┌─────────────┴─────────────┐
                    v                           v
      deterministic finding rules [new]  bounded synthesis [future]
                    └─────────────┬─────────────┘
                                  v
                append-only finding ledger [existing]
                                  │
                    finding/action relations [new]
                                  │
          ┌─────────────┬─────────┴────────┬──────────────┐
          v             v                  v              v
    George [future] Somm [future] Projector [future] Chip/Spindle [future]
     decide/act      route policy      calibration     eval/promotion
          └───────────── authoritative receipts ──────────┘
                                  │
                                  v
                   action/disposition projection [new]
```

## Components

### Adapter and coverage layer — existing, extended

- **Purpose:** recover typed facts without changing producers.
- **Responsibilities:** incremental source discovery, privacy policy,
  source-native identity, field-level coverage, fail-open diagnostics.
- **Extensions:** Somm eval/campaign/decision/recommendation/late-update facts;
  richer Fab verifier/artifact receipts; authoritative PR lifecycle; memory
  inventory/access records; later Projector and Spindle receipt ids.
- **Interface:** `Adapter.read() -> SourceRead[NormalizedEvent | CrosswalkRecord
  | RelationRecord]`.

Aggregate campaign, recommendation, or dashboard totals are marked rollups and
never emitted as additional billable observations.

### Identity crosswalk — existing, bounded

- **Purpose:** traverse explicit external identity associations.
- **Responsibilities:** assertion/refutation history, method, confidence,
  evidence ids, stable link ids.
- **Non-responsibility:** causal or workflow meaning. `fab.job=X` related to a
  `george.entry=Y` does not by itself prove which produced, verified, or acted
  on the other.

### Directed relation graph — new

- **Purpose:** preserve causal/workflow claims separately from identity.
- **Responsibilities:** append-only assertions and refutations for a small
  predicate vocabulary; evidence and source method; graph traversal.
- **Initial predicates:** `part_of`, `attempt_of`, `produced`, `verifies`,
  `evaluates`, `acts_on`, `refutes`, and `promotes`.
- **Interface:** `MiltonStore.write_relation()`, `current_relations()`, and
  typed traversal from a source or target reference.

The vocabulary is deliberately small. A predicate without a consumer or
deletion-detectable test is not admitted.

### Accounting projection — existing, hardened

- **Purpose:** select among monetary observations only when exact shared
  billable identity and economic kind prove equivalence.
- **Extensions:** observation role (`production`, `shadow_gold`,
  `shadow_judge`, `eval`), provider request/billing id, billing mode, rollup
  exclusion, and explicit foreign/imported origin.
- **Producer gates:** Somm must ledger auxiliary eval calls and make its OTLP
  round trip idempotent before Milton treats Somm coverage as complete.

### Outcome attribution projection — new

- **Purpose:** reconcile selected cost to typed outcomes.
- **Responsibilities:** attribution precedence, explainable paths, conservation
  of selected spend, ambiguity detection, and unallocated reason codes.
- **Initial outcome types:** `fab.job`, `fab.attempt`, `george.entry`,
  `git.commit`; PR merged/reverted/closed-unmerged follows when an authoritative
  source exists.
- **Interface:** `build_outcome_attribution(events, crosswalks, relations)` and
  `milton cost --per-outcome`.

Version 1 permits only a single exact allocation weight of `1`. If one cost can
reach multiple non-hierarchical economic outcomes, it is ambiguous. Fractional
allocation is deferred until a real, reviewable policy exists.

### Finding generators — new consumers of existing ledger

- **Deterministic runner:** executes named, versioned rules against one source
  snapshot. The first rule family detects stale, re-minted, and unconsulted
  George gates.
- **Synthesis runner:** later extracts facets, clusters, and describes bounded
  corpora through a pluggable model seam. It cannot promote its own leads.
- **Evaluation runner:** compares generated findings to labeled cases,
  calculates precision/coverage, retains refutations, and enforces promotion
  floors.
- **Interface:** `milton findings generate|evaluate|list|show`.

### Finding/action projection — new

- **Purpose:** close the north-star loop without becoming an action tracker.
- **Responsibilities:** relate an exact finding revision to an authoritative
  receipt; derive current disposition and historical `ever_acted_on`; qualify
  freshness when source coverage is unavailable; and change history only when
  a receipt or relation is explicitly refuted.
- **Interface:** relation records such as
  `milton.finding=fnd... --acts_on--> george.entry=...`; no mutable
  `acted_on=true` field.

### Consumer exports — new and optional

- **George:** versioned finding candidate plus evidence/coverage/expiry; George
  returns decision/disposition receipt.
- **Somm:** outcome-conditioned tuple observations or Milton finding origin;
  Somm returns recommendation/action receipt. Somm falls back to local facts if
  a Milton snapshot is stale or under-covered.
- **Projector:** recommendation/experiment/promotion ids in; later measured
  outcome projection out.
- **Chip/Spindle:** idempotent procedure-candidate projection out; evaluation,
  promotion, and binding receipt ids back.
- **Flip:** optional immutable finding export for evidence custody, not an
  editable duplicate finding.

All exchanges prefer schema-versioned JSON/JSONL/SQLite views over reciprocal
Python imports.

## Data Model

### `RelationRecord`

```text
relation_id: str             stable id over subject, predicate, object
revision_id: str             immutable assertion/refutation revision
subject: TypedRef            namespace + stable value
predicate: RelationKind      bounded directed vocabulary
object: TypedRef             namespace + stable value
state: asserted | refuted
method: explicit | derived | human
confidence: Decimal          0..1; never replaces method
evidence_event_ids: tuple[str, ...]
recorded_at: datetime
supersedes: str | None
note: str | None
```

### `OutcomeAttribution`

```text
attribution_id: str
accounting_event_id: str
selected_amount_usd: Decimal
state: attributed | ambiguous | unallocated
outcome_ref: TypedRef | None
method: direct-relation | explicit-crosswalk-path | none
path_record_ids: tuple[str, ...]
reason_code: str | None
projection_version: int
```

The projection-level invariant is:

```text
selected_total = attributed_total + ambiguous_total + unallocated_total
```

### Finding action relation

No new mutable finding field is introduced. A current asserted
`RelationRecord(predicate=acts_on|refutes|evaluates|promotes)` links
`milton.finding` or a specific `milton.finding-revision` to a canonical receipt
identity. New relations target an exact revision. The finding projection checks
receipt validity and reports current disposition, historical `ever_acted_on`,
and freshness separately; missing source coverage cannot erase a prior receipt.

### Generator manifest additions

The existing finding manifest remains the reproducibility envelope. Generator
details include rule/model/harness version, parameter digest, source cutoff,
labeled-eval version, precision result, aggregation threshold, and content
policy where applicable.

## APIs and Interfaces

### CLI

- `milton cost --per-outcome [--since] [--outcome-type] [--format]`
- `milton relations show NAMESPACE=VALUE [--direction]`
- `milton findings generate GENERATOR [--since] [--dry-run]`
- `milton findings evaluate GENERATOR --cases PATH`
- `milton findings list [--kind] [--grade] [--acted-on]`
- `milton findings show FINDING_ID`
- `milton findings relate FINDING_ID --acts-on NAMESPACE=VALUE`
- `milton findings export FINDING_ID --format json`

Effectful source-system actions are intentionally absent. Consumer systems own
their own apply/dismiss/retire/promote interfaces.

### Python

- `build_outcome_attribution(...) -> OutcomeAttributionProjection`
- `build_findings(generator, snapshot) -> tuple[FindingRevision, ...]`
- `build_finding_activity(...) -> FindingActivityProjection`
- `MiltonStore.write_relation(...)`
- `MiltonStore.current_relations(...)`

### Producer contracts

Somm call observations add stable provider request/billing id, role, billing
mode, provenance, and imported/foreign status. Fab and George propagate caller
and outcome identities. Neither mints provider identity or a second cost.

## Implementation Phases

### Phase 1 — Trust contracts

- Add directed relations and action-receipt projection.
- Add attribution model with conservation and abstention.
- Commission Somm fixes for auxiliary eval calls and OTLP idempotency.
- Commission shared billing and Fab/George identity propagation.

**End-to-end gate:** ingest one live direct Fab→Somm trace and one
George→Fab→Git trace; prove identity and directed relations remain distinct.

### Phase 2 — Two vertical proofs

- Ship `milton cost --per-outcome` for Fab/George/Git.
- Ship finding review CLI and deterministic stale-gate detector.
- Commission George intake/disposition receipts.
- Close one acted-on finding.

**End-to-end gate:** selected spend conserves across outcome buckets, and one
real finding reaches an external action receipt without Milton mutating George.

### Phase 3 — Measured expansion

- Add PR lifecycle and richer Somm evidence tables.
- Add failure-motif/drift generator and held-out eval harness.
- Add two memory adapters, including agentmemory if locally adopted.
- Export outcome-conditioned tuple evidence to Somm.

**End-to-end gate:** a promoted motif meets its precision floor and an accepted
memory recommendation has a valid receipt.

### Phase 4 — Procedure compounding

- Add idempotent Chip candidate export.
- Add Spindle evaluation/promotion receipt import.
- Measure one promoted candidate against its baseline.

**End-to-end gate:** one candidate completes Milton → Chip → Spindle → Fab →
Milton with pinned evaluation identity and an honest outcome.

## Technical Risks

| Risk | Impact | Likelihood | Mitigation |
| --- | --- | --- | --- |
| Identity graph is mistaken for causality | High | High | Separate directed relation table and APIs; attribution tests reject association-only paths where direction is required |
| Producer rollups become duplicate costs | High | High | Observation/rollup role, child-call references, exact accounting keys, cross-source replay tests |
| Somm OTLP loop duplicates mediated calls | High | Current defect | Required exporter→wire→ingester idempotency test and foreign-row isolation |
| Shadow eval omits real spend | High | Current defect | First-class auxiliary calls using returned tokens and eval receipt relations |
| Sparse outcomes make cost-per-outcome misleading | High | Medium | Conservation, ambiguity/unallocated buckets, method coverage, narrow initial outcome unit |
| Findings create decision spam | High | Medium | Dry run, labeled precision gate, rate/aggregation limits, George remains action owner |
| Model synthesis is hard to reproduce | High | Medium | Tuple-bound manifests, held-out corpus, retained outputs/refutations, deterministic shell |
| Action relation asserts causality too easily | High | Medium | Explicit/human method, source receipt validation, refutable revisions |
| Cross-repo package cycle | Medium | Low | Data contracts and optional extras; no required Somm↔Milton imports |
| Open-source badge hides a closed load-bearing engine | High | Medium | Full dependency-chain license and offline-exit review; open-core/source-available systems cannot become required runtime |
| Owning more code creates maintenance or security defects | High | Medium | Keep strategic mechanisms small and deletion-tested; buy mature specialist engines only behind replaceable interfaces |

## Dependencies

### External producer/consumer contracts

- Somm: mediated/auxiliary calls, eval and recommendation receipts.
- Fab: attempts, terminal/verifier/artifact receipts.
- George: work hierarchy, decisions, actions, disposition receipts.
- Git/GitHub: landed/reverted/closed outcomes.
- Projector: recommendation/experiment/promotion ids.
- Chip/Spindle: candidate and evaluation/promotion identities.
- Memory systems: inventory/access exports where available.

### Runtime

None for the deterministic built-ins beyond Python and SQLite. Model-assisted
and network adapters are optional. The default architecture prefers owned,
stdlib-scale mechanisms for evidence semantics. A new runtime dependency needs
the documented gate in [`docs/build-vs-adopt.md`](../../docs/build-vs-adopt.md):
complete open-source license chain, offline completeness, export/exit, pinned
provenance, transitive review, and a demonstrated complexity or safety benefit.

## Integration Impact

### New Components → Existing Consumers

| New component | Existing consumer | Integration action |
| --- | --- | --- |
| Directed relations | Activity and future attribution | Traverse relations alongside identity, display method/evidence, never merge semantics |
| Outcome attribution | `MiltonStore`, CLI, report consumers | Add stable projection/JSON; George displays it rather than recomputing |
| Finding/action projection | Finding ledger and George adapter | Relate finding revisions to George receipts and derive acted-on |
| Somm evidence adapter | Accounting, attribution, future findings | Ingest auxiliary calls, eval receipts, decisions, recommendations, late updates without counting rollups |
| Finding generators | Finding ledger | Validate evidence/manifests before append; dry-run and eval gates |
| Tuple outcome export | Somm | Optional read/cache with source snapshot and fallback behavior |
| Chip candidate export | Chip/Spindle | Idempotent source reference and return receipt identities |

### Deprecated or narrowed behavior

| Existing behavior | Replacement | Action |
| --- | --- | --- |
| Generic crosswalk used to imply workflow causality | Directed relation graph | Keep identity traversal; migrate causal consumers and tests |
| Historical/cross-source totals in individual producers presented as whole-system | Milton accounting/outcome projection | Retain producer-local operational views with explicit scope |
| Planned storage of Fab task outcomes in Somm | Milton outcome projection consumed by Somm | Reframe before implementation; keep Somm call/eval facts |
| Somm arbitrary OTLP import into authoritative call ledger | Milton foreign OTel adapter or isolated idempotent Somm compatibility | Deprecate after compatibility contract exists |
| Somm global mirrored call rows | Primary ledgers plus Milton projection | Deprecate only after registry and consumer coverage are proven |

### Integration Verification

- Phase 1: host-shaped fixture and live trace prove relation direction and
  crosswalk identity differ.
- Phase 2: live accounting conservation plus George action-receipt round trip.
- Phase 3: held-out finding precision and optional Somm consumer fallback.
- Phase 4: pinned candidate promotion loop with baseline/outcome comparison.

## Security and Privacy Considerations

- Retrieved and transcript content is hostile data, never instruction.
- Taint/provenance survives synthesis and exports; quotes remain structurally
  distinct from control fields.
- Metadata-only remains default; generation on full content is explicit.
- External actions require the owning system's authority and deduplication.
- Finding/action relations can be refuted; no unreviewed model output gains
  effect authority.
- Provider ids and source locations are local metadata and require redaction in
  public exports.
- Default installation and tests do not run floating package executors,
  unreviewed install scripts, or network fetches. Adopted components are pinned,
  license/SBOM recorded, and isolated behind a replaceable Milton interface.

## Future Considerations

- Team-scale query concurrency or cold analytics may eventually justify
  DuckDB/PostgreSQL projections, but no current evidence requires migration.
- OTel can become an interchange adapter after canonical-id and foreign-row
  semantics stabilize.
- A human explorer may project the stable APIs later; it is not an architecture
  driver.
- Direct frontier-model log analysis may obsolete clustering stages. The
  adapter, evidence, relation, grading, and action contracts remain valuable.

---

**Next:** executable decomposition in [itemized-plan.md](itemized-plan.md).
