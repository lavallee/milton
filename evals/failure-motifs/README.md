# Failure-motif evaluation v1

`direct-result-v1.json` is the immutable shared-harness result derived from
the frozen corpus in `experiments/failure-motifs/cases-v1.jsonl` and the two
retained direct-synthesis runs in the method checkpoint.

The recurrence gate removes the two-case permission-loop proposal before
surface evaluation. The measured direct method therefore has six true
positives, three false negatives, three true negatives, no false positives,
1.00 precision, and 0.667 operator-family coverage. The result authorizes
candidate-grade review only; it cannot issue a corroborated finding.

The result is bound to the exact Qwen blob described in the report, local
Ollama harness, prompt/taxonomy parameter digest, and corpus snapshot. The
held-out source sessions are disjoint from the tuning sessions.
