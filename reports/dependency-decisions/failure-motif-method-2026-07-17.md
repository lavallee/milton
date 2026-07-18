# Failure-motif dependency decision — 2026-07-17

No external clustering engine or library is adopted.

Milton will own deterministic facets, recurrence and aggregation gates,
evaluation, and finding projection. The experiment used an already-installed
Apache-2.0 Qwen model through local Ollama to compare synthesis shapes. Those
tools are replaceable experiment harnesses, absent from `pyproject.toml`, and
not required to ingest, evaluate, review, or export Milton data.

Consequently the build-versus-adopt exception gate is not invoked. If a future
implementation proposes Qwen, Ollama, or a hosted/open-core clustering system
as a required runtime, it must undergo the complete license-chain, commercial,
offline, SBOM, provenance, data-exit, and replacement-fixture review in
`docs/build-vs-adopt.md`; this experiment does not grandfather such adoption.
