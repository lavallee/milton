# Landscape (research digest, 2026-07)

Distilled from a primary-source scan; URLs inline. This is the evidence base
for the workplan's bets.

## Cross-session synthesis exists — only closed and SDK-gated

The category moved past "store traces, render waterfalls, run evals" in the
last ~12 months, but every instance is proprietary and requires
instrumenting your agents with the vendor's SDK: LangSmith Insights
(clustering + drift, https://docs.langchain.com/langsmith/insights),
Braintrust Topics (UMAP+HDBSCAN, https://www.braintrust.dev/blog/topics),
Datadog LLM Obs Patterns
(https://docs.datadoghq.com/llm_observability/monitoring/patterns/), Arize
AX Signal (closed beta, https://arize.com/docs/ax/observe/signal), Galileo
Insights Engine. **No OSS/self-hostable tool does any cross-session
synthesis**: Langfuse's docs enumerate none
(https://langfuse.com/docs/analytics/overview); Arize Phoenix removed its
clustering in v13
(https://github.com/Arize-ai/phoenix/blob/main/MIGRATION.md); Helicone and
AgentOps stop at dashboards/replay.

## The coding-agent corpus is unreached

Session-log tooling splits into cost accounting and rendering. ccusage
(https://github.com/ryoppippi/ccusage) normalized cost across ~15 agents'
local logs — zero semantic analysis. Viewers (claude-code-log,
claude-code-viewer) render. sniffly (https://github.com/chiphuyen/sniffly)
is the lone behavioral tool and is intentionally light. First-party
analytics (https://code.claude.com/docs/en/analytics) count outcomes
(sessions, spend, PR attribution) without analyzing behavior; the OTel
export (https://code.claude.com/docs/en/monitoring-usage) is a pipe, not
insight. SDK-based SaaS structurally cannot read on-disk exhaust after the
fact — the highest-value corpus is theirs to miss.

## The intellectual template: Clio

Anthropic's Clio (https://www.anthropic.com/research/clio,
https://arxiv.org/abs/2412.13678): facet extraction → embedding clustering
→ LLM cluster description → hierarchy, with privacy thresholds — applied to
~500k coding interactions
(https://www.anthropic.com/research/impact-software-development). It exists
as population-scale internal research, not as a tool you point at your own
logs. "Clio for your own exhaust" is the milton phase-2 shape.

## Cost-per-outcome: named everywhere, shipped nowhere

FinOps for AI names custom value metrics as the goal and computes nothing
(https://www.finops.org/wg/finops-for-ai-overview/). Provider cost APIs
stop at workspace/model/day. LiteLLM tags reach task granularity with
manual instrumentation (https://docs.litellm.ai/docs/proxy/cost_tracking).
Where cost-per-merged-PR numbers exist, they are hand-built spreadsheets
(https://getunblocked.com/blog/cost-per-merged-pr/). Outcome-based
*pricing* exists in CX (Sierra, Intercom Fin) — billing, not accounting.

## Memory hygiene: a plantable flag

Promotion research is mature (reflection scoring, sleep-time refinement:
https://arxiv.org/abs/2504.13171, Mem0 https://arxiv.org/abs/2504.19413,
Zep/Graphiti https://arxiv.org/abs/2501.13956); forgetting is the neglected
half, and store-wide **read-back auditing** — detecting memories banked but
never consulted — is named only in passing by early-2026 preprints
(https://arxiv.org/abs/2605.26112, https://arxiv.org/abs/2605.24579,
https://arxiv.org/abs/2604.12007) and implemented nowhere. Benchmarks
(LoCoMo, LongMemEval) test recall, not write discipline.

## Standards posture

OTel GenAI semantic conventions remain development-status with active
breaking churn
(https://github.com/open-telemetry/semantic-conventions-genai); the only
cross-session construct is a bare `gen_ai.conversation.id`. Ride OTel as
one optional adapter; do not build on it.

## The bear case (kept in view)

1. Anthropic ships "Clio for your team" first-party and erases the largest
   single corpus advantage.
2. SaaS incumbents out-engineer the synthesis; an OSS entrant must win on
   corpus reach + finding trustworthiness, not algorithms.
3. Graded findings degrade into LLM-judge slop without a measured precision
   floor — the finding-quality eval harness is not optional.
4. Cost-per-outcome attribution is inherently noisy; honesty about the
   method is the only defensible posture.
5. Adapter maintenance is a treadmill, not a moat; it is the price of the
   no-lock-in principle, accepted knowingly.
