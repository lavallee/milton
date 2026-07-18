# Milton implementation audit — 2026-07-17

## Outcome

The original 28-task itemized plan has been worked through. The execution
ledger records 27 tasks `complete` and A-2.6 `narrowed`. There are no pending,
in-progress, or implementation-only task rows.

Narrowing A-2.6 is a product result, not unfinished plumbing: the live George
contract returned one valid refutation, but retired zero gates and increased
review burden, so the stale-gate detector remains offline rather than being
misrepresented as useful automation.

## Final task closure

The last task, A-4.6, now has real—not fixture-literal—acceptance evidence. A
pinned local Qwen/Ollama evaluation produced a +0.475 held-out delta; Spindle
owned the eligible bind and promotion; Fab and Somm retained exact origin,
tuples, and both native comparison calls; and Milton appended an
`improvement` calibration. The retained claim is limited to the narrow
policy-adherence corpus and fresh synthetic operational case.

The full A-4.6 coordinate chain and accounting interpretation are in
`reports/procedure-promotion-pilot-2026-07-17.md`.

## Verification

| Repository | Verification | Result |
| --- | --- | --- |
| Milton | full tests, Ruff lint/format, strict mypy, sdist + wheel | 100 passed; all quality/build gates green |
| Chip | full tests, Ruff lint, strict mypy; changed-surface format | 197 passed, 4 optional skips; green |
| Spindle | isolated full suite; changed-surface Ruff lint | 661 passed; green |
| Fab | full suite; receipt-surface Ruff lint/format | 469 passed; green |
| Somm | full workspace suite; procedure/cost-surface Ruff lint | 814 passed, 1 optional skip, 1 deprecation warning; green |
| George | full workspace suite | 1,355 passed, 2 optional Fab-integration skips; green |

Across the six repositories, 3,596 tests passed and seven optional tests were
skipped. The Milton package built as both
`dist/milton_agents-0.1.0.tar.gz` and
`dist/milton_agents-0.1.0-py3-none-any.whl`.

Spindle's repository-wide Ruff and mypy baselines are not globally green
outside the changed evaluation/binding surface (38 lint findings and 11 typing
findings were observed). Its isolated full behavior suite passes. This is
recorded rather than silently folded into Milton's release proof.

## Original-doc reconciliation

`docs/workplan.md` no longer says cost-per-outcome and a stale-gate action are
the next proofs. `ROADMAP.md` now separates itemized implementation closure
from product graduation:

- A1, B1, B3, C1, and C2 have retained scoped checkpoints.
- A2 contracts are implemented, with live request-id coverage conditional on
  producer/provider support.
- A3 stays evidence-only and cannot change routing automatically.
- B2 is narrowed offline after the negative burden checkpoint.
- B4 is stage-honest but lacks live read/use signals and a real accepted
  retirement, so its broader product threshold is not met.

## Remaining release gates

Milton is not called an operational release from this audit. The roadmap still
requires:

- a clean committed release tree;
- supported-version CI plus dependency/workflow audits from that tree;
- a tested trusted-publishing or explicit release path; and
- a retained clean-machine fixture smoke test reproducing accounting,
  attribution, and finding manifests.

These are release/operations tasks beyond the completed implementation plan;
they are not hidden as task-ledger leftovers.

## Forge feedback

Five observations remain in the dedicated Forge feedback ledger. F-001 through
F-004 were already validated during execution. A-4.6 added F-005: checkpoint
templates should bind acceptance to an explicit evidence level and require
symmetric producer-native custody for paired baseline/variant comparisons.
No Forge change was upstreamed as part of Milton implementation.
