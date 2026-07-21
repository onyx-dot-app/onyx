from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock, patch

import pytest
from fastapi import Request

from onyx.db.enums import Permission
from onyx.db.llm import fetch_accessible_llm_provider_by_id
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.models import ReasoningEffort
from onyx.server.features.build import craft_gateway
from onyx.server.features.build.craft_gateway import CRAFT_GATEWAY_CONSUMER
from onyx.tracing.flows import LLMFlow


def _request(token_scopes: list[Permission] | None) -> Request:
    request = Request({"type": "http", "headers": []})
    if token_scopes is not None:
        request.state.token_scopes = token_scopes
    return request


def test_craft_consumer_requires_gateway_capable_token_scope() -> None:
    user = cast(User, MagicMock(spec=User))
    assert not CRAFT_GATEWAY_CONSUMER.matches(_request(None), user)
    assert not CRAFT_GATEWAY_CONSUMER.matches(_request([Permission.BASIC_ACCESS]), user)


def test_craft_consumer_matches_craft_sandbox_scope() -> None:
    user = cast(User, MagicMock(spec=User))
    assert CRAFT_GATEWAY_CONSUMER.matches(_request([Permission.CRAFT_SANDBOX]), user)


def test_craft_consumer_matches_directly_scoped_gateway_token() -> None:
    user = cast(User, MagicMock(spec=User))
    assert CRAFT_GATEWAY_CONSUMER.matches(_request([Permission.USE_LLM_GATEWAY]), user)


def test_craft_consumer_authorize_rejects_when_craft_disabled() -> None:
    user = cast(User, MagicMock(spec=User))
    request = _request([Permission.CRAFT_SANDBOX])
    with (
        patch.object(craft_gateway, "is_craft_enabled_for_user", return_value=False),
        pytest.raises(OnyxError) as exc_info,
    ):
        CRAFT_GATEWAY_CONSUMER.authorize(request, user)
    assert exc_info.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS


def test_craft_consumer_authorize_accepts_when_craft_enabled() -> None:
    user = cast(User, MagicMock(spec=User))
    with patch.object(craft_gateway, "is_craft_enabled_for_user", return_value=True):
        CRAFT_GATEWAY_CONSUMER.authorize(_request([Permission.CRAFT_SANDBOX]), user)


def test_craft_consumer_tags_generations_with_craft_flow() -> None:
    assert CRAFT_GATEWAY_CONSUMER.flow is LLMFlow.CRAFT_LLM_GENERATION


def test_craft_consumer_defaults_to_medium_reasoning_effort() -> None:
    assert CRAFT_GATEWAY_CONSUMER.default_reasoning_effort is ReasoningEffort.MEDIUM


def test_craft_consumer_uses_build_provider_accessibility() -> None:
    assert CRAFT_GATEWAY_CONSUMER.fetch_provider is fetch_accessible_llm_provider_by_id
