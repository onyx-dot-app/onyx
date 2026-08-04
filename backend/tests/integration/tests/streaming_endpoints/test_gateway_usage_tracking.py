import time

from onyx.db.enums import Permission
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.managers.pat import PATManager
from tests.integration.common_utils.test_models import DATestUser

_GATEWAY_MODEL = "gpt-5-mini"
# Drain thread flushes on a ~2s interval; give it generous headroom.
_POLL_TIMEOUT_SECONDS = 45


def _usage_tokens_for_model(user: DATestUser, model: str) -> int:
    """Tokens, not cost: they are recorded regardless of whether the model is
    priced, so this is robust to the deployment's default-cost config."""
    resp = client.get(
        f"{API_SERVER_URL}/user/usage",
        headers=user.headers,
        cookies=user.cookies,
    )
    resp.raise_for_status()
    body = resp.json()
    return sum(
        row["input_tokens"] + row["output_tokens"]
        for row in body["per_day_by_model"]
        if row["model"] == model
    )


def _wait_for_usage_increase(user: DATestUser, model: str, baseline_tokens: int) -> int:
    latest_tokens = baseline_tokens
    deadline = time.monotonic() + _POLL_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        latest_tokens = _usage_tokens_for_model(user, model)
        if latest_tokens > baseline_tokens:
            break
        time.sleep(1)
    return latest_tokens


def _gateway_pat(user: DATestUser, name: str) -> str:
    pat = PATManager.create(
        name=name,
        expiration_days=None,
        user_performing_action=user,
        scopes=[Permission.USE_LLM_GATEWAY],
    )
    assert pat.token, "PAT creation did not return a raw token"
    return pat.token


def test_gateway_streamed_completion_records_per_user_usage(
    admin_user: DATestUser,
) -> None:
    provider = LLMProviderManager.create(
        default_model_name=_GATEWAY_MODEL, user_performing_action=admin_user
    )
    token = _gateway_pat(admin_user, "gateway-usage-streaming")

    baseline_tokens = _usage_tokens_for_model(admin_user, _GATEWAY_MODEL)

    response = client.post(
        f"{API_SERVER_URL}/gateway/v1/chat/completions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "model": f"{provider.id}/{_GATEWAY_MODEL}",
            "messages": [{"role": "user", "content": "Reply with a single word."}],
            "stream": True,
        },
        timeout=60,
    )
    response.raise_for_status()
    # The generation span is opened on a worker thread spawned after the
    # StreamingResponse is returned, so usage is only recorded once that
    # thread finishes -- the SSE body must be fully drained first.
    frames = [line for line in response.iter_lines() if line]

    # An upstream failure is an in-band SSE error frame on a 200, which would
    # otherwise surface as a misleading "no usage was recorded".
    assert "data: [DONE]" in frames, f"stream did not complete: {frames[-3:]}"
    assert not any('"error"' in frame for frame in frames), (
        f"gateway returned an in-band stream error: {frames[:3]}"
    )

    latest_tokens = _wait_for_usage_increase(
        admin_user, _GATEWAY_MODEL, baseline_tokens
    )

    assert latest_tokens > baseline_tokens, (
        f"expected the PAT owner's windowed {_GATEWAY_MODEL} token usage to "
        f"increase after a streamed gateway completion (baseline="
        f"{baseline_tokens}, latest={latest_tokens}); the gateway usage "
        "recorder never landed a row"
    )


def test_gateway_non_streaming_completion_records_per_user_usage(
    admin_user: DATestUser,
) -> None:
    provider = LLMProviderManager.create(
        default_model_name=_GATEWAY_MODEL, user_performing_action=admin_user
    )
    token = _gateway_pat(admin_user, "gateway-usage-non-streaming")

    baseline_tokens = _usage_tokens_for_model(admin_user, _GATEWAY_MODEL)

    response = client.post(
        f"{API_SERVER_URL}/gateway/v1/chat/completions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "model": f"{provider.id}/{_GATEWAY_MODEL}",
            "messages": [{"role": "user", "content": "Reply with a single word."}],
            "stream": False,
        },
        timeout=60,
    )
    response.raise_for_status()
    assert response.json()["usage"]["total_tokens"] > 0

    latest_tokens = _wait_for_usage_increase(
        admin_user, _GATEWAY_MODEL, baseline_tokens
    )

    assert latest_tokens > baseline_tokens, (
        f"expected the PAT owner's windowed {_GATEWAY_MODEL} token usage to "
        f"increase after a non-streamed gateway completion (baseline="
        f"{baseline_tokens}, latest={latest_tokens}); the gateway usage "
        "recorder never landed a row"
    )
