from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock, patch

import pytest
from fastapi import Request

from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.gateway import consumers
from onyx.server.gateway.consumers import (
    GatewayConsumer,
    register_gateway_consumer,
    resolve_gateway_consumer,
)
from onyx.tracing.flows import LLMFlow


def _consumer(
    name: str,
    *,
    matches: bool,
    flow: LLMFlow = LLMFlow.CRAFT_LLM_GENERATION,
) -> GatewayConsumer:
    return GatewayConsumer(
        name=name,
        flow=flow,
        matches=lambda _request, _user: matches,
        authorize=lambda _request, _user: None,
        fetch_provider=MagicMock(),
    )


def _request() -> Request:
    return Request({"type": "http", "headers": []})


def test_resolve_returns_first_matching_consumer() -> None:
    matching = _consumer("matching", matches=True)
    with patch.object(
        consumers, "_CONSUMERS", [_consumer("other", matches=False), matching]
    ):
        resolved = resolve_gateway_consumer(
            _request(), cast(User, MagicMock(spec=User))
        )
    assert resolved is matching


def test_resolve_rejects_when_no_consumer_matches() -> None:
    with (
        patch.object(consumers, "_CONSUMERS", [_consumer("other", matches=False)]),
        pytest.raises(OnyxError) as exc_info,
    ):
        resolve_gateway_consumer(_request(), cast(User, MagicMock(spec=User)))
    assert exc_info.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS


def test_resolve_propagates_consumer_authorization_failure() -> None:
    def _deny(_request: Request, _user: User) -> None:
        raise OnyxError(OnyxErrorCode.INSUFFICIENT_PERMISSIONS, "feature disabled")

    denied = GatewayConsumer(
        name="denied",
        flow=LLMFlow.CRAFT_LLM_GENERATION,
        matches=lambda _request, _user: True,
        authorize=_deny,
        fetch_provider=MagicMock(),
    )
    with (
        patch.object(consumers, "_CONSUMERS", [denied]),
        pytest.raises(OnyxError, match="feature disabled"),
    ):
        resolve_gateway_consumer(_request(), cast(User, MagicMock(spec=User)))


def test_register_is_idempotent_per_name() -> None:
    registry: list[GatewayConsumer] = []
    with patch.object(consumers, "_CONSUMERS", registry):
        register_gateway_consumer(_consumer("craft", matches=True))
        register_gateway_consumer(_consumer("craft", matches=True))
    assert len(registry) == 1
