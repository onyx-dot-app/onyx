"""End-to-end: a real streamed chat message must flow through the whole
per-user usage seam — generation span -> tracing processor registration ->
background drain thread -> user_usage rollup -> readable back through
GET /user/usage, attributed to the calling user.

Every other test for this feature mocks that seam (sqlite / MagicMock /
monkeypatched record_user_usage). This one exercises the wiring that unit tests
cannot: that the processor is actually registered at startup and that the drain
thread lands a row in Postgres for the right user.
"""

import time

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.test_models import DATestUser

# Drain thread flushes on a ~2s interval; give it generous headroom.
_POLL_TIMEOUT_SECONDS = 45


def _usage_token_total(user: DATestUser) -> int:
    """Caller's total (input + output) tokens in the current window, summed over
    the per-model breakdown returned by GET /user/usage. Token counts are
    recorded regardless of whether the model is priced, so this is robust to the
    deployment's default-cost config."""
    resp = client.get(
        f"{API_SERVER_URL}/user/usage",
        headers=user.headers,
        cookies=user.cookies,
    )
    resp.raise_for_status()
    body = resp.json()
    return sum(
        row["input_tokens"] + row["output_tokens"] for row in body["per_day_by_model"]
    )


def test_streamed_chat_records_per_user_usage(admin_user: DATestUser) -> None:
    LLMProviderManager.create(user_performing_action=admin_user)

    baseline_tokens = _usage_token_total(admin_user)

    session = ChatSessionManager.create(user_performing_action=admin_user)
    response = ChatSessionManager.send_message(
        chat_session_id=session.id,
        message="Reply with a single word.",
        user_performing_action=admin_user,
    )
    assert response.error is None, response.error
    assert len(response.full_message) > 0

    latest_tokens = baseline_tokens
    deadline = time.monotonic() + _POLL_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        latest_tokens = _usage_token_total(admin_user)
        if latest_tokens > baseline_tokens:
            break
        time.sleep(1)

    assert latest_tokens > baseline_tokens, (
        "expected the caller's windowed token usage to increase after a streamed "
        f"chat message (baseline={baseline_tokens}, latest={latest_tokens}); the "
        "usage recorder never landed a row"
    )
