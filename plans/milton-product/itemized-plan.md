# Itemized Plan: Milton Product

> Source: [VISION.md](../../VISION.md) and [ROADMAP.md](../../ROADMAP.md)
> Orient: [orientation.md](orientation.md) | Architect: [architecture.md](architecture.md)
> Generated: 2026-07-17
> Granularity: Micro tasks, normally one focused agent session

## Context Summary

Milton has a validated ingestion, identity, accounting, and activity spine but
does not yet deliver its north star. This plan builds two vertical proofs:
conservative cost per outcome, and a stale-gate finding that causes a receipted
George action. Broader synthesis, memory, and procedure work remains gated on
those proofs.

**Mindset:** production | **Scale:** personal first, team-capable contracts

---

## Epic: milton-product-A-0 — Trust relations and action receipts

Priority: P0
Labels: `phase-1`, `model:sonnet`, `complexity:high`, `risk:high`, `slice:acted-on`

Separate causal/workflow relations from identity association and make acted-on
findings derivable from authoritative receipts.

### Task: milton-product-A-0.1 — Define typed directed relation records

Priority: P0
Labels: `phase-1`, `model:opus`, `complexity:high`, `model`, `risk:high`
Blocks: `milton-product-A-0.2`, `milton-product-A-0.3`,
`milton-product-A-1.2`, `milton-product-A-2.1`, `milton-product-A-3.2`,
`milton-product-A-3.4`

**Context:** The crosswalk can prove explicit association but not `attempt_of`,
`produced`, `verifies`, or `acts_on` direction.

**Implementation Steps**:
1. Add `TypedRef`, bounded `RelationKind`, state, method, confidence, evidence,
   supersession, validation, and stable serialization.
2. Add append-only/refutable SQLite relation schema and indexes.
3. Export the contract from the public package.

**Acceptance Criteria**:
- [ ] Relation identity and revision identity are deterministic and round-trip.
- [ ] Stale assertions, invalid predicates, and backward revisions fail closed.
- [ ] An integration fixture stores both a crosswalk and `attempt_of` relation
      for one Fab/Somm trace and proves they remain separate query results.

**Files:** `src/milton/relations.py`, `src/milton/store.py`, `src/milton/__init__.py`, `tests/test_relations.py`

### Task: milton-product-A-0.2 — Add relation traversal and explanation

Priority: P0
Labels: `phase-1`, `model:sonnet`, `complexity:medium`, `logic`, `api`
Blocks: `milton-product-A-0.5`, `milton-product-A-1.2`,
`milton-product-A-2.5`, `milton-product-A-3.2`, `milton-product-A-3.4`

**Context:** Consumers need a path with predicate, direction, method, and
evidence—not an unlabeled connected component.

**Implementation Steps**:
1. Implement current asserted incoming/outgoing relation queries.
2. Add relation edges to activity documents without merging them into links.
3. Add `milton relations show` JSON/text output.

**Acceptance Criteria**:
- [ ] Traversal respects direction, refutation, and maximum depth.
- [ ] Activity JSON distinguishes `links` from `relations` with evidence ids.
- [ ] A CLI integration test explains George → Fab → Somm direction while the
      existing activity command remains schema-compatible.

**Files:** `src/milton/store.py`, `src/milton/activity.py`, `src/milton/cli.py`, `tests/test_store.py`, `tests/test_cli.py`

### Task: milton-product-A-0.3 — Derive finding action state from receipts

Priority: P0
Labels: `phase-1`, `model:sonnet`, `complexity:high`, `logic`, `slice:acted-on`
Blocks: `milton-product-A-2.5`

**Context:** The north star cannot be a mutable checkbox on a finding.

**Implementation Steps**:
1. Add a finding-activity projection over exact finding revisions and
   `acts_on|refutes|evaluates|promotes` relations.
2. Validate referenced receipts and distinguish explicit refutation from
   temporarily unavailable source coverage.
3. Expose current disposition, historical `ever_acted_on`, freshness, and
   acted-on/refuted/evaluated/promoted state through Python and JSON.

**Acceptance Criteria**:
- [ ] A finding without a valid receipt does not count as acted-on.
- [ ] Refuting the receipt/relation changes current disposition without
      rewriting history; losing source coverage marks freshness unknown but
      does not erase a historically valid action.
- [ ] An end-to-end fixture links a finding to a George disposition event and
      derives exactly one acted-on or refuted result.

**Files:** `src/milton/findings.py`, `src/milton/activity.py`, `src/milton/store.py`, `tests/test_findings.py`

### Task: milton-product-A-0.4 — Add finding review CLI primitives

Priority: P0
Labels: `phase-1`, `model:sonnet`, `complexity:medium`, `api`, `slice:acted-on`
Blocks: `milton-product-A-2.3`

**Context:** The ledger exists only as a library initialized by `milton init`.

**Implementation Steps**:
1. Add `findings list` and `findings show` with grade/kind/action filters.
2. Add explicit revision/refutation and relation commands with validation.
3. Add immutable JSON export for consumer intake or Flip custody.

**Acceptance Criteria**:
- [ ] Commands never mutate source systems and append rather than update.
- [ ] Text and JSON make evidence, manifest, expiry, and action receipts visible.
- [ ] CLI integration creates, refutes, exports, and re-reads one finding through
      the public store/ledger APIs.

**Files:** `src/milton/cli.py`, `src/milton/findings.py`, `tests/test_cli.py`

### Task: milton-product-A-0.5 — Trust-contract live checkpoint

Priority: P0
Labels: `phase-1`, `model:opus`, `complexity:medium`, `checkpoint`, `test`
Blocks: `milton-product-A-1.5`, `milton-product-A-2.6`

**Context:** Relation semantics need proof against real Fab/George/Somm shapes.

**Implementation Steps**:
1. Ingest a bounded live window into a fresh store.
2. Inspect one direct Fab→Somm trace and one George→Fab→Git trace.
3. Save a redacted receipt with identities, directed relations, coverage, and
   any unresolved gaps.

**Acceptance Criteria**:
- [ ] No trace relies on time, token, content hash, or stdout-text equality.
- [ ] Identity and relation paths are independently inspectable.
- [ ] The saved checkpoint can be reproduced by a documented CLI command on a
      new store.

**Files:** `reports/`, `docs/adapters.md`, integration fixtures as needed

---

## Epic: milton-product-A-1 — Conservative cost per outcome

Priority: P0
Labels: `phase-2`, `model:opus`, `complexity:high`, `risk:high`, `slice:cost-outcome`

Turn the accounting projection into explainable outcome attribution while
preserving conservation, ambiguity, and unallocated spend.

### Task: milton-product-A-1.1 — Specify attribution states and conservation

Priority: P0
Labels: `phase-2`, `model:opus`, `complexity:high`, `model`, `risk:high`
Blocks: `milton-product-A-1.2`, `milton-product-A-1.3`

**Context:** “Cost per PR” is easy to label and easy to misrepresent.

**Implementation Steps**:
1. Define attributed, ambiguous, and unallocated records and reason codes.
2. Define exact method precedence and v1 single-allocation policy.
3. Encode the selected = attributed + ambiguous + unallocated invariant.

**Acceptance Criteria**:
- [ ] The spec distinguishes runner, task, commit, and later PR outcomes.
- [ ] Association-only or multiply reachable outcomes abstain where required.
- [ ] Property-style tests conserve selected amounts across a mixed integration
      fixture with exact, ambiguous, and missing paths.

**Files:** `src/milton/outcomes.py`, `docs/outcome-attribution.md`, `tests/test_outcomes.py`

### Task: milton-product-A-1.2 — Build exact attribution paths

Priority: P0
Labels: `phase-2`, `model:opus`, `complexity:high`, `logic`, `risk:high`
Blocks: `milton-product-A-1.3`, `milton-product-A-1.4`

**Context:** Attribution combines selected accounting events, event families,
identity associations, and directed relations.

**Implementation Steps**:
1. Resolve eligible outcome candidates with recorded path ids and direction.
2. Apply explicit precedence and mark competing non-hierarchical outcomes
   ambiguous.
3. Group output by outcome type without counting the same amount twice in an
   economic total.

**Acceptance Criteria**:
- [ ] Every attributed record includes all event/link/relation ids in its path.
- [ ] Two reachable outcomes never silently receive the same full amount.
- [ ] A George→Fab→Somm→Git fixture yields the documented outcome while a
      competing path remains ambiguous in the end-to-end projection.

**Files:** `src/milton/outcomes.py`, `src/milton/store.py`, `tests/test_outcomes.py`

### Task: milton-product-A-1.3 — Add `milton cost --per-outcome`

Priority: P0
Labels: `phase-2`, `model:sonnet`, `complexity:medium`, `api`, `slice:cost-outcome`
Blocks: `milton-product-A-1.5`

**Context:** The product needs a stable consumer surface, not only a library.

**Implementation Steps**:
1. Add time and outcome-type filters with text/JSON output.
2. Display totals, denominators, attribution methods, and coverage gaps.
3. Keep `milton accounting` as the observation projection and link the two
   schemas explicitly.

**Acceptance Criteria**:
- [ ] JSON includes schema version, selected total, all three buckets, per-outcome
      records, paths, and coverage.
- [ ] Text never calls unknown or estimated amounts actual provider spend.
- [ ] A CLI fixture reconciles exactly to `milton accounting` on the same store.

**Files:** `src/milton/cli.py`, `src/milton/store.py`, `README.md`, `tests/test_cli.py`

### Task: milton-product-A-1.4 — Add outcome projection regression fixtures

Priority: P0
Labels: `phase-2`, `model:sonnet`, `complexity:medium`, `test`, `risk:high`
Blocks: `milton-product-A-1.5`

**Context:** Attribution correctness lives in negative and ambiguous seams.

**Implementation Steps**:
1. Add landed, failed, reverted-placeholder, abandoned, runner-only,
   multi-outcome, and missing-link cases.
2. Add rollup-not-observation and economic-kind separation cases.
3. Add replay/refutation and time-window boundary cases.

**Acceptance Criteria**:
- [ ] Removing direction, ambiguity, or conservation logic fails a named test.
- [ ] Rollups and duplicate observer rows cannot inflate outcome totals.
- [ ] Host-shaped adapter fixtures pass through ingest → accounting → outcome
      projection rather than constructing only unit-level objects.

**Files:** `tests/fixtures/`, `tests/test_outcomes.py`, `tests/test_sqlite_adapters.py`

### Task: milton-product-A-1.5 — Ten-trace outcome checkpoint

Priority: P0
Labels: `phase-2`, `model:opus`, `complexity:high`, `checkpoint`, `experiment`
Blocks: `milton-product-A-3.1`

**Context:** Graduation depends on real attribution coverage, not green fixtures.

**Implementation Steps**:
1. Select ten representative priced traces across available sources.
2. Independently verify outcome paths and classify all abstentions.
3. Publish a redacted audit with coverage, disagreements, and a go/narrow
   decision against ROADMAP Epic A1.

**Acceptance Criteria**:
- [ ] Selected totals conserve exactly across all buckets.
- [ ] Each trace has an independently reviewable path or reason code.
- [ ] The checkpoint states whether the product graduates, narrows to runner
      outcomes, or requires a named producer contract before further build.

**Files:** `reports/cost-per-outcome-pilot-*.md`, fixture promotions as warranted

---

## Epic: milton-product-A-2 — Stale-gate acted-on finding

Priority: P0
Labels: `phase-2`, `model:sonnet`, `complexity:high`, `slice:acted-on`, `checkpoint`

Prove the full evidence → finding → decision → action-receipt loop on the live
George stale/re-minted gate problem.

### Task: milton-product-A-2.1 — Normalize George gate evidence

Priority: P0
Labels: `phase-2`, `model:sonnet`, `complexity:medium`, `adapter`, `slice:acted-on`
Blocks: `milton-product-A-2.2`, `milton-product-A-2.4`

**Context:** The detector needs canonical gate coordinates, references, mint
history, consultations, decisions, and dispositions with honest gaps.

**Implementation Steps**:
1. Inventory George ledger/API shapes for current and historical gates.
2. Emit typed events/relations for gate mint, consult, decision, and disposition.
3. Preserve PR/fix coordinates and unavailable consultation evidence.

**Acceptance Criteria**:
- [ ] Canonical gate coordinate and individual mint ids remain distinct.
- [ ] Missing read evidence is unknown, never interpreted as non-use.
- [ ] A host-shaped fixture ingests repeated and already-resolved gates through
      the normal George adapter and exposes the required detector evidence.

**Files:** `src/milton/adapters/george.py`, `docs/adapters.md`, `tests/test_runtime_adapters.py`

### Task: milton-product-A-2.2 — Implement deterministic gate detectors

Priority: P0
Labels: `phase-2`, `model:sonnet`, `complexity:high`, `logic`, `slice:acted-on`
Blocks: `milton-product-A-2.3`, `milton-product-A-2.4`

**Context:** Three claims require separate evidence: condition resolved,
coordinate repeatedly re-minted, and old/unconsulted.

**Implementation Steps**:
1. Implement versioned rules with bounded windows and explicit abstention.
2. Emit separate finding kinds/details with evidence and manifests.
3. Add dry-run generation that does not append or contact George.

**Acceptance Criteria**:
- [ ] Each rule has positive, negative, ambiguous, and stale-source fixtures.
- [ ] The detector never closes a gate or promotes its own grade.
- [ ] End-to-end generation from a George fixture appends stable findings once
      and replays without duplicates.

**Files:** `src/milton/generators/george_gates.py`, `src/milton/generators/__init__.py`, `tests/test_generators.py`

### Task: milton-product-A-2.3 — Wire finding generation and evaluation CLI

Priority: P0
Labels: `phase-2`, `model:sonnet`, `complexity:medium`, `api`, `slice:acted-on`
Blocks: `milton-product-A-2.5`

**Context:** Operators need dry-run, append, and evaluation paths with explicit
source snapshots.

**Implementation Steps**:
1. Add `findings generate` with generator/since/dry-run options.
2. Add `findings evaluate` over labeled JSONL cases.
3. Record generator version, parameters, cutoff, coverage, and precision result.

**Acceptance Criteria**:
- [ ] Dry run and append produce byte-equivalent finding documents apart from
      recorded time/revision identity.
- [ ] A generator below its promotion floor cannot emit corroborated findings.
- [ ] CLI integration generates, evaluates, lists, and shows the gate findings
      through public surfaces.

**Files:** `src/milton/cli.py`, `src/milton/generators/`, `tests/test_cli.py`

### Task: milton-product-A-2.4 — Build and review the labeled gate corpus

Priority: P0
Labels: `phase-2`, `model:opus`, `complexity:medium`, `test`, `experiment`
Blocks: `milton-product-A-2.5`

**Context:** The roadmap requires 90% precision before high-confidence
surfacing and narrows below 80%.

**Implementation Steps**:
1. Sample live gate families with redacted evidence packets.
2. Label supported, unsupported, ambiguous, and duplicate cases independently.
3. Freeze the first corpus and calculate per-rule precision and coverage.

**Acceptance Criteria**:
- [ ] Labels include rationale and immutable source coordinates.
- [ ] No case used to tune a rule is represented as held-out evaluation.
- [ ] The evaluation report drives an explicit surface/offline/narrow decision
      used by the generation integration.

**Files:** `evals/george-gates/`, `reports/george-gate-finding-eval-*.md`

### Task: milton-product-A-2.5 — Export findings to George intake contract

Priority: P0
Labels: `phase-2`, `model:sonnet`, `complexity:medium`, `integration`, `blocking`
Blocks: `milton-product-A-2.6`

**Context:** George remains the action owner; Milton supplies a versioned,
deduplicated candidate document.

**Implementation Steps**:
1. Implement immutable finding export with target/action suggestion and taint.
2. Add fixture compatibility with the George commission contract.
3. Ingest returned disposition/action receipts as directed relations.

**Acceptance Criteria**:
- [ ] Export contains id/revision, evidence, coverage, expiry, generator, and
      no source-system mutation instruction.
- [ ] Re-export and re-ingest are idempotent by finding revision/receipt id.
- [ ] Contract integration derives acted-on/refuted from a simulated George
      round trip without a Milton→George Python dependency.

**Files:** `src/milton/exports.py`, `src/milton/adapters/george.py`, `tests/test_exports.py`

### Task: milton-product-A-2.6 — Live acted-on finding checkpoint

Priority: P0
Labels: `phase-2`, `model:opus`, `complexity:high`, `checkpoint`, `risk:high`
Blocks: `milton-product-A-4.1`

**Context:** The north star advances only when George actually acts or refutes.

**Implementation Steps**:
1. Select one reviewed high-confidence stale or re-mint finding.
2. Send it through the accepted George contract under normal authority gates.
3. Re-ingest the receipt and measure queue/duplicate effect.

**Acceptance Criteria**:
- [ ] George, not Milton, performs or refuses the action.
- [ ] Milton derives exactly one acted-on or refuted finding with a valid
      canonical receipt.
- [ ] The report compares operator burden before/after and records a
      graduate/narrow/kill result for ROADMAP Epic B2.

**Files:** `reports/stale-gate-pilot-*.md`, live fixture promoted only after redaction

---

## Epic: milton-product-A-3 — Producer and consumer contract closure

Priority: P0
Labels: `phase-1`, `model:opus`, `complexity:high`, `integration`, `risk:high`

Close gaps in canonical producer facts before delegating historical projections
or claiming complete accounting.

### Task: milton-product-A-3.1 — Execute Somm accounting-integrity commission

Priority: P0
Labels: `phase-1`, `model:opus`, `complexity:high`, `blocking`, `project:somm`
Blocks: `milton-product-A-3.2`

**Context:** Shadow gold/judge spend is omitted from calls and OTLP round trips
can duplicate a billed call.

**Implementation Steps**:
1. Review and dispatch `commissions/somm-accounting-integrity.md` in Somm.
2. Require auxiliary-call custody, provider ids, and exporter→ingester
   idempotency under Somm's full suite.
3. Accept only with a Milton cardinality fixture/receipt.

**Acceptance Criteria**:
- [ ] Production, shadow gold, and shadow judge requests appear exactly once.
- [ ] Exporting and re-ingesting a Somm call leaves one billable row.
- [ ] Milton's normal adapter consumes the accepted fixture and accounting
      projection without a special-case duplicate filter.

**Files:** `plans/milton-product/commissions/somm-accounting-integrity.md`, target `../somm`

### Task: milton-product-A-3.2 — Expand the Somm evidence adapter

Priority: P1
Labels: `phase-3`, `model:sonnet`, `complexity:high`, `adapter`
Blocks: `milton-product-A-3.5`, `milton-product-A-4.1`

**Context:** The current adapter reads calls only; eval receipts, campaigns,
decisions, recommendation actions, and late updates are outcome inputs.

**Implementation Steps**:
1. Inventory/version all accepted Somm tables and views.
2. Emit auxiliary calls as observations and aggregates as non-counting rollups.
3. Emit directed relations for eval, campaign, decision, recommendation, and
   late-outcome receipts.

**Acceptance Criteria**:
- [ ] Aggregate campaign/recommendation costs never enter billable totals.
- [ ] Legacy/missing tables fail open with stored coverage diagnostics.
- [ ] A host-shaped Somm fixture flows through activity, accounting, and outcome
      attribution with correct observation cardinality.

**Files:** `src/milton/adapters/somm.py`, `docs/adapters.md`, `tests/test_sqlite_adapters.py`

### Task: milton-product-A-3.3 — Execute Fab identity-receipts commission

Priority: P0
Labels: `phase-1`, `model:opus`, `complexity:high`, `blocking`, `project:fab`
Blocks: `milton-product-A-3.4`

**Context:** Stdout parsing is not a sufficient durable outcome/evidence
contract.

**Implementation Steps**:
1. Review and dispatch `commissions/fab-identity-receipts.md` in Fab.
2. Require stable commission, attempt, verifier, artifact, and terminal ids.
3. Accept only with restart/retry and Milton trace receipts.

**Acceptance Criteria**:
- [ ] A disposable job retains explicit George, Fab, and Somm/native ids across
      retry/restart.
- [ ] Fab aggregate cost is typed as a rollup referencing child accounting ids.
- [ ] Milton activity and outcome projection traverse the accepted receipt
      without stdout-text matching.

**Files:** `plans/milton-product/commissions/fab-identity-receipts.md`, target `../fab`

### Task: milton-product-A-3.4 — Ingest stable Fab verifier and artifact receipts

Priority: P1
Labels: `phase-3`, `model:sonnet`, `complexity:medium`, `adapter`
Blocks: `milton-product-A-4.1`

**Context:** Independent proof strengthens outcome and finding corroboration.

**Implementation Steps**:
1. Add format-driven receipt discovery and stable identities.
2. Emit `verifies`/`produced` relations and coverage.
3. Keep artifacts referenced rather than copied by default.

**Acceptance Criteria**:
- [ ] Missing artifacts or verifier services are not treated as failed code.
- [ ] Aggregate/summary receipts cannot create new cost observations.
- [ ] An end-to-end Fab fixture shows verifier and artifact relations in
      activity and outcome attribution evidence.

**Files:** `src/milton/adapters/fab.py`, `tests/test_runtime_adapters.py`, `docs/adapters.md`

### Task: milton-product-A-3.5 — Execute George disposition commission

Priority: P0
Labels: `phase-2`, `model:opus`, `complexity:high`, `blocking`, `project:george`
Blocks: `milton-product-A-2.6`

**Context:** The stale-gate pilot cannot close without canonical action receipts.

**Implementation Steps**:
1. Review and dispatch `commissions/george-finding-disposition.md` in George.
2. Require deduplicated intake, normal authority gates, and disposition export.
3. Accept with a simulated and then live Milton round trip.

**Acceptance Criteria**:
- [ ] George preserves finding id/revision and returns stable disposition ids.
- [ ] No Milton path can directly close or obviate a gate.
- [ ] Re-ingesting the accepted receipt derives one action state through the
      public Milton relation/finding projection.

**Files:** `plans/milton-product/commissions/george-finding-disposition.md`, target `../george`

### Task: milton-product-A-3.6 — Reconcile Somm overlap and export tuple evidence

Priority: P1
Labels: `phase-3`, `model:opus`, `complexity:medium`, `docs`, `integration`
Blocks: none

**Context:** Delegation is incomplete if old surfaces continue claiming the
same retrospective authority or Somm cannot consume the bounded outcome
evidence Milton owns.

**Implementation Steps**:
1. Document retained hot-path/source-local Somm views and Milton-owned history.
2. Export a versioned `(implementation, profile, served model, harness)`
   outcome snapshot with cutoff, coverage, sample, and uncertainty metadata;
   retain per-call evals and bounded policy recommendations in Somm.
3. Demonstrate evidence-only consumption and safe fallback, then plan
   deprecation of arbitrary authoritative OTLP import and global mirrored
   call rows only after coverage gates pass.

**Acceptance Criteria**:
- [ ] Somm and Milton docs agree on every ownership row and dependency direction.
- [ ] Source-local Somm totals identify scope/provenance and do not claim the
      whole system.
- [ ] One integration fixture shows Somm consuming a versioned Milton snapshot
      without automatically changing policy and falling back safely when the
      snapshot is stale, sparse, confounded, or unavailable.

**Files:** `docs/boundaries.md`, target `../somm/README.md`, `../somm/docs/BLUEPRINT.md`

---

## Epic: milton-product-A-4 — Measured synthesis and compounding

Priority: P1
Labels: `phase-3`, `phase-4`, `model:opus`, `complexity:high`, `experiment`

Expand only after the two MVP checkpoints graduate.

### Task: milton-product-A-4.1 — Build the finding-quality evaluation harness

Priority: P1
Labels: `phase-3`, `model:opus`, `complexity:high`, `test`, `risk:high`
Blocks: `milton-product-A-4.2`, `milton-product-A-4.3`, `milton-product-A-4.4`

**Context:** Finding precision must be measured against held-out labeled cases.

**Implementation Steps**:
1. Define case, expected finding/disposition, corpus split, and metric schemas.
2. Bind results to generator/model/harness/parameter/source tuples.
3. Enforce per-generator precision, recurrence, and aggregation floors.

**Acceptance Criteria**:
- [ ] Training/tuning and held-out cases are disjoint and reproducible.
- [ ] Refuted live findings can enter later calibration without rewriting old
      results.
- [ ] The stale-gate generator runs through the same harness used by future
      motifs and its CLI promotion gate consumes the measured result.

**Files:** `src/milton/evaluation.py`, `evals/`, `tests/test_evaluation.py`

### Task: milton-product-A-4.2 — Compare direct analysis with facet clustering

Priority: P1
Labels: `phase-3`, `model:opus`, `complexity:high`, `experiment`, `risk:high`
Blocks: `milton-product-A-4.3`

**Context:** LangSmith, Braintrust, Datadog, AX, and Clio set a high bar; a
clustering pipeline is not automatically justified.

**Implementation Steps**:
1. Freeze a privacy-bounded failure/drift corpus with receipt labels.
2. Run direct model analysis and facet→cluster→describe under equal budgets.
3. Compare precision, stability, operator value, cost, and maintenance burden.
4. If the winning approach uses an external engine or library, publish a
   build-versus-adopt exception record covering its complete license/runtime
   chain, commercial compatibility, offline behavior, pinned provenance,
   transitive security/SBOM review, data exit, and replacement fixture.

**Acceptance Criteria**:
- [ ] Both approaches use the same held-out cases and declared model/harness.
- [ ] The report retains counterexamples and coordination/maintenance cost.
- [ ] Only the winning or deliberately hybrid approach is integrated into the
      finding generator surface; the rejected path remains documented.
- [ ] The selected approach either remains Milton-owned or passes every gate in
      `docs/build-vs-adopt.md`; an open-core/hosted requirement, floating
      installer, missing license-chain review, or failed replacement fixture
      prevents graduation.

**Files:** `experiments/failure-motifs/`, `reports/failure-motif-method-*.md`,
`reports/dependency-decisions/`

### Task: milton-product-A-4.3 — Ship bounded failure-motif and drift findings

Priority: P1
Labels: `phase-3`, `model:sonnet`, `complexity:high`, `logic`
Blocks: `milton-product-A-4.5`

**Context:** This is the synthesis wedge only after an evaluated method wins.

**Implementation Steps**:
1. Implement deterministic facets and the accepted bounded synthesis stage.
2. Add recurrence across independent sessions and receipt corroboration.
3. Emit lead/candidate revisions with privacy thresholds and expiry.

**Acceptance Criteria**:
- [ ] No cluster promotes itself to corroborated without independent evidence.
- [ ] Small/private groups abstain according to declared aggregation policy.
- [ ] A live bounded scan produces reviewable findings whose measured results
      match the frozen evaluation within the allowed tolerance.

**Files:** `src/milton/generators/motifs.py`, `tests/test_generators.py`, `docs/findings.md`

### Task: milton-product-A-4.4 — Audit two memory systems

Priority: P1
Labels: `phase-3`, `model:sonnet`, `complexity:high`, `adapter`, `experiment`
Blocks: `milton-product-A-4.5`

**Context:** Milton audits across stores and does not auto-delete. agentmemory
is useful prior art and an optional existing-operator source, but its required
ELv2 iii engine prevents it from becoming Milton's default dependency.

**Implementation Steps**:
1. Define inventory, loaded, retrieved, referenced, applied, and unknown stages.
2. Implement two read-only adapters over factory-native file/rules/skills and
   decision-memory stores; optionally test agentmemory only when already
   installed, without adding its runtime.
3. Emit keep/park/retire findings only at evidence-supported grades.

**Acceptance Criteria**:
- [ ] Retrieval is not represented as causal application.
- [ ] Missing host signals remain unknown rather than write-only.
- [ ] An end-to-end audit reports coverage for both systems and links one
      reviewed recommendation to a simulated action receipt.

**Files:** `src/milton/adapters/`, `src/milton/generators/memory.py`, `tests/`, `docs/adapters.md`

### Task: milton-product-A-4.5 — Export idempotent Chip procedure candidates

Priority: P2
Labels: `phase-4`, `model:opus`, `complexity:high`, `integration`
Blocks: `milton-product-A-4.6`

**Context:** Chip's current append/tally shape needs a stable source id before
automated repeated export.

**Implementation Steps**:
1. Define Milton finding→Chip candidate mapping with occurrence,
   counterexample, and fixture refs.
2. Commission idempotent candidate/source identity in Chip if absent.
3. Add `findings export --target chip` and receipt import.

**Acceptance Criteria**:
- [ ] Re-exporting one finding revision cannot increase Chip occurrence count.
- [ ] The candidate preserves negative/exception fixtures and source limits.
- [ ] A contract test completes Milton export → Chip ingest → stable candidate
      receipt → Milton relation without private-store access.

**Files:** `src/milton/exports.py`, `tests/test_exports.py`, target `../chip`

### Task: milton-product-A-4.6 — Close one procedure promotion outcome loop

Priority: P2
Labels: `phase-4`, `model:opus`, `complexity:high`, `checkpoint`, `risk:high`
Blocks: none

**Context:** A candidate is not value until independent evaluation, promotion,
and later operational measurement occur.

**Implementation Steps**:
1. Preserve Milton origin on Chip and Spindle evaluation/promotion receipts.
2. Bind evaluation to implementation/profile/model/harness tuple and baseline.
3. Compare post-promotion outcomes and update finding/candidate calibration.

**Acceptance Criteria**:
- [ ] Spindle, not Milton, evaluates and binds the procedure.
- [ ] Fab/Somm receipts identify the exact evaluated tuple and Milton origin.
- [ ] Milton records improvement, regression, or inconclusive outcome and the
      result changes calibration rather than merely closing a task.

**Files:** `src/milton/adapters/spindle.py`, `reports/procedure-promotion-pilot-*.md`, target `../spindle`

---

## Summary

| Epic | Tasks | Priority | Description |
| --- | ---: | --- | --- |
| `milton-product-A-0` | 5 | P0 | Directed relations, finding actions, review surfaces |
| `milton-product-A-1` | 5 | P0 | Conservative cost-per-outcome projection and live audit |
| `milton-product-A-2` | 6 | P0 | Stale-gate detector and one acted-on finding |
| `milton-product-A-3` | 6 | P0/P1 | Somm/Fab/George producer and consumer contracts |
| `milton-product-A-4` | 6 | P1/P2 | Measured motifs, memory audit, and procedure loop |

**Total:** 5 epics, 28 tasks. The first ready slice is
`milton-product-A-0.1`; cross-repo commission tasks remain proposed until the
target owner accepts their contracts.
