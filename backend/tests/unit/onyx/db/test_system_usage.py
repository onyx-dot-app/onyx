"""System LLM usage rollup writes and reads."""

import datetime
from unittest.mock import MagicMock

from sqlalchemy.dialects import postgresql

from onyx.db.enums import SystemUsageAttribution
from onyx.db.llm_usage import LLMUsageRecord
from onyx.db.system_usage import record_system_usage


def test_record_system_usage_builds_accumulating_upsert() -> None:
    db_session = MagicMock()
    window_start = datetime.datetime(2026, 9, 2, tzinfo=datetime.timezone.utc)

    record_system_usage(
        db_session,
        attribution=SystemUsageAttribution.ATTRIBUTED,
        usage=LLMUsageRecord(
            model="claude-sonnet",
            flow="image_summarization",
            provider="anthropic",
            input_tokens=100,
            output_tokens=20,
            cache_read_tokens=10,
            cache_creation_tokens=5,
            cost_cents=1.5,
            window_start=window_start,
        ),
    )

    statement = db_session.execute.call_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    assert compiled.params["system_attribution"] == SystemUsageAttribution.ATTRIBUTED
    assert "user_usage.input_tokens + excluded.input_tokens" in str(compiled)
    db_session.flush.assert_called_once()
