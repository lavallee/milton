# Roadmap

**Date:** 2026-07-17
**Source:** [VISION.md](VISION.md)
**State policy:** this file stores sequence and gates, not status. Current state
is re-derived from George, the repository, and live validation receipts.

## Sequence

Milton advances through vertical proofs, not infrastructure-complete phases:

1. make identity, attribution, and finding-action contracts explicit;
2. ship two end-to-end proofs: cost per outcome and one acted-on finding;
3. admit model-assisted synthesis and broader memory analysis only after the
   proof contracts hold; and
4. emit procedure candidates only after findings demonstrate measured value.

The old Phase 0–4 language remains useful as a capability taxonomy in
`docs/workplan.md`, but it is not permission to build all of one horizontal
layer before proving user value.

## Outcome A — Whole-work truth

### Epic A1 — Deterministic cost-per-outcome projection

**Target:** Milton
**Outcome:** selected accounting observations join to Fab terminal receipts,
George work, and Git commits without hiding ambiguous or unallocated spend.

Deliver a typed attribution record, explicit method precedence, a
`milton cost --per-outcome` projection, and event-by-event explanation. The
first version must prefer abstention to fractional or temporal guesswork.

**Graduation threshold**

- ten representative live traces can be reconstructed from cost observation
  to outcome or an explicit unallocated reason;
- no multiply reachable cost is silently assigned to more than one economic
  outcome; and
- raw selected spend equals attributed plus ambiguous plus unallocated spend.

**Kill or narrow if**

- fewer than half of Fab-mediated priced observations reach even a runner
  terminal outcome after explicit identity propagation; narrow the product to
  runner-level outcomes until richer joins exist; or
- useful totals require time-window or token-count matching presented as fact.

### Epic A2 — Shared billable identity and economic-kind receipts

**Target:** Somm, with a separate Fab propagation commission
**Outcome:** future mediated and native observations carry the provider request
or billing coordinate and declared marginal/notional/included semantics when
the source actually knows them.

Somm retains its canonical per-call ledger and hot-path behavior. Fab propagates
caller and task coordinates but does not mint provider identity. Milton consumes
the fields and remains conservative when they are absent.

**Graduation threshold**

- fixtures prove a provider request id survives provider → Somm/harness → Fab
  receipt → Milton event where available;
- one live supported-provider path reproduces the fixture result, or a named
  unavailability report establishes why no current provider exposes the id;
- the source of cost kind and pricing version is inspectable; and
- replay produces one shared accounting group without collapsing distinct
  economic kinds.

**Kill or narrow if**

- a provider or harness does not expose a stable request/billing id; retain a
  source-local key and stop instead of manufacturing one.

### Epic A3 — Outcome-conditioned routing export

**Target:** Milton; Somm is the consumer
**Outcome:** Somm can improve `(provider, model, harness, profile)` selection
from versioned task-outcome evidence without becoming the canonical task-outcome
store.

This P1 epic starts only after the cost-per-outcome and stale-gate MVP proofs
graduate. The first export is evidence, never an automatic routing change.

**Graduation threshold**

- the export binds results to the exact implementation/profile/model/harness
  tuple and source outcome ids;
- a predeclared minimum sample, uncertainty interval, confound review, source
  cutoff, and freshness rule are present;
- Somm can reproduce one route comparison from the exported snapshot without
  automatically changing policy; and
- deleting the cache in Somm loses no canonical outcome history.

**Kill or narrow if**

- the sample is too sparse or confounded to support a route change; expose it
  as evidence, not a recommendation.

## Outcome B — Graded operational findings

### Epic B1 — Finding review and action-receipt lifecycle

**Target:** Milton
**Outcome:** findings can be generated, listed, inspected, corroborated,
refuted, expired, and linked to authoritative actions without mutating source
systems.

**Graduation threshold**

- every current finding has a reproducibility manifest and valid evidence;
- every grade transition is append-only and reviewable; and
- representative lead→review→refute and lead→review→action fixture flows both
  pass, so the lifecycle cannot graduate with zero adjudicated findings; and
- `acted-on` is derived from a typed directed relation to an external receipt,
  never toggled as a boolean in the finding ledger.

**Kill or narrow if**

- the lifecycle creates a second task/decision tracker; keep George canonical
  and reduce Milton to read-only finding plus receipt references.

### Epic B2 — Stale and re-minted George gate pilot

**Target:** Milton, with a George consumer commission
**Outcome:** deterministic findings identify gates whose condition is already
resolved, whose coordinate is repeatedly re-minted, or which are old and never
consulted. George accepts, refutes, or retires them and returns receipts.

This epic manifests the live George shaping item
`01KXRRSBQAES74FH9DWZMAWZ0Z` without giving Milton authority to close gates.

**Graduation threshold**

- a labeled sample establishes at least 90% precision for automatically
  surfaced high-confidence candidates;
- at least one accepted finding retires or deduplicates a real gate and is
  counted as acted-on; and
- the resulting decision burden is lower than the baseline queue.

**Kill or narrow if**

- reviewed precision falls below 80%, or the detector produces more operator
  work than it removes; retain it as an offline audit only.

### Epic B3 — Failure motifs and drift with measured precision

**Target:** Milton
**Outcome:** deterministic facets plus bounded clustering produce graded leads
over recurring failures and behavioral drift, corroborated by independent
receipts when possible.

**Graduation threshold**

- a held-out labeled corpus and generator tuple are versioned;
- each promoted motif meets its declared precision and recurrence floor across
  independent sessions; and
- refutations are retained and alter later calibration.

**Kill or narrow if**

- a frontier model analyzing a bounded transcript set directly matches the
  pipeline at lower maintenance cost; retain only adapters, manifests, evidence,
  and grading.

### Epic B4 — Memory read-back audit

**Target:** Milton
**Outcome:** at least two memory systems expose what exists, what was loaded,
what was consulted, and what appears write-only, without auto-deletion.

**Graduation threshold**

- coverage distinguishes unavailable read evidence from evidence of non-use;
- reviewed keep/park/retire recommendations meet their precision floor; and
- at least one accepted retirement is linked back as an action receipt.

**Kill or narrow if**

- the host exposes no trustworthy read/load signal; report inventory and
  unknown consultation rather than infer write-only status.

## Outcome C — Compounding procedure

### Epic C1 — Evidence-bearing procedure candidate feed

**Target:** Milton; Chip and Spindle are consumers
**Outcome:** recurring successful work shapes become candidate records with
occurrence refs, counterexamples, counts, fixture material, and scope limits.

**Graduation threshold**

- a candidate is accepted by the Chip contract without lossy translation;
- repeated export of the same candidate/occurrence preserves one source row and
  does not inflate recurrence counts;
- Spindle can evaluate it without reading Milton's private store directly; and
- the candidate includes negative and exception fixtures, not only successes.

**Kill or narrow if**

- candidates merely restate prompts or cannot separate dialogic judgment from
  stable operational procedure.

### Epic C2 — Promotion outcome measurement

**Target:** Milton
**Outcome:** Milton compares the post-promotion outcome to the baseline that
motivated a procedure candidate and records success, regression, or uncertainty.

**Graduation threshold**

- one promoted candidate has a pinned implementation/model/harness evaluation
  tuple, baseline, and post-promotion outcome; and
- the result changes candidate or source calibration.

**Kill or narrow if**

- the change cannot be isolated from model, harness, or workflow changes;
  retain an inconclusive outcome instead of claiming improvement.

## Cross-cutting release gate

Before calling the first Milton release operational:

- the package is built from a clean committed tree;
- CI passes on supported Python versions with dependency and workflow audits;
- trusted publishing or another explicit release path is present and tested;
- the default install starts no service and performs no network transmission;
- every runtime dependency has a recorded full-stack license/exit review,
  pinned provenance, and security justification; no load-bearing feature
  depends on open-core or hosted-only code;
- public docs distinguish implemented commands from roadmap commands; and
- one clean-machine smoke test ingests a fixture corpus and reproduces the
  accounting, attribution, and finding manifests.

## Roadmap-to-work traceability

| Roadmap epic | Itemized work | External contract/checkpoint |
| --- | --- | --- |
| A1 — cost per outcome | `A-1.1`–`A-1.5` | Ten-trace conservation checkpoint |
| A2 — billable identity | `A-3.1`–`A-3.4` | Somm and Fab commissions |
| A3 — routing evidence | `A-3.2`, `A-3.6` | Optional Somm snapshot and fallback proof |
| B1 — finding lifecycle | `A-0.1`–`A-0.5` | Trust-contract live checkpoint |
| B2 — stale gates | `A-2.1`–`A-2.6`, `A-3.5` | George disposition commission and live action |
| B3 — motifs and drift | `A-4.1`–`A-4.3` | Held-out direct-versus-clustering decision |
| B4 — memory audit | `A-4.1`, `A-4.4` | Two-store audit and reviewed disposition |
| C1 — procedure feed | `A-4.5` | Idempotent Chip export proof |
| C2 — promotion outcome | `A-4.6` | Spindle/Fab/Somm receipt loop |

The itemized identifiers are execution coordinates, not alternate roadmap epic
names. [`plans/milton-product/README.md`](plans/milton-product/README.md)
preserves the full lineage.

## Current derived signal

At the date above, the itemized plan has 27 complete tasks and one narrowed
task. The retained checkpoints support A1, B1, B3, C1, and C2 at their declared
scope. A2's producer contracts are accepted while live provider-request-id
coverage remains source-dependent. A3 is implemented as evidence-only and is
not authorized to change routing. B2 is narrowed to offline audit because its
only live review added burden and retired no gate. B4 has stage-honest
inventory/readback coverage, but no trustworthy live access signals or real
accepted retirement, so it has not met its product graduation threshold.

The first operational release is not yet declared. The Forge OSS review added
the family repository shape, an OIDC publish workflow, and a retained
clean-wheel corpus smoke. Local isolated Python 3.12 and 3.13 runs now reproduce
the accounting, attribution, and finding manifests and pass dependency and
workflow audits. A release declaration still requires this candidate to pass
CI from a committed review branch, the PyPI trusted publisher to be registered
and exercised, a clean tagged tree, and a post-publish install verification.
