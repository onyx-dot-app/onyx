"""Worker identity context and host-controlled cloud identity grants."""

import asyncio
from unittest.mock import MagicMock

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from onyx.chat.pi import auth, client
from onyx.chat.pi.auth import worker_identity
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.interfaces import LLM, LLMConfig
from onyx.llm.models import ReasoningEffort
from shared_configs.contextvars import get_current_tenant_id


def test_worker_http_auth_and_concurrent_tenant_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ONYX_AGENT_SERVICE_TOKEN", "test-only-worker-token")
    monkeypatch.setattr(auth, "MULTI_TENANT", True)
    app = FastAPI()

    @app.get("/identity", dependencies=[Depends(worker_identity)])
    async def identity() -> dict[str, str]:
        await asyncio.sleep(0.01)
        return {"tenant": get_current_tenant_id()}

    async def exercise() -> None:
        initial_tenant = get_current_tenant_id()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as http:
            for authorization in ("", "Bearer incorrect-token"):
                with pytest.raises(OnyxError):
                    await http.get(
                        "/identity",
                        headers={
                            "authorization": authorization,
                            "x-onyx-tenant-id": "tenant_a",
                        },
                    )
            responses = await asyncio.gather(
                *(
                    http.get(
                        "/identity",
                        headers={
                            "authorization": "Bearer test-only-worker-token",
                            "x-onyx-tenant-id": tenant,
                        },
                    )
                    for tenant in ("tenant_a", "tenant_b")
                )
            )
            assert [response.json() for response in responses] == [
                {"tenant": "tenant_a"},
                {"tenant": "tenant_b"},
            ]
        assert get_current_tenant_id() == initial_tenant

    asyncio.run(exercise())


@pytest.mark.parametrize("multi_tenant", [True, False])
def test_tenant_config_cannot_grant_workload_identity(
    monkeypatch: pytest.MonkeyPatch, multi_tenant: bool
) -> None:
    monkeypatch.setattr(client, "MULTI_TENANT", multi_tenant)
    llm = MagicMock(spec=LLM)
    llm.config = LLMConfig(
        model_provider="openai",
        model_name="gpt-5-mini",
        temperature=0,
        max_input_tokens=4096,
        custom_config={"allowWorkloadIdentity": "true"},
    )
    llm.request_options = {"allowWorkloadIdentity": True}
    start = client.build_start(llm, None, ReasoningEffort.MEDIUM)
    assert start["allowWorkloadIdentity"] is not multi_tenant


@pytest.mark.parametrize(
    "headers,configured_token,expected_status",
    [
        ({}, "token", 401),
        ({"authorization": "Bearer incorrect"}, "token", 401),
        ({"authorization": "Bearer token", "x-onyx-tenant-id": "public"}, "", 401),
        (
            {"authorization": "Bearer token", "x-onyx-tenant-id": "invalid;schema"},
            "token",
            400,
        ),
        (
            {"authorization": "Bearer token", "x-onyx-tenant-id": "other_tenant"},
            "token",
            400,
        ),
        (
            {
                "authorization": "Bearer token",
                "x-onyx-tenant-id": "public",
                "x-onyx-public-request": "true",
            },
            "token",
            404,
        ),
    ],
)
def test_worker_rejects_unauthorized_requests_before_execution(
    monkeypatch: pytest.MonkeyPatch,
    headers: dict[str, str],
    configured_token: str,
    expected_status: int,
) -> None:
    from onyx.error_handling.exceptions import register_onyx_exception_handlers

    monkeypatch.setenv("ONYX_AGENT_SERVICE_TOKEN", configured_token)
    monkeypatch.setattr(auth, "MULTI_TENANT", False)
    monkeypatch.setattr(auth, "POSTGRES_DEFAULT_SCHEMA", "public")
    app = FastAPI()
    register_onyx_exception_handlers(app)
    executed = False

    @app.post("/callback", dependencies=[Depends(worker_identity)])
    async def callback() -> dict[str, bool]:
        nonlocal executed
        executed = True
        return {"ok": True}

    async def exercise() -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as http:
            response = await http.post("/callback", headers=headers)
            assert response.status_code == expected_status
        assert not executed

    asyncio.run(exercise())
