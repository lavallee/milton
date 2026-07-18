# Two-store memory audit checkpoint — 2026-07-17

## Decision

Accept A-4.4. Milton now audits factory-native files/rules/skills and
decision-memory stores through separate, read-only, dependency-free adapters.
Inventory, loaded, retrieved, referenced, and applied remain distinct;
retrieval is never represented as causal application.

## Live inventory

A metadata-only Lisbon scan covered two native roots
(`~/.codex/memories` and `~/.agents/skills`) and two decision roots (Astrid and
Edie):

| System | Inventoried | Loaded known | Retrieved known | Referenced known | Applied known | Unknown items |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Factory native | 3 | 0 | 0 | 0 | 0 | 3 |
| Decision memory | 29 | 0 | 0 | 0 | 0 | 29 |

The scan emitted 32 `memory-evidence` events, retained hashes/lengths rather
than bodies, and produced no keep/park/retire recommendation. That abstention
is the correct result: these hosts expose inventory but no trustworthy access
or application receipts.

## Executable positive and action control

A source-shaped fixture exercised the optional
`milton.memory-access/v1` boundary across both adapters:

- one applied skill produced a candidate-grade `keep` recommendation;
- one retrieved/referenced decision produced a lead-grade `keep`, while its
  applied stage remained explicitly unknown;
- one 90-day-old native rule with complete bounded non-use evidence and a
  named superseding skill produced a candidate-grade `retire` recommendation;
  and
- an exact simulated human action receipt was related to that retire finding,
  deriving valid/current `acted_on` and historical `ever_acted_on` state.

The adapters did not modify the rule, skill, or decision files. The simulated
receipt says only that the recommendation was reviewed in the fixture; it does
not claim a real retirement in the live stores.

## Optional agentmemory posture

No `agentmemory` installation was found, so no adapter or runtime was added.
Its architecture remains prior art and an optional future read-only source for
an operator already running it. The required ELv2 engine still prevents it
from becoming Milton's default dependency.

## Reproduction

```console
uv run milton scan native-memory decision-memory \
  --store /tmp/milton-memory-live.db \
  --source native-memory=~/.codex/memories \
  --source native-memory=~/.agents/skills \
  --source decision-memory=../astrid \
  --source decision-memory=../edie
uv run milton memory audit \
  --store /tmp/milton-memory-live.db \
  --cutoff 2026-07-18T01:00:00Z --format json
uv run pytest tests/test_memory_audit.py
```
