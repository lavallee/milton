# Procedure-promotion pilot

This pilot closes one producer-owned Milton -> Chip -> Spindle -> Fab -> Somm
-> Milton loop with the locally installed Qwen 2.5 7B model. The model and
Ollama are experiment tools, not Milton runtime dependencies.

The procedure is deliberately narrow: after the same permission-failure
fingerprint appears twice, choose an authorized recovery class using an
explicit factory precedence. Spindle evaluates a raw baseline and the exact
content-hashed procedure on disjoint development and held-out fixtures. Only
an eligible held-out result may be bound. A fresh operational case then runs
both arms through Somm; Fab records the promoted-arm execution and Somm owns
the paired outcome receipt. Milton consumes public receipts and classifies the
result without interpreting task closure as effectiveness.

The model tuple is pinned to the installed blob
`sha256:2bada8a7450677000f678be90653b85d364de7db25eb5ea54136ada5f3933730`.
Both evaluation and operational calls use Ollama `/api/chat`, temperature zero,
1,024 predicted-token headroom, and the same JSON schema. Raw prompts and
responses stay out of retained receipts; response hashes, parsed decisions,
token counts, and scores remain.

Run from the Milton checkout after the sibling Chip, Spindle, Fab, and Somm
checkouts have the contracts documented in this project:

```console
PYTHONPATH=src:../chip/src:../spindle/src:../fab/src:\
../somm/packages/somm/src:../somm/packages/somm-core/src \
  uv run python experiments/procedure-promotion/pilot.py --phase prepare

PYTHONPATH=../spindle/src \
  uv run python experiments/procedure-promotion/pilot.py --phase development

PYTHONPATH=src:../chip/src:../spindle/src:../fab/src:\
../somm/packages/somm/src:../somm/packages/somm-core/src \
  SOMM_CROSS_PROJECT=0 SOMM_DB_DIR=.milton/procedure-promotion/somm \
  uv run python experiments/procedure-promotion/pilot.py --phase heldout
```

`prepare` is replay-safe. `development` is for harness validation only and
never authorizes binding. `heldout` freezes the declared fixtures, lets
Spindle decide eligibility and own binding, then records one fresh operational
comparison if and only if the evaluation is eligible.
