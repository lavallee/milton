# Accounting projection

Milton preserves observations first and projects an answer second. A source
amount is never silently promoted to “actual spend,” and a timestamp match is
never treated as proof that two rows represent the same billable call.

## Three independent cost facts

| Field | Values | Question answered |
| --- | --- | --- |
| `basis` | `reported`, `computed`, `unknown` | Did an upstream artifact supply the amount, or was it derived from usage and prices? |
| `kind` | `marginal`, `notional`, `included`, `unknown` | Is this incremental cash cost, list-price equivalent, subscription-included value, or not classified? |
| `accuracy` | `actual`, `estimated`, `unknown` | Does the authority consider the amount settled or estimated? |

`authority` records who made the observation; `pricing_version` identifies the
price material when available. Reported does not mean provider-billed. For
example, OpenCode reports an amount to Milton but does not currently expose its
billing semantics, while Somm normally computes an amount from tokens and its
local `model_intel` snapshot.

Local Ollama is the important exception. A numeric `0.0` compatibility field
means that no metered provider price was charged; it does not establish zero
electricity, hardware, or opportunity cost. Somm labels those rows
`basis=unknown`, `kind=included`, `accuracy=unknown`, and
`source=local-included-unpriced`. Milton retains tokens but projects the dollar
amount as unavailable until an explicit local resource-rate model exists.

## Exact identity before deduplication

Every new adapter cost event carries an `accounting_key` and a key scope:

- `shared`: a provider/request or other identifier that independent systems
  can reproduce exactly;
- `source`: a stable native billable-unit ID, safe for replay suppression only
  inside that adapter;
- `unknown`: missing or unusable identity.

Milton groups monetary observations by exact key **and economic kind**. Keeping
kind in the group is deliberate: a `$0` subscription-included marginal amount
and a `$4` notional list-price equivalent may both be valid for one call. A
source-local key is never joined to another adapter by time, model, hashes, or
matching token counts.

Events whose `observation_role` is `rollup` are excluded before monetary
selection. A rollup may summarize child calls for an operator, but it is not a
second billable observation. Production, shadow-gold, shadow-judge, and eval
roles remain first-class observations when their producer records them.

## Explicit precedence

Within an exact group, the selected amount follows this order:

1. `reported.actual`
2. `computed.actual`
3. `unknown.actual`
4. `reported.estimated`
5. `computed.estimated`
6. `unknown.estimated`
7. `reported.unknown`
8. `computed.unknown`
9. `unknown.unknown`

Equal-quality observations use the authority tiebreak `provider`, `somm`,
`hermes`, `opencode`, `claude-code`, `codex`, then deterministic lexical order.
The machine-readable projection emits both lists and every duplicate decision.

`raw_observed` is the sum of all source amounts. `selected_observations` is the
sum after exact-key suppression, retained for reconciliation. Consumers should
normally display the separate marginal, notional, included, and unclassified
buckets rather than treating their sum as one economic number.

```console
milton accounting --store .milton/events.db --since 7d
milton accounting --store .milton/events.db --since 7d --format json
milton cost --per-outcome --store .milton/events.db --since 7d --format json
```

## Somm boundary and duplication audit

Somm currently performs four accounting-adjacent jobs:

- token-times-price calculation for a mediated call;
- per-workload daily budget enforcement;
- machine-wide plan/quota pacing and PAYG burn rate;
- historical summaries such as `somm spend` and campaign totals.

The first three remain in Somm because routing needs them in flight. Its call
schema now records cost basis, kind, accuracy, source, and pricing version so
Milton does not have to infer future rows. Cross-source history,
deduplication, and outcome attribution belong in Milton. Somm may later expose
an optional convenience command over the evidence document, but Milton does
not become a required `somm-core` dependency. Today Somm's dependency-free
consumer validates `milton.outcome-tuple/v1` as evidence-only input and cannot
apply a route change.

Somm source-local views such as spend, plan pacing, frontier statistics, eval
campaign totals, and recommendation summaries remain useful. They must state
their scope. Campaign and recommendation totals are rollups over child facts,
not additional billable observations. Future task/model-harness outcome memory
should consume a versioned Milton projection rather than introduce a second
canonical copy of Fab/George task outcomes.

The Somm producer-integrity gate is now accepted. Shadow gold and judge
requests are first-class call observations with returned usage and custody;
OTLP re-ingest honors `somm.call_id`; and genuinely foreign imports are marked
non-policy rather than entering native budgets or rankings. Milton consumes
provider request ids as shared accounting keys when present and otherwise
retains Somm's call id as source-local. Campaign totals remain explicit
`rollup` observations and are excluded before monetary selection. See the
[accepted commission](../plans/milton-product/commissions/somm-accounting-integrity.md).

Fab's import of `somm.harnesses` does not create a second cost observation: it
reuses command construction and runs the native CLI. Direct Fab-to-Somm calls
and native harnesses now carry the deterministic Fab attempt coordinate
`<job>:attempt:<n>` as `correlation_id`. Fab's finished receipt relates that
attempt to the job and to the supported Somm call or native session id. Fab
rollups are always `observation_role=rollup`, `counting=false`, and enumerate
known child accounting keys; they are excluded before selection. These are
work-trace edges, not permission to collapse all calls in one job into a single
accounting unit or to synthesize a provider request id.
