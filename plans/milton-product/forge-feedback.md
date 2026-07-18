# Forge skill feedback ledger

This ledger captures possible improvements discovered while using Forge to
orient, architect, itemize, commission, and execute Milton. An entry is not an
upstream recommendation until Milton supplies concrete evidence that it is a
repeatable workflow problem.

## States

- `candidate`: observed once and worth watching.
- `validated`: reproduced or materially affected execution.
- `upstreamed`: delivered to the Forge source with its evidence.
- `declined`: intentionally kept project-local or disproved.

## Observations

### F-001 — Pair itemization with execution-state validation

- State: `validated`
- Skills: itemize, commission
- Observation: the Markdown task DAG and JSONL projection are useful static
  artifacts, but neither is an execution ledger. A later dependency refinement
  also has to remain synchronized across both projections.
- Milton evidence: the A-4.2 build/adopt refinement required coordinated plan
  edits; implementation then needed a separate 28-task status/evidence ledger.
- Possible upstream change: generate or validate projections from one canonical
  task model, and optionally scaffold a progress ledger whose statuses cannot be
  confused with the task definition.
- Validation: it recurred in A-2. The progress projection still used an older
  A-2.3–A-2.5 task naming/order after the canonical itemized plan had split out
  evaluation and corpus work. Execution had to realign the ledger before A-2.5
  could be claimed. A single canonical task model plus generated projections is
  ready for an upstream change.
- A-3 follow-up: it recurred again. The progress ledger still named the older
  producer-contract breakdown while the canonical itemized plan named the
  Somm/Fab/George commissions and adapters separately. Acceptance required a
  second manual realignment before A-3.1/A-3.2 could be recorded honestly.
- A-4 follow-up: it recurred a third time. The progress rows labeled A-4.3 as
  memory hygiene and shifted the remaining task names, while the canonical
  itemized plan assigns A-4.3 to motifs, A-4.4 to memory, A-4.5 to Chip, and
  A-4.6 to the promotion loop. Execution realigned the projection again before
  recording A-4.3. This is now strong evidence for generating all projections
  from one canonical task model rather than maintaining parallel prose tables.

### F-002 — Make current-state and target-state labels explicit

- State: `validated`
- Skills: orient, architect
- Observation: architecture documents can read as if proposed contracts already
  exist unless every major surface distinguishes current, planned, and proven
  state.
- Milton evidence: the execution ledger explicitly treats existing foundations
  as foundations rather than task-completion evidence.
- Possible upstream change: add a current/target/proof pass to architecture and
  roadmap review templates.
- Validation: A-0.5 changed two adapter relations from target to executable and
  required the adapter guide to split current exact relations from the larger
  planned producer surface. Without the state label, “none executable today”
  became false while the broader gaps remained real.

### F-003 — Record acceptance state separately from dispatch state

- State: `validated`
- Skills: commission
- Observation: planned, dispatched, implemented, validated, and accepted are
  distinct states; collapsing them makes checkpoint work look complete early.
- Milton evidence: several plan tasks require cross-repository or live evidence
  after local implementation.
- Possible upstream change: commission output should provide separate fields for
  implementation and acceptance evidence, especially for live checkpoints.
- Validation: A-0.1 through A-0.4 were locally implemented and green before
  A-0.5 supplied live acceptance. The live check then found both a missing
  exclusive window and an unreachable Git coordinate that fixtures did not.
- Possible upstream action: add explicit `implementation_evidence` and
  `acceptance_evidence` fields to commissioned checkpoint tasks. Re-evaluate
  the exact schema after A-1.5 before upstreaming.
- A-1.5 follow-up: the split held again. A-1.1 through A-1.4 were implemented
  and fully green before the live sample established acceptance; the live
  sample then narrowed the supported claim to a conservative projection with
  explicit producer-contract dependencies. The proposed field split is ready
  for an upstream patch after its owning Forge skill/template is located.
- A-3 follow-up: Somm implementation was green before Milton's independent
  host-shaped consumer fixture established acceptance. The commission now
  records dispatch, implementation evidence, and acceptance evidence as
  separate fields.
- A-4.5 follow-up: Milton's exporter and Chip's commissioning helper were each
  locally green before the actual two-repository replay proved acceptance:
  the same revision returned the same receipt, appended no duplicate, and
  re-entered Milton through the public receipt boundary. Cross-repository
  commissions should name that consumer-driven acceptance test separately
  from each repository's implementation suite.

### F-004 — Require positive and abstention examples at live checkpoints

- State: `validated`
- Skills: itemize, commission
- Observation: a ten-trace sample containing only valid abstentions can satisfy
  conservation and per-trace reason criteria without proving the vertical
  positive path the checkpoint is meant to graduate.
- Milton evidence: the first A-1.5 store had exactly ten cross-source
  observations and conserved perfectly, but all ten lacked an outcome path. It
  was preserved as a partial checkpoint and replaced with a ten-trace sample
  containing one exact Fab→Somm outcome and nine honest abstentions.
- Possible upstream change: checkpoint task templates should name the minimum
  positive, negative/abstention, and replay/control evidence when the product
  claim depends on all of them.
- Validation: A-2.6 reproduced the problem. One valid refutation proved receipt
  plumbing but could not satisfy the product claim that an accepted finding
  removes a real gate and lowers burden. The checkpoint correctly narrowed B2
  only because the roadmap separately named that positive path. Forge
  checkpoint templates should require a minimum accepted/acted positive plus a
  refuted/abstention control whenever graduation depends on both.

### F-005 — Bind checkpoint claims to an evidence level

- State: `validated`
- Skills: architect, itemize, commission
- Observation: a fully green cross-repository loop can prove contract custody
  and narrow behavioral improvement without proving broad production efficacy.
  Checkpoint language needs to say which level is actually graduating.
- Milton evidence: A-4.6 used real local-model calls, an independently owned
  Spindle bind, and exact Chip/Fab/Somm receipts. It measured improvement on a
  frozen policy-adherence corpus and one fresh synthetic operational case, but
  that does not estimate effect on arbitrary production work. The explicit
  limitation prevented “real model” from silently becoming “production
  efficacy.”
- Possible upstream change: checkpoint templates should require a declared
  `claim_level` (contract, synthetic behavior, shadow/live behavior, or
  production outcome), the evidence needed for that level, and explicit
  non-claims. Paired comparisons should also require symmetric producer-native
  baseline and variant custody rather than accepting one native arm plus one
  free-form baseline label.

## Upstream activity

No Forge change has been upstreamed yet.
