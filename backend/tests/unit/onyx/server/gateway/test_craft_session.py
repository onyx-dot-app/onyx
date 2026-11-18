"""Craft session attribution on gateway traces."""

import asyncio
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import Request

from onyx.server.features.build import request_context as craft_session
from onyx.server.features.build.configs import CRAFT_SESSION_HEADER
from onyx.server.features.build.request_context import (
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


def test_session_of_another_user_is_ignored() -> None:
    with patch.object(craft_session, "get_build_session", return_value=None):
        assert resolve_craft_session_id(uuid4(), MagicMock(), MagicMock()) is None


def test_owned_session_is_returned() -> None:
    session_id = uuid4()
    user = MagicMock()
    db = MagicMock()
    with patch.object(
        craft_session, "get_build_session", return_value=object()
    ) as lookup:
        assert resolve_craft_session_id(session_id, user, db) == str(session_id)
    lookup.assert_called_once_with(session_id, user.id, db)


def test_binder_sets_and_resets_the_context_variable() -> None:
    session_id = str(uuid4())
    bind = craft_session_binder(lambda: MagicMock())

    async def scenario() -> tuple[str | None, str | None]:
        with (
            patch.object(craft_session, "get_session_with_current_tenant"),
            patch.object(craft_session, "get_build_session", return_value=object()),
        ):
            dependency = bind(_request(session_id), MagicMock())
            await dependency.__anext__()
            bound = CRAFT_SESSION_ID_CONTEXTVAR.get()
            try:
                await dependency.__anext__()
            except StopAsyncIteration:
                pass
        return bound, CRAFT_SESSION_ID_CONTEXTVAR.get()

    assert asyncio.run(scenario()) == (session_id, None)


def test_trace_carries_bound_session() -> None:
    session_id = str(uuid4())
    token = CRAFT_SESSION_ID_CONTEXTVAR.set(session_id)
    try:
        with llm_gateway_trace(LLMFlow.CRAFT_LLM_GENERATION, "m") as active:
            assert (active.export() or {})["metadata"] == {
                "flow": LLMFlow.CRAFT_LLM_GENERATION.value,
                "model": "m",
                "craft_session_id": session_id,
            }
    finally:
        CRAFT_SESSION_ID_CONTEXTVAR.reset(token)


def test_trace_without_session_is_unchanged() -> None:
    with llm_gateway_trace(LLMFlow.LLM_GATEWAY, "m") as active:
        assert (active.export() or {})["metadata"] == {
            "flow": LLMFlow.LLM_GATEWAY.value,
            "model": "m",
        }


def test_unowned_session_cannot_bind_a_turn_trace() -> None:
    bind = craft_session_binder(lambda: MagicMock())

    async def scenario() -> None:
        with (
            patch.object(craft_session, "get_session_with_current_tenant"),
            patch.object(craft_session, "get_build_session", return_value=None),
            patch.object(craft_session, "get_craft_turn_trace_id") as lookup,
        ):
            dependency = bind(_request(str(uuid4())), MagicMock())
            await dependency.__anext__()
            with llm_gateway_trace(LLMFlow.CRAFT_LLM_GENERATION, "m"):
                pass
            with pytest.raises(StopAsyncIteration):
                await dependency.__anext__()
            lookup.assert_not_called()

    asyncio.run(scenario())


def test_ownership_connection_is_released_before_cache_lookup() -> None:
    bind = craft_session_binder(lambda: MagicMock())
    session_context = MagicMock()

    def read_turn_trace(_session_id: object) -> str:
        session_context.__exit__.assert_called_once()
        return "a" * 32

    async def scenario() -> None:
        with (
            patch.object(
                craft_session,
                "get_session_with_current_tenant",
                return_value=session_context,
                create=True,
            ),
            patch.object(craft_session, "get_build_session", return_value=object()),
            patch.object(
                craft_session, "get_craft_turn_trace_id", side_effect=read_turn_trace
            ),
        ):
            dependency = bind(_request(str(uuid4())), MagicMock())
            await dependency.__anext__()
            with llm_gateway_trace(LLMFlow.CRAFT_LLM_GENERATION, "m") as active:
                assert (active.export() or {})["metadata"][
                    "distributed_trace_id"
                ] == "a" * 32
            with pytest.raises(StopAsyncIteration):
                await dependency.__anext__()

    asyncio.run(scenario())


@pytest.mark.parametrize("header", [None, "not-a-uuid"])
def test_binder_skips_database_for_invalid_claims(header: str | None) -> None:
    bind = craft_session_binder(lambda: MagicMock())

    async def scenario() -> None:
        with (
            patch.object(craft_session, "get_session_with_current_tenant") as database,
            patch.object(craft_session, "run_in_threadpool") as worker,
        ):
            dependency = bind(_request(header), MagicMock())
            await dependency.__anext__()
            with pytest.raises(StopAsyncIteration):
                await dependency.__anext__()
            database.assert_not_called()
            worker.assert_not_called()

    asyncio.run(scenario())
