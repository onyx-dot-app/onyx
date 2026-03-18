from onyx.db.enums import HookFailStrategy
from onyx.db.enums import HookPoint
from onyx.hooks.points.query_processing import QueryProcessingSpec


def test_hook_point_is_query_processing() -> None:
    assert QueryProcessingSpec().hook_point == HookPoint.QUERY_PROCESSING


def test_default_fail_strategy_is_hard() -> None:
    assert QueryProcessingSpec().default_fail_strategy == HookFailStrategy.HARD


def test_default_timeout_seconds() -> None:
    # User is actively waiting — 5s is the documented contract for this hook point
    assert QueryProcessingSpec().default_timeout_seconds == 5.0


def test_input_schema_required_fields() -> None:
    schema = QueryProcessingSpec().input_schema
    assert schema["type"] == "object"
    required = schema["required"]
    assert "query" in required
    assert "user_email" in required
    assert "chat_session_id" in required


def test_input_schema_chat_session_id_is_string() -> None:
    props = QueryProcessingSpec().input_schema["properties"]
    assert props["chat_session_id"]["type"] == "string"


def test_input_schema_query_is_string() -> None:
    props = QueryProcessingSpec().input_schema["properties"]
    assert props["query"]["type"] == "string"


def test_input_schema_user_email_is_nullable() -> None:
    props = QueryProcessingSpec().input_schema["properties"]
    assert "null" in props["user_email"]["type"]


def test_output_schema_query_is_required() -> None:
    schema = QueryProcessingSpec().output_schema
    assert "query" in schema["required"]


def test_output_schema_query_is_nullable() -> None:
    # null means "reject the query"
    props = QueryProcessingSpec().output_schema["properties"]
    assert "null" in props["query"]["type"]


def test_output_schema_rejection_message_is_optional() -> None:
    schema = QueryProcessingSpec().output_schema
    assert "rejection_message" not in schema.get("required", [])


def test_input_schema_no_additional_properties() -> None:
    assert QueryProcessingSpec().input_schema.get("additionalProperties") is False
