# Workplan: footprint and phases

Status: the 28-task implementation plan was worked through on Lisbon on
2026-07-17: 27 tasks completed and the George stale-gate live checkpoint was
explicitly narrowed. The core contracts, twelve built-in source adapters,
conservative cost-per-outcome projection, finding lifecycle, evaluated motif
and memory audits, Chip candidate feed, and Spindle/Fab/Somm procedure return
loop are executable. This is implementation/checkpoint closure, not an
operational-release claim; the cross-cutting release gates in `ROADMAP.md`
remain authoritative.

This document is the capability taxonomy. [ROADMAP.md](../ROADMAP.md) is the
gated product sequence; [`plans/milton-product/`](../plans/milton-product/) is
the Forge-derived architecture and executable work breakdown. A horizontal
phase is not considered complete because its types or storage exist.

## Package footprint

Family-standard shape (the somm/chip pattern):

- `milton-ai` configured for PyPI, import package `milton`, src layout,
  hatchling, MIT, Python ≥3.12. Releases use the OIDC workflow, and the
  clean-wheel smoke proves the dependency-free installed surface.
- **Light dependency-free core and built-ins.** Core = the normalized event model, the
  findings/grading ledger, the ID crosswalk, the store, and the query/CLI
  surface, and filesystem/SQLite/Git readers. The shipped adapters require no
  Python runtime dependencies. A future OTel/network adapter may be an extra;
  installing Milton never starts or transmits anything.
- **Vertically integrated evidence semantics.** Identity, relations,
  accounting, attribution, grading, and receipts stay Milton-owned. External
  mechanisms enter only through the complete-open-source, offline-exit, and
  replacement gate in [build, borrow, or adopt](build-vs-adopt.md).
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
3. **Directed relations**: causal/workflow assertions such as `attempt_of`,
   `produced`, `verifies`, `acts_on`, and `promotes`. They are evidence-bearing
   and refutable but remain distinct from identity association.
4. **Findings**: typed (`failure-motif`, `procedure-candidate`,
   `memory-hygiene`, `drift`, plus actionable anomalies derived from
   accounting/outcome projections), graded
   (`lead → candidate → corroborated`, refuted-retained), each carrying
   evidence refs into the event store. Findings are projections with
   manifests: source snapshot, generator, scope, confidence-as-coverage,
   expiry.
5. **Action receipts**: not a mutable finding status or second action ledger.
   Milton derives current disposition and historical acted-on/refuted/
   evaluated/promoted state by relating an exact finding revision to a
   canonical George/Git/Fab/Somm/Spindle receipt. Coverage loss changes
   freshness, not valid history.

## Phases

**Phase 0 — read everything (deterministic only).**
Adapters: Claude Code JSONL, Codex sessions, Somm's global ledger by default
with explicit alternate roots supported, Fab receipts/rollups/lifecycle, and
Git log. Normalized store + the
crosswalk + `milton report` (what ran, where, cost by source — parity with
cost tools, then past them by joining sources). Exit: one command answers
"what did agents do this week and what did it cost," with a stated
coverage map. No LLM calls anywhere in phase 0.

Operational proof on Lisbon: the original deterministic eight read Claude
Code, Codex, Somm, Fab, George, Git, Hermes, and OpenCode. Chip, Spindle,
native-memory, and decision-memory later joined the built-in registry at their
public receipt/readback boundaries. A fixed-cutoff repeat pass skips unchanged
sources and appends growing transcripts without conflicts; stored coverage
includes zero-event adapters. `milton scan --since 7d` is the one-command
surface. `milton accounting` separates reported/computed
provenance and marginal/notional/included semantics, applies precedence only
to exact accounting keys, and leaves source-local overlap visible. Dollar
totals remain coverage-qualified where a native harness supplies tokens but no
amount.

The planned producer contracts were implemented: Somm carries source-owned
request/custody fields and exact evaluation calls; Fab emits stable
attempt/outcome/verifier/artifact receipts and non-counting child-keyed
rollups. Real records that predate those contracts or providers that expose no
stable billing id remain source-local coverage gaps rather than dedup
heuristics.

**Phase 1 — outcomes.**
Join spend to outcomes: commits/PRs (merged/reverted), runner terminal
receipts, task ledgers where present. `milton cost --per-outcome`. Exit:
cost per landed change computed from real history, with the attribution
method and its known noise documented rather than hidden.

**Phase 2 — synthesis (the wedge).**
Compare direct bounded analysis with facet → cluster → describe on the same
held-out corpus before choosing a maintained pipeline. The accepted method uses
aggregation thresholds and produces failure-motif and drift findings as graded
leads; independent receipts promote them. Includes the finding-quality eval
harness: a held-out labeled set, precision floors, and retained refutations.
Exit: motif findings whose precision and operator effect are measured, not
asserted.

**Phase 3 — memory hygiene.**
Read-back auditing across memory stores (including a memory runtime such as
agentmemory plus file/rules/skills stores): what exists, what is loaded,
retrieved, referenced, demonstrably applied, or unknown. Retention
recommendations are findings (retire/park/keep), never auto-deletion. Exit: a
stage-honest read-back coverage report over at least two memory systems.

**Phase 4 — procedure candidates.**
Recurring work-shape mining over sessions + receipts, emitted as an idempotent
projection of Chip's candidate-ledger convention with counterexamples and
fixture material. Spindle remains the evaluation/binding owner. Exit: one
candidate feed plus a return receipt that later operational outcomes can join.

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

## Decisions from the Phase 0 build

1. SQLite remains the normalized event and crosswalk index; append-only JSONL
   remains the findings ledger. Lisbon-scale scans do not require DuckDB.
2. Somm call facts are mirrored into typed events while raw bodies remain in
   Somm and are referenced by native IDs.
3. Metadata-only is the default. Sensitive bodies are hashed/length-counted;
   raw storage is an explicit `--content full` opt-in.
4. Ingestion is incremental from day one through source fingerprints, SQLite
   WAL awareness, Git-ref fingerprints, and stable IDs.
5. Adapter conformance is enforced through host-shaped fixtures, privacy-mode
   tests, stable replay/conflict behavior, fail-open diagnostics, and a live
   Lisbon first-pass/repeat-pass smoke gate.
6. Identity association and causal/workflow relation are separate contracts;
   connected records do not automatically prove attribution.
7. Cross-source retrospective accounting and task outcomes belong in Milton;
   Somm keeps source-local hot-path controls and consumes optional versioned
   projections without a required dependency.
8. The first finding proof is deterministic stale/re-minted George-gate
   detection, gated by labeled precision and a real external action receipt.
