# Forge OSS release-readiness review — 2026-07-17

## Result

Milton now satisfies the repository-shape and locally testable portions of the
OSS release standard. This is a release-candidate result, not a claim that
v0.1.0 has been published. Strict public-source graduation also depends on the
Fab disposition described below.

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

## External release gates still open

1. Fab is a named, implemented adapter and boundary in Milton's existing public
   history, while the current private release doctrine still classifies Fab as
   internal-only. Removing the adapter would contradict Milton's integration
   direction. Before release, either publish Fab after its receipt changes land
   or record an explicit doctrine revision that permits this public contract.
2. The review branch must pass GitHub Actions from a committed tree.
3. Register the pending PyPI trusted publisher for project `milton-ai`,
   repository `lavallee/milton`, workflow `publish.yml`, environment
   `pypi-milton-ai`.
4. Merge, create a clean annotated `v0.1.0` tag and GitHub release, and observe
   the OIDC publish job succeed.
5. Install the published artifact in a new environment and rerun the retained
   smoke.
6. Enable and verify GitHub Pages from `main` / `docs` after the landing page is
   merged.
