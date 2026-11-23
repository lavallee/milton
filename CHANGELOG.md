# Changelog

All notable changes to Milton will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- **Claude Code subagents:** when one prompt fans out to several subagents,
  each subagent transcript starts with that prompt's uuid. Turn identities were
  keyed by the uuid alone, so the first subagent file claimed it and every
  other file failed with an identity conflict. Subagent turns are now keyed by
  their subagent session. Main-session turn identities are unchanged.

- **Attribution performance:** outcome walks skip nodes that cannot reach any
  candidate outcome within the remaining depth, using one reverse
  breadth-first pass per projection. Walks to every outcome are unchanged
  (property-tested against the unpruned search). On a large identity graph
  where each walk had covered the whole connected component, a 30-day
  projection went from over an hour to about two minutes.

## [0.2.1] — 2026-11-23

### Fixed

- **Release publishing:** the publish workflow now pins
  `pypa/gh-action-pypi-publish` v1.14.3, whose Twine accepts core metadata
  2.5 as emitted by current Hatchling. 0.2.0 was tagged but its upload was
  rejected, so it never reached PyPI. 0.2.1 contains the same code as 0.2.0.

## [0.2.0] — 2026-11-23

### Fixed

- Claude Code `api-request-blob` records (hash-keyed request bodies with a
  `message` but no timestamp) are skipped as transcript metadata instead of
  being counted as malformed. Current Claude Code transcripts produced
  thousands of false `invalid-timestamp` warnings per host. A `user` or
  `assistant` record without a timestamp is still malformed.

### Added

- **Notional valuation:** `milton cost --per-outcome --notional` values
  unpriced usage (for example subscription coding-agent sessions) at public
  list prices in memory, as `kind=notional`, `basis=computed`,
  `accuracy=estimated` observations with a `pricing_version`. A built-in,
  sourced price table covers current Anthropic and OpenAI models;
  `--prices FILE` overrides it. Unknown models are counted, never guessed.
  Stored events and the selected projection are unchanged.
- **Cross-host joins:** fleet collection rebuilds a derived merged store from
  host stores after every run and snapshots it, so cost per outcome can follow
  relations across machines. Identity conflicts keep the first host's record
  and are counted. The dashboard adds notional columns, a merged fleet row, and
  a cross-host cost-per-outcome section. Host names beginning with `_` are
  reserved.

- Import explicit Pi v3 session files for metadata-only call and usage accounting. Fab job attribution follows exact receipt relations.
- **Fleet collection:** `milton fleet collect --hosts MANIFEST` runs
  `milton scan` on each declared host (SSH, or `ssh = "local"`) under the
  metadata content policy, copies back only the normalized store, and writes a
  per-host snapshot and a status index. Failed hosts keep their last good
  snapshot. Scans run from a per-command state directory, so a Milton upgrade
  builds a fresh store and cwd-relative adapters never walk a remote home.
  See [fleet collection](docs/fleet.md).
- **Dashboard:** `milton serve --fleet DIR` is a read-only standard-library
  HTTP dashboard and JSON API over the snapshots, with a `/health` endpoint.
  Fleet totals are labeled as sums of host projections.

- A dependency-free, explicit-source-only `barnowl.research-outcome/v1`
  adapter with strict private-safe validation and exact Somm-call cost
  attribution. The existing outcome precedence order is unchanged; the new
  outcome type is appended to the supported vocabulary.
- The read-only `milton effectiveness barnowl` projection with separate
  receipt-join and selected-window coverage, exact Decimal conservation,
  privacy-safe aggregates, and standardized follow-up claimability gates.

## [0.1.0] — 2026-07-18

### Added

- Typed normalized event envelopes with field-level coverage declarations.
- SQLite event index and refutable identity crosswalk.
- Append-only, evidence-bearing findings ledger.
- Dependency-free `milton init` and `milton report` commands.
- Read-only adapters for Claude Code, Codex, Fab, George, Git, Hermes,
  OpenCode, and Somm.
- Incremental source fingerprints, persisted adapter-run coverage, moving or
  fixed ingestion windows, and the one-pass `milton scan` command.
- Metadata-only privacy defaults with explicit full-content opt-in.
- Refutable identity graph traversal and the schema-versioned `milton activity`
  projection for George and other downstream consumers.
- Python 3.12/3.13 CI with formatting, lint, strict typing, tests, build, and
  dependency/workflow security audits.
- Forge OSS release shape: contribution and release guides, a GitHub Pages
  product surface, OIDC trusted-publishing workflow, and a clean-wheel fixture
  smoke that reproduces accounting, attribution, and finding manifests.
- Chip, Spindle, Fab, and Somm procedure-custody adapters plus append-only
  post-promotion calibration as improvement, regression, or inconclusive.
- A retained local-model procedure-promotion pilot with exact origin/tuple
  custody, producer-native baseline and promoted call IDs, replay protection,
  and separate reported versus computed cost semantics.
- Independent producer receipts may corroborate the same exact directed
  relation without aborting ingestion; their assertion history remains
  append-only and an explicit refutation still closes the relation.

### Documentation

- Re-grounded the product vision around whole-work accounting, graded
  operational findings, and procedure promotion, with explicit graduation and
  kill criteria in `ROADMAP.md`.
- Distinguished reported and computed amounts, economic cost kind, accuracy,
  direct observations, and non-billable rollups in the accounting contract.
- Added the George schema-versioned consumer contract and documented the
  planned separation between identity links, directed work relations, and
  finding disposition receipts.
- Reassessed the 2026 coding-agent analytics, observability, transcript, and
  memory-tool landscape and narrowed Milton's wedge to conservative
  cross-provider evidence joined to real outcomes.
- Added Forge-derived orientation, architecture, itemized work, and proposed
  cross-repository commissions for Somm, Fab, and George. Proposed work is
  labeled separately from executable behavior.
- Established a vertical-integration default and a complete-open-source,
  offline-exit, provenance, and replacement gate for borrowing or adopting
  market-map components.
