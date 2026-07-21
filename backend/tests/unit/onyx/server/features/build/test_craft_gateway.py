from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock, patch

from fastapi import Request

from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.server.features.build import craft_gateway
from onyx.server.features.build.craft_gateway import is_craft_gateway_request


def _request(token_scopes: list[Permission] | None) -> Request:
    request = Request({"type": "http", "headers": []})
    if token_scopes is not None:
        request.state.token_scopes = token_scopes
    return request


def test_gateway_requires_gateway_capable_token_scope() -> None:
    user = cast(User, MagicMock(spec=User))
    with patch.object(craft_gateway, "is_craft_enabled_for_user", return_value=True):
        assert not is_craft_gateway_request(_request(None), user)
        assert not is_craft_gateway_request(_request([Permission.BASIC_ACCESS]), user)


def test_gateway_accepts_enabled_craft_sandbox() -> None:
    user = cast(User, MagicMock(spec=User))
    with patch.object(craft_gateway, "is_craft_enabled_for_user", return_value=True):
        assert is_craft_gateway_request(_request([Permission.CRAFT_SANDBOX]), user)


def test_gateway_accepts_directly_scoped_gateway_token() -> None:
    user = cast(User, MagicMock(spec=User))
    with patch.object(craft_gateway, "is_craft_enabled_for_user", return_value=True):
        assert is_craft_gateway_request(_request([Permission.USE_LLM_GATEWAY]), user)


def test_gateway_rejects_craft_sandbox_scope_when_craft_disabled() -> None:
    user = cast(User, MagicMock(spec=User))
    with patch.object(craft_gateway, "is_craft_enabled_for_user", return_value=False):
        assert not is_craft_gateway_request(_request([Permission.CRAFT_SANDBOX]), user)
