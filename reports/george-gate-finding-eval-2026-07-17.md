# George gate finding evaluation — 2026-07-17

## Decision

Keep all three George gate rules **offline**. The live review verifies exact
negative and abstention behavior, but the held-out partition has no independent
positive family. Precision is therefore unavailable, not 100%, and no rule can
cross the 0.90 surfacing floor or the 0.80 narrow floor.

This decision is enforced by the generation path. The same corpus yields no
surface-approved rules and an append attempt exits non-zero with
`no detected finding belongs to a rule approved for surfacing`. Dry run remains
available for operator review and for collecting future labels.

## Bounded source and custody

- Source adapter: `george`
- Source interval: 2026-07-07T00:00:00Z through exclusive
  2026-07-17T22:45:00Z
- Retained local event store: `.milton/a2-gates-inventory-2026-07-17.db`
- Generator: `milton.george-gates/v1`
- Evaluator: `milton.george-gates-eval/v1`
- Source snapshot: `snp_546a84525628b655c7128c56`
- Frozen corpus: `evals/george-gates/cases-v1.jsonl`
- Corpus snapshot: `evl_7ea8940456dd4e898414c2c1`

The committed corpus contains immutable structural event IDs and source
coordinates but no George entry bodies. This report replaces live coordinates
with packet labels. The local SQLite source is ignored by Git and remains the
reproducibility authority for the structural IDs.

## Independent labeling boundary

Five cases are explicitly tuning-only:

- packet T1: one canonical target minted 12 times and later resolved by an
  exact human decision;
- packets T2 and T3: two decisions that target individual mint receipts and
  resolve exactly through mint-to-canonical-coordinate mapping;
- one re-mint claim over packet T1; and
- one duplicate mint from packet T1 that must not count as a second family.

Those observations informed the detector's threshold and resolution mapping.
They are not represented as held-out evaluation.

Nine held-out cases use coordinates disjoint from tuning: two unresolved
condition negatives and one unkeyed condition ambiguity; two single-mint
re-mint negatives and one unkeyed ambiguity; and one old gate with unavailable
consultation evidence, one too-young negative, and one unkeyed ambiguity. Each
label includes a rationale and exact immutable source coordinates in the
frozen JSONL corpus.

The source contains no explicit consultation receipts. Missing consultation is
therefore labeled ambiguous and expected to abstain; it is never reinterpreted
as `not consulted`.

## Held-out results

| Rule | Cases | TP | FP | TN | FN | Abstain | Exact | Coverage | Precision | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| condition resolved | 3 | 0 | 0 | 2 | 0 | 1 | 3 | 66.7% | unavailable | offline |
| re-minted | 3 | 0 | 0 | 2 | 0 | 1 | 3 | 66.7% | unavailable | offline |
| old/unconsulted | 3 | 0 | 0 | 1 | 0 | 2 | 3 | 33.3% | unavailable | offline |

All nine held-out expectations match exactly. That verifies the current
negative/abstention boundary, but it does not estimate positive predictive
value. A rule with no held-out predicted positives cannot receive a precision
score and cannot be surfaced.

## Full-window dry run

The fresh-source projection produced 93 assessments: 4 detected, 72 not
detected, and 17 abstentions. Its four review candidates are three
condition-resolved leads and one re-minted lead. The generator's maximum grade
is `lead`; it cannot self-promote to `corroborated`. Because the evaluation
approved zero rules, the emission projection contains zero candidates and
writes nothing to the finding ledger.

## Reproduction

Evaluate the frozen cases:

```console
uv run milton findings evaluate \
  --store .milton/a2-gates-inventory-2026-07-17.db \
  --cases evals/george-gates/cases-v1.jsonl \
  --format json
```

Review full-window candidates under the frozen decision:

```console
uv run milton findings generate \
  --generator george-gates \
  --store .milton/a2-gates-inventory-2026-07-17.db \
  --since 2026-07-07T00:00:00Z \
  --until 2026-07-17T22:45:00Z \
  --evaluation-cases evals/george-gates/cases-v1.jsonl \
  --dry-run --format json
```

Remove `--dry-run` to verify fail-closed append behavior. No source system is
contacted or mutated by either command.

## Next evidence required

The detector may graduate only after the frozen corpus is versioned with
independent, disjoint held-out positives:

1. at least one newly observed resolved-condition family not used to alter the
   rule;
2. at least one newly observed re-mint family reviewed as independently
   supported; and
3. explicit consultation or non-consultation receipts before evaluating the
   old/unconsulted positive path.

Until then, a live George round trip may exercise the versioned intake contract
using an explicitly manual, tuning-sample review packet, but it must not be
represented as a surfaced Milton finding or as held-out precision evidence.
