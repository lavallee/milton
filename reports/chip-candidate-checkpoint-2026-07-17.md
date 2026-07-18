# Chip candidate checkpoint — 2026-07-17

## Decision

A-4.5 graduates. Milton remains the finding-history authority; Chip owns the
candidate ledger and commissioning receipt. Neither repository imports the
other at runtime.

## Contract

- `milton findings export FINDING --target chip` emits
  `milton.chip-candidate-export/v1` with stable candidate/source identity and
  an exact finding revision.
- The projection keeps deduplicated occurrence references separate from
  counterexamples and negative/exception fixture references. It also preserves
  source snapshot, coverage, gaps, expiry, generator, and scope/privacy limits.
- Chip's `commission_candidate` rejects incomplete identity, content changes at
  one source revision, and candidate-id reuse across source/shape boundaries.
- Replaying one exact revision returns the same content-addressed
  `chip.candidate-receipt/v1` and appends neither a candidate nor a receipt.
  Later revisions are tallied by the union of occurrence references, not by
  row count.
- Milton's `chip` adapter consumes only the public receipt ledger. It records
  exact `milton.finding-revision --produced--> chip.candidate` origin and
  `chip.candidate-receipt --verifies--> chip.candidate` custody. Capture is not
  mislabeled as evaluation or promotion.

## Acceptance proof

`tests/test_exports.py` creates a Milton procedure finding with two
occurrences, a negative counterexample, positive and exception fixtures, and
bounded source limits. It invokes the real sibling Chip package in a separate
Python process twice. The second call returns byte-identical receipt JSON;
candidate and receipt ledgers each retain one line. A fresh Milton store then
ingests only `candidate-receipts.jsonl` and recovers one outcome and two exact
relations, including the original finding revision.

Verification:

- Milton: Ruff and format green; 92 tests passed.
- Chip: 197 tests passed, 4 optional `jsonschema` tests skipped; changed-file
  Ruff, format, and mypy checks green.
- Milton's full strict mypy audit still reports pre-existing narrowing errors
  in three A-3 test files. Source mypy and the A-4.5 contract files are green;
  the test annotations remain a final-audit cleanup item rather than evidence
  against the runtime contract.

## Remaining boundary

This proves recurrence-safe candidate capture and return custody. It does not
prove that a candidate was evaluated, bound, promoted, or operationally useful.
Those claims require Spindle-owned exact-tuple evaluation/binding receipts and
the A-4.6 post-promotion outcome comparison.
