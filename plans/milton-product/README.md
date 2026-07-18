# Milton product plan

This directory turns Milton's standing vision into bounded, traceable work. It
does not assert that roadmap behavior is implemented.

## Lineage

```text
VISION.md
  └─ ROADMAP.md — product outcomes, graduation thresholds, kill criteria
       ├─ orientation.md — P0/P1/P2 requirements, assumptions, experiments
       ├─ architecture.md — ownership, contracts, components, risk controls
       └─ itemized-plan.md — 28 acceptance-tested work items
            └─ itemized-plan.todos.jsonl — importable work projection
```

Market and boundary evidence lives in
[`reports/market-and-boundary-review-2026-07.md`](../../reports/market-and-boundary-review-2026-07.md).
The original horizontal capability taxonomy remains in
[`docs/workplan.md`](../../docs/workplan.md); `ROADMAP.md` controls sequence.

## Artifacts

| Artifact | Purpose | Authority |
| --- | --- | --- |
| [Orientation](orientation.md) | Refined requirements, constraints, open experiments, MVP | Planning input |
| [Architecture](architecture.md) | Milton internals and cross-system data contracts | Proposed design |
| [Itemized plan](itemized-plan.md) | Epics, tasks, acceptance criteria, dependencies | Proposed execution order |
| [Todo projection](itemized-plan.todos.jsonl) | Machine-readable copy of the 28 work items | Projection; Markdown remains readable source |
| [Commissions](commissions/README.md) | Somm, Fab, and George producer/consumer changes | Proposed only; target repo must accept |
| [Build/adopt policy](../../docs/build-vs-adopt.md) | License-chain, lock-in, supply-chain, and exception gate | Standing architecture constraint |

The JSONL projection has been checked for valid JSON, unique task IDs, and
resolvable dependency targets. The private plan-ingest dry run has not been run
because that operator is not installed in this environment.

## Current versus planned

The current executable surface is documented in the repository
[README](../../README.md), [adapter contract](../../docs/adapters.md),
[accounting contract](../../docs/accounting.md), and
[George consumer contract](../../docs/george-consumer.md). Planned commands and
schemas appear only in the roadmap and plan files. A cross-repository commission
is not dispatched work until it is reviewed and accepted in its owning repo.
