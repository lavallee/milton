# Proposal: tool-stream query and motif surfaces

**State:** proposal — not accepted work. Motivated by an external exercise;
each item needs its own tests and, where it touches privacy or precedence, a
CONTRIBUTING-mandated changelog note before it lands.

## Motivating exercise

A `flip`-CLI friction study (2026-07-24) used Milton to characterize how a
coding agent used a research CLI across 35 Claude Code sessions. Milton did the
structural work well: it enumerated every session and its JSONL location, gave
per-session token totals, incrementally picked up the two newest sessions with
`scan --since`, and reported coverage honestly. But the questions the exercise
actually asked — *which sessions ran `flip …`? where are the usage-error and
`--help`-thrash clusters?* — could not be answered from the store. They were
recovered by grepping the raw `~/.claude/projects/**/*.jsonl` transcripts by
hand, outside Milton.

The gap is not accounting. It is that the **tool stream is metadata-redacted by
default and carries no queryable command shape**, and that Milton has **no
generic motif generator over tool usage**. Two mechanical defects found in the
same exercise (report token roll-up returning 0 for claude-code; `--until`
rejected by `report`/`accounting`) are fixed separately in code. This document
covers the three larger, doc-first items.

Numbers cited below are from that exercise: 35 flip-bearing transcripts, 384
flip Bash calls, **214 `flip … --help/--version` invocations**, and grouped-noun
usage errors (e.g. `flip question "text"` → `No such command 'text…'`).

Privacy is the fixed point for all three. Milton's default `--content metadata`
policy never stores tool inputs/outputs; it keeps a whole-input `sha256` and a
character count, and raw bodies require an explicit `--content full` opt-in
(see [adapters](../adapters.md#privacy-contract)). No proposal here weakens
that default.

---

## (a) Opt-in searchable tool-input index

### Problem

The tool-call payload redacts `input` to `null` under the default policy and
retains only a sha256 of the *entire* serialized input plus a char count. That
hash proves exact-repeat equality but is opaque to any question about *what a
tool was invoked with*. "Which sessions ran `flip …`?" is unanswerable without
`--content full` (which retains whole bodies) or leaving Milton entirely. The
exercise chose the latter.

### Evidence

384 flip Bash calls across 35 sessions were located only by transcript grep.
The store already held the tool-call events — 29,223 `tool-call.input:redacted`
in the 30d window — but nothing about them was selectable by command shape.

### Proposed shape

An opt-in, derived **argv-head index** computed at ingestion, distinct from the
existing whole-input hash and from `--content full`:

- A new content tier (e.g. `--content argv-index`) sitting between `metadata`
  and `full`. Default stays `metadata`; nothing changes unless opted in.
- For shell-shaped tools (Bash and equivalents), the adapter derives a bounded
  **argv head**: the first N tokens of the command line (program plus leading
  subcommands/flags), each token either length-truncated or, past a length
  cap, replaced by its own salted hash. Free-form operands (paths, quoted
  prose, heredocs) are dropped or hashed, never stored verbatim.
- The derived head is stored as structural metadata on the tool-call event and
  is indexed for prefix/equality queries, enabling `sessions whose Bash argv
  head starts with "flip "` without retaining the command body.
- For non-shell tools the head is the tool name plus a bounded set of
  allow-listed structural keys (never values).

Selection surfaces (a `tool` query or a filter on `activity`) then answer
command-shape questions directly.

### Contract / privacy constraints honored

- `metadata` remains the default and remains body-free. The argv head is an
  **explicit opt-in tier**, and its coverage is declared per field
  (recovered/inferred/redacted) like every other adapter output.
- The head is bounded and truncated-or-hashed by construction: it is a command
  *shape*, not a command *transcript*. Operand bodies never enter the index.
- The salt for token hashing is local and per-store, so the index cannot be
  dictionary-attacked across machines; it still supports exact-repeat equality
  within a store, matching the existing sha256 guarantee.
- Per CONTRIBUTING, this adds a field/tier and a stored index: it ships with
  redacted-default and opt-in tests and a changelog note.

### Non-goals

- Not on by default; `metadata` behavior is untouched.
- Not full-content retention; operands are never stored verbatim.
- Not a general log search; the head is a bounded structural prefix, not the
  whole command.
- No parsing of tool *outputs* into an index.

---

## (b) Path-glob session filtering

### Problem

`--project` matches **explicit producer-declared project ownership** and the
child events of owned sessions; the README is deliberate that it is *not a
repository-path or text-substring heuristic*. External research sessions in the
exercise (barnowl/edie/chip working directories) carry no producer-declared
owner, so `--project` correctly cannot slice them — and there is no other way to
scope a projection to "sessions that ran under this directory tree."

### Evidence

The exercise's genuine-usage corpus (six sessions under distinct external repo
working directories) could only be assembled by hand. Milton records each
claude-code session's `working_directory`/`project` (derived from `cwd`) as
recovered metadata, so the data to filter on exists; there is just no filter.

### Proposed shape

A **separate, explicit** path filter that is a sibling of `--project`, never a
redefinition of it:

- `--cwd-under PATH` (and/or `--path-glob GLOB`) on the read/projection
  surfaces (`report`, `accounting`, `cost`, `activity` where cheap).
- It matches on the session's already-recovered working-directory metadata:
  include a session (and its child events) when its `working_directory` is at
  or under the given path / matches the glob.
- It is explicitly heuristic and labeled as such in output coverage: a path
  match is a **locational filter**, not an ownership assertion, and it never
  emits or implies an ownership relation.
- `--project` and `--cwd-under` may combine (intersect) but neither weakens the
  other; `--project` continues to mean producer-declared ownership only.

### Contract / privacy constraints honored

- `--project` semantics are unchanged. This is a new, differently named filter
  with its own documented meaning, honoring the README boundary that ownership
  is never derived from a path.
- Working directory is already recovered structural metadata; no new content is
  stored.
- Coverage output distinguishes locational filtering from ownership scoping so
  a path filter can never be mistaken for a producer-declared outcome denominator.

### Non-goals

- Does not change, alias, or fall back to `--project`.
- Does not infer project ownership, cost ownership, or a work relation from a
  path or its similarity.
- Not a content search; it matches recorded directory metadata only.

---

## (c) Tool-error / help-thrash motif generator

### Problem

Milton's only finding generator today is the deterministic George-gate
detector; the failure-motif surface requires an external synthesis receipt.
There is no generic, deterministic generator over the **tool stream** for the
motifs this exercise is about: usage-error clusters, same-command retry storms,
and `--help` re-read density. That was named in the exercise as the
highest-value Milton feature the work implied.

### Evidence

Across 35 transcripts: **214 `--help/--version` reads**; grouped-noun usage
errors recurring across independent sessions (e.g. `flip question "text"` →
`No such command`, `flip ws show` → `No such command 'show'`); ~19% of flip
touches in the genuine-usage set were the agent re-reading the CLI. These are
exactly recurrence-across-sessions motifs — but only characterizable today by
hand.

### Proposed shape

A deterministic generator, shaped by the [findings](../findings.md) generator
contract, that facets the tool stream and emits typed, graded finding records:

- **Facets** (deterministic, Milton-owned): per session, cluster tool-call
  events by argv head (from (a)) into
  - *usage-error clusters* — repeated failed invocations of the same command
    shape (`status=failed`, same head);
  - *retry storms* — the same argv head repeated within a short window
    regardless of terminal status;
  - *help-thrash* — density of `--help`/`--version`-shaped heads for one
    program within a session.
- **Records**: typed `failure-motif`-family findings carrying a bounded source
  snapshot, generator identity, coverage, and evidence refs to the exact
  tool-call events (never bodies).
- **Grading**: generator maximum is `lead`; promotion to `candidate` requires
  independent recurrence across sessions and clearing the declared
  recurrence/aggregation floors; a motif that appears in a single session or
  under the aggregation/privacy floor abstains. Emitted revisions expire. This
  reuses the existing `milton.failure-motifs/v1` floors and evaluation
  envelope; the synthesis/description layer stays replaceable while Milton owns
  membership.

The flip corpus (214 help reads across 35 transcripts; grouped-noun usage
errors recurring across barnowl/edie/chip) is the first motivating corpus for
evaluation cases.

### Dependency

This generator **depends on (a)**. Under the default `metadata` policy the tool
stream carries only tool name, a whole-input hash, and status — enough to count
same-tool retries coarsely, but not to distinguish `flip question` from
`flip claim`, nor a `--help` read from an action. The argv-head index is what
makes command-shape clustering possible without `--content full`. Absent (a),
the generator is limited to tool-name-and-status motifs and must declare that
coverage limit rather than guess command shape.

### Contract / privacy constraints honored

- Deterministic facets only; no model runtime is imported or contacted, per the
  findings contract. Any naming/description of a motif remains a separate,
  replaceable synthesis step that cannot weaken floors or self-promote past
  `candidate`.
- Findings carry evidence refs to events, not command bodies; the aggregation/
  privacy floor gates emission.
- Grading is `lead → candidate` under measured recurrence; nothing auto-promotes
  to `corroborated`. Threshold/floor choices ship with tests and a changelog
  note.

### Non-goals

- Not a real-time linter or an agent-behavior intervention; it is retrospective,
  offline, and read-only.
- Does not rewrite, grade, or act on the source sessions.
- Does not synthesize a motif from a single session or below the floors.
- Does not depend on `--content full`; command-shape sensitivity comes from (a).
