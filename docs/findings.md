# Finding generation and evaluation

Milton separates detection from permission to surface a finding. A generator
may always run in dry-run mode, but a measured held-out result must authorize
append. Tuning examples never contribute to that decision.

## Shared evaluation envelope

`milton.finding-evaluation/v1` binds every result to the exact generator,
model, harness, parameter digest, and source snapshot. The result ID also
covers the frozen corpus, predictions, and floors, so replay is stable and a
changed input produces a new result rather than revising history.

Every case declares its tuning, held-out, or later-calibration partition,
expected finding and optional disposition, source coordinates, and evidence
IDs. Coordinate or evidence overlap across partitions fails closed. Promotion
uses held-out precision only and additionally requires every emitted positive
to meet the declared independent-recurrence and aggregation/privacy floors.
Calibration metrics remain visible but cannot retroactively authorize a
generator.

Reviewed live dispositions can be appended to a `CalibrationLedger`. A
refutation becomes a new calibration case referencing the exact finding
revision and source-owned receipt. It never changes the old corpus snapshot or
evaluation result.

The deterministic George gate evaluator is the first adapter to this shared
contract. `milton findings generate` consumes its measured decision directly;
there is no separate promotion calculation hidden in the CLI.

## Finding grades

- `lead`: bounded evidence worth review; generator maximum for unevaluated or
  deterministic first-pass output.
- `candidate`: independent evidence and evaluation support further work.
- `corroborated`: declared precision, recurrence, aggregation, and receipt
  requirements all pass.
- `refuted`: an immutable later revision records contrary review evidence.

External systems remain action owners. Milton relates exact finding revisions
to their decision, action, evaluation, or promotion receipts and derives
current disposition without a mutable `acted_on` flag.

## Failure motifs

`milton.failure-motifs/v1` keeps synthesis and evidence ownership separate.
The replaceable synthesis receipt names and describes a motif, while Milton's
deterministic facets own membership. Under the metadata-only policy, exact tool
inputs remain redacted; their hashes can prove that the same failed action
repeated without exposing the input.

A motif must recur across independent sessions, meet the aggregation/privacy
floor, and carry a source-native failed-tool or outcome receipt in every
session. The synthesis model cannot weaken the floors, introduce an unknown
session, or promote itself beyond `candidate`. Unsupported, small, or
under-receipted groups abstain, and emitted revisions expire.

The CLI accepts a versioned `milton.motif-synthesis/v1` receipt plus an exact
`milton.finding-evaluation/v1` result. A dry run without a synthesis receipt
exports the bounded facets and source snapshot needed to create one. Milton
does not import or contact a model runtime.

## Memory hygiene

The memory audit treats inventory, loaded, retrieved, referenced, and applied
as separate evidence stages. A missing host signal is `unknown`; retrieval is
never upgraded to causal application. The two built-in read-only sources cover
factory-native files/rules/skills and decision-memory directories. Optional
`milton.memory-access/v1` sidecars can carry affirmative or complete bounded
non-use receipts without adding a memory runtime dependency.

Applied or referenced evidence can support `keep`. A sufficiently old item can
support `park` only when the host explicitly reports non-observation for every
post-inventory stage; `retire` additionally requires a named superseding item.
Otherwise Milton abstains. Recommendations are lead/candidate revisions with
expiry and never delete or edit the source memory.

## Chip candidate projection

`milton findings export FINDING_ID --target chip` emits
`milton.chip-candidate-export/v1`. The embedded candidate has stable
candidate/source identity, an exact finding revision, deduplicated occurrence
references, separate counterexample and fixture references, and explicit
coverage/expiry/source limits. The export is data, never instructions.

Chip commissions that document idempotently and publishes only its stable
`chip.candidate-receipt/v1`. Ingest it with
`milton scan chip --source chip=/path/to/candidate-receipts.jsonl`. Milton
recovers exact origin and custody relations from the receipt without opening
Chip's private candidate or fixture store. This records capture only;
evaluation and promotion require separate Spindle-owned receipts.

## Procedure promotion calibration

A procedure candidate is not useful merely because it was captured. A Spindle
procedure evaluation must preserve the exact Milton finding revision and Chip
candidate/receipt, compare a content-hashed implementation against an explicit
baseline on the same profile/model/harness, pass held-out promotion floors, and
enter a Spindle-owned evaluated binding. Milton cannot make those decisions.

After binding, Fab carries that origin and both tuples on its exact execution
receipt. Somm's `somm.procedure-outcome/v1` receipt records the baseline and
post-promotion operational score, Fab job/receipt, and both native Somm calls.
The baseline is stored as `source_call_id` and the promoted arm as `call_id`,
so the comparison has symmetric custody and both arms are de-duplicable.
Ingest the public receipts, then run:

```console
milton findings calibrate-promotion SPINDLE_PROMOTION_RECEIPT_ID \
  --store .milton/events.db \
  --calibration .milton/procedure-calibration.jsonl
```

Milton emits `improvement`, `regression`, or `inconclusive`. Missing, duplicated,
failed, or tuple-mismatched Fab/Somm evidence is inconclusive. The result is
appended to calibration; exact replay is a no-op. It does not rewrite the
finding, close a task, or infer effectiveness from the binding alone.
