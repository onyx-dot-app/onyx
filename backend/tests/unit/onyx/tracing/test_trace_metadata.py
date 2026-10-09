from onyx.tracing.framework.create import ChatTraceMetadata
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR


def test_chat_trace_metadata_uses_current_tenant() -> None:
    token = CURRENT_TENANT_ID_CONTEXTVAR.set("tenant")
    try:
        metadata = ChatTraceMetadata(chat_session_id="session", user_id="user")
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)

    assert metadata.model_dump() == {
        "tenant_id": "tenant",
        "chat_session_id": "session",
        "user_id": "user",
    }
