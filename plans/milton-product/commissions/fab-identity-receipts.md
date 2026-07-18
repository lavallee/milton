# Commission: Fab identity and evidence receipts

**Target repo:** `fab`
**Parent:** Milton ROADMAP Epics A1/A2 — cost-per-outcome and shared identity
**State:** accepted; implemented and independently ingested

## Outcome

Every Fab attempt and terminal job preserves the caller's George commission or
todo coordinate, the Somm/native harness attempt coordinate, and stable
verifier/artifact receipt ids so Milton can attribute selected cost to outcomes
without reading worktrees or counting Fab rollups as new spend.

## Acceptance criteria

- WHEN George dispatches work to Fab, Fab SHALL persist the George entry id and
  commission revision/fingerprint on the job and every attempt.
- WHEN Fab starts a Somm or native harness attempt, it SHALL propagate the Fab
  job/attempt and George coordinates through the supported correlation/session
  fields; it SHALL NOT manufacture a provider request id.
- WHEN an attempt completes, Fab SHALL persist stable attempt, verifier, and
  artifact receipt coordinates independently of stdout parsing.
- WHEN Fab records any aggregate cost, the record SHALL reference child Somm or
  provider accounting keys and be typed as a rollup; absent child keys, it SHALL
  remain a non-counting observation.
- WHEN a job reaches a terminal state, Fab SHALL emit one typed relation from
  attempt to job and one semantic outcome receipt with terminal reason.
- WHEN the daemon restarts or retries, replay SHALL not mint duplicate receipt
  identities or continue superseded work.
- A host-shaped fixture SHALL prove George → Fab job → attempt → Somm/native
  session → terminal/verifier/artifact receipts through stable ids.
- A Milton activity and cost-per-outcome integration test SHALL traverse the
  chain without timestamp, hash, stdout-text, or token-count matching.

## Constraints

- Fab remains the durable supervised-run owner: retries, worktrees, leases,
  verification, repair, release, and terminal semantics stay in Fab.
- Somm remains the one-attempt/model-harness owner.
- George remains the intent and decision owner.
- Existing receipts are extended or versioned; Milton does not become a Fab
  runtime dependency.

## Out of scope

- Cross-source accounting selection or outcome allocation policy.
- Provider billing identity generation.
- Model/harness recommendation logic.
- General workflow language or new task database.

## Verification evidence

- `fab.execution-receipt/v1` now persists job, attempt, runtime/semantic
  outcome, verifier, and artifact records. The deterministic attempt coordinate
  is propagated as correlation for direct Somm and Somm-owned Claude/Codex/
  OpenCode harness adapters; supported native call/session ids are recovered by
  the producer after quiescence.
- `tests/test_execution_receipts.py`, `tests/test_somm_runner.py`, the backend
  adapter tests, and process-custody/e2e coverage prove stable replay,
  correlation propagation, native sidecars, and terminal publication. Fab's
  full suite passes: 469 tests.
- Milton's `tests/test_fab_receipts.py` proves George → Fab job → attempt →
  Somm call → terminal/verifier/artifact traversal with exact ids, two excluded
  Fab rollups, one selected `$0.25` observation, and unchanged replay. Milton's
  full suite, Ruff, format, and strict mypy pass: 76 tests.
- The safe disposable runtime proof and retained output are in
  [`reports/fab-receipt-checkpoint-2026-07-17.md`](../../../reports/fab-receipt-checkpoint-2026-07-17.md).

## Acceptance notes

- Fab remains the only job/attempt/retry/terminal owner. Milton is a read-only
  consumer and never enters Fab's runtime dependency graph.
- The JSONL ledger remains chronology; receipts are the exact identity and
  evidence surface. Milton suppresses corresponding ledger rows and stdout
  discovery when a current receipt exists, while retaining legacy fallback.
- Fab never manufactures a provider request id. Its rollups are source-local,
  non-counting observations and enumerate only child keys it actually knows.
- Current attempt-scoped correlation is owned directionally by the Fab
  finished receipt. Somm keeps the exact association but only emits the legacy
  job→call relation for old job-scoped correlation, avoiding duplicate relation
  producers.
