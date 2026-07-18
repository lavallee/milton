# George gate evaluation corpus v1

This corpus freezes the first bounded live review of George gate evidence from
2026-07-07 through the exclusive 2026-07-18 cutoff. Cases contain structural
event IDs and gate coordinates only; they do not retain entry bodies.

The partitions are deliberately asymmetric. The repeated gate family and the
three observed resolution paths informed rule design, so all positive examples
are marked `tuning`. Held-out cases use disjoint coordinates and test negative
and ambiguous behavior. The held-out sample contains no independently observed
positive re-mint or resolved-condition family, and the source contains no
explicit consultation receipts. Precision is consequently unavailable rather
than imputed from tuning evidence, and all three rules remain offline.

Labels mean:

- `supported`: the evidence packet supports the rule's claim;
- `unsupported`: the packet provides enough coverage to reject the claim;
- `ambiguous`: a required coordinate or receipt is unavailable, so abstention
  is expected; and
- `duplicate`: evidence is part of an already represented family and must not
  be counted as an independent positive.

Reproduce the evaluation against the retained live store:

```console
uv run milton findings evaluate \
  --store .milton/a2-gates-inventory-2026-07-17.db \
  --cases evals/george-gates/cases-v1.jsonl \
  --format json
```

Generation uses this decision directly. An append attempt with this corpus is
refused because no rule meets the 0.90 promotion floor; `--dry-run` remains
available for review and future labeling.

The gate-specific reader feeds `milton.finding-evaluation/v1`, the same
generator-neutral harness used by later motif generators. Each rule result is
bound to its deterministic implementation, harness, parameter digest, and
source snapshot. The default recurrence and aggregation floors are one for
these coordinate-level rules; increasing either floor can only narrow
eligibility.
