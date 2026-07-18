# Vision

**Re-grounded:** 2026-07-17
**Freshness trigger:** revisit after each roadmap graduation, a material change
to Somm/Fab/George ownership, or a competitor shipping local cross-session
synthesis over native coding-agent exhaust.

## North star

Milton helps people running heterogeneous LLM agents turn operational exhaust
into evidence-backed, receipted improvements in cost, reliability, memory, and
procedure.

Milton should answer, without requiring every agent to adopt an SDK:

- what work happened across gateways, harnesses, runners, and repositories;
- what it cost per outcome, with uncertainty and economic meaning intact;
- what keeps going wrong across sessions rather than in one transcript;
- what learned procedure is worth preserving; and
- what stored memory, rule, or gate has become dead weight.

## North-star metric

**Acted-on findings:** distinct graded findings that led to a verified change
in the system that produced the exhaust.

An action counts only when Milton can join the finding to an authoritative
receipt: a landed commit or configuration change, a retired memory or gate, a
budget or routing adjustment, or a promoted procedure candidate. Generated
findings, dashboard views, recommendations without a receipt, and explicit
refutations do not count as acted-on. A refutation counts separately as an
adjudicated finding and calibrates the generator.

Guardrails:

- **False-finding rate:** corroborated findings later refuted by a human or
  stronger evidence must remain below the threshold declared by the generator.
- **Coverage honesty:** every projection declares missing adapters, unreadable
  stores, unavailable amounts, ambiguous joins, and retention limits.
- **Privacy posture:** metadata-only is the default; raw transcript bodies are
  local, opt-in, and never required for deterministic accounting.
- **Operator burden:** acted-on findings must save more attention than they
  consume. A detector that creates a new noisy inbox has failed.

## Strategy bets

### 1. Whole-work truth

Join heterogeneous agent activity to real outcomes without inventing identity
or silently counting the same economic event twice. The useful product is not
another token dashboard; it is cost, time, and attempts per landed or explicitly
failed outcome, with attributed, ambiguous, and unallocated work separated.

Graduation signal: representative Fab/George/Git histories produce
reproducible cost-per-outcome projections whose attribution paths can be
inspected event by event and whose unallocated remainder is visible.

### 2. Graded operational findings

Detect cross-session failure motifs, drift, and memory-hygiene problems as
evidence-bearing findings. Deterministic detectors come first; model-assisted
facet extraction and clustering graduate only behind labeled cases, aggregation
thresholds, and measured precision.

The first vertical proof is stale and repeatedly re-minted George gates: Milton
should identify them, George should retire or refute them, and the returned
disposition receipt should close the adjudication loop. Only a verified change
counts toward acted-on findings.

Graduation signal: at least one detector produces multiple reviewed findings,
meets its declared precision floor, and causes a verified operational change
without increasing the decision backlog.

### 3. Compounding procedure

Turn recurring successful work shapes into portable procedure candidates with
evidence and fixture material. Milton proposes; Chip defines the candidate
contract and Spindle remains the composition, evaluation, and binding boundary.

Graduation signal: a Milton candidate is independently evaluated, promoted by
the owning system, and later shows a measurable improvement on the outcome that
motivated it.

Everything else is not now. In particular, Milton is not pursuing a general
observability UI, online agent control, a workflow runtime, or a generic
enterprise analytics platform.

## Engine map

Milton owns projections over other systems' canonical facts. It does not become
their new system of record.

| Vision bet | Canonical engines and their responsibility | Milton's responsibility |
| --- | --- | --- |
| Whole-work truth | Somm: mediated call facts and hot-path spend gates; harnesses: native usage/request ids; Fab: attempts and terminal receipts; George: intent and task disposition; Git/GitHub: landed and reverted changes | Normalize, crosswalk, reconcile exact accounting observations, attribute selected cost to outcomes, expose ambiguity |
| Graded operational findings | Source systems retain raw records; George owns decisions and guarded actions; Projector owns external-development recommendations and experiment gates | Analyze internal operational exhaust, retain graded findings and refutations, link findings to authoritative action receipts |
| Compounding procedure | Chip owns the candidate contract; Spindle owns composition/binding; Fab owns isolated evaluation; Somm owns model/harness selection | Emit evidence-bearing candidates and later measure their operational outcomes |

Cross-system contracts:

- **Somm remains independently operable.** It keeps routing, fallback, provider
  and model advice, in-flight budgets, plan pacing, per-call records, and
  call-level evaluation. It may consume Milton's versioned outcome projections,
  but it does not duplicate Fab/George task outcomes as a second canonical
  ledger and does not require Milton on its hot path.
- **Projector and Milton analyze different worlds.** Projector evaluates
  external developments and recommends bounded experiments; Milton measures
  internal work and recurring operational behavior. Projector may use Milton
  outcomes to calibrate recommendations, while Milton may ingest experiment and
  promotion identifiers to measure effects. Neither copies the other's claims
  or findings store.
- **George owns intent and action.** Milton can emit a finding or guarded-action
  candidate; George records the decision and disposition. Milton derives
  `acted-on` by joining back to that receipt.

## Current reality and drift

The Phase 0 spine is real: eight local adapters, normalized events, refutable
crosswalks, privacy-aware coverage, exact-key accounting, activity projection,
and an append-only findings ledger. The live corpus already supports explicit
Fab-to-Somm and George-to-Git paths.

The product is not yet the vision:

- accounting is source-honest but most priced rows still lack a shared provider
  billing key and a known marginal/notional/included classification;
- outcome records exist, but there is no canonical cost-per-outcome projection;
- finding types and revisions exist, but no generator, review CLI, action
  receipt, or measured precision loop exists;
- Somm and George currently contain proposals to store or display task-level
  cost and outcomes themselves, which must be reframed as consumers of Milton's
  cross-source projection rather than parallel retrospective ledgers; and
- the package builds locally, but release/publishing proof is not part of the
  current product evidence.

Drift is work input, not a reason to weaken the vision. The gated sequence lives
in [ROADMAP.md](ROADMAP.md); executable work packets live under `plans/`.

## Non-goals

- Not a tracing or observability SaaS, and not an SDK every agent must adopt.
- Not a thin integration facade or a venture-style uniqueness exercise. Milton
  owns compact mechanisms that make the factory coherent and releases useful
  infrastructure without optimizing the architecture for hosted lock-in.
- Not a dashboard-first product; typed query and finding contracts precede UI.
- Not an eval framework, prompt manager, gateway, runner, or workflow engine.
- Not a real-time judge or controller of individual sessions.
- Not an external technology scout or research recommendation engine; that is
  Projector's boundary.
- Not an autonomous cleanup agent. Retirements, routing changes, promotions,
  and other effects remain owned and receipted by the affected system.

## Decision journal

- **2026-07-17:** retained acted-on findings as the north star; narrowed the
  initial proof to cost-per-outcome plus one deterministic stale-gate finding;
  kept Somm independent and made Milton the retrospective cross-source owner;
  separated Milton's internal-exhaust synthesis from Projector's external
  intelligence boundary.
- **2026-07-17:** made vertical integration the default for the strategic
  evidence chain. Truly open, locally complete, replaceable components remain
  eligible for focused reuse; open-core, source-available, proprietary, or
  hosted-first systems are inspiration or optional interchange surfaces unless
  a documented exception passes the build-versus-adopt gate.
