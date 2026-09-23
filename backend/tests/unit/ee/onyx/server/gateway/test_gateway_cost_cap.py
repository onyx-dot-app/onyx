"""The cloud cost cap on Onyx-managed provider keys applies to the gateway.

The chat route runs `check_llm_cost_limit_for_provider` for every provider it
calls. The gateway's generating routes did not, so a tenant over its weekly cap
could keep spending Onyx's managed keys through `/v1/*`. The cap itself is
real here; only the usage lookup is stubbed to report "over the cap".
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from ee.onyx.server.gateway import api as gateway_api
from onyx.db.models import User
from onyx.server import usage_limits
from onyx.server.gateway.models import (
    AnthropicMessagesRequest,
    ChatCompletionRequest,
    ResponsesRequest,
)
from onyx.server.manage.llm.models import LLMProviderView, ModelConfigurationView
from onyx.tracing.flows import LLMFlow

_MANAGED_KEY = "onyx-managed-test-key"

_GENERATING_ROUTES: list[tuple[Callable[..., Any], Callable[[], Any], list[str]]] = [
    (
        gateway_api.gateway_chat_completions,
        lambda: ChatCompletionRequest(
            model="1/test", messages=[{"role": "user", "content": "hi"}]
        ),
        ["handle_chat_completion"],
    ),
    (
        gateway_api.gateway_responses,
        lambda: ResponsesRequest(model="1/test", input="hi"),
        ["handle_openai_responses_passthrough", "handle_responses_request"],
    ),
    (
        gateway_api.gateway_anthropic_messages,
        lambda: AnthropicMessagesRequest(
            model="1/test",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=16,
        ),
        ["handle_anthropic_passthrough", "handle_anthropic_messages"],
    ),
]


def _provider(api_key: str) -> tuple[LLMProviderView, ModelConfigurationView]:
    model = ModelConfigurationView(
        name="test",
        is_visible=True,
        supports_image_input=False,
        supports_reasoning=False,
    )
    provider = LLMProviderView(
        id=1,
        name=None,
        provider="openai",
        api_key=api_key,
        model_configurations=[model],
    )
    return provider, model


def _over_cap(**_kwargs: object) -> None:
    raise HTTPException(status_code=429, detail="LLM usage limit exceeded")


@pytest.mark.parametrize(
    "route,make_request,handler_names",
    _GENERATING_ROUTES,
    ids=["chat_completions", "responses", "anthropic_messages"],
)
def test_managed_key_over_cap_never_reaches_the_provider(
    route: Callable[..., Any],
    make_request: Callable[[], Any],
    handler_names: list[str],
) -> None:
    handlers = {name: MagicMock() for name in handler_names}
    with (
        patch.object(
            gateway_api,
            "gateway_request_flow",
            MagicMock(return_value=LLMFlow.LLM_GATEWAY),
        ),
        patch.object(gateway_api, "check_token_rate_limits"),
        patch.object(
            gateway_api, "resolve_gateway_model", return_value=_provider(_MANAGED_KEY)
        ),
        patch.object(usage_limits, "USAGE_LIMITS_ENABLED", True),
        patch.object(usage_limits, "_ONYX_MANAGED_API_KEYS", {_MANAGED_KEY}),
        patch.object(
            usage_limits, "check_usage_and_raise", side_effect=_over_cap
        ) as usage_check,
        patch.multiple(gateway_api, **handlers),
        pytest.raises(HTTPException) as exc_info,
    ):
        route(
            request=make_request(),
            http_request=cast(Request, MagicMock(spec=Request)),
            user=cast(User, MagicMock(spec=User)),
            db_session=cast(Session, MagicMock(spec=Session)),
        )

    assert exc_info.value.status_code == 429
    usage_check.assert_called_once()
    for handler in handlers.values():
        handler.assert_not_called()


def test_own_provider_key_is_not_subject_to_the_cap() -> None:
    with (
        patch.object(
            gateway_api,
            "gateway_request_flow",
            MagicMock(return_value=LLMFlow.LLM_GATEWAY),
        ),
        patch.object(gateway_api, "check_token_rate_limits"),
        patch.object(
            gateway_api,
            "resolve_gateway_model",
            return_value=_provider("customer-own-key"),
        ),
        patch.object(usage_limits, "USAGE_LIMITS_ENABLED", True),
        patch.object(usage_limits, "_ONYX_MANAGED_API_KEYS", {_MANAGED_KEY}),
        patch.object(
            usage_limits, "check_usage_and_raise", side_effect=_over_cap
        ) as usage_check,
        patch.object(gateway_api, "handle_chat_completion") as handle,
    ):
        handle.return_value.to_wire.return_value = {}
        gateway_api.gateway_chat_completions(
            request=ChatCompletionRequest(
                model="1/test", messages=[{"role": "user", "content": "hi"}]
            ),
            http_request=cast(Request, MagicMock(spec=Request)),
            user=cast(User, MagicMock(spec=User)),
            db_session=cast(Session, MagicMock(spec=Session)),
        )

    usage_check.assert_not_called()
    handle.assert_called_once()
