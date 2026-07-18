# Procedure-promotion pilot — 2026-07-17

## Decision

Accept A-4.6 for one narrow procedure-policy loop. Spindle independently
evaluated and bound a content-hashed procedure after a frozen held-out result;
Fab and Somm retained the exact post-bind execution; Milton classified the
paired operational result as `improvement` and appended calibration. The
result supports this policy-adherence fixture family, not general production
efficacy.

## Source and candidate custody

The candidate was derived from the accepted metadata-only retry-storm source
finding `fnd_d0d736bd26707214a5ea3514`, synthesis receipt
`syn_45e6a8b4a33212a6f723084c`, and result
`evr_4d9dc501cafb85df13703f29`. Milton materialized a separate immutable
procedure-candidate revision rather than claiming that motif recurrence itself
proved a remedy:

- Milton finding: `fnd_7225d1bba731685f2c9ce88a`
- exact revision: `fnr_a40360546d07b06e44f0abb6`
- Chip candidate: `chc_dde41c1f40bb024d05c6fa45`
- Chip receipt: `ccr_7d9cbcbc9bd8d77b94380ce4`

Running preparation twice left one Milton revision, one Chip candidate row,
and one Chip receipt. The candidate preserves three occurrence references, a
failed-tool control reference, development/held-out/operational fixtures, the
source snapshot and expiry, and the explicit non-claims that the motif does not
establish root cause, avoidable cost, or universal remedy.

## Development and frozen evaluation

The local model was Qwen 2.5 7B at installed blob
`sha256:2bada8a7450677000f678be90653b85d364de7db25eb5ea54136ada5f3933730`.
The profile/harness was
`factory-recovery-controller@1` / `ollama-chat/v1;temperature=0;num_predict=1024;format=decision-schema-v1`.
The baseline implementation was `raw-factory-recovery-controller@1`; the
final procedure implementation was
`sha256:1db53f01e1367a79ca93c5b7ec7bd96dfbc3373565a15c5909c140ede4d80f13`.

Development caught real ambiguity. The initial prose barely improved the mean
(0.567 to 0.600) and sometimes invented authority. A literal decision table,
tuned only on the development split, produced 0.567 to 0.933. Both earlier
tuning receipts and the final development receipt are retained; development
runs are never promotion-eligible by themselves.

The disjoint four-case held-out split was then frozen and run once:

- baseline mean: `0.525`
- procedure mean: `1.000`
- delta: `+0.475`
- runner errors: `0`
- required delta: `0.10`
- Spindle decision: eligible
- evaluation receipt: `spr-eval-6692c606539e55f2df45b379`

Spindle, not Milton, recorded evaluated binding `2168806fc137fd9a` and
promotion receipt `spr-promote-a479e8689d984045d38773b3`. Both receipts carry
the exact Milton/Chip origin and baseline/variant tuple.

## Operational measurement

A fresh case, excluded from development and held-out evaluation, compared the
same raw and bound systems through actual pinned Somm calls to local Ollama,
with fallback disabled and the same response schema:

| Arm | Somm call | Score | Input / output tokens | Cost status |
| --- | --- | ---: | ---: | --- |
| Baseline | `2d25b2fa-2d40-439d-85b4-17fb7eadb8d3` | 0.30 | 114 / 52 | included / unpriced |
| Bound procedure | `18ca4a49-2e20-4586-a79b-5c4103074372` | 1.00 | 403 / 62 | included / unpriced |

Fab job `milton-procedure-pilot-2026-07-17` retained the origin and tuples,
linked its attempt to the promoted Somm call, and emitted semantic outcome
receipt `fabr-1384f82289f034a484a4b113`. Somm receipt
`01bea229-c9c6-4a5c-8b66-d08ff5bb684a` stores the baseline call as
`source_call_id` and the promoted call as `call_id`; neither side is merely a
caller-provided label.

Milton ingested only public Chip/Spindle/Fab/Somm surfaces. Calibration
`pcr_21b017c8b3d72f1405eafc55` classified the exact 0.30 to 1.00 comparison as
`improvement`, with no custody or tuple-mismatch reasons, and finding activity
became `promoted`. Re-running the held-out phase made zero additional model
calls and appended zero procedure receipts.

## Accounting and limits

Ollama supplied no reported dollar amount or invoice. Somm classifies both
calls as `basis=unknown`, `kind=included`, `accuracy=unknown`, and
`source=local-included-unpriced`; Milton therefore retains their token usage
but sets the monetary amount to unavailable. Computed economic cost is also
unavailable because no local electricity, hardware amortization, or
opportunity-cost rate model is configured. Somm's backward-compatible numeric
result field remains `0.0`, but the provenance contract explicitly identifies
it as a sentinel rather than an economic zero.

The first operational pass exposed the older misleading
`computed/marginal/estimated $0` semantics. Its artifacts are retained with
the `v0-cost-semantics` suffix and its private store under
`.milton/partial-checkpoints/`; no call history was overwritten. The producer
contract and Milton adapter were corrected, then only the fresh operational
pair was rerun. The frozen Spindle held-out evaluation and promotion receipt
were reused unchanged.

This measures adherence to a narrow repeated-permission recovery policy on
synthetic, source-shaped fixtures. It does not show that the procedure improves
arbitrary coding tasks, that the fresh scenario occurred in production, or
that one comparison estimates a general effect size. The durable result is
therefore a positive calibration observation, not a universal promotion claim.

## Retained proof

Public evidence is under
`reports/evidence/procedure-promotion-2026-07-17/`. It includes the exact
finding/export/Chip receipts, all three development receipts, frozen Spindle
evaluation and promotion receipts, call hashes and token/cost summaries, the
Somm outcome receipt, Milton calibration, and the compact end-to-end summary.
The private Somm/Fab/Milton stores remain under `.milton/procedure-promotion/`.
