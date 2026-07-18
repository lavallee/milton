# Somm overlap and tuple-evidence checkpoint — 2026-07-17

## Decision

Accept A-3.6. Somm retains its hot-path and source-local responsibilities;
Milton owns coverage-declared cross-source history and cost-per-outcome. The
dependency boundary is a versioned JSON evidence document, not a Python or
runtime dependency in either routing path.

| Concern | Authority |
| --- | --- |
| One mediated call, returned usage, local computed/reported cost | Somm |
| Budget admission, plan pacing, quota learning, fallback | Somm |
| Per-call evals, campaigns, bounded recommendations | Somm |
| Native Somm spend/status totals | Somm, explicitly source-local |
| Exact cross-source accounting selection | Milton |
| Fab/George/Git outcome attribution | Milton |
| Tuple outcome evidence | Milton document; Somm validates evidence only |
| Route/policy change | Somm decision path; never automatic from snapshot |

## Contract

`milton evidence export-tuple` emits `milton.outcome-tuple/v1` for one exact
`(Git implementation, Somm profile/workload id, served model, Fab/native
harness)` tuple. It carries an inclusive start when supplied, exclusive cutoff,
source coverage, minimum sample, selected cost split by economic kind, outcome
status counts, attribution/path ids, and explicit
`ready|sparse|confounded|unavailable` producer uncertainty. Its declared policy
effect is always `evidence_only`.

`somm.assess_outcome_snapshot()` has no Milton import and no mutation hook. It
requires the exact expected tuple and independently checks schema, cutoff,
freshness, sample floor, ambiguity/unallocated counts, and producer state.
`ready` only sets `eligible_for_review=true`; every result keeps
`policy_changed=false` and `policy_action=null`.

## Cross-repository proof

An executable disposable fixture built a real Milton snapshot from one exact
Somm-call → Fab-attempt → Git-commit attribution path and passed the resulting
document directly to Somm's consumer. It also exercised the fallback controls:

```json
{
  "consumer_states": {
    "confounded": "confounded",
    "ready": "ready",
    "sparse": "sparse",
    "stale": "stale",
    "unavailable": "unavailable"
  },
  "producer_state": "ready",
  "proof_root": "/tmp/milton-somm-tuple-3np854yv",
  "ready_policy_action": null,
  "ready_policy_changed": false,
  "schema": "milton.outcome-tuple/v1",
  "snapshot_id": "mts_f3bd9dd55f123498dec4b08b",
  "tuple": {
    "harness": "codex",
    "implementation": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "profile": "profile-1",
    "served_model": "model-1"
  }
}
```

Milton unit/CLI coverage lives in `tests/test_tuple_evidence.py`; Somm consumer
and negative controls live in `packages/somm/tests/test_outcome_evidence.py`.

## Deprecation posture

No global call mirror or arbitrary OTLP import was removed. Native OTLP replay
now attaches by `somm.call_id`; genuinely foreign imports are explicitly
`foreign_imported` and non-policy. Removing broader import/mirror surfaces
would be a separate compatibility change and remains gated on demonstrated
adapter coverage, data-exit evidence, and a migration plan. The accepted
boundary does not need that destructive step.

## Verification

- Milton: 80 tests, Ruff, format, and strict mypy passed before this report.
- Somm focused consumer: 6 tests and changed-source Ruff/format passed.
- Somm full suite: 812 passed, 1 optional OpenTelemetry skip.
