# Landscape

**Evidence date:** 2026-07-17
**Posture:** primary-source product/repository review plus the existing Projector
software-factory and workflow-primitive scans. Shipped capability, preview or
beta capability, vendor claim, and local inference remain distinct.

**Dependency posture:** Milton prefers a vertically integrated, dependency-light
evidence chain. Market offerings are design evidence first. Adoption requires
the complete-open-source and replaceability gates in
[build, borrow, or adopt](build-vs-adopt.md).

## Position in one sentence

Milton is not the only local coding-agent log analyzer, the only
cross-session synthesis system, or the first product to show cost per commit or
pull request. Its defensible wedge is the combination this review did not find
elsewhere: **post-hoc heterogeneous coding-agent evidence, conservative
cross-source cost reconciliation, real outcome joins, graded findings, and
receipted actions**.

That claim is intentionally conjunctive. Each component has credible adjacent
or competing implementations.

The conjunction is not a venture-style uniqueness exercise. Milton is being
built to fit the software factory and be useful to others; any differentiated
product position is a consequence of coherent infrastructure, not the reason to
outsource or withhold useful mechanisms.

## Competitive and adjacent map

| Category | Current offerings | What is actually shipped | Boundary relative to Milton |
| --- | --- | --- | --- |
| Cross-session semantic synthesis | [LangSmith Insights](https://docs.langchain.com/langsmith/insights), [Braintrust Topics](https://www.braintrust.dev/docs/observe/topics), [Datadog Patterns](https://docs.datadoghq.com/llm_observability/monitoring/patterns/), [Arize AX Signal](https://arize.com/blog/building-ai-factory-self-improving-agents-arize-ax/) | Behavior/failure categorization, facet extraction, clustering, trend or drift views, and cost/error/eval overlays over traces held by each platform. AX additionally claims persistent issue memory and proposed remediation. | These systems set the quality bar for failure motifs. They remain primarily proprietary and trace-platform scoped. Milton must win on native historical corpus reach, evidence locators, privacy, precision, and action receipts—not on generic clustering. |
| Local coding-agent trace analysis | [TraceLab](https://github.com/uw-syfi/TraceLab), [ccusage](https://github.com/ccusage/ccusage) | TraceLab normalizes and validates local Claude/Codex histories, publishes a sanitized 357k-round research corpus, and ships reproducible workload analyses and a local viewer. ccusage reads local usage across many coding CLIs. | TraceLab is both competitor and useful analogue for normalized rounds, cache accounting, validators, and self-contained analysis artifacts. Milton should not duplicate serving-workload plots; it adds cross-system identity, outcomes, findings, and actions. |
| Cost per engineering output | [Claude Code Analytics](https://code.claude.com/docs/en/analytics), [CodeTelemetry](https://codetelemetry.com/dashboards/productivity), [cc-ledger](https://github.com/delta-hq/cc-ledger) | Claude reports estimated cost and contribution metrics, including cost-per-commit/value formulas. CodeTelemetry shows estimated dollars per commit/PR. cc-ledger joins Claude hooks, transcripts, Git, branches, and PRs for local rollups. | The label is occupied. Milton must distinguish reported from computed and marginal from notional/included; reconcile multiple observers by exact identity; model merged, reverted, failed, and abandoned outcomes; and keep ambiguous/unallocated spend visible. |
| Memory runtime and retention | [agentmemory](https://github.com/rohitg00/agentmemory) | A local multi-agent memory service with capture, retrieval logs, decay/retention, stale eviction, contradiction handling, provenance, audit, and broad coding-agent integrations. Its repository is Apache-2.0, but its required iii engine is ELv2. | Useful design evidence and an optional audit source for existing operators, not a Milton dependency or default substrate. Milton should distinguish loaded/retrieved/applied evidence and emit reviewable keep/park/retire findings rather than automatically forgetting. |
| Open-core trace/eval substrate | [Langfuse](https://github.com/langfuse/langfuse) and adjacent OTel systems | Self-hosted traces, sessions, cost analytics, user-defined judges, and review queues. The repository is MIT except its `ee` directories. | Optional input/export surface and design reference, not Milton's canonical store or required runtime. OTel remains optional because native coding-agent exhaust contains richer retrospective context and the conventions continue to change. |
| Research template | [Anthropic Clio](https://www.anthropic.com/research/clio) and its [coding-interaction study](https://www.anthropic.com/research/impact-software-development) | Facet extraction, semantic clustering, descriptions, hierarchy, and privacy thresholds, applied internally to a large Claude corpus. | The intellectual pattern remains relevant, but it is not the product claim. Milton must connect motifs to local receipts and measured changes; the cited coding study did not connect interactions to eventual code quality or shipped outcomes. |

## Market-map posture

The map answers two separate questions:

1. **What should Milton learn?** Almost everything is fair game for close study:
   interaction patterns, schemas, formulas, evaluation design, privacy
   thresholds, UX, and failure modes.
2. **What should Milton depend on?** Very little. Strategic evidence semantics
   stay inside Milton. A component becomes eligible only when its full
   load-bearing stack is truly open source, locally complete, exportable,
   security-reviewable, and replaceable.

Accordingly:

- proprietary products are deep-inspiration and quality-bar inputs;
- open-core or source-available systems are optional interchange targets at
  most;
- complete permissively licensed tools may provide small borrowed mechanisms,
  test oracles, or optional adapters; and
- a runtime dependency is justified only when the component is unusually
  complex or safety-sensitive and passes a documented build-versus-adopt
  decision.

This posture deliberately favors an integrated factory over a portfolio of
loosely coupled third-party products. The security benefit is fewer external
packages, installers, hosted services, and upgrade paths; the counter-risk is
owned maintenance, which is controlled with narrow contracts and deletion
tests.

## Corrections to the original thesis

The first landscape draft made useful directional bets but overstated novelty.
The following claims are retired:

- **“Cross-session synthesis exists only closed and SDK-gated.”** Closed
  platforms dominate semantic synthesis, but LangSmith accepts uploaded chat
  histories, Braintrust documents an early-access self-hosted path, and
  TraceLab is local and open. The meaningful distinction is semantic synthesis
  plus outcome/action evidence, not whether any cross-session analysis exists.
- **“The coding-agent corpus is unreached.”** TraceLab directly reads Claude and
  Codex histories; cc-ledger reads Claude transcripts and Git/PR state;
  CodeTelemetry accepts Claude/Codex telemetry. The remaining opening is
  heterogeneous post-hoc semantic analysis with conservative cross-source
  joins.
- **“Cost per outcome is named but shipped nowhere.”** Cost per commit/PR has
  shipped in provider-local and local forms. The unresolved problem is causal
  and accounting honesty: exact lineage, economic meaning, quality/revert
  outcomes, and an unallocated remainder.
- **“Memory read-back auditing is implemented nowhere.”** agentmemory records
  access and uses it in retention. Milton's narrower opportunity is independent
  audit across multiple stores, including stores that cannot prove a retrieved
  memory influenced behavior.

No future document should use a global “nobody does this” claim. The supported
form is: **this dated scan found no verified offering that combines** Milton's
full contract, followed by the exact contract.

## Strongest product implications

### Outcome attribution is urgent, not optional polish

Competitors already occupy the attractive cost-per-PR phrase. Milton's first
proof must show why conservative attribution is different:

- provider/source amount versus locally computed amount;
- actual, estimated, and unknown accuracy;
- marginal cash cost versus subscription-included or notional value;
- exact shared billing identity versus source-local replay identity;
- landed, reverted, failed, abandoned, and runner-only outcomes; and
- attributed, ambiguous, and unallocated totals that reconcile to selected
  observations.

### Failure motifs need an evaluation advantage

Braintrust, Datadog, LangSmith, and AX make a cluster browser undifferentiated.
Milton should require evidence locators, independent receipt corroboration,
aggregation/privacy thresholds, a held-out labeled corpus, explicit precision
floors, retained refutations, and action receipts. The first stale-gate detector
is intentionally deterministic so the lifecycle can be proven before adding a
model-assisted synthesis pipeline.

### Memory hygiene is an audit role

Milton should learn from agentmemory's staged access model and may add an
optional adapter for an operator who already runs it, but should not adopt its
runtime: the required iii engine is ELv2. “Read” must be decomposed into
inventory, loaded into context, retrieved by a memory system, referenced by
later work, and causally applied. Most hosts can prove only a subset. Missing
evidence remains unknown, not write-only.

### TraceLab is a borrow/compare candidate

Before extending Milton's Claude/Codex normalization, compare TraceLab's round
schema, prompt-cache derivation, sanitization, denominator/formula validators,
and self-contained analysis artifact convention. Its Apache-2.0 code is
eligible for focused reuse with provenance and notices, but true openness is
eligibility rather than an architectural reason to import the whole stack.
Borrow only mechanisms that preserve Milton's event/crosswalk contracts; do not
create a second normalized store or import the public corpus as though it
contains outcome truth.

## Complementary local systems

Projector's July software-factory scan remains the controlling local ownership
context:

- George owns intent, decisions, and action disposition.
- Fab owns supervised runs, recovery, and terminal/evidence receipts.
- Somm owns model/provider/harness selection, hot-path spend control, and one
  mediated call or attempt's facts.
- Projector owns external-development evidence, recommendations, experiment
  gates, and adoption calibration.
- Milton owns retrospective projections and findings over internal operational
  exhaust.
- Chip owns the procedure-candidate contract; Spindle owns composition,
  evaluation, distribution, and binding.

The key crossfeed is outcome-shaped: Projector recommendations and
Chip/Spindle promotions carry stable ids into George/Fab; Milton measures the
later operational result; Projector, Somm, or Spindle may consume that versioned
projection. None needs a copy of Milton's private event store.

## Evidence limits and refresh triggers

- Vendor documentation is authoritative for declared surface area, not quality
  or comparative effectiveness.
- AX Signal availability, limits, precision, and remediation acceptance remain
  unverified beyond its announcement.
- CodeTelemetry's production attribution method is not public; sample formulas
  do not prove reconciliation behavior.
- cc-ledger is young and currently narrower than its broader landing-page
  language.
- agentmemory access logs prove use of its retrieval surface, not semantic or
  causal influence on the model.
- Commit, PR, and lines-added counts are not automatically successful outcomes;
  reviews, reverts, correctness, and delayed value matter.

Refresh this landscape when a named system materially changes corpus access or
outcome semantics, when Milton graduates cost-per-outcome or the first finding
pilot, or at least quarterly while these categories remain fast-moving.
