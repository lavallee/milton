# George gate findings

Milton's first deterministic finding generator reviews George gate evidence
without mutating George. It emits separate assessments for three claims:

- `condition-resolved`: an exact decision or disposition receipt resolves the
  gate's canonical coordinate;
- `re-minted`: at least the declared number of mint receipts share one exact
  coordinate inside the declared window; and
- `old-unconsulted`: the gate is old enough and carries an explicit
  `not_consulted` receipt.

Canonical gate coordinates and individual mint IDs are distinct. A decision
that targets a mint may resolve through that mint's exact canonical coordinate;
fuzzy content, timestamps, or similar-looking text never establish the join.
Missing or conflicting coordinates abstain. Missing consultation evidence also
abstains and is never treated as non-consultation. Stale or unknown George
source coverage abstains all keyed rules.

## Dry run and evaluation

```console
uv run milton findings generate \
  --generator george-gates \
  --since 2026-07-07T00:00:00Z \
  --until 2026-07-18T00:00:00Z \
  --dry-run --format json

uv run milton findings evaluate \
  --store .milton/a2-gates-inventory-2026-07-17.db \
  --cases evals/george-gates/cases-v1.jsonl \
  --format json
```

Dry run never appends to the finding ledger or contacts George. Append requires
an evaluation corpus, and only rules with held-out positives at or above the
promotion floor may emit. The generator's maximum grade is always `lead`.
Promotion requires independent evidence through the finding ledger; it is not
a generator side effect.

The v1 live corpus intentionally approves no rules. Known positive examples
informed the implementation and remain in the tuning partition. The disjoint
held-out partition contains negatives and ambiguities but no independent
positive, so precision is unavailable and generation fails closed. See the
[evaluation report](../reports/george-gate-finding-eval-2026-07-17.md).

## Reproducibility contract

Every assessment records the versioned rule, exact cutoff, threshold/window,
source state, source snapshot, evidence event IDs, and a reason. Every candidate
adds a stable subject, finding ID, evidence roles, coverage and gaps, expiry,
and generator version. Replaying the same snapshot produces the same candidate
document; append adds a new revision only when that document changes.

George remains the action owner. A future accepted candidate crosses the
versioned document contract described in the
[George disposition commission](../plans/milton-product/commissions/george-finding-disposition.md),
and Milton derives action state only after re-ingesting George's receipt.
