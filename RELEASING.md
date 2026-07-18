# Releasing Milton

This is Milton's canonical release path. If the path changes, update this file
before cutting the release.

## Versioning

Milton follows semantic versioning. The version moves in lockstep in:

- `pyproject.toml`
- `src/milton/version.py`

Use a patch release for fixes and documentation that do not change a contract;
a minor release for backward-compatible CLI, adapter, or library additions; and
a major release for breaking CLI flags, schemas, precedence, threshold, or
economic-semantics changes. Call out load-bearing threshold changes explicitly.

The distribution name is `milton-ai`; the import package and CLI are both
`milton`.

## Release checklist

1. Run the current public-source hygiene gate from the private release operator.
   Resolve every match; do not copy the internal denylist into public history.

2. Run every local gate:

   ```console
   uv lock --check
   uv run ruff format --check src/ tests/ scripts/
   uv run ruff check src/ tests/ scripts/
   uv run mypy --strict src tests scripts
   uv run pytest -q
   uv build
   uv run python scripts/release_smoke.py dist/milton_ai-*.whl
   uvx --from pip-audit pip-audit . --strict --disable-pip
   uvx --from zizmor zizmor .github/workflows --offline \
     --min-severity high --min-confidence high
   ```

3. Bump `pyproject.toml` and `src/milton/version.py` in lockstep. Refresh
   `uv.lock` and verify `milton --version` from the built wheel.
4. Move the release notes out of `Unreleased` in `CHANGELOG.md` under a dated
   `X.Y.Z` heading.
5. Update the version and status in `docs/index.html`.
6. Commit a clean `chore(release): X.Y.Z`; the tag must point at a clean tree.
7. Tag and push:

   ```console
   git tag -a vX.Y.Z -m "vX.Y.Z — short summary"
   git push origin main
   git push origin vX.Y.Z
   ```

8. Create a focused GitHub release with a compare link. Publishing the release
   triggers `.github/workflows/publish.yml`.
9. Verify the trusted-publishing job, then install `milton-ai==X.Y.Z` in a
   new environment and rerun the fixture smoke against that installed artifact.
10. Verify the GitHub Pages landing page reports the released version.

## Trusted-publishing setup

Before the first release, register a pending PyPI trusted publisher for:

- owner: `lavallee`
- repository: `milton`
- workflow: `publish.yml`
- environment: `pypi-milton-ai`
- project: `milton-ai`

The workflow uses GitHub OIDC and stores no PyPI token. The manual fallback is
`uv build && uv publish`, which requires an explicitly supplied PyPI credential.
