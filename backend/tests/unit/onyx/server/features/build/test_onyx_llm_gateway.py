from __future__ import annotations

import threading
from contextlib import nullcontext
from typing import cast
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session

from onyx.db.enums import Permission
from onyx.db.models import BuildSession, Sandbox, User
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.interfaces import LLM, LLMConfig
from onyx.llm.model_response import Delta, ModelResponseStream, StreamingChoice
from onyx.llm.models import (
    ChatCompletionMessage,
    ReasoningEffort,
    SystemMessage,
    UserMessage,
)
from onyx.server.auth_check import check_router_auth
from onyx.server.features.build import llm_gateway
from onyx.server.features.build.sandbox.models import (
    GatewayModelConfig,
    LLMProviderConfig,
)
from onyx.server.features.build.sandbox.util.opencode_config import (
    build_session_opencode_config,
)
from onyx.server.features.build.session import llm_config
from onyx.server.features.build.session import manager as manager_module
from onyx.server.features.build.session.manager import SessionManager
from onyx.server.manage.llm.models import LLMProviderView, ModelConfigurationView


def _model(
    name: str,
    *,
    display_name: str | None = None,
    is_visible: bool = True,
    supports_reasoning: bool = False,
    max_input_tokens: int | None = None,
) -> ModelConfigurationView:
    return ModelConfigurationView(
        name=name,
        display_name=display_name,
        is_visible=is_visible,
        supports_image_input=False,
        supports_reasoning=supports_reasoning,
        max_input_tokens=max_input_tokens,
    )


def _provider(
    provider_id: int,
    provider_type: str,
    models: list[ModelConfigurationView],
    *,
    name: str | None = None,
) -> LLMProviderView:
    return LLMProviderView(
        id=provider_id,
        name=name,
        provider=provider_type,
        api_key="test-key",
        model_configurations=models,
    )


class _ConfigOnlyLLM(LLM):
    def __init__(self, config: LLMConfig) -> None:
        self._config = config

    @property
    def config(self) -> LLMConfig:
        return self._config


def test_resolve_model_preserves_slashes_after_provider_id() -> None:
    model = _model("anthropic/claude-3.5-sonnet")
    provider = _provider(23, "openrouter", [model])
    db_session = cast(Session, MagicMock(spec=Session))
    user = cast(User, MagicMock(spec=User))

    with patch.object(
        llm_gateway,
        "fetch_accessible_build_llm_provider_by_id",
        return_value=provider,
    ) as fetch_provider:
        resolved_provider, resolved_model = llm_gateway._resolve_model(
            db_session,
            user,
            "23/anthropic/claude-3.5-sonnet",
        )

    assert resolved_provider is provider
    assert resolved_model is model
    fetch_provider.assert_called_once_with(db_session, user, 23)


@pytest.mark.parametrize(
    "requested_model",
    ["claude-3.5-sonnet", "not-an-id/claude-3.5-sonnet", "23/hidden"],
)
def test_resolve_model_rejects_malformed_or_hidden_models(
    requested_model: str,
) -> None:
    provider = _provider(23, "anthropic", [_model("hidden", is_visible=False)])

    with (
        patch.object(
            llm_gateway,
            "fetch_accessible_build_llm_provider_by_id",
            return_value=provider,
        ),
        pytest.raises(OnyxError) as exc_info,
    ):
        llm_gateway._resolve_model(
            cast(Session, MagicMock(spec=Session)),
            cast(User, MagicMock(spec=User)),
            requested_model,
        )

    assert exc_info.value.status_code == 404


def test_gateway_config_qualifies_collisions_and_selects_exact_default() -> None:
    direct = _provider(
        3,
        "anthropic",
        [_model("claude-sonnet", display_name="Claude Sonnet")],
        name="Direct Anthropic",
    )
    bedrock = _provider(
        7,
        "bedrock",
        [_model("anthropic/claude-sonnet", display_name="Claude Sonnet")],
        name="AWS Bedrock",
    )

    with patch.object(llm_config, "SANDBOX_API_SERVER_URL", "https://onyx.test"):
        config = llm_config.build_onyx_gateway_config(
            [bedrock, direct],
            requested_provider_id=7,
            requested_provider_type="bedrock",
            requested_model_name="anthropic/claude-sonnet",
        )

    assert config is not None
    assert config.provider == "onyx"
    assert config.model_name == "7/anthropic/claude-sonnet"
    assert config.api_base == "https://onyx.test/api/build/llm-gateway/v1"
    assert config.models is not None
    assert {model.id for model in config.models} == {
        "3/claude-sonnet",
        "7/anthropic/claude-sonnet",
    }
    assert {model.display_name for model in config.models} == {
        "Claude Sonnet (Direct Anthropic)",
        "Claude Sonnet (AWS Bedrock)",
    }


def test_gateway_config_fallback_supports_any_provider() -> None:
    bedrock = _provider(2, "bedrock", [_model("bedrock-model")])
    anthropic = _provider(9, "anthropic", [_model("claude-first")])

    with patch.object(llm_config, "SANDBOX_API_SERVER_URL", "https://onyx.test"):
        config = llm_config.build_onyx_gateway_config([bedrock, anthropic])

    assert config is not None
    assert config.model_name == "2/bedrock-model"


def test_gateway_config_can_target_direct_api_service() -> None:
    with (
        patch.object(llm_config, "SANDBOX_API_SERVER_URL", "http://api:8080/"),
        patch.object(llm_config, "SANDBOX_API_PREFIX", ""),
    ):
        config = llm_config.build_onyx_gateway_config(
            [_provider(2, "bedrock", [_model("bedrock-model")])]
        )

    assert config is not None
    assert config.api_base == "http://api:8080/build/llm-gateway/v1"


def _request(token_scopes: list[Permission] | None) -> Request:
    request = Request({"type": "http", "headers": []})
    if token_scopes is not None:
        request.state.token_scopes = token_scopes
    return request


def test_gateway_requires_craft_sandbox_scope() -> None:
    user = cast(User, MagicMock(spec=User))
    with pytest.raises(OnyxError):
        llm_gateway._require_sandbox_gateway_access(_request(None), user)
    with pytest.raises(OnyxError):
        llm_gateway._require_sandbox_gateway_access(
            _request([Permission.BASIC_ACCESS]), user
        )


def test_gateway_accepts_enabled_craft_sandbox() -> None:
    user = cast(User, MagicMock(spec=User))
    with patch.object(llm_gateway, "is_craft_enabled_for_user", return_value=True):
        assert (
            llm_gateway._require_sandbox_gateway_access(
                _request([Permission.CRAFT_SANDBOX]), user
            )
            is user
        )


def test_gateway_route_exposes_standard_auth_dependency() -> None:
    application = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    application.include_router(llm_gateway.router)

    check_router_auth(application, public_endpoint_specs=[])


@pytest.mark.asyncio
async def test_gateway_auth_accepts_basic_user_with_craft_sandbox_scope() -> None:
    application = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    application.include_router(llm_gateway.router)
    gateway_route = cast(
        APIRoute,
        next(
            route
            for route in application.routes
            if getattr(route, "path", None)
            == f"{llm_gateway.ONYX_GATEWAY_PATH_PREFIX}/v1/chat/completions"
        ),
    )
    auth_dependencies = [
        dependency.call
        for dependency in gateway_route.dependant.dependencies
        if getattr(dependency.call, "_is_require_permission", False)
    ]
    assert len(auth_dependencies) == 1

    user = cast(User, MagicMock(spec=User))
    user.effective_permissions = [Permission.BASIC_ACCESS.value]
    request = _request([Permission.CRAFT_SANDBOX])

    auth_dependency = auth_dependencies[0]
    assert auth_dependency is not None
    authenticated_user = await auth_dependency(request=request, user=user)
    with patch.object(llm_gateway, "is_craft_enabled_for_user", return_value=True):
        assert (
            llm_gateway._require_sandbox_gateway_access(request, authenticated_user)
            is user
        )


class _StreamingLLM(_ConfigOnlyLLM):
    def __init__(self, closed: threading.Event, *, fail: bool = False) -> None:
        super().__init__(
            LLMConfig(
                model_provider="openai",
                model_name="test",
                temperature=0,
                max_input_tokens=1_000,
            )
        )
        self._closed = closed
        self._fail = fail

    def stream(self, *args: object, **kwargs: object):  # type: ignore[no-untyped-def,override]
        del args, kwargs
        try:
            if self._fail:
                raise RuntimeError("secret-provider-response")
            for index in range(1_000):
                yield ModelResponseStream(
                    id=str(index),
                    created="0",
                    choice=StreamingChoice(delta=Delta(content="x")),
                )
        finally:
            self._closed.set()


class _RaisingCloseStream:
    def __init__(self) -> None:
        self._remaining = 1

    def __iter__(self) -> _RaisingCloseStream:
        return self

    def __next__(self) -> ModelResponseStream:
        if not self._remaining:
            raise StopIteration
        self._remaining -= 1
        return ModelResponseStream(
            id="1",
            created="0",
            choice=StreamingChoice(delta=Delta(content="x")),
        )

    def close(self) -> None:
        raise RuntimeError("cleanup failed")


class _RaisingCloseLLM(_ConfigOnlyLLM):
    def stream(self, *args: object, **kwargs: object) -> _RaisingCloseStream:  # type: ignore[override]
        del args, kwargs
        return _RaisingCloseStream()


def _gateway_stream(llm: LLM):
    return llm_gateway._stream_sse(
        llm=llm,
        messages=[UserMessage(content="hello")],
        tools=None,
        tool_choice=None,
        max_tokens=None,
        reasoning_effort=ReasoningEffort.AUTO,
        model="1/test",
    )


def test_stream_disconnect_closes_upstream_producer() -> None:
    closed = threading.Event()
    stream = _gateway_stream(_StreamingLLM(closed))
    with patch.object(llm_gateway, "llm_generation_span", return_value=nullcontext()):
        next(stream)
        stream.close()
    assert closed.wait(timeout=2)


def test_stream_error_hides_provider_details() -> None:
    closed = threading.Event()
    stream = _gateway_stream(_StreamingLLM(closed, fail=True))
    with patch.object(llm_gateway, "llm_generation_span", return_value=nullcontext()):
        payload = next(stream)
        stream.close()
    assert "upstream LLM request failed" in payload
    assert "secret-provider-response" not in payload


def test_stream_cleanup_failure_does_not_hang_response() -> None:
    llm = _RaisingCloseLLM(
        LLMConfig(
            model_provider="openai",
            model_name="test",
            temperature=0,
            max_input_tokens=1_000,
        )
    )
    with patch.object(llm_gateway, "llm_generation_span", return_value=nullcontext()):
        payloads = list(_gateway_stream(llm))

    assert payloads[-1] == "data: [DONE]\n\n"


@pytest.mark.parametrize(
    ("raw", "supports_reasoning", "expected"),
    [
        (None, True, ReasoningEffort.HIGH),
        (None, False, ReasoningEffort.AUTO),
        ("low", False, ReasoningEffort.LOW),
        ("invalid", True, ReasoningEffort.AUTO),
    ],
)
def test_reasoning_effort_defaults_from_model_capability(
    raw: str | None,
    supports_reasoning: bool,
    expected: ReasoningEffort,
) -> None:
    assert llm_gateway._parse_reasoning_effort(raw, supports_reasoning) is expected


def test_prepare_messages_marks_stable_prefix_for_prompt_cache() -> None:
    config = LLMConfig(
        model_provider="anthropic",
        model_name="claude-sonnet",
        temperature=0,
        max_input_tokens=200_000,
    )
    llm = _ConfigOnlyLLM(config)
    messages: list[ChatCompletionMessage] = [
        SystemMessage(content="stable instructions"),
        UserMessage(content="new request"),
    ]
    processed = [*messages]

    with patch.object(
        llm_gateway,
        "process_with_prompt_cache",
        return_value=(processed, None),
    ) as process_prompt:
        result = llm_gateway._prepare_messages(llm, messages)

    assert result is processed
    process_prompt.assert_called_once_with(
        llm_config=config,
        cacheable_prefix=messages[:-1],
        suffix=messages[-1:],
        continuation=False,
    )


def test_prepare_messages_uses_no_cacheable_prefix_for_single_message() -> None:
    config = LLMConfig(
        model_provider="openai",
        model_name="gpt-5-mini",
        temperature=0,
        max_input_tokens=128_000,
    )
    llm = _ConfigOnlyLLM(config)
    messages: list[ChatCompletionMessage] = [UserMessage(content="only message")]

    with patch.object(
        llm_gateway,
        "process_with_prompt_cache",
        return_value=(messages, None),
    ) as process_prompt:
        llm_gateway._prepare_messages(llm, messages)

    assert process_prompt.call_args.kwargs["cacheable_prefix"] is None
    assert process_prompt.call_args.kwargs["suffix"] == messages


def test_normalize_agent_selection_uses_gateway_identity() -> None:
    assert llm_config.normalize_agent_selection(17, "anthropic/claude-sonnet") == (
        "onyx",
        "17/anthropic/claude-sonnet",
    )


def test_normalize_agent_selection_requires_provider_id_for_gateway() -> None:
    with pytest.raises(OnyxError, match="provider_id is required"):
        llm_config.normalize_agent_selection(None, "claude-sonnet")


def test_manager_uses_first_recommended_model_from_first_alphabetical_provider() -> (
    None
):
    anthropic = _provider(
        3,
        "anthropic",
        [_model("claude-sonnet"), _model("gpt-5.5")],
        name="Zulu provider",
    )
    bedrock = _provider(
        7,
        "bedrock",
        [_model("bedrock-default"), _model("claude-opus-4-8")],
        name="Alpha provider",
    )
    manager = SessionManager.__new__(SessionManager)
    manager._db_session = cast(Session, MagicMock(spec=Session))  # type: ignore[attr-defined]
    user = cast(User, MagicMock(spec=User))

    with (
        patch.object(llm_config, "SANDBOX_API_SERVER_URL", "https://onyx.test"),
        patch.object(
            manager_module,
            "fetch_all_accessible_build_llm_providers",
            return_value=[anthropic, bedrock],
        ) as fetch_providers,
    ):
        config = manager.build_llm_configs(user)

    assert config.provider == "onyx"
    assert config.model_name == "7/claude-opus-4-8"
    fetch_providers.assert_called_once_with(manager._db_session, user)  # type: ignore[attr-defined]


def _gateway_config() -> LLMProviderConfig:
    return LLMProviderConfig(
        provider="onyx",
        model_name="13/gpt-5-mini",
        api_key="proxy-placeholder",
        api_base="https://onyx.test/build/llm-gateway/v1",
        npm="@ai-sdk/openai-compatible",
        models=[
            GatewayModelConfig(
                id="13/gpt-5-mini",
                display_name="GPT-5 Mini",
            )
        ],
    )


def test_empty_gateway_session_skips_unchanged_catalog() -> None:
    manager = SessionManager.__new__(SessionManager)
    manager._db_session = cast(Session, MagicMock(spec=Session))  # type: ignore[attr-defined]
    manager._sandbox_manager = MagicMock()  # type: ignore[attr-defined]
    config = _gateway_config()
    expected = build_session_opencode_config(
        config, manager_module.OPENCODE_DISABLED_TOOLS
    )
    assert expected is not None
    manager._sandbox_manager.read_file.return_value = expected.encode()  # type: ignore[attr-defined]
    manager.build_llm_configs = MagicMock(return_value=config)  # type: ignore[method-assign]

    manager.reconcile_session_llm_config(
        cast(Sandbox, MagicMock(id=1)),
        cast(BuildSession, MagicMock(id=2)),
        cast(User, MagicMock(spec=User)),
        None,
        None,
        None,
    )

    manager._sandbox_manager.regenerate_session_config.assert_not_called()  # type: ignore[attr-defined]
    manager._sandbox_manager.dispose_opencode_instance.assert_not_called()  # type: ignore[attr-defined]


def test_empty_gateway_session_restarts_instance_for_changed_catalog() -> None:
    manager = SessionManager.__new__(SessionManager)
    manager._db_session = cast(Session, MagicMock(spec=Session))  # type: ignore[attr-defined]
    manager._sandbox_manager = MagicMock()  # type: ignore[attr-defined]
    manager._sandbox_manager.read_file.return_value = b"stale"  # type: ignore[attr-defined]
    config = _gateway_config()
    manager.build_llm_configs = MagicMock(return_value=config)  # type: ignore[method-assign]
    sandbox = cast(Sandbox, MagicMock(id=1))
    session = cast(
        BuildSession,
        MagicMock(id=2, opencode_session_id="ses-old", nextjs_port=3010),
    )
    user = cast(User, MagicMock(spec=User, personal_name="Roshan"))

    with patch.object(manager_module, "get_connectable_apps_for_user", return_value=[]):
        manager.reconcile_session_llm_config(sandbox, session, user, None, None, None)

    manager._sandbox_manager.regenerate_session_config.assert_called_once()  # type: ignore[attr-defined]
    manager._sandbox_manager.dispose_opencode_instance.assert_called_once_with(  # type: ignore[attr-defined]
        sandbox.id, session.id
    )
