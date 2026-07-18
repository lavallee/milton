# milton

**Understand what your agents actually did.**

Milton ingests the exhaust that LLM agents and their infrastructure already
produce — coding-agent session transcripts, runner receipts, gateway audit
ledgers, git activity — normalizes it, and is being built to emit
**conservative projections and graded, typed findings**:

- **Deterministic projection: performance accounting** — cost and tokens per *outcome* (per merged PR,
  per resolved task, per shipped change), not per token. The number everyone
  agrees is right and everyone computes in a spreadsheet.
- **Graded finding: failure motifs** — recurring patterns across sessions: retry storms, tool
  errors, stalls, injection attempts, interventions.
- **Graded finding: procedure candidates** — work shapes that recur often enough to be worth
  codifying (the feed for a skill/chip distillation pipeline).
- **Graded finding: memory hygiene** — read-back auditing of what agents have banked: which
  stored memories, rules, and skills are actually consulted, and which are
  write-only.

## Why

Useful pieces of this product now exist elsewhere: proprietary platforms cluster
and summarize traces; TraceLab analyzes local Claude/Codex histories; provider
and local tools show cost per commit or PR; memory runtimes record reads and age
stored material. Milton's narrower job is to connect the pieces those systems
usually keep apart: heterogeneous post-hoc exhaust, conservative accounting,
real work outcomes, graded findings, and authoritative action receipts.

Milton is adapters-first because much of the useful evidence still sits in
native session logs, runner receipts, gateway ledgers, work registries, and Git
history rather than one observability platform. See the dated
[landscape](docs/landscape.md) for the evidence and claim limits.

Two principles govern the design:

1. **No tool lock-in.** People use Claude Code, Codex, Cursor, aider, hermes,
   and things not invented yet — some through a gateway, some direct to a
   provider. Milton is designed to report across them, subject to explicit
   adapter coverage. A gateway can speak authoritatively only for the traffic
   it mediated; Milton's target job is the coverage-declared cross-source view.
2. **Findings are graded, or they're slop.** Every finding is a typed record
   carrying its evidence references and a grading state (lead → candidate →
   corroborated), promoted only when independent evidence agrees. Pattern
   synthesis over transcripts is exactly where hallucinated insight hides;
   the grading discipline is the product.

Milton also defaults to vertical integration for compact mechanisms that define
the evidence chain. Truly open, locally complete, replaceable software remains
eligible for focused reuse or optional adapters; a public repository or
"self-hosted" badge alone is insufficient. The decision and current market-map
dispositions are documented in [build, borrow, or adopt](docs/build-vs-adopt.md).

## Status

The deterministic foundation and conservative cost-per-outcome projection are
operational. Milton reads Chip, Claude Code, Codex, Fab, George, Git, Hermes,
OpenCode, Somm, and Spindle exhaust; records identity joins separately from directed
work relations; projects reported versus computed cost with exact-key
precedence; attributes spend through inspectable paths; and exposes append-only
finding review and action-receipt surfaces. The first George gate detector is
implemented but remains offline because its frozen held-out corpus has no
independent positive examples. Its promotion path now uses the
generator-neutral, tuple-bound contract described in
[findings](docs/findings.md), including recurrence and aggregation floors. The
Somm, Fab, George, Chip, and Spindle producer contracts and their
live/host-shaped checkpoints are accepted. Bounded failure-motif synthesis,
two-store memory auditing, idempotent procedure-candidate export, and one
evaluated/bound/post-measured procedure calibration loop are implemented.

The distribution is `milton-ai` (the bare name belongs to an unrelated project;
the import package and CLI remain `milton`). The broader distribution name
reflects that Milton can account for gateway, provider, and other AI work—not
only work performed by agents. The Forge OSS release shape, trusted
publishing workflow, and retained clean-wheel smoke are present; the first OIDC
publish and post-publish install remain external release proofs. Milton requires
Python 3.12 or newer and its core has no runtime dependencies.

The standing direction is [VISION.md](VISION.md), the gated sequence is
[ROADMAP.md](ROADMAP.md), and the Forge-derived executable plan lives under
[`plans/milton-product/`](plans/milton-product/README.md).

## Try it

From a checkout:

```console
uv sync
uv run milton init
uv run milton scan --since 7d
uv run milton report --since 7d --format json
uv run milton accounting --since 7d
```

By default Milton creates `.milton/events.db` and
`.milton/findings.jsonl`. Nothing is transmitted off the machine. Transcript,
tool, George context, and commit-message bodies are hashed and redacted unless
`--content full` is explicitly selected. Adapter failures are isolated and
persisted as coverage state; one unavailable source cannot block the rest.

On Lisbon, the default discovery roots cover the live local stores. Override a
root when needed with a repeatable `--source ADAPTER=PATH` option. The built-in
adapters and their coverage are documented in [source adapters](docs/adapters.md).

To inspect everything connected to a George/Fab run:

```console
uv run milton activity fab.job=20260717T152816_744822 --format json
uv run milton relations show fab.job=20260717T152816_744822 --format json
uv run milton cost --per-outcome --since 7d --format json
uv run milton evidence export-tuple \
  --implementation GIT_SHA --profile SOMM_WORKLOAD_ID \
  --served-model MODEL --harness codex \
  --cutoff 2026-07-18T00:00:00Z --minimum-observations 5
uv run milton findings list --format json
uv run milton findings show FINDING_ID --format json
uv run milton findings export FINDING_ID
uv run milton findings export FINDING_ID --target chip
uv run milton findings calibrate-promotion SPINDLE_PROMOTION_RECEIPT_ID
uv run milton findings evaluate \
  --cases evals/george-gates/cases-v1.jsonl --format json
uv run milton findings generate \
  --generator george-gates --since 7d --dry-run --format json
```

That schema-versioned projection follows explicit George → Fab → native
harness/session joins, prints the asserted trace edges, and includes the
connected outcomes, costs, tokens, and coverage gaps. See the
[George consumer contract](docs/george-consumer.md).

`milton accounting` is the canonical monetary projection. It keeps raw
observations visible, separates marginal, notional, included, and unclassified
amounts, and suppresses another observation only when both sources carry the
same exact shared accounting key. Its precedence and dependency boundary are
documented in [accounting](docs/accounting.md).

Tuple evidence is a bounded consumer document, not a routing command. It
requires an exact Git implementation, Somm profile/workload id, served model,
and Fab/native harness; declares an exclusive cutoff, coverage, sample floor,
and uncertainty; and labels its policy effect `evidence_only`. Somm validates
the JSON without importing Milton and never applies it automatically.

The public library surface includes `NormalizedEvent`, its typed payloads,
`MiltonStore`, `CrosswalkRecord`, `RelationRecord`, `TypedRef`,
`FindingLedger`, and `build_activity`.
Stable identifiers make ingestion idempotent, while conflicting reuse of an
identifier fails closed.

## Development

```console
uv run ruff check .
uv run ruff format --check .
uv run mypy --strict src tests
uv run pytest
uv build
uv run python scripts/release_smoke.py dist/milton_ai-*.whl
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for evidence-contract expectations and
[RELEASING.md](RELEASING.md) for the release and trusted-publishing checklist.

## Relationship to adjacent projects

- [somm](https://github.com/lavallee/somm) — the LLM gateway. Currently
  canonical for persisted mediated-call observations, routing, hot-path
  budgets, model/workload evals, and bounded route actions. The planned
  boundary makes auxiliary calls first-class and delegates cross-source
  retrospective analysis to milton; milton can return versioned outcome
  evidence or findings for Somm to validate and apply. See
  [boundaries](docs/boundaries.md).
- Projector — external-development evidence, portfolio recommendations, and
  experiment/promotion calibration. Milton analyzes internal operational
  exhaust and returns later outcome evidence; neither copies the other's store.
- George — canonical intent, decisions, gates, and action disposition. The
  planned contract lets Milton emit findings and derive acted-on state from
  George receipts; Milton does not act on George directly.
- [chip](https://github.com/lavallee/chip) — portable operational components.
  Milton procedure findings feed an idempotent projection of Chip's
  candidate-ledger convention; Chip returns public custody receipts without
  exposing its private candidate/fixture store.
- Spindle — canonical skill/package evaluation, distribution, and binding. A
  procedure promotion preserves exact Milton/Chip origin and baseline/variant
  tuples; Milton measures later Fab/Somm outcomes without evaluating or binding
  on Spindle's behalf. The retained local-model checkpoint closes one such
  chain with an explicitly narrow policy-adherence claim; see
  [the procedure-promotion pilot](reports/procedure-promotion-pilot-2026-07-17.md).
- fab (being open-sourced) — the reference runner whose receipts are a
  first-class adapter.

## License

MIT.
