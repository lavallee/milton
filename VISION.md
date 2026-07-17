# Vision

Milton exists so that a person or team running LLM agents can answer, with
evidence, the questions that actually govern the work: what did the agents do,
what did it cost per outcome, what keeps going wrong, what have they learned
that should be banked, and what have they banked that is dead weight.

## North-star metric

**Acted-on findings** — graded findings that led to a receipted change: a
procedure codified, a memory retired, a budget adjusted, a failure motif
fixed. A finding nobody acts on is a report; the loop closes only when the
insight changes the system that produced the exhaust.

## Guardrails (what must not rise while the north star rises)

- **False-finding rate.** A finding promoted to `corroborated` that a human
  later refutes. The grading ladder exists precisely to keep this near zero;
  synthesis quality is measured against held-out labeled cases, not vibes.
- **Coverage honesty.** Milton must state what it could not see (missing
  adapters, unreadable stores, truncated retention) in every report. A
  partial picture presented as whole is worse than no picture.
- **Privacy posture.** Session transcripts are the most sensitive corpus a
  development machine holds. Milton is local-first, ships nothing anywhere,
  and treats redaction and aggregation thresholds as first-class features,
  not enterprise add-ons.
- **Shim discipline.** Milton's LLM-assisted synthesis stages are candidates
  for their own obsolescence: as models get better at direct log analysis,
  milton should shrink toward adapters, the normalized model, the grading
  ledger, and the join keys — the parts that stay valuable regardless of
  model capability.

## Non-goals

- Not a tracing/observability SaaS, and not an SDK you must wire into agents.
- Not a dashboard product first — the query surface and typed findings come
  before any UI.
- Not an eval framework, a prompt manager, or a gateway.
- Not a judge of individual sessions in real time; milton is retrospective
  synthesis across many sessions.
