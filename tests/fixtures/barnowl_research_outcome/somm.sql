CREATE TABLE calls (
    id TEXT PRIMARY KEY,
    ts TEXT NOT NULL,
    project TEXT NOT NULL,
    workload_id TEXT,
    prompt_id TEXT,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    tokens_in INTEGER NOT NULL,
    tokens_out INTEGER NOT NULL,
    cost_usd REAL NOT NULL,
    outcome TEXT NOT NULL,
    correlation_id TEXT,
    cost_basis TEXT,
    cost_kind TEXT,
    cost_accuracy TEXT,
    cost_source TEXT,
    pricing_version TEXT,
    observation_role TEXT
);

INSERT INTO calls VALUES
    (
        'fixture-call-1', '2026-07-18T12:00:00+00:00', 'barnowl',
        'fixture_workload', 'fixture-workload:evaluator-v1',
        'fixture-provider-a', 'fixture-model-a', 100, 20, 0.12, 'ok',
        'correlation-retry-1', 'reported', 'marginal', 'actual',
        'fixture-provider-receipt', 'fixture-pricing-v1', 'production'
    ),
    (
        'fixture-call-2', '2026-07-18T12:00:01+00:00', 'barnowl',
        'fixture_workload', 'fixture-workload:evaluator-v1',
        'fixture-provider-b', 'fixture-model-b', 80, 10, 0.18, 'ok',
        'correlation-retry-1', 'reported', 'marginal', 'actual',
        'fixture-provider-receipt', 'fixture-pricing-v1', 'production'
    );
