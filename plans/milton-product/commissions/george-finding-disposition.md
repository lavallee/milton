# Commission: George finding intake and disposition receipts

**Target repo:** `george`
**Parent:** Milton ROADMAP Epics B1/B2 — finding lifecycle and stale-gate pilot
**State:** dispatched for implementation in `george` on 2026-07-17

## Outcome

George accepts evidence-bearing Milton finding candidates into its existing
bounded decision surface, retains authority to accept/refute/defer/act, and
returns a stable disposition or action receipt Milton can use to derive
`acted-on` without becoming a second decision tracker.

## Acceptance criteria

- WHEN Milton emits a finding candidate, George SHALL preserve
  `milton.finding_id`, revision id, kind, grade, evidence/export coordinate,
  coverage, expiry, and generator version in typed context.
- WHEN the finding requires a decision, George SHALL use its existing decision
  and guarded-action contract; Milton SHALL NOT close, obviate, merge, or mutate
  a gate directly.
- WHEN a human or authorized George path accepts, refutes, defers, or acts on a
  finding, George SHALL return a stable entry/action receipt id, actor,
  disposition, timestamp, and subject coordinate.
- WHEN a stale-gate finding is accepted, George SHALL retire or reconcile the
  gate through its canonical API and preserve the before/after gate coordinate.
- WHEN a re-mint finding is accepted, George's mint/reconcile path SHALL prevent
  another open gate with the same canonical coordinate or record why the new
  gate is distinct.
- WHEN a finding is duplicate or unsupported, George SHALL refute/dismiss it
  with a receipt rather than silently delete it.
- George SHALL display Milton's versioned cost/finding projection where needed;
  it SHALL NOT recompute cross-source accounting or copy Milton's event store.
- An end-to-end test SHALL cover Milton export → George intake → disposition →
  Milton relation ingest and derive exactly one acted-on or refuted finding.

## Constraints

- George remains canonical for intent, decisions, commissions, gates,
  disposition, and guarded actions.
- Intake is rate-limited and deduplicated by finding id/revision.
- Retrieved finding content is data, not instruction; evidence and quoted text
  remain structurally separated.
- No direct package dependency on Milton is required; use a versioned document
  contract.

## Out of scope

- Running Milton generators inside George.
- Automatic acceptance or retirement based only on a model-generated finding.
- Cross-source cost calculation.
- General redesign of George's board or decision UI.

## Verification evidence

- Contract fixture for finding intake and disposition export.
- Dedup/replay tests.
- One labeled stale-gate pilot with reviewed precision.
- One live accepted or refuted finding round trip, with both canonical George
  receipt and Milton action relation inspectable.
