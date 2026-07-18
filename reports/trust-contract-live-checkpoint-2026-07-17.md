# Trust-contract live checkpoint

**Run date:** 2026-07-17
**Scope:** Milton A-0.5
**Decision:** pass, with the bounded gaps below
**Content policy:** metadata only

This checkpoint used a fresh ignored SQLite store and two small, exclusive live
windows. It proves one direct Fab→Somm path and one George→Fab→Git path using
source-owned coordinates. No relation depends on timestamp proximity, token
counts, content hashes, stdout text, or model-output equality.

## Redacted receipt

Native identifiers are represented by the first 16 hex characters of their
SHA-256 digest. Stable Milton record IDs are retained so the append-only
records can be audited without publishing native coordinates.

| Alias | Typed reference digest |
| --- | --- |
| F1 | `fab.job=sha256:450c1d7dcff30981` |
| S1 | `somm.call=sha256:7d39d72d6ec4956d` |
| G1 | `george.entry=sha256:0ce68027906218e7` |
| F2 | `fab.job=sha256:6364cf0a125c237b` |
| C1 | `git.commit=sha256:51da963b4aa28aa1` |

### Direct Fab→Somm

- Directed claim: `F1 --produced/source_receipt--> S1`.
- Relation: `rel_0a8e19cdbf6e1a7fe83d462b`, assertion revision
  `rrv_c00acbc3f7ffbd8955afd351`.
- Evidence event: `evt_8afc5b11348cf1ae97b0e620`, the exact Somm call
  whose `project=fab` and `correlation_id` is F1.
- Independent identity path: F1 ↔ correlation
  (`xwl_373baffa89e4c1cd8e930c1d`) ↔ S1
  (`xwl_133546b3cd2b9719b3dea376`).
- The activity projection returned one Fab session, Fab attempt/job outcomes,
  the Somm model call and cost observation, two identity links, and one
  directed relation.

### George→Fab→Git

- Directed claims: `G1 --verifies/source_receipt--> F2` and
  `F2 --produced/source_receipt--> C1`.
- Relations: `rel_fcd7652f1267f8591303b55b` and
  `rel_1f331371467a9caa3a377e42`.
- Shared evidence event: `evt_1bffad11006903a7cc244705`, the exact George
  entry carrying both producer-owned coordinates.
- Independent identity path: G1 ↔ F2
  (`xwl_0add0be6c3e18f5382a451b9`), G1 ↔ C1
  (`xwl_bcb740024ddd2d11abdc63e4`), and C1 ↔ its repository-specific
  commit event (`xwl_324822ac97f98f66f8b70e5b`).
- The activity projection reached the Git outcome event and displayed identity
  links separately from typed relations.

## Coverage

The final checkpoint store contains 35 normalized events, nine crosswalk
revisions, six relation revisions, and five adapter-run receipts.

| Window | Source | Read result |
| --- | --- | --- |
| 2026-07-14 01:17–01:18 UTC | Fab | 3 events, 1 crosswalk, no failures |
| 2026-07-14 01:17–01:18 UTC | Somm | 11 calls → 22 events, 1 crosswalk, 1 relation, no failures |
| 2026-07-03 21:23–21:26 UTC | Fab | 4 events, no failures |
| 2026-07-03 21:23–21:26 UTC | George | 4 events, 5 crosswalks, 5 relations, no failures |
| 2026-07-03 21:23–21:26 UTC | Git/Fab repository | 2 outcomes, 2 exact crosswalks, no failures |

The `--until` boundary is exclusive and is retained in adapter-run coverage.
It was added during this checkpoint after a seven-day Somm scan selected about
322,000 calls and proved that `--since` alone was not an operationally useful
definition of bounded.

## Reproduce on a new store

Run from Milton's repository root. These commands discover the unredacted
roots from the authoritative source fields rather than hard-coding the receipt
above.

```bash
A0_CHECKPOINT_DIR="$(mktemp -d)"
A0_CHECKPOINT_STORE="$A0_CHECKPOINT_DIR/events.db"
A0_FAB_LEDGER="$HOME/.local/share/fab/ledger.jsonl"
A0_SOMM_LEDGER="$HOME/.somm/global.sqlite"
A0_GEORGE_LEDGER="../Central/.george/inbox/lisbon/2026-07.jsonl"
A0_FAB_REPO="../fab"

uv run milton ingest fab somm \
  --source "fab=$A0_FAB_LEDGER" \
  --source "somm=$A0_SOMM_LEDGER" \
  --store "$A0_CHECKPOINT_STORE" \
  --since 2026-07-14T01:17:00Z \
  --until 2026-07-14T01:18:00Z --format json

uv run milton ingest fab george git \
  --source "fab=$A0_FAB_LEDGER" \
  --source "george=$A0_GEORGE_LEDGER" \
  --source "git=$A0_FAB_REPO" \
  --store "$A0_CHECKPOINT_STORE" \
  --since 2026-07-03T21:23:00Z \
  --until 2026-07-03T21:26:00Z --format json

A0_FAB_SOMM_JOB="$(sqlite3 -readonly "$A0_SOMM_LEDGER" \
  "SELECT correlation_id FROM calls WHERE project='fab' AND correlation_id IS NOT NULL AND datetime(ts)>=datetime('2026-07-14T01:17:00Z') AND datetime(ts)<datetime('2026-07-14T01:18:00Z') ORDER BY ts,id LIMIT 1")"
A0_GEORGE_ENTRY="$(jq -r 'select(.ts >= "2026-07-03T21:23:00Z" and .ts < "2026-07-03T21:26:00Z" and (.context.fab_job_id // "") != "" and ((.context.git_sha // .context.sha // .context.commit // "") != "")) | .id' "$A0_GEORGE_LEDGER" | tail -n 1)"

uv run milton relations show "fab.job=$A0_FAB_SOMM_JOB" \
  --store "$A0_CHECKPOINT_STORE" --direction outgoing --max-depth 1 --format json
uv run milton relations show "george.entry=$A0_GEORGE_ENTRY" \
  --store "$A0_CHECKPOINT_STORE" --direction outgoing --max-depth 2 --format json
uv run milton activity "george.entry=$A0_GEORGE_ENTRY" \
  --store "$A0_CHECKPOINT_STORE" --max-depth 4 --format json
```

## Bounded gaps and follow-ups

- A newer July 14 George/Fab receipt referenced a Git object still present in
  object storage but no longer reachable from current refs. The Git adapter
  intentionally omitted it from `git log --all`; the reachable July 3 trace
  above is the positive proof. Later outcome work must classify unreachable or
  rewritten commits explicitly rather than treating object existence as a
  landed outcome.
- Fab legacy jobs in both windows retained attempt and terminal records but not
  a `submitted` row in the current ledger. Stable parent identity recovered the
  outcomes; the George and Somm source receipts supplied the directed claims.
- `source_coverage()` reports the latest adapter run per adapter. The SQLite
  adapter-run ledger retains both windows, but a future multi-window export
  should expose that history without requiring SQL.
- The live store is `.milton/a0-trust-2026-07-17.db` and is intentionally
  ignored. Two interrupted/broader stores were moved to
  `.milton/partial-checkpoints/` and remain recoverable.
