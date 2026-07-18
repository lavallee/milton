# George consumer contract

Status: schema version 2 is executable and tested.

George should consume Milton's projection, not the normalized SQLite tables.
The projection boundary lets Milton evolve its store while George depends only
on one schema-versioned document.

```text
George entry ──explicit──> Fab job ──receipt──> native harness session
     │                       │                         │
     └─ work outcomes        └─ runner outcomes       └─ turns/tools/tokens/cost
```

## Python API

```python
from milton import ExternalIdentity, MiltonStore, build_activity

with MiltonStore("/path/to/events.db") as store:
    activity = build_activity(store, ExternalIdentity("fab.job", fab_job_id))
    document = activity.to_dict()
```

George may instead root the graph at a known entry:

```python
ExternalIdentity("george.entry", entry_id)
```

`build_activity` follows only the current asserted revision of each crosswalk
and directed relation. Retained refutations immediately remove their edge from
the current projection without deleting revision history.

## CLI API

```console
milton activity fab.job=JOB_ID --store /path/to/events.db --format json
```

The top-level document contains:

- `schema_version`: currently `2`;
- `root`: the requested namespace/value;
- `related_identities`: the explicit identity graph reached within four hops;
- `links`: the current asserted edges, methods, confidence, and evidence IDs;
- `relations`: current asserted typed, directed relation revisions with method,
  confidence, evidence IDs, and stable relation/revision IDs;
- `report`: event/time/source totals, costs, tokens, and field coverage gaps;
- `outcomes`: counts by normalized outcome type and status.

The text form is for operators; George should consume JSON or the Python
objects. Global adapter freshness is available from
`MiltonStore.source_coverage()` or the `source_coverage` section of
`milton report --format json`.

## Current joins on Lisbon

- George entries carrying `context.fab_job_id` join to `fab.job`.
- Fab attempt receipts join a job to `codex.session`,
  `claude-code.session`, or `opencode.session`.
- George entries carrying a Git SHA join to `git.commit`, which resolves to
  repository-specific commit events.
- Somm calls carrying session/correlation IDs join to their native session or
  correlation identity.

All of these are explicit or exact joins. Milton does not silently promote a
timestamp coincidence into a George-facing association.

## Coverage George must display honestly

Somm is authoritative for the amount recorded on a mediated call, but that
amount is normally computed from tokens and Somm's pricing snapshot rather
than reported by the provider. OpenCode supplies a native amount with unknown
billing semantics; Hermes distinguishes actual and estimated fields. Codex and
Claude Code transcripts currently provide token usage but no dollar amount;
their `cost.amount_usd` field is therefore unavailable, not zero. Consumers
should use the report's `accounting` projection and render unclassified or
source-local-key coverage alongside any numeric total.

A run can predate the requested ingestion window while its terminal events
fall inside it. Milton uses the stable parent identity to include those child
events without fabricating a session record.

## Version 2: relations

Schema version 2 retains version 1's identity association surface and adds a
separate relation surface. Identity links answer "which records are explicitly
associated in one work context?" They do not assert direction or causal
meaning. Relations encode claims such as an attempt belonging to a job or a
commit being produced by an attempt without converting either endpoint into an
alias.

The current relation vocabulary is deliberately bounded:

- typed, directed relations such as `part_of`, `attempt_of`, `produced`,
  `verifies`, `evaluates`, `acts_on`, `refutes`, and `promotes`, each with
  evidence and append-only refutation semantics.

Operators can inspect a path independently from activity projection:

```console
milton relations show george.entry=ENTRY_ID --direction outgoing --format json
```

## Planned finding/disposition projection

The next versioned surface links an exact Milton finding revision to George's
canonical intake item and later disposition receipt.

George remains the system of record for intake and disposition. Milton must
not mutate George state or infer "acted on" from elapsed time, a nearby commit,
or a closed finding. It derives that projection only after ingesting an
explicit George receipt that references the finding revision. Temporary loss
of George coverage marks freshness unknown; it does not erase a previously
valid action. Only explicit receipt/relation refutation changes that history.
Conversely, George should display Milton's grade, evidence, and projection
without reimplementing Milton's synthesis logic.

The proposed producer-side contract and acceptance criteria are recorded in
[`plans/milton-product/commissions/george-finding-disposition.md`](../plans/milton-product/commissions/george-finding-disposition.md).
