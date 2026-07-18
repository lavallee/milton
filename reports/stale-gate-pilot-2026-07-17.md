# Stale-gate live pilot — 2026-07-17

## Result

**Narrow ROADMAP Epic B2 to an offline audit. Do not graduate automatic
surfacing.** George explicitly refused one exact but obsolete tuning-sample
finding, and Milton derived that refutation from a valid canonical receipt.
The trust loop works; the product-effect threshold does not.

The pilot removed zero gates and required one review/disposition. It therefore
did not reduce decision burden. The held-out corpus still has no independent
positive family, so precision remains unavailable. B2's required accepted
finding, real deduplication, and lower queue burden remain unproven.

## Before

The fixed source snapshot `snp_546a84525628b655c7128c56` covers George gate
evidence from 2026-07-07T00:00:00Z through exclusive
2026-07-17T22:45:00Z:

- 42 gate mints, 39 with exact canonical coordinates;
- three human decision receipts;
- one packet with 12 mints for the same canonical target followed by an exact
  human resolution; and
- four dry-run leads: three condition-resolved and one re-minted.

The frozen evaluation `evl_7ea8940456dd4e898414c2c1` approves no surface rule.
All four leads remain review-only and append fails closed.

## Selected packet

The selected packet is the 12-mint condition-resolved family. Its claim is
deterministically supported by an exact later resolution receipt, but it is not
independent evaluation evidence: that family informed the detector. The local
finding therefore records all of the following explicitly:

- grade `lead`;
- `intake_mode=manual-tuning-review`;
- `surface_approved=false`;
- `evaluation_decision=offline`; and
- coverage 39/42, with unavailable consultation receipts and no independent
  held-out positive called out as gaps.

Custody coordinates:

- finding `fnd_ce78b0c03fd4fdbb0c089f24`;
- revision `fnr_5772299e48406829f1bae5af`;
- immutable George export `gfx_b88e99c01940e87d285fefbf`; and
- redacted subject packet `gate-family-A` (the exact coordinate remains in the
  local ledger and versioned contract).

## George-owned handoff and refusal

Milton exported `milton.finding-candidate/v1` over JSON; George imported no
Milton package. The document preserved finding/revision IDs, evidence roles,
coverage/gaps, expiry, generator/snapshot, target, and taint. It carried
`instruction_authority=none` and only an advisory `review-stale-gate`
suggestion.

George's service created intake entry `01KXS4EC0B54FEDR0W9C8FZJH4`, then the
George-owned pilot actor returned disposition receipt
`01KXS4EPFN8WVFY1NGYGF3NPFH`. George refused the action because:

1. the packet is tuning-only and lacks held-out positive precision; and
2. its exact coordinate already had a prior human resolution, so attempting to
   close it again would create duplicate work rather than remove it.

Replaying both intake and disposition returned the same IDs with
`replayed=true` and appended no additional entries. George, not Milton, made
and recorded the refusal. Milton never called a gate-mutation surface.

## Receipt re-ingest

Milton re-ingested the two ordinary George ledger rows from the bounded source
file. The ingest added two events, one identity crosswalk, and one directed
relation. `milton findings show` now derives:

- disposition `refuted`;
- exactly one `refutes` relation from the exact finding revision to
  `george.disposition=01KXS4EPFN8WVFY1NGYGF3NPFH`;
- receipt validity `valid` and freshness `current`;
- `acted_on=false`, `ever_acted_on=false`; and
- no mutable finding-status rewrite.

## Burden comparison

| Measure | Before | After | Effect |
| --- | ---: | ---: | --- |
| gate mints | 42 | 42 | 0 |
| gate decision/disposition evidence | 3 | 3 | 0 |
| automatically surfaced Milton candidates | 0 | 0 | 0 |
| George records for this finding | 0 | 2 | +1 intake, +1 refusal |
| real gates retired/deduplicated by the pilot | 0 | 0 | 0 |
| valid Milton action relations | 0 | 1 `refutes` | trust loop proven |

The replay control added no records, but the first review added burden without
reducing the queue. This is a correct refusal and a successful contract proof,
not a successful stale-gate product proof.

## Operational note

The configured `GEORGE_SERVICE_URL` targets dash-main, whose running service did
not yet expose the new route and returned 404. The live contract check therefore
used Lisbon's repository-backed interim George service against the canonical
Central inbox, then restored that service to its prior inactive state. The
George change must be published/deployed before this intake is available on the
production service; the receipt itself is already in the append-only George
source and is fully re-ingested.

## Next graduation evidence

B2 remains offline until all three conditions are met:

1. freeze at least one independent held-out positive for a rule without
   changing that rule from the example;
2. have George accept a later surfaced candidate and actually retire or
   deduplicate a still-open real gate; and
3. demonstrate that removed duplicate/obsolete decisions exceed the review
   work introduced by Milton.

The old/unconsulted rule additionally remains blocked on explicit consultation
receipts. Unknown reads must continue to abstain.
