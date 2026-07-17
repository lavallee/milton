# Boundaries: milton and its neighbors

Milton sits in an ecosystem with a gateway (somm), a runner (fab), a
component contract (chip), and whatever harnesses people actually use. The
boundaries below are commitments, not aspirations; each one answers "who is
authoritative for what."

## milton ↔ somm (the load-bearing boundary)

**Somm is authoritative for somm-mediated work.** Its audit ledger (calls,
decisions, eval receipts) is ground truth for every call it routed:
provider, model, tokens, cost, outcome codes, decision rationale. Milton
never re-derives or second-guesses those records — it ingests them as the
richest single adapter.

**Milton is authoritative for the whole picture.** A deliberate principle of
these systems is that usage is never constrained to our own tools: agents
run through Claude Code, Codex, Cursor, aider, hermes, and direct provider
APIs, and much of that traffic never touches a gateway. Only a
gateway-independent reader can do performance accounting, motif mining, or
memory auditing over *all* of it. Gateway ledgers are one adapter among
several — privileged in richness, not in scope.

**Division of labor:**

| Concern | Owner |
| --- | --- |
| In-flight routing, fallback, spend gates, model advice | somm |
| Per-call audit records for mediated traffic | somm |
| Cross-source normalization and the ID crosswalk | milton |
| Retrospective synthesis (motifs, drift, candidates, hygiene) | milton |
| Cost-per-outcome joins (spend ↔ git/PR/receipt outcomes) | milton |
| Consuming findings to improve routing advice | somm (reads milton) |

**Divestment path.** Somm today carries the beginnings of cross-project
analysis (decision recall, eval aggregation). As milton matures, somm
delegates retrospective/cross-source analysis to milton and keeps what only
a gateway can do: mediate, meter, and advise in-flight. The two remain
separately usable — somm without milton is a complete gateway; milton
without somm still reads sessions, receipts, and git.

**Mutual awareness.** Somm's records carry correlation/session identifiers;
milton's crosswalk joins them to harness session ids, runner job ids, and
commits. Where identifiers are missing, that is a coverage-honesty finding,
not something to paper over.

## milton ↔ harnesses (Claude Code, Codex, Cursor, aider, hermes, …)

Adapters read each harness's native on-disk exhaust (JSONL transcripts,
session stores, history files) without requiring any change to the harness.
Adapter maintenance is acknowledged treadmill work — the price of the
no-lock-in principle — and each adapter declares what it can and cannot
recover (tokens, tool calls, models, timestamps) so coverage stays honest.
OpenTelemetry GenAI input is one optional adapter, not the foundation: the
conventions are still in development-status churn, and the highest-value
corpora are not OTel today.

## milton ↔ chip

Milton's procedure-candidate findings are emitted in chip's candidate-ledger
convention (`candidates.jsonl`: shape, occurrence refs, fixture-worthy
examples, counts) so a distillation pipeline can mint from them. The
grading discipline matches chip's evaluation posture: a candidate is a
hypothesis until receipts corroborate recurrence. Down the road, milton's
own recurring analysis passes are natural chips (deterministic ingestion
with one bounded synthesis stage, receipted on a host) — milton the library
stays runtime-free either way.

## milton ↔ runners (fab and others)

Runner receipts (attempts, outcomes, verifier verdicts, chip receipts,
rollups) are the corroboration substrate: they turn transcript-derived
hypotheses into graded findings and provide the outcome side of
cost-per-outcome. Fab is the reference adapter; the receipt reader is
format-driven so other runners can implement the same surface.

## The grading ladder (cross-cutting)

Findings move `lead → candidate → corroborated`, in the style of
evidence-gated research notebooks: an LLM-extracted pattern is a lead; a
structural bar (recurrence count, multiple sources) makes it a candidate;
independent corroboration (a receipt, a matched outcome, a human
confirmation) promotes it. Refuted findings are retained with their
refutation — negative evidence is evidence.
