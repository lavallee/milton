# Forge OSS release-readiness review — 2026-07-17

## Result

Milton now satisfies the repository-shape and locally testable portions of the
OSS release standard. This is the retained release-candidate proof for v0.1.0;
live publication is verified separately from this checked-in pre-release
record.

## Public-source gate

- MIT license and author metadata are present.
- The runtime core has no dependencies, proprietary packages, network startup,
  or telemetry.
- The private public-source scrub returns no incidental internal-tool matches.
- `CONTRIBUTING.md`, `RELEASING.md`, `docs/index.html`, `docs/.nojekyll`, and the
  Pages stylesheet are present.
- `milton-ai` is the distribution name; `milton` remains the import and CLI.

## Reproducible release proof

`scripts/release_smoke.py` creates a new virtual environment, installs only the
built wheel with `--no-deps`, constructs a synthetic Somm ledger from checked-in
SQL, and ingests checked-in Fab and George receipts. It compares a compact
manifest that proves:

- three cost events are visible but two Fab observations are non-counting
  rollups;
- one computed, estimated, marginal Somm observation selects exactly `$0.25`;
- the full `$0.25` follows the asserted Somm call → Fab attempt → Fab job path;
- selected cost equals attributed cost with no ambiguous or unallocated amount;
- the evaluated George re-mint rule emits one lead, then replays without a
  duplicate finding; and
- independent George and Fab assertions of the same trace edge do not abort an
  adapter or erase source history.

The expected projection is retained at
`tests/fixtures/release-smoke/expected-manifest.json`.

## Local gates run

- isolated Python 3.12: format, Ruff, strict mypy, 101 tests, wheel smoke;
- isolated Python 3.13: format, Ruff, strict mypy, 101 tests, wheel smoke;
- `uv lock --check` and `uv build`;
- Twine metadata and wheel-content validation;
- dependency audit: no known vulnerabilities in the dependency-free runtime;
- offline high/high Zizmor audit: no findings in CI or publish workflows; and
- tracked public-source scrub and `git diff --check`: clean.

## External release-gate disposition — 2026-07-18

1. **Resolved — optional Fab boundary.** The Forge OSS doctrine now permits a
   named adapter for an optional non-public producer only when the public
   interchange contract is self-contained and the adapter has no install,
   import, or default-runtime dependency on that producer. Milton satisfies
   that rule: its wheel installs with `--no-deps`, the reader is Milton-owned,
   and absent Fab receipts are a coverage gap rather than a failure. Fab does
   not need to be public for Milton to be published.
2. **Resolved — committed-tree CI.** The implementation branch was merged and
   the resulting `main` GitHub Actions run passed.
3. **Resolved — trusted publisher registration.** The pending publisher is
   registered for project `milton-ai`, repository `lavallee/milton`, workflow
   `publish.yml`, and environment `pypi-milton-ai`.
4. **Release execution.** Create an annotated `v0.1.0` tag and published GitHub
   release from a clean, green `main`, then require the OIDC job to pass.
5. **Artifact verification.** Download the exact published version into a new
   environment and rerun the retained wheel smoke.
6. **Site verification.** Enable GitHub Pages from `main` / `docs` and verify
   the deployed landing page.
