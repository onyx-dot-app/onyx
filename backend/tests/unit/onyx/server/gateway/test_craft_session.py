"""Craft session attribution on gateway traces."""

import asyncio
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import Request

from onyx.server.gateway import craft_session
from onyx.server.gateway.configs import CRAFT_SESSION_HEADER
from onyx.server.gateway.craft_session import (
    CRAFT_SESSION_ID_CONTEXTVAR,
    craft_session_binder,
    resolve_craft_session_id,
)
from onyx.server.gateway.tracing import llm_gateway_trace
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


def test_binder_sets_and_resets_the_context_variable() -> None:
    session_id = str(uuid4())
    bind = craft_session_binder(lambda: MagicMock())

    async def scenario() -> tuple[str | None, str | None]:
        with patch.object(craft_session, "get_build_session", return_value=object()):
            dependency = bind(_request(session_id), MagicMock(), MagicMock())
            await dependency.__anext__()
            bound = CRAFT_SESSION_ID_CONTEXTVAR.get()
            try:
                await dependency.__anext__()
            except StopAsyncIteration:
                pass
        return bound, CRAFT_SESSION_ID_CONTEXTVAR.get()

    assert asyncio.run(scenario()) == (session_id, None)


def test_trace_carries_bound_session() -> None:
    token = CRAFT_SESSION_ID_CONTEXTVAR.set("sess-1")
    try:
        with llm_gateway_trace(LLMFlow.CRAFT_LLM_GENERATION, "m") as active:
            assert (active.export() or {})["metadata"] == {
                "flow": LLMFlow.CRAFT_LLM_GENERATION.value,
                "model": "m",
                "craft_session_id": "sess-1",
            }
    finally:
        CRAFT_SESSION_ID_CONTEXTVAR.reset(token)


def test_trace_without_session_is_unchanged() -> None:
    with llm_gateway_trace(LLMFlow.LLM_GATEWAY, "m") as active:
        assert (active.export() or {})["metadata"] == {
            "flow": LLMFlow.LLM_GATEWAY.value,
            "model": "m",
        }
