# Commission: Somm accounting integrity

**Target repo:** `somm`
**Parent:** Milton ROADMAP Epic A3 — producer contracts and compatibility
**State:** accepted 2026-07-17

**Dispatch:** executed in the sibling `somm` repository under the explicitly
authorized cross-repository refinement.

**Implementation evidence:** Somm schema v22 adds auxiliary-call custody,
provider request/billing ids, origin, and budget eligibility. Shadow gold and
judge requests are ordinary idempotent call rows; OTLP import honors
`somm.call_id`; foreign imports are retained but excluded from native policy
arithmetic.

**Acceptance evidence:** Somm's full suite passes with 806 tests and one
optional OTel-dependency skip. Milton's host-shaped v22 fixture ingests one
production, one gold, and one judge observation; selects exactly their $0.15
sum; excludes the $0.15 campaign rollup; and connects eval, campaign,
decision, recommendation, and late-update receipts through activity.

## Outcome

Every provider request made by Somm—including shadow-eval gold and judge
requests—has one first-class call observation, and a Somm call exported through
OTLP cannot re-enter the authoritative ledger as a second billed call.

This makes Somm trustworthy as the canonical producer for mediated call facts
while leaving cross-source reconciliation and cost-per-outcome in Milton.

## Acceptance criteria

- WHEN shadow evaluation makes a gold or judge provider request, Somm SHALL
  persist a first-class auxiliary call using the returned input/output token
  counts, provider/model, cost provenance, and role
  `shadow_gold|shadow_judge`.
- WHEN an auxiliary call is persisted, Somm SHALL link its stable call id to
  the source call and eval receipt; eval/campaign rollups SHALL reference child
  call ids and SHALL NOT emit another billable observation.
- WHEN shadow-eval budget use is calculated, Somm SHALL sum those auxiliary
  call ids rather than estimate gold spend from the production call's tokens or
  parse cost from JSON notes.
- WHEN a persisted Somm call is exported to OTLP and ingested back into the same
  database, the database SHALL contain exactly one billable call and one amount.
- WHEN an OTLP span carries an existing `somm.call_id`, ingest SHALL attach
  trace/session metadata or no-op idempotently; it SHALL NOT mint another call.
- WHEN an OTLP span references an absent upstream call, the imported row SHALL
  preserve the upstream id, be marked `foreign/imported`, and be excluded from
  budgets, plan pacing, frontier ranking, and recommendations unless explicitly
  opted in.
- WHEN an error span is ingested, it SHALL map to a valid Somm outcome.
- WHEN a provider response exposes a stable request/billing id, Somm SHALL
  preserve it separately from its gateway call id and include it in exports.
- WHEN an amount is stored, Somm SHALL expose basis, kind, accuracy, pricing
  version, billing mode, and source coverage honestly; unknown remains valid.
- An exporter → wire payload → ingester integration test SHALL exercise the
  real round trip, and a Milton fixture scan SHALL see production, gold, and
  judge requests exactly once each.

## Constraints

- Preserve Somm's hot-path routing, fallback, spend gates, plan pacing, call
  ledger, evals, campaigns, recommendation actions, decision memory, and
  one-attempt harness boundary.
- Do not introduce a required Milton dependency or network call in `somm-core`
  or the request path.
- Prefer versioned schema and export fields over reciprocal Python imports.
- Existing legacy rows remain readable with unknown provenance.

## Out of scope

- Cross-source deduplication or cost-per-commit/PR/task.
- General failure motifs, drift, memory cleanup, or procedure mining.
- Storing Fab/George task outcomes as a new canonical Somm table.
- Deleting the global mirror or arbitrary OTLP compatibility before consumers
  and migration behavior are proven.

## Verification evidence

- New migration and model/repository round-trip tests.
- Shadow-eval integration test with actual auxiliary token counts.
- OTLP round-trip idempotency test.
- Milton adapter fixture proving exact billable observation cardinality.
- Existing Somm full suite and Milton accounting suite remain green.

## Accepted verification

- `somm`: `uv run pytest -q` → 806 passed, 1 optional-dependency skip.
- `somm`: changed-source Ruff and format checks pass; repository-wide strict
  mypy remains a pre-existing non-gate with unrelated errors.
- `milton`: `uv run pytest -q` → 75 passed; Ruff, format, and strict mypy pass.
- Focused OTLP + shadow suite: 49 passed.
- Host fixture: 4 cost events, 1 excluded rollup, 3 selected observations,
  selected total `$0.15`, and no adapter-specific duplicate filter.
