# Orient Report: Milton Product

**Date:** 2026-07-17
**Depth:** deep
**Status:** Proposed planning interpretation; experiments and promotion gates remain open

---

## Executive Summary

Milton is a local-first retrospective intelligence layer over heterogeneous LLM
agent exhaust. It earns its place by joining work, cost, outcomes, recurring
failures, memory use, and procedure changes without requiring one gateway or
SDK and without duplicating source systems' canonical state.

The smallest product proof is not “all adapters work.” It is two vertical
outcomes: a conservative cost-per-outcome projection and one graded finding
that causes a receipted change. The live stale/duplicated George-gate problem is
the first finding pilot.

## Problem Statement

People operating multiple agents can inspect individual transcripts, gateway
spend, runner jobs, and repository outcomes, but cannot reliably answer across
those layers:

- which observations describe the same work or economic event;
- what selected spend belongs to which completed, failed, reverted, or
  abandoned outcome;
- which failure or behavior patterns recur across sessions;
- which memories, rules, or gates are consulted versus merely accumulated; and
- whether a finding actually changed the operating system.

Existing products solve valuable subsets—trace clustering, local workload
analysis, cost-per-commit formulas, or memory retention—but this review found
no verified offering that combines heterogeneous post-hoc evidence, exact
reconciliation, real outcome joins, graded findings, and action receipts.

## Refined Vision

Build a dependency-light local library and CLI that reads native operational
exhaust, preserves source authority and uncertainty, derives cross-source
projections, emits graded evidence-bearing findings, and proves when those
findings lead to authoritative external actions.

Milton owns no gateway, runner, task tracker, memory runtime, skill registry, or
external research corpus. It owns the retrospective joins and projections that
none of those systems can produce alone.

## Requirements

### P0 — Must Have

- Reconcile selected cost observations using exact billable identity,
  provenance, economic kind, and explicit precedence; retain raw observations
  and an unallocated remainder.
- Attribute cost to Fab terminal receipts, George work, and Git outcomes using
  typed methods; never silently assign ambiguous work.
- Expose `milton cost --per-outcome` in stable JSON and human-readable forms,
  including the complete attribution path and coverage gaps.
- Add an append-only finding review lifecycle with generation manifests,
  evidence validation, refutation, expiry, and action-receipt references.
- Derive `acted-on` from a typed directed relation to a canonical
  George/Git/Fab/Spindle receipt rather than store it as mutable finding
  status.
- Implement the deterministic stale/re-minted George-gate pilot with a labeled
  precision gate; Milton proposes and George decides or acts.
- Preserve the ownership boundary: Somm remains hot-path and independently
  operable; Fab owns run outcomes; George owns intent/actions; Projector owns
  external intelligence; Spindle owns binding.
- Close known source-contract holes before claiming complete accounting:
  provider/shared billing ids, shadow-evaluation call custody, and idempotent
  OTLP round trips.
- Keep metadata-only privacy and coverage honesty as schema-level defaults.

### P1 — Should Have

- Import merged, reverted, closed-unmerged, and review-burden outcomes from an
  authoritative GitHub or equivalent source.
- Export outcome-conditioned `(implementation, profile, served model,
  harness)` observations for Somm routing without making Somm the canonical
  task-outcome ledger.
- Add failure-motif and drift generation using deterministic facets before
  bounded model-assisted clustering.
- Ship a held-out labeled finding corpus, precision floors, aggregation/privacy
  thresholds, and calibration from retained refutations.
- Audit at least two memory systems. Prefer factory-native file/rule/decision
  stores; an agentmemory adapter is optional for operators who already run it,
  because its required iii engine does not pass the complete-open-source gate.
- Compare TraceLab's normalization, cache-accounting, sanitization, validator,
  and reproducible-artifact mechanisms before extending overlapping code.
- Provide list/show/review/export CLI surfaces for findings and their evidence.

### P2 — Nice to Have

- Emit Chip-compatible procedure candidates with occurrence refs,
  counterexamples, and fixture material.
- Measure post-promotion outcomes for Spindle-bound procedures.
- Accept OTel/network or provider-billing exports as optional adapters without
  making them foundational.
- Add a read-only human explorer only after query and finding contracts have
  proven useful.

## Constraints

- Python 3.12+, dependency-free core and built-in local adapters.
- SQLite remains the rebuildable event/crosswalk index at Lisbon scale;
  append-only JSONL remains the finding history.
- Raw source bodies stay in their owning stores by default; Milton records
  typed projections and source coordinates.
- No service, telemetry, network transmission, or API key is introduced by the
  default install.
- Strategic evidence semantics are vertically integrated by default. Adoption
  requires a completely open load-bearing stack, local operation/export,
  replacement proof, pinned provenance, and a material complexity or safety
  advantage over owning the mechanism.
- Model-assisted stages use a pluggable seam and bind results to generator,
  model, harness, inputs, and source snapshot.
- No time/hash/token fuzzy match is promoted as exact identity.
- Consequential actions remain human- or owner-system-gated.

## Assumptions

- Fab, George, Somm, Git, and native harnesses continue to expose stable ids or
  can be commissioned to propagate them.
- A useful first product can be personal/local while preserving contracts that
  later support team-scale corpora.
- The strongest early finding is deterministic; clustering is not required to
  prove the finding/action loop.
- Somm can consume a versioned derived projection or feature snapshot without
  taking a required Milton dependency.

## Open Questions / Experiments

- **Attribution coverage:** how much selected spend reaches a unique meaningful
  outcome? → Run the ten-trace Phase A1 audit and report attributed,
  ambiguous, and unallocated shares.
- **Outcome unit:** commit, PR, George task, or Fab job? → Preserve all as typed
  outcomes; pilot landed change and runner terminal outcome rather than force
  one universal denominator.
- **Finding value:** does stale-gate detection reduce operator burden? → Label a
  sample, measure precision and queue reduction, and require one external action
  receipt.
- **Synthesis complexity:** does a clustering pipeline outperform direct model
  analysis enough to justify maintenance? → Run both against the same held-out
  corpus and retain the simpler winner.
- **Memory causality:** can a host prove a memory was applied rather than only
  loaded? → Record the strongest available stage and leave causality unknown
  where evidence stops.
- **Route feedback:** is outcome-conditioned routing statistically useful? →
  Export evidence first; allow Somm to change policy only after sample and
  confound gates pass.

## Out of Scope

- General tracing SaaS, dashboards-first observability, live agent control, or
  mandatory SDK instrumentation.
- Gateway routing, provider fallback, in-flight budgets, or plan pacing.
- Runner retries, worktrees, verification, release, or approvals.
- External technology scouting and research recommendation.
- Memory capture/retrieval runtime, automatic forgetting, or automatic cleanup.
- Skill composition, binding, or a general workflow/chip runtime.

## Risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Cross-source joins remain sparse | High | Treat unallocated spend as a first-class result; commission ids only where the source can supply them |
| Milton and Somm both grow historical spend/outcome products | High | Keep Somm source-local and hot-path; make cross-source retrospective projections canonical in Milton |
| Findings become cluster-shaped noise | High | Deterministic first pilot, held-out labels, precision floors, aggregation thresholds, retained refutations |
| Action receipts recreate a task tracker | High | Store references and derived joins only; George/Git/Fab/Spindle remain canonical |
| Sensitive transcript content leaks | High | Metadata default, hashes/lengths, explicit full-content opt-in, local-only stages |
| Adapter treadmill consumes the roadmap | Medium | Conformance fixtures, coverage declarations, borrow compatible TraceLab mechanisms, prioritize high-value corpora |
| Competitors commoditize one feature | Medium | Defend the combined evidence → outcome → finding → action contract, not a single visualization |
| Procedure mining duplicates Forge/Spindle | Medium | Milton emits evidence candidates only; Forge plans commissions and Spindle evaluates/binds |
| A public repo hides a closed engine, enterprise requirement, or hosted lock-in | High | Audit the complete load-bearing license/runtime/exit path; treat open-core and source-available systems as inspiration or optional adapters |
| Vertical integration recreates complex commodity infrastructure badly | Medium | Own compact strategic semantics; adopt mature databases, parsers, cryptography, or numerical engines only behind narrow replaceable interfaces after a written exception |

## MVP Definition

From one local store, an operator can:

1. run a conservative cost-per-outcome projection that reconciles to selected
   spend and explains every attribution or abstention;
2. generate and review stale/re-minted George-gate findings with evidence and a
   declared precision result; and
3. resolve or refute one finding in George and see Milton derive the matching
   disposition; only a verified change increases acted-on findings, while a
   refutation increases adjudicated findings and calibrates the detector.

The MVP is incomplete if either proof requires reading raw SQLite manually,
silently guesses identity, mutates George directly, or counts a generated
finding as an outcome.

---

**Next:** technical design in [architecture.md](architecture.md).
