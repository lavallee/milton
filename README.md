# milton

**Understand what your agents actually did.**

Milton ingests the exhaust that LLM agents and their infrastructure already
produce — coding-agent session transcripts, runner receipts, gateway audit
ledgers, git activity — normalizes it, and emits **graded, typed findings**:

- **Performance accounting** — cost and tokens per *outcome* (per merged PR,
  per resolved task, per shipped change), not per token. The number everyone
  agrees is right and everyone computes in a spreadsheet.
- **Failure motifs** — recurring patterns across sessions: retry storms, tool
  errors, stalls, injection attempts, interventions.
- **Procedure candidates** — work shapes that recur often enough to be worth
  codifying (the feed for a skill/chip distillation pipeline).
- **Memory hygiene** — read-back auditing of what agents have banked: which
  stored memories, rules, and skills are actually consulted, and which are
  write-only.

## Why

Cross-session synthesis exists today only in closed, SDK-instrumented SaaS.
Nothing open and self-hostable reads the heterogeneous exhaust that already
sits on your disk — and the highest-value corpus (coding-agent session logs,
runner receipts) is structurally unreachable by SDK-based products. Milton is
adapters-first and reads what's already there.

Two principles govern the design:

1. **No tool lock-in.** People use Claude Code, Codex, Cursor, aider, hermes,
   and things not invented yet — some through a gateway, some direct to a
   provider. Milton reports on all of it. A gateway can speak authoritatively
   only for the traffic it mediated; milton's job is the whole picture.
2. **Findings are graded, or they're slop.** Every finding is a typed record
   carrying its evidence references and a grading state (hypothesis →
   corroborated), promoted only when independent evidence agrees. Pattern
   synthesis over transcripts is exactly where hallucinated insight hides;
   the grading discipline is the product.

## Status

Pre-build. This repository currently holds the commission: the
[workplan](docs/workplan.md), the [boundary contracts](docs/boundaries.md)
with adjacent systems, and the [landscape research](docs/landscape.md) that
shaped them.

Planned distribution: PyPI as `milton-agents` (the bare name is taken;
import package is `milton`).

## Relationship to adjacent projects

- [somm](https://github.com/lavallee/somm) — the LLM gateway. Authoritative
  for somm-mediated calls; its audit ledger is milton's richest single
  adapter. Somm delegates cross-source retrospective analysis to milton;
  milton feeds findings back for somm's routing advice. See
  [boundaries](docs/boundaries.md).
- [chip](https://github.com/lavallee/chip) — portable operational components.
  Milton's procedure-candidate findings feed chip's candidate-ledger
  convention; a mature milton analysis loop may itself run as chips.
- fab (being open-sourced) — the reference runner whose receipts are a
  first-class adapter.

## License

MIT.
