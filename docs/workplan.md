# Workplan: footprint and phases

Status: pre-build commission, 2026-07-17. The build starts in its own
session; this document is the contract for what gets built and in what
order.

## Package footprint

Family-standard shape (the somm/chip pattern):

- `milton-agents` on PyPI, import package `milton`, src layout, hatchling,
  MIT, Python ≥3.12.
- **Light core, adapter extras.** Core = the normalized event model, the
  findings/grading ledger, the ID crosswalk, the store, and the query/CLI
  surface — minimal dependencies. Each adapter is an extra
  (`milton-agents[claude-code]`, `[codex]`, `[somm]`, `[fab]`, `[otel]`,
  `[git]`) so installing milton never drags in what you don't read.
- **Local-first storage**: append-only JSONL for findings (the grading
  ledger is an audit log), SQLite for the normalized event index. No
  server, no telemetry, nothing leaves the machine.
- **LLM-assisted stages route through a pluggable gateway seam** — somm
  when present, direct provider otherwise, none for the deterministic
  subset. Milton core holds no API keys (the somm/artoo discipline).
- CI/release per the family OSS standard: SHA-pinned actions, lint + test
  matrix + pip-audit + zizmor, trusted publishing, Keep-a-Changelog.

## The data model (the real product)

1. **Normalized events**: sessions, turns, tool calls, model calls, costs,
   outcomes — each with source adapter, native ids, and recovered fields
   declared per-adapter (coverage honesty is schema-level).
2. **The crosswalk**: joins across id schemes (harness session id, gateway
   correlation id, runner job id, commit/PR). Every join is itself a
   record with a confidence and a method, queryable and refutable.
3. **Findings**: typed (`cost-per-outcome`, `failure-motif`,
   `procedure-candidate`, `memory-hygiene`, `drift`), graded
   (`lead → candidate → corroborated`, refuted-retained), each carrying
   evidence refs into the event store. Findings are projections with
   manifests: source snapshot, generator, scope, confidence-as-coverage,
   expiry.

## Phases

**Phase 0 — read everything (deterministic only).**
Adapters: Claude Code JSONL, Codex sessions, somm ledgers (per-project +
global), fab receipts/rollups/lifecycle, git log. Normalized store + the
crosswalk + `milton report` (what ran, where, cost by source — parity with
cost tools, then past them by joining sources). Exit: one command answers
"what did agents do this week and what did it cost," with a stated
coverage map. No LLM calls anywhere in phase 0.

**Phase 1 — outcomes.**
Join spend to outcomes: commits/PRs (merged/reverted), runner terminal
receipts, task ledgers where present. `milton cost --per-outcome`. Exit:
cost per landed change computed from real history, with the attribution
method and its known noise documented rather than hidden.

**Phase 2 — synthesis (the wedge).**
Facet extraction + clustering over sessions (the Clio pattern: extract →
cluster → describe, with aggregation thresholds), producing failure-motif
and drift findings as graded leads; corroboration against receipts
promotes them. Includes the finding-quality eval harness: a held-out
labeled set, precision floors, and a refuted-findings ledger. Exit:
motif findings whose precision is measured, not asserted.

**Phase 3 — memory hygiene.**
Read-back auditing across memory stores (agent memory dirs, rules files,
skills): what exists, what is loaded, what is ever consulted, what is
write-only. Retention recommendations as findings (retire/park/keep), never
auto-deletion. Exit: a read-back coverage report over at least two memory
systems.

**Phase 4 — procedure candidates.**
Recurring work-shape mining over sessions + receipts, emitted in chip's
candidate-ledger convention with harvested fixture material. Exit: a
candidate feed a distillation pipeline can mint from.

## Principles carried forward (learned building the chip stack)

- **Contract-first, host-faithful tests.** The bugs that matter live in the
  seams; every adapter ships a "reads real exhaust exactly like production"
  test, the way chip examples are loaded the way a host loads them.
- **Fail-closed on grading, fail-open on ingestion.** A malformed record
  never becomes a finding; a missing adapter never blocks the others —
  it becomes a coverage gap in the report.
- **Derived, never authored.** Reports and surfaces are projections
  regenerated from the store; nothing hand-maintained can go stale.
- **Subtraction discipline.** Every stage/field must be deletable-detectable
  (something fails when it's removed) or it goes. Complexity budgets on the
  finding types themselves — better three trustworthy finding types than
  eight speculative ones.
- **Planned demolition.** The LLM-assisted synthesis stages carry the
  model generation they were tuned against and are re-derived, not
  hand-patched, as models improve. The durable assets are the model,
  crosswalk, and grading ledger.
- **Names are identity.** Findings and events carry stable ids from day
  one; append-only corrections supersede rather than erase.

## Open questions for the build session

1. Store choice detail: single SQLite with JSONL sidecars, or DuckDB for
   the analytical queries? (Phase 0 decides on real volume.)
2. How much of the somm ledger schema to mirror vs reference by id.
3. Redaction defaults for transcript-derived evidence quoted in findings.
4. Whether the phase-2 synthesis runs batch-only or supports an incremental
   cursor from day one (chip-shaped from the start).
5. Adapter conformance kit: how a third party proves a new adapter honest
   (the chip conformance-kit pattern, applied to readers).
