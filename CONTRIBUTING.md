# Contributing to Milton

Milton turns heterogeneous agent exhaust into conservative, inspectable
projections. Contributions should preserve that trust boundary: retain source
custody, state uncertainty, and prefer abstention to an invented join or cost.

## Development setup

Milton requires Python 3.12 or newer and uses `uv` for its development
environment:

```console
uv sync --frozen
uv run ruff format --check src/ tests/ scripts/
uv run ruff check src/ tests/ scripts/
uv run mypy --strict src tests scripts
uv run pytest -q
uv build
```

The default package has no runtime dependencies. Keep optional, network-bound,
or heavyweight integrations behind adapter seams; the local deterministic path
must continue to work after `pip install milton-agents` alone.

## Evidence contracts

- Preserve native source coordinates and evidence locators.
- Keep identity association separate from directed work relations.
- Do not infer that two costs are duplicates without an exact shared accounting
  key; reported and computed values remain distinct observations.
- Never turn a rollup into a counting observation merely because it has an
  amount.
- Findings must carry a bounded source snapshot, generator identity, coverage,
  evidence references, grade, and expiry.
- Changes to thresholds, precedence, schemas, or economic semantics require
  explicit tests and a changelog note. Treat load-bearing threshold changes as
  breaking changes.

## Adapter fixtures

Adapters are read-only. Add the smallest representative fixture for a producer
format, including malformed and incomplete cases where relevant. Tests must
prove both what Milton can conclude and where it abstains. Do not commit real
transcripts, credentials, provider payloads, or private source material.

## Release smoke

The clean-install release smoke builds a fresh virtual environment, installs
only the wheel, ingests the checked-in synthetic corpus, and compares compact
accounting, attribution, and finding manifests:

```console
uv build
uv run python scripts/release_smoke.py dist/milton_agents-*.whl
```

Update the expected manifest only when an intentional contract change has been
reviewed and documented.
