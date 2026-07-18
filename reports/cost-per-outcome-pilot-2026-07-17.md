# Cost-per-outcome ten-trace checkpoint

**Run date:** 2026-07-17
**Scope:** Milton A-1.5 / ROADMAP Epic A1
**Decision:** graduate the conservative projection; require the named Somm and
Fab producer contracts before claiming broad outcome coverage
**Content policy:** metadata only

This checkpoint selected exactly ten live cost observations from three
authorities and reconstructed each one to either a typed outcome or an explicit
abstention. One Fab-mediated Somm observation reaches a successful Fab terminal
receipt through a source-owned directed relation. The other nine observations
remain unallocated because their native harness/session roots have no supported
Fab, George, or Git outcome path in the selected windows.

The checkpoint graduates Milton's v1 projection contract: it conserves every
selected observation and does not manufacture attribution. It does **not**
establish high outcome coverage or cross-source billable deduplication.

## Conservation receipt

```text
selected     $0.02910777
= attributed $0.00000000
+ ambiguous  $0.00000000
+ unallocated $0.02910777
```

The zero-dollar attributed observation remains an observation and denominator;
it is not silently dropped. The projection selected ten of ten amount-bearing
events, excluded no rollups, suppressed no exact duplicates, and satisfied
`selected = attributed + ambiguous + unallocated` exactly.

Cost semantics remain separate from attribution:

| Declared dimension | Selected amount | Observation count |
| --- | ---: | ---: |
| Reported, accuracy unknown (OpenCode) | $0.02821497 | 4 |
| Computed, estimated (Somm and Hermes) | $0.00089280 | 5 |
| Unknown basis and accuracy (legacy Somm) | $0.00000000 | 1 |
| Computed, estimated, included (Hermes; overlaps the computed row above) | $0.00000000 | 1 |

The table is intentionally not additive across dimensions. Economic kind is
`unknown` for $0.02910777 and `included` for $0.00. None of the ten records is
described as actual provider spend. All ten operational roles are `unknown`;
Milton does not infer `production` from the shape or location of a source row.

## Redacted trace audit

Native source identifiers are omitted. Stable Milton event and relation IDs are
retained so the local receipt is reviewable without publishing harness/session
coordinates.

| Trace | Source | Amount | Basis / accuracy / kind | Result | Independent check |
| --- | --- | ---: | --- | --- | --- |
| T01 | OpenCode `evt_b2188f281b8e81a627ba6f39` | $0.01412184 | reported / unknown / unknown | `unallocated:no-outcome-path` | Native message amount matched; session has no typed outcome relation. |
| T02 | OpenCode `evt_43a25d70bfc6495745a6dbc9` | $0.01409313 | reported / unknown / unknown | `unallocated:no-outcome-path` | Native message amount matched; session has no typed outcome relation. |
| T03 | OpenCode `evt_5629c372e35b45d2a0ab28a4` | $0.00000000 | reported / unknown / unknown | `unallocated:no-outcome-path` | Native message amount matched; session has no typed outcome relation. |
| T04 | OpenCode `evt_af83d4295af2c70e00fa8d08` | $0.00000000 | reported / unknown / unknown | `unallocated:no-outcome-path` | Native message amount matched; session has no typed outcome relation. |
| T05 | Somm `evt_ccb4268b5beed2ab563c7068` | $0.00000000 | unknown / unknown / unknown | `attributed:exact-directed-path` → successful `fab.job` | Native call coordinates match the relation; Fab ledger ends `succeeded`. |
| T06 | Hermes `evt_d2cd2e9625fc477043554d11` | $0.00000000 | computed / estimated / included | `unallocated:no-outcome-path` | Native session amount matched; session has no typed outcome relation. |
| T07 | Somm `evt_9f0626c1370237ddb375f21f` | $0.00034140 | computed / estimated / unknown | `unallocated:no-outcome-path` | Native call amount and semantics matched; call has no typed outcome relation. |
| T08 | Somm `evt_3c95a93f18c21076f1b72a07` | $0.00032580 | computed / estimated / unknown | `unallocated:no-outcome-path` | Native call amount and semantics matched; call has no typed outcome relation. |
| T09 | Somm `evt_2551c68271f71f2816835663` | $0.00000000 | computed / estimated / unknown | `unallocated:no-outcome-path` | Native call amount and semantics matched; call has no typed outcome relation. |
| T10 | Somm `evt_345c7f53be56eb392e05459e` | $0.00022560 | computed / estimated / unknown | `unallocated:no-outcome-path` | Native call amount and semantics matched; call has no typed outcome relation. |

All ten normalized amounts were joined back to their authoritative SQLite rows
and matched exactly. There were no amount or path disagreements.

### Positive path

T05 roots at model-call event `evt_8afc5b11348cf1ae97b0e620` and traverses the
stored claim
`fab.job --produced/source_receipt--> somm.call` in reverse to outcome event
`evt_b0067c71e089fe35544e723a`:

- relation `rel_0a8e19cdbf6e1a7fe83d462b`;
- relation revision `rrv_c00acbc3f7ffbd8955afd351`;
- path event IDs: the cost, exact Somm call, and successful Fab terminal event;
- source verification: the Somm row's call and correlation coordinates equal
  the relation endpoints; and
- independent outcome verification: Fab records `attempt_finished` with
  `outcome=succeeded` and `status_changed` to `succeeded`.

The path uses no time proximity, token equality, content hash, or stdout text as
identity evidence.

## Double-counting boundary

This sample deliberately contains ten distinct native observations. It does
not prove that the same provider request observed by Fab, Somm, and a downstream
harness would be deduplicated today. Every live accounting key in this pilot is
source-local; shared-key coverage is zero. Milton can suppress duplicate
observers only when producers propagate the same stable provider/billing key
and the same economic kind. It refuses to equate rows merely because their
timing, tokens, model, or text look alike.

The required follow-up is already named:

- the Somm accounting-integrity contract must persist production, shadow-gold,
  and shadow-judge calls exactly once, retain stable provider/billing IDs where
  exposed, classify operational roles, and make exporter→ingester replay
  idempotent; and
- the Fab identity-receipts contract must propagate task, attempt, and native
  harness coordinates while treating any aggregate cost as a non-counting
  rollup over child accounting keys.

Until those contracts pass, reported and computed observations remain visible
as separate source claims; Milton must not advertise them as one actual bill.

## ROADMAP decision

Epic A1 graduates because ten live traces are reconstructable to a typed
outcome or explicit reason, no observation is assigned twice, and conservation
holds exactly. The narrow condition is not triggered: the one Fab-mediated
priced observation in the sample reaches its runner terminal outcome, and no
attribution depends on temporal or token matching.

Outcome coverage is nevertheless only 1/10 overall, so the next claim is
bounded: v1 is a conservative outcome projection, not a comprehensive
cost-per-commit or cost-per-PR product. Broader coverage depends on the named
producer contracts above and later George/Git receipts. This is a contract
dependency, not permission to weaken abstention.

## Reproduce

Run from Milton's repository root. The resulting store contains exactly ten
selected cost events; raw source coordinates remain local.

```bash
A1_CHECKPOINT_DIR="$(mktemp -d)"
A1_CHECKPOINT_STORE="$A1_CHECKPOINT_DIR/events.db"

uv run milton init --store "$A1_CHECKPOINT_STORE"

uv run milton ingest fab --store "$A1_CHECKPOINT_STORE" \
  --source "fab=$HOME/.local/share/fab/ledger.jsonl" \
  --since 2026-07-14T01:17:11Z --until 2026-07-14T01:17:23Z
uv run milton ingest somm --store "$A1_CHECKPOINT_STORE" \
  --since 2026-07-14T01:17:12Z --until 2026-07-14T01:17:13Z
uv run milton ingest somm --store "$A1_CHECKPOINT_STORE" \
  --since 2026-07-17T22:04:20Z --until 2026-07-17T22:04:32Z
uv run milton ingest opencode --store "$A1_CHECKPOINT_STORE" \
  --since 2026-07-13T22:20:14Z --until 2026-07-13T22:22:01Z
uv run milton ingest hermes --store "$A1_CHECKPOINT_STORE" \
  --since 2026-07-16T19:02:42Z --until 2026-07-16T19:02:43Z

uv run milton accounting --store "$A1_CHECKPOINT_STORE" --format json
uv run milton cost --per-outcome --store "$A1_CHECKPOINT_STORE" --format json
```

The retained ignored receipt is `.milton/a1-cost-pilot-2026-07-17.db`. The
first all-unlinked ten-trace attempt was preserved recoverably under
`.milton/partial-checkpoints/`; it is not part of this decision.
