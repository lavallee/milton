# Source adapters

Milton's built-ins are read-only and dependency-free. `milton scan` runs all
of them by default; `milton scan codex fab git` limits a pass. Every emitted
field declares recovered, inferred, unavailable, or redacted coverage, and a
source failure is recorded without stopping the other adapters.

| Adapter | Default Lisbon source | Recovered surface |
| --- | --- | --- |
| `claude-code` | `~/.claude/projects/**/*.jsonl` | sessions and subagents, turns, streamed model usage, paired tools |
| `chip` | `candidate-receipts*.jsonl` (override with `MILTON_CHIP_RECEIPTS`) | bounded candidate custody outcomes plus exact finding-revision origin and receipt verification relations |
| `codex` | `~/.codex/sessions/**/rollout-*.jsonl` | sessions, turns, tools, token usage, task completion |
| `fab` | `~/.local/share/fab/jobs/*/receipts/*.json`, with legacy ledger/stdout fallback | source custody, job/attempt outcomes, rollups, verifier/artifact receipts, and exact native coordinates |
| `george` | `$GEORGE_CENTRAL_DIR/.george/inbox` or Lisbon's sibling `Central` checkout | work lifecycle outcomes, gate mint/consult/decision/disposition evidence, and George entry → Fab/Git/session joins |
| `git` | `$MILTON_PROJECTS_ROOT`, `$GEORGE_PROJECTS_ROOT`, or the detected projects root | commits across all refs, parents, repository identity |
| `hermes` | `~/.hermes/state.db` | sessions, turns, model/tool calls, actual or marked-estimated session cost |
| `native-memory` | current checkout; override with factory roots | metadata-only inventory of `AGENTS.md`, `CLAUDE.md`, `MEMORY.md`, rule files, and `SKILL.md`; optional versioned host access rows |
| `decision-memory` | current checkout; override with decision-store roots | metadata-only `decisions/*.md` inventory and optional versioned host access rows |
| `opencode` | `~/.local/share/opencode/opencode.db` | sessions, typed parts, model usage, tool calls and cost |
| `somm` | `~/.somm/global.sqlite` | mediated production/gold/judge calls, cost/custody provenance, eval and campaign receipts, decisions, recommendations, late updates, and exact joins |
| `spindle` | `$MILTON_SPINDLE_RECEIPTS` or `$SPINDLE_HOME/receipts` | procedure evaluation and promotion receipts with exact Milton/Chip origin, baseline/variant tuple, and evaluated binding |

Every cost event distinguishes amount `basis` (`reported`, `computed`, or
`unknown`), economic `kind` (`marginal`, `notional`, `included`, or `unknown`),
and `accuracy` (`actual`, `estimated`, or `unknown`). “Reported” means the
upstream artifact supplied the amount; it does not by itself claim that a
provider invoice supplied it. See [accounting](accounting.md).

## Current coverage limits

The table describes implemented recovery, not complete source custody. The
most important known limits are:

- Legacy Somm databases may lack the evidence/custody tables added through
  schema v22. The adapter reads their call ledger, records an explicit coverage
  diagnostic, and continues. Current databases expose first-class production,
  shadow-gold, and shadow-judge calls plus eval results/receipts, campaigns,
  decisions, recommendations, and late updates.
- Legacy Fab jobs may predate `fab.execution-receipt/v1`. Milton reads their
  ledger and supported native transcripts as a fallback and records missing
  session ids honestly. Current jobs expose deterministic attempt correlation,
  source/commission custody, terminal semantics, verifier and artifact ids,
  and non-counting rollups with named child accounting keys.
- George provides explicit entry links and lifecycle outcomes. It does not yet
  provide the finding intake/disposition receipt needed to derive Milton's
  `acted_on` state. Existing gate rows also provide no consultation-read
  receipt, so consultation remains unavailable rather than being interpreted
  as non-use.
- Chip exposes idempotent candidate custody receipts. Milton reads only that
  public receipt ledger, not Chip's candidate or fixture store. Spindle exposes
  bounded evaluation and promotion receipts only for procedure manifests that
  provide complete origin and tuple custody.
- Native file and decision stores usually expose inventory but no trustworthy
  load/retrieval/reference/application log. Milton reports every absent stage
  as unknown. A local `.milton-memory-access.jsonl` is consumed only when the
  host explicitly exports `milton.memory-access/v1` rows; retrieval never
  implies application.

These are producer-contract gaps, not invitations for Milton to reconstruct
facts heuristically. The proposed changes are scoped as commissions under
[`plans/milton-product/commissions`](../plans/milton-product/commissions/README.md).
Until those contracts land, reports must surface the missing coverage and keep
ambiguous work unassigned.

## Exact directed relations

Current relation emission is deliberately narrow:

- For legacy job-scoped correlation, Somm emits
  `fab.job --produced--> somm.call`. Current Fab attempts use the explicit
  `<job>:attempt:<n>` coordinate; the Somm row supplies the association and the
  Fab finished receipt owns the directed `fab.attempt --produced--> somm.call`
  assertion, avoiding two competing producers for one relation.
- Fab emits `george.entry --verifies--> fab.job`,
  `fab.attempt --attempt_of--> fab.job`, and exact `produced` relations to
  Somm calls, native harness sessions, commits, and review artifacts from its
  producer-owned receipts. Attempt correlation is `<job>:attempt:<n>`; stdout
  parsing is used only for legacy jobs without a finished receipt.
- Somm call rows link explicitly to workloads and eval results. Eval results
  and receipts `evaluate` their named calls; auxiliary calls and receipts are
  `part_of` their exact eval result. Campaign events are `part_of` campaigns;
  decisions and recommendations `act_on` their named workload; late updates
  `act_on` their named call. Shared eval `run_id` values remain crosswalks.
- George emits `george.entry --verifies--> fab.job` from an explicit
  `context.fab_job_id`. When the same receipt carries a Git SHA it also emits
  `fab.job --produced--> git.commit`; without a Fab coordinate, the George
  entry is the subject.
- George emits a distinct `gate-evidence` event for each explicit human gate,
  declared consultation, marked gate decision, or marked gate disposition.
  Exact `work_coordinate`/`triage_coordinate` values or one exact ref/edge
  target become a canonical `george.gate` coordinate. Each mint keeps its own
  `george.gate-mint` identity and links to the coordinate with `part_of`;
  consultation/decision events use `evaluates`, and dispositions use
  `acts_on`. Missing or conflicting coordinates abstain from emitting a
  relation.
- Chip receipts assert exact
  `milton.finding-revision --produced--> chip.candidate` origin and
  `chip.candidate-receipt --verifies--> chip.candidate` custody. Candidate
  capture is deliberately not modeled as evaluation or promotion.
- Spindle evaluation receipts `evaluate` both the exact Milton finding revision
  and Chip candidate. Promotion receipts `promote` both and `produce` the
  evaluated binding coordinate. Fab then relates the promotion/finding origin
  to its exact post-promotion job. Somm procedure outcome receipts `evaluate`
  the exact promotion and `verify` the named Fab job.
- Procedure-outcome eval receipts also `evaluate` both native Somm calls: the
  baseline is producer-owned `source_call_id`, and the promoted arm is
  producer-owned `call_id`. A free-form baseline label alone is rejected.

These relations use `source_receipt`, confidence 1, and exact event evidence.
They do not use timestamp proximity, token counts, content hashes, or stdout
equality. The same coordinates continue to emit crosswalks independently.

## Planned adapter expansion

Somm auxiliary/evaluation/action/procedure records, Fab verifier/artifact and
procedure-origin receipts, George dispositions, the idempotent Chip candidate
round trip, and Spindle evaluation/promotion receipts are implemented.
Additional relations remain separate from identity crosswalk edges.

## Privacy contract

The default `--content metadata` policy never stores transcript bodies, tool
inputs/outputs, George content/context, commit messages, author identities, or
Fab launch/tag bodies. Milton stores hashes and lengths where they are useful
for equality and recurrence analysis. Raw bodies require the explicit
`--content full` opt-in and remain local.

Identifiers needed to join systems—Fab job IDs, George entry IDs, Git SHAs,
native session IDs—are structural metadata and remain queryable. Adapter tests
assert both the redacted default and full-content opt-in.

## Incremental behavior

Milton fingerprints each source (including SQLite WAL state and Git refs) and
skips unchanged inputs. JSONL sources are append-safe. Calls that are still
open at EOF are not persisted under their final identity; a later pass recovers
them after the matching output appears. This keeps the normalized store
append-only while live Codex and Claude transcripts grow.

Use fixed ISO bounds for a strictly repeatable pass. `--until` is exclusive:

```console
milton scan --since 2026-07-10T00:00:00Z --until 2026-07-11T00:00:00Z
```

Both bounds enter the source fingerprint and adapter-run coverage. Duration
cutoffs such as `7d` intentionally move on every invocation. A
malformed native record is diagnosed and skipped. A source-level exception is
reported as a failed source and does not suppress other adapters.

## Overrides

Discovery can be replaced per adapter without a config file:

```console
milton scan git george \
  --source git=/srv/projects \
  --source george=/srv/Central/.george/inbox
```

Memory roots are explicit in a factory-wide audit:

```console
milton scan native-memory decision-memory \
  --source native-memory=/srv/factory/skills \
  --source decision-memory=/srv/project-a \
  --source decision-memory=/srv/project-b
milton memory audit --cutoff 2026-07-18T00:00:00Z
```

Multiple roots for one adapter may be supplied by repeating `--source`. The
machine-readable ingestion result and stored adapter-run coverage distinguish
`ok`, `empty`, and `error`, including adapters that legitimately emitted zero
events in the requested window.
