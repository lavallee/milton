# Failure-motif live checkpoint — 2026-07-17

## Decision

Accept A-4.3 for a bounded retry-storm candidate. Direct synthesis names and
describes the motif; deterministic metadata-only facets own exact membership,
receipt corroboration, recurrence, aggregation/privacy, grade, and expiry. The
generator cannot self-issue `corroborated`.

## Negative control

The first 24-hour scan retained 41,823 Codex, Claude Code, and Fab events and
697 session facets. Only one session contained the exact same failed tool-input
fingerprint more than once, so the scan abstained under the three-session
floor. The window was widened instead of weakening the gate.

## Bounded live scan

- Window: 2026-07-11T00:30:49.364956Z through the exclusive
  2026-07-18T00:00:00Z cutoff.
- Ingested: 211,216 events; 3,163 session facets.
- Content: metadata-only; inputs and outputs remained redacted. Equality uses
  the adapter-produced input SHA-256 and never exposes the input.
- Exact repeated-failure population: 54 independent Claude Code sessions.
- Bounded evaluation sample: 24 structural positives and 6 failed-tool
  controls without an exact repeated input.
- Source receipts: every accepted member carried at least one exact native
  failed-tool receipt; the selected candidate had 24 independently
  corroborated sessions.

The local direct-synthesis run used the exact evaluated Qwen 2.5 7B blob,
Ollama harness, parameter digest, seed 17, temperature zero, and 1,600-token
cap. It named `retry-storm` from three examples. Milton's declared membership
policy then included all 24 bounded cases satisfying the exact deterministic
facet and excluded all six controls. Live precision and recall were both 1.00,
within the declared 0.15 recall tolerance of the frozen 1.00/0.889 result.

The result produced one candidate-grade finding,
`fnd_d0d736bd26707214a5ea3514`, backed by synthesis receipt
`syn_45e6a8b4a33212a6f723084c` and evaluation result
`evr_4d9dc501cafb85df13703f29`. It expires at
2026-08-01T00:00:00Z. No source system was mutated.

## Accounting and limitations

The local model call used 2,688 prompt and 226 output tokens and took 7.145
seconds. Reported and computed dollar cost are both unavailable; the run is
recorded as `local-included-unpriced`, not silently represented as `$0`.

The candidate says repeated exact failed actions recur. It does not claim the
root cause, wasted dollar amount, or that every retry was avoidable. The live
sample is structurally labeled by the exact fingerprint predicate; later human
refutations enter append-only calibration and cannot rewrite this result.

Reproduction is documented in
`experiments/failure-motifs/README.md`; the retained executable result for this
run was `/tmp/milton-motif-live-result-v2.json`.
