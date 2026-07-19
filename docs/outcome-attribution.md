# Outcome attribution

Milton allocates the exact monetary observations selected by
[`milton accounting`](accounting.md). It does not rescore reported versus
computed cost, add rollups, or turn an estimate into actual provider spend.

## Conservation

Every selected observation enters exactly one bucket:

```text
selected_total = attributed + ambiguous + unallocated
```

- `attributed`: one eligible outcome remains after explicit precedence;
- `ambiguous`: multiple outcomes at the same precedence compete; and
- `unallocated`: no typed root/path exists, or only an identity association
  exists without a directed workflow claim.

Version 1 assigns each selected observation once with weight 1. It does not
fractionally split a call across tasks or copy the full amount into every
reachable runner/task/commit rollup. Economic kind remains attached to each
record, so marginal, notional, included, and unknown amounts stay separately
inspectable.

## Outcome precedence

When a single connected work graph contains nested outcomes, the later
operational result wins:

1. `git.commit`
2. `george.entry`
3. `fab.job`
4. `fab.attempt`
5. `barnowl.research-outcome`

One commit can therefore supersede its George task receipt and Fab runner
result without counting the same call three times. Two reachable commit
coordinates are not silently ranked; the observation is `ambiguous`. A
filtered projection such as `--outcome-type fab.job` applies the same rules to
that explicitly selected candidate vocabulary.

PR merged/reverted/closed-unmerged outcomes remain out of the vocabulary until
an authoritative PR source is implemented.

The Barnowl type is appended, so the relative precedence and behavior of all
four existing outcome types remain unchanged. Its eligible edge is narrowly
`somm.call --produced--> barnowl.research-outcome`, emitted only from an exact
non-null call ID in the source receipt. The selected Somm cost must begin at
that exact immediate call root, and the path must be the receipt-authored,
one-step, forward edge. Crosswalks, reverse edges, longer walks, and cycles do
not qualify Barnowl attribution. Provider/model coordinates, hashes, timestamps,
and JSONL ordering are not join inputs.

## Eligible paths

A path begins at an exact parent/session reference for a selected cost event.
It may traverse current asserted crosswalks and directed relations, but it is
eligible only if at least one typed relation establishes workflow meaning.
Crosswalk-only reachability is reported as `association-only` and abstains.

Every attributed or candidate path exposes:

- normalized event IDs, including the cost, root, outcome, and edge evidence;
- crosswalk link and revision IDs;
- relation and relation-revision IDs;
- ordered typed references; and
- each relation predicate plus whether traversal followed or reversed its
  stored direction.

Every attribution record also retains the selected observation's source
adapter and native coordinate, authority, reported/computed basis,
actual/estimated accuracy, economic kind, pricing version, accounting key and
scope, and operational role. Missing producer declarations remain `unknown`;
Milton does not infer that an observation is production spend merely because
it came from a production-shaped table.

Reversing a relation during graph traversal does not reverse its claim. For
example, a cost rooted at `somm.call` may follow the stored
`fab.job --produced--> somm.call` edge in reverse to recover its producer; the
path still renders the predicate and `reverse` traversal direction.

A direct synchronous Somm dataset eval can also provide an eligible
`somm.call --evaluates--> git.commit` path. This edge is accepted only when the
Somm eval receipt explicitly carries the implementation coordinate; a shared
timestamp, repository name, or model id never creates it.

## Reason codes

| Code | Bucket | Meaning |
| --- | --- | --- |
| `exact-directed-path` | attributed | Exactly one highest-precedence typed outcome has a relation-bearing path. |
| `competing-outcomes` | ambiguous | Multiple outcomes compete at the highest reachable precedence. |
| `association-only` | unallocated | An outcome is reachable only through identity/event association. |
| `no-root-reference` | unallocated | The selected cost has no recoverable exact parent/session reference. |
| `no-outcome-path` | unallocated | A root exists but no supported outcome is reachable. |

Refuted relation revisions remain in history but leave the current graph.
Failed, reverted, and abandoned runner/task outcomes remain typed outcomes;
their status is not rewritten into success or dropped from the denominator.

## CLI

```console
milton cost --per-outcome --since 2026-07-10T00:00:00Z \
  --until 2026-07-11T00:00:00Z --format json
milton cost --per-outcome --outcome-type fab.job
milton cost --per-outcome --outcome-type barnowl.research-outcome
```

JSON embeds the accounting projection, all three bucket totals, conservation
proof, reason counts, per-outcome records and denominators, exact paths, and
adapter coverage. Text output calls values selected observations and always
shows ambiguity and unallocated amounts.
