from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from onyx.db.models import BuildSession, Sandbox, User
from onyx.error_handling.exceptions import OnyxError
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

    with patch.object(llm_config, "ONYX_SERVER_URL", "https://onyx.test/api"):
        config = llm_config.build_onyx_gateway_config(
            [bedrock, direct],
            requested_provider_id=7,
            requested_provider_type="bedrock",
            requested_model_name="anthropic/claude-sonnet",
        )

    assert config is not None
    assert config.provider == "onyx"
    assert config.model_name == "7/anthropic/claude-sonnet"
    assert config.api_base == "https://onyx.test/api/gateway/v1"
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

    with patch.object(llm_config, "ONYX_SERVER_URL", "https://onyx.test"):
        config = llm_config.build_onyx_gateway_config([bedrock, anthropic])

    assert config is not None
    assert config.model_name == "2/bedrock-model"


def test_gateway_config_can_target_direct_api_service() -> None:
    with patch.object(llm_config, "ONYX_SERVER_URL", "http://api:8080/"):
        config = llm_config.build_onyx_gateway_config(
            [_provider(2, "bedrock", [_model("bedrock-model")])]
        )

    assert config is not None
    assert config.api_base == "http://api:8080/gateway/v1"


def test_gateway_config_preserves_url_path_prefix() -> None:
    with patch.object(llm_config, "ONYX_SERVER_URL", "https://onyx.example/api"):
        config = llm_config.build_onyx_gateway_config(
            [_provider(2, "bedrock", [_model("bedrock-model")])]
        )

    assert config is not None
    assert config.api_base == "https://onyx.example/api/gateway/v1"


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
        patch.object(llm_config, "ONYX_SERVER_URL", "https://onyx.test"),
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
        api_base="https://onyx.test/gateway/v1",
        npm_package="@ai-sdk/openai-compatible",
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
