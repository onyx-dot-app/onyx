"""Craft session attribution on gateway traces."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import Request

from onyx.server.gateway import craft_session
from onyx.server.gateway.configs import CRAFT_SESSION_HEADER
from onyx.server.gateway.craft_session import (
    llm_gateway_trace,
    resolve_craft_session_id,
)
from onyx.tracing.flows import LLMFlow


def _request(header: str | None) -> Request:
    headers = (
        [(CRAFT_SESSION_HEADER.lower().encode(), header.encode())] if header else []
    )
    return Request({"type": "http", "method": "POST", "path": "/", "headers": headers})


def test_no_header_means_no_session() -> None:
    assert resolve_craft_session_id(_request(None), MagicMock(), MagicMock()) is None


def test_malformed_header_is_ignored() -> None:
    with patch.object(craft_session, "get_build_session") as lookup:
        assert (
            resolve_craft_session_id(_request("not-a-uuid"), MagicMock(), MagicMock())
            is None
        )
    lookup.assert_not_called()


def test_session_of_another_user_is_ignored() -> None:
    with patch.object(craft_session, "get_build_session", return_value=None):
        assert (
            resolve_craft_session_id(_request(str(uuid4())), MagicMock(), MagicMock())
            is None
        )


def test_owned_session_is_returned() -> None:
    session_id = uuid4()
    user = MagicMock()
    db = MagicMock()
    with patch.object(
        craft_session, "get_build_session", return_value=object()
    ) as lookup:
        assert resolve_craft_session_id(_request(str(session_id)), user, db) == str(
            session_id
        )
    lookup.assert_called_once_with(session_id, user.id, db)


def test_trace_carries_session_when_known() -> None:
    with llm_gateway_trace(LLMFlow.CRAFT_LLM_GENERATION, "m", "sess-1") as active:
        exported = active.export() or {}
        assert exported["metadata"] == {
            "flow": LLMFlow.CRAFT_LLM_GENERATION.value,
            "model": "m",
            "craft_session_id": "sess-1",
        }


def test_trace_without_session_is_unchanged() -> None:
    with llm_gateway_trace(LLMFlow.LLM_GATEWAY, "m") as active:
        exported = active.export() or {}
        assert exported["metadata"] == {"flow": LLMFlow.LLM_GATEWAY.value, "model": "m"}
