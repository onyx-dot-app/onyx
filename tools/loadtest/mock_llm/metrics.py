"""Bounded-label workload metrics, separate from application performance."""

from prometheus_client import Counter, Histogram

REQUESTS = Counter(
    "mock_llm_planned_calls", "Prepared model calls", ["profile", "size", "phase"]
)
TOKENS = Histogram(
    "mock_llm_planned_tokens",
    "Simulated tokenizer counts",
    ["direction"],
    buckets=(1, 10, 50, 100, 500, 1000, 5000, 10000, 30000, 100000),
)
CHUNKS = Histogram(
    "mock_llm_planned_chunks",
    "Planned deltas, including tool and reasoning deltas",
    buckets=(1, 10, 50, 100, 200, 500, 1000, 3000),
)
COMPLETED = Counter(
    "mock_llm_completed_calls", "Completed provider responses", ["transport"]
)
