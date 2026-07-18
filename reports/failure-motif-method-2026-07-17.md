# Failure-motif method checkpoint — 2026-07-17

## Decision

Select bounded direct synthesis behind Milton-owned deterministic facets and
corroboration gates. Do not integrate facet-only clustering as the synthesis
surface. Facets remain useful as inspectable evidence and hard promotion
controls, but the facet-only model input lost two of three operator-relevant
families in the held-out comparison.

This is a deliberately small, vertically integrated mechanism: Milton owns
case construction, facets, recurrence/privacy gates, evaluation, and finding
records. The local model/harness used for this experiment is not a runtime
dependency.

## Frozen comparison

- Corpus: 4 tuning and 12 held-out cases across 16 disjoint synthetic,
  source-shaped sessions.
- Content: metadata-only signal and receipt identifiers; no prompt,
  transcript, tool body, path, repository, or user content.
- Corpus SHA-256:
  `dd5540f7fbf0157c26ae842913f5468ad707907a4b799ff6bb14720182282f04`.
- Model: locally installed `qwen2.5:7b`, exact Ollama blob
  `sha256-2bada8a7450677000f678be90653b85d364de7db25eb5ea54136ada5f3933730`.
- License observed from the local model manifest: Apache-2.0.
- Harness: local Ollama generate API, temperature 0, seeds 17 and 23.
- Equal model budget: one call and at most 1,600 output tokens per method per
  seed. Deterministic facet extraction uses no model budget.

| Measure | Direct synthesis | Deterministic facet → cluster |
| --- | ---: | ---: |
| Precision, both seeds | 1.00 | 1.00 |
| Recall, both seeds | 0.889 | 0.333 |
| Operator-value family coverage | 0.667 | 0.333 |
| Assignment stability, Jaccard | 1.00 | 1.00 |
| Model calls per seed | 1 | 1 |
| Prompt/output tokens per seed | 1,459 / 211 | 1,312 / 77 |
| Runtime per seed | 6.85–7.02 s | 2.87–2.89 s |
| Maintenance units | 1 | 2 |

There is no reported or computed dollar amount for these local runs. The
experiment records both as unavailable, with the resource basis
`local-included-unpriced`; token counts and elapsed time are not silently
converted into a dollar cost.

## Counterexamples and limits

Direct synthesis found all retry-storm and context-drift cases, but grouped
only two of three permission-loop cases. Because a recurring motif requires
three independent sessions, that family must abstain rather than surface. The
facet-only path emitted only retry-storm and missed all six context-drift and
permission-loop assignments.

A preliminary two-model-call facet run also exposed a coordination cost: its
first 400-token facet budget truncated the schema before all twelve cases were
represented. Raising the total budget made it complete, but the final fair
comparison instead moved facet extraction into deterministic local code and
gave both synthesis methods one equal-budget model call.

The corpus is deliberately bounded and source-shaped, not a claim about broad
production precision. A live scan in A-4.3 must stay within tolerance of this
frozen result, retain abstentions, and never promote its own output.

## Reproduction

```console
uv run python experiments/failure-motifs/run.py \
  --output /tmp/milton-motif-method.json
```

The runner validates tuning/held-out session disjointness, pins model/harness
parameters, retains raw findings and every missed/false-positive/invalid case,
and applies the published selection rule.
