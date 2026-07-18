# Fab receipt checkpoint — 2026-07-17

## Decision

Accept the Fab identity-receipts producer contract and Milton's receipt-first
adapter. The safe disposable proof preserved one George entry, one Fab job and
attempt, one Somm call, one verifier, one commit artifact, and both runtime and
semantic terminal outcomes through exact producer ids. Milton selected and
attributed `$0.25` once while excluding both Fab rollups.

## Disposable proof

The proof ran Fab's real queue, process-custody, classifier, policy, and
terminal publication path in a temporary state directory. To avoid external
model spend, the `somm` backend was replaced in-process by the existing noop
subprocess while still writing the native call sidecar; a host-shaped Somm
SQLite row supplied the corresponding computed/estimated `$0.25` observation.
Verifier, artifact, and semantic delivery receipts were written through Fab's
public producer functions, then the ordinary Fab and Somm adapters ingested the
result.

Retained console result:

```json
{
  "attempt_id": "20260717T234911_4878dd:attempt:0",
  "attributed_usd": "0.25",
  "fab_rollups": 2,
  "job_id": "20260717T234911_4878dd",
  "proof_root": "/tmp/milton-fab-proof-elyk04fs",
  "receipt_kinds": [
    "artifact",
    "attempt_finished",
    "attempt_started",
    "delivery_outcome",
    "job_outcome",
    "job_submitted",
    "verifier"
  ],
  "related_identities": 7,
  "selected_usd": "0.25"
}
```

This is a custody/integration proof, not a provider-billing claim. The sole
monetary row is explicitly `computed`, `estimated`, and `marginal`.

## Reproducible gates

- Fab: `uv run pytest -q` → `469 passed`.
- Fab changed-source lint: `uv run ruff check ...` → passed.
- Milton: `uv run pytest -q` → `76 passed`.
- Milton: `uv run ruff check src tests`, `uv run ruff format --check src tests`,
  and `uv run mypy --strict src/milton` → passed.
- `tests/test_fab_receipts.py` is the dependency-free host-shaped regression:
  it asserts the full relation chain, two excluded Fab rollups, one selected
  `$0.25` production observation, exact Fab-job attribution, and unchanged
  replay.

## Refinement learned

Current Fab correlation is attempt-scoped: `<job>:attempt:<n>`. Somm therefore
keeps that value as an exact association but does not independently assert the
same directed attempt-to-call relation; the finished Fab receipt owns that
assertion. Legacy job-scoped Somm correlation retains the older
`fab.job --produced--> somm.call` projection. This prevents two producers from
creating competing revisions of one relation while preserving legacy traces.
