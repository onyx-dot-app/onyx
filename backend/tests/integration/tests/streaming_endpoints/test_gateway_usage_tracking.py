"""End-to-end: a call through the OpenAI-compatible LLM gateway
(POST /gateway/v1/chat/completions), authenticated with a scoped PAT rather
than a session, must flow through the same per-user usage seam as chat: a
generation span recorded inside an active tracing trace -> the tracing
processor -> the background drain thread -> a user_usage rollup -> readable
back through GET /user/usage, attributed to the PAT's owning user.

The gateway previously opened no trace at all, so its generation spans
degraded to NoOpSpan and the processor never saw them -- zero usage was
recorded for every gateway call. Unit tests mock the trace/span seam and
cannot catch that; this test exercises the real wiring, for both the
non-streaming path and the streaming path (whose generation span runs on a
worker thread spawned only after the endpoint has already returned the
StreamingResponse -- the case most likely to regress silently).
"""

import time

from onyx.db.enums import Permission
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.managers.pat import PATManager
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


def _wait_for_usage_increase(user: DATestUser, baseline_tokens: int) -> int:
    latest_tokens = baseline_tokens
    deadline = time.monotonic() + _POLL_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        latest_tokens = _usage_token_total(user)
        if latest_tokens > baseline_tokens:
            break
        time.sleep(1)
    return latest_tokens


def test_gateway_streamed_completion_records_per_user_usage(
    admin_user: DATestUser,
) -> None:
    provider = LLMProviderManager.create(user_performing_action=admin_user)
    pat = PATManager.create(
        name="gateway-usage-streaming",
        expiration_days=None,
        user_performing_action=admin_user,
        scopes=[Permission.USE_LLM_GATEWAY],
    )
    assert pat.token, "PAT creation did not return a raw token"

    assert provider.default_model_name, "provider has no default model to route to"
    model_id = f"{provider.id}/{provider.default_model_name}"

    baseline_tokens = _usage_token_total(admin_user)

    response = client.post(
        f"{API_SERVER_URL}/gateway/v1/chat/completions",
        headers={"Authorization": f"Bearer {pat.token}"},
        json={
            "model": model_id,
            "messages": [{"role": "user", "content": "Reply with a single word."}],
            "stream": True,
        },
        timeout=60,
    )
    response.raise_for_status()
    # The generation span is opened on a worker thread spawned after the
    # StreamingResponse is returned, so usage is only recorded once that
    # thread finishes -- the SSE body must be fully drained first.
    list(response.iter_lines())

    latest_tokens = _wait_for_usage_increase(admin_user, baseline_tokens)

    assert latest_tokens > baseline_tokens, (
        "expected the PAT owner's windowed token usage to increase after a "
        f"streamed gateway completion (baseline={baseline_tokens}, "
        f"latest={latest_tokens}); the gateway usage recorder never landed a row"
    )


def test_gateway_non_streaming_completion_records_per_user_usage(
    admin_user: DATestUser,
) -> None:
    provider = LLMProviderManager.create(user_performing_action=admin_user)
    pat = PATManager.create(
        name="gateway-usage-non-streaming",
        expiration_days=None,
        user_performing_action=admin_user,
        scopes=[Permission.USE_LLM_GATEWAY],
    )
    assert pat.token, "PAT creation did not return a raw token"

    assert provider.default_model_name, "provider has no default model to route to"
    model_id = f"{provider.id}/{provider.default_model_name}"

    baseline_tokens = _usage_token_total(admin_user)

    response = client.post(
        f"{API_SERVER_URL}/gateway/v1/chat/completions",
        headers={"Authorization": f"Bearer {pat.token}"},
        json={
            "model": model_id,
            "messages": [{"role": "user", "content": "Reply with a single word."}],
            "stream": False,
        },
        timeout=60,
    )
    response.raise_for_status()

    latest_tokens = _wait_for_usage_increase(admin_user, baseline_tokens)

    assert latest_tokens > baseline_tokens, (
        "expected the PAT owner's windowed token usage to increase after a "
        f"non-streamed gateway completion (baseline={baseline_tokens}, "
        f"latest={latest_tokens}); the gateway usage recorder never landed a row"
    )
