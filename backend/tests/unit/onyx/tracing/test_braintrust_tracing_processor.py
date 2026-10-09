import sys
from unittest.mock import MagicMock, patch

import pytest

from onyx.tracing.framework.span_data import GenerationSpanData

# The connector tests also define a top-level package named braintrust. Stub the
# optional SDK so full-suite collection cannot bind this import to that package.
with patch.dict(sys.modules, {"braintrust": MagicMock()}):
    from onyx.tracing.braintrust_tracing_processor import BraintrustTracingProcessor


def test_generation_cost_prices_cache_creation_at_write_rate() -> None:
    span = MagicMock()
    span.started_at = None
    span.ended_at = None
    span.span_data = GenerationSpanData(
        model="claude-sonnet-4-5",
        model_config={"model_provider": "anthropic"},
        usage={
            "input_tokens": 3000,
            "output_tokens": 0,
            "cache_creation_input_tokens": 2000,
        },
    )

    processor = BraintrustTracingProcessor()
    metrics = processor._generation_log_data(span)["metrics"]

    assert metrics["cost_cents"] == pytest.approx(1.05)
