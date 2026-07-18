# Build, borrow, or adopt

Milton defaults to vertical integration for the mechanisms that define its
evidence chain. This is factory infrastructure first and reusable software
second, not a thin product layer assembled to create a novel SaaS position.

The default is not "build everything." It is: **own the small, strategic
mechanisms; adopt only when the adopted component is genuinely open,
replaceable, and materially safer or harder than maintaining it ourselves.**

## Why vertical integration is the default

Milton's adapters, identity and relation contracts, accounting selection,
outcome attribution, finding manifests, grading, and action receipts determine
whether its conclusions can be trusted. Keeping those mechanisms in the
repository gives the factory one inspectable chain, makes cross-system changes
coherent, and avoids semantic drift between a vendor's product model and ours.

A dependency-light core also reduces exposure to compromised packages,
install-time scripts, abandoned transitive dependencies, surprise telemetry,
license changes, and hosted control planes. That does not make owned code free:
more local code creates maintenance and security-review obligations. The
tradeoff is favorable when the mechanism is small, central, and testable; it is
not favorable when we would be reimplementing a mature database, cryptography,
parser, or specialized numerical engine poorly.

## The complete-open-source gate

A component is eligible for adoption only when all load-bearing pieces pass:

1. The code needed for Milton's use is under an OSI-approved open-source
   license compatible with Milton's intended distribution and operation,
   including required engines, workers, schemas, and build tooling. Copyleft,
   attribution, patent, and network-use obligations are reviewed explicitly.
2. The useful local path does not require a vendor account, hosted control
   plane, license key, phone-home check, or unavailable enterprise module.
3. We can build, test, operate, back up, export, and replace it without the
   vendor. Source, documented behavior, and distributed artifacts are
   reconcilable.
4. Its data format and API permit a complete exit. Milton's canonical records
   never exist only behind that component.
5. The dependency and install path can meet our security bar: pinned versions
   and hashes, reviewed transitive graph, SBOM/license record, no unreviewed
   `curl | sh` or floating `npx ...@latest`, and no default network egress.

A public repository, "self-hosted" deployment, source-available license, open
SDK around a closed engine, or open core with required proprietary features does
not pass by itself. A cloud business model is not disqualifying, but it raises
the burden of proving local completeness, source-to-binary parity, and a clean
exit. A genuinely open component whose license obligations do not fit Milton's
commercial or distribution posture stays in the learn/compare lane rather than
being treated as morally or technically inferior.

## Decision ladder

Prefer the least coupled choice that solves the problem:

1. **Learn:** use papers, product behavior, schemas, and public demos as deep
   design inspiration; take no code or runtime dependency.
2. **Borrow:** adapt a small permissively licensed mechanism, retaining license,
   provenance, and focused conformance tests. Reimplementation from an idea is
   kept distinct from copied code.
3. **Compare:** use an external tool as a test oracle or corpus during
   development without putting it in Milton's runtime or canonical path.
4. **Adapt:** offer a read-only or export adapter for users who already operate
   the component. The adapter remains optional and loss of the component becomes
   a declared coverage gap.
5. **Adopt:** take a pinned runtime dependency only when its complexity,
   correctness, or security advantage outweighs integration and supply-chain
   cost. Keep it behind a Milton-owned interface and prove replacement.

Strategic evidence semantics stay at levels 1–3. Level 5 should be exceptional.

## Current dispositions

| Offering | Openness finding | Milton posture |
| --- | --- | --- |
| [TraceLab](https://github.com/uw-syfi/TraceLab) | Code is Apache-2.0; public data is CC BY 4.0; collection, sanitization, analysis, validators, and local viewer are present in the repository | Eligible to borrow small validators, sanitization, and accounting mechanisms with notices and conformance tests. Compare schemas and outputs; do not import its store as Milton's canonical model or take the whole stack as a runtime dependency. |
| [ccusage](https://github.com/ccusage/ccusage) | MIT, mature, local readers and reports, but a large TypeScript/Rust dependency surface relative to Milton's built-ins | Use as a compatibility oracle and source of pricing/accounting test cases. Keep native Milton adapters rather than depend on its CLI. |
| [cc-ledger](https://github.com/delta-hq/cc-ledger) | MIT and buildable locally; cloud sync is opt-in, but the repository is very young and the hosted funnel is explicit | Inspiration/watch lane. Audit source/artifact parity, installer, data completeness, and project durability before borrowing code; no runtime dependency or cloud sync. |
| [agentmemory](https://github.com/rohitg00/agentmemory) | Repository is Apache-2.0, but its required [iii engine](https://github.com/iii-hq/iii) is Elastic License 2.0 while only the SDK/console/docs are Apache-2.0 | Does not pass the complete-open-source gate as a Milton dependency. An optional read-only adapter is acceptable for an operator who already uses it; Milton should not require the runtime or treat it as the default memory substrate. |
| [Langfuse](https://github.com/langfuse/langfuse) | Self-hostable repository is MIT except `ee` directories; therefore open-core rather than completely open | Optional interchange/export target and design reference only. Do not make it the trace store, review queue, or required eval substrate. |
| LangSmith, Braintrust, Datadog, Arize AX, Claude Analytics, CodeTelemetry | Proprietary, hosted, unclear, or product-scoped for Milton's purposes | Deep inspiration and competitive quality bar only. No canonical data, runtime, identity, or workflow dependency. |

These decisions are about dependency posture, not whether the projects are
good. A truly open component remains eligible, not automatically selected; a
closed product can still teach us a great deal without entering the system.

## Buy rather than build

Adoption deserves a serious presumption when all of the following hold:

- correctness is specialist work and failure is dangerous;
- the component has a stable, narrow interface and complete local exit;
- its implementation and maintenance burden is large relative to Milton's
  differentiated work;
- the full dependency chain passes the open-source and security gates; and
- a replacement test proves Milton's records and behavior are not trapped.

Likely categories include database engines after SQLite stops fitting,
cryptographic primitives, mature file/protocol parsers, and numerical or
clustering engines after an experiment proves they are needed. UI dashboards,
trace stores, generic finding queues, and accounting semantics are not presumed
exceptions: they overlap the integrated system we are deliberately building.
