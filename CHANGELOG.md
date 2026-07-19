# Changelog

All notable changes to Milton will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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
