# Failure-motif method comparison

This experiment compares direct bounded synthesis with Milton-owned,
deterministic facets followed by bounded clustering over the same metadata-only
held-out cases. It uses the locally installed Apache-2.0 Qwen 2.5 7B model
through Ollama only as an experiment harness; neither is a Milton runtime
dependency.

Each method receives 1,600 maximum model-output tokens per seed and one model
call. Facet extraction is dependency-free local code and consumes no model
budget. Both run at temperature zero with seeds 17 and 23. Selection requires
precision at least 0.90 in both runs, assignment stability at least 0.80, and
operator value for at least two of the three expected recurring families. The
ranking then prefers operator value, recall, stability, and finally the smaller
maintenance surface.

Run against the already-installed local model:

```console
uv run python experiments/failure-motifs/run.py --output /tmp/milton-motif-method.json
```

The corpus contains source-shaped receipt IDs and operational metadata but no
transcript, prompt, tool input/output, repository path, or user content. Tuning
and held-out sessions are disjoint.

The bounded live checkpoint uses the same model/harness/parameter tuple and
compares a structural positive sample with explicit controls:

```console
uv run python experiments/failure-motifs/live_scan.py \
  --store /tmp/milton-motif-live-7d.db \
  --since 2026-07-11T00:30:49.364956Z \
  --cutoff 2026-07-18T00:00:00Z \
  --evaluation evals/failure-motifs/direct-result-v1.json \
  --output /tmp/milton-motif-live-result.json
```
