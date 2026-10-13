from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import cast
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from onyx.db.models import BuildSession, Sandbox, User
from onyx.llm.well_known_providers.auto_update_models import (
    LLMProviderRecommendation,
    LLMRecommendations,
)
from onyx.llm.well_known_providers.models import SimpleKnownModel
from onyx.server.features.build.configs import OPENCODE_DISABLED_TOOLS
from onyx.server.features.build.sandbox.models import CraftLLMProviderConfig
from onyx.server.features.build.sandbox.util.opencode_config import (
    build_provider_opencode_config,
)
from onyx.server.features.build.session import llm_config
from onyx.server.features.build.session import manager as manager_module
from onyx.server.features.build.session.manager import SessionManager
from onyx.server.gateway import model_catalog
from onyx.server.gateway.models import GatewayModelDescriptor
from onyx.server.manage.llm.models import LLMProviderView, ModelConfigurationView


def _model(
    name: str,
    *,
    display_name: str | None = None,
    is_visible: bool = True,
    supports_image_input: bool = False,
    supports_reasoning: bool = False,
    max_input_tokens: int | None = None,
    configured_max_input_tokens: int | None = None,
) -> ModelConfigurationView:
    return ModelConfigurationView(
        name=name,
        display_name=display_name,
        is_visible=is_visible,
        supports_image_input=supports_image_input,
        supports_reasoning=supports_reasoning,
        max_input_tokens=max_input_tokens,
        configured_max_input_tokens=configured_max_input_tokens,
    )


def _provider(
    provider_id: int,
    provider_type: str,
    models: list[ModelConfigurationView],
    *,
    name: str | None = None,
    deployment_name: str | None = None,
) -> LLMProviderView:
    return LLMProviderView(
        id=provider_id,
        name=name,
        provider=provider_type,
        api_key="test-key",
        deployment_name=deployment_name,
        model_configurations=models,
    )


_TEST_RECOMMENDATIONS = LLMRecommendations(
    version="test",
    updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    providers={
        "anthropic": LLMProviderRecommendation(
            default_model=SimpleKnownModel(name="claude-opus-5")
        ),
        "bedrock": LLMProviderRecommendation(
            default_model=SimpleKnownModel(name="bedrock-pro")
        ),
        "openai": LLMProviderRecommendation(
            default_model=SimpleKnownModel(name="gpt-5.6-sol")
        ),
    },
)


@pytest.fixture(autouse=True)
def _mock_recommendations() -> Iterator[None]:
    # get_recommendations() otherwise does a live GitHub fetch; pin it so default
    # selection is deterministic and tests don't drift when the json regenerates.
    with patch.object(
        llm_config, "get_recommendations", return_value=_TEST_RECOMMENDATIONS
    ):
        yield


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
            llm_config.GatewaySelection(7, "anthropic/claude-sonnet"),
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


def test_gateway_model_capabilities_reach_opencode_catalog() -> None:
    provider = _provider(
        3,
        "anthropic",
        [
            _model(
                "claude-opus-5",
                supports_image_input=True,
                supports_reasoning=True,
            ),
            _model("claude-text-only"),
        ],
    )

    with patch.object(llm_config, "ONYX_SERVER_URL", "https://onyx.test"):
        gateway_config = llm_config.build_onyx_gateway_config([provider])

    assert gateway_config is not None
    opencode_models = build_provider_opencode_config(gateway_config)["provider"][
        "onyx"
    ]["models"]

    vision_model = opencode_models["3/claude-opus-5"]
    assert vision_model["modalities"] == {
        "input": ["text", "image"],
        "output": ["text"],
    }
    assert vision_model["attachment"] is True
    assert vision_model["reasoning"] is True
    assert "options" not in vision_model

    text_model = opencode_models["3/claude-text-only"]
    assert text_model["modalities"] == {
        "input": ["text"],
        "output": ["text"],
    }
    assert text_model["attachment"] is False
    assert text_model["reasoning"] is False
    assert "options" not in text_model


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


def test_custom_azure_alias_renders_deployment_limits_for_opencode() -> None:
    provider = _provider(
        300,
        "azure",
        [
            _model(
                "GPT-5.6-SOL",
                # This is the misleading fallback produced when the alias itself
                # is absent from LiteLLM, matching the production regression.
                max_input_tokens=30_976,
            )
        ],
        deployment_name="gpt-5",
    )
    model_map = {
        "azure/gpt-5": {
            "max_input_tokens": 272_000,
            "max_output_tokens": 128_000,
        }
    }

    with (
        patch.object(llm_config, "ONYX_SERVER_URL", "https://onyx.test"),
        patch.object(model_catalog, "get_model_map", return_value=model_map),
    ):
        gateway_config = llm_config.build_onyx_gateway_config([provider])

    assert gateway_config is not None
    opencode_config = build_provider_opencode_config(gateway_config)
    assert opencode_config["provider"]["onyx"]["models"]["300/GPT-5.6-SOL"][
        "limit"
    ] == {
        "context": 272_000,
        "input": 272_000,
        "output": 128_000,
    }


def test_gateway_config_preserves_explicit_context_override() -> None:
    provider = _provider(
        300,
        "azure",
        [
            _model(
                "Customer Alias",
                max_input_tokens=30_976,
                configured_max_input_tokens=200_000,
            )
        ],
        deployment_name="gpt-5",
    )
    model_map = {
        "azure/gpt-5": {
            "max_input_tokens": 272_000,
            "max_output_tokens": 128_000,
        }
    }

    with (
        patch.object(llm_config, "ONYX_SERVER_URL", "https://onyx.test"),
        patch.object(model_catalog, "get_model_map", return_value=model_map),
    ):
        gateway_config = llm_config.build_onyx_gateway_config([provider])

    assert gateway_config is not None
    opencode_config = build_provider_opencode_config(gateway_config)
    assert opencode_config["provider"]["onyx"]["models"]["300/Customer Alias"][
        "limit"
    ] == {
        "context": 200_000,
        "input": 200_000,
        "output": 128_000,
    }


def test_unknown_model_omits_unverified_token_limits() -> None:
    provider = _provider(
        7,
        "custom",
        [_model("unknown-model", max_input_tokens=30_976)],
    )

    with (
        patch.object(llm_config, "ONYX_SERVER_URL", "https://onyx.test"),
        patch.object(model_catalog, "get_model_map", return_value={}),
    ):
        gateway_config = llm_config.build_onyx_gateway_config([provider])

    assert gateway_config is not None
    opencode_config = build_provider_opencode_config(gateway_config)
    model_config = opencode_config["provider"]["onyx"]["models"]["7/unknown-model"]
    assert "limit" not in model_config


def test_small_input_override_does_not_reduce_provider_output() -> None:
    provider = _provider(
        7,
        "azure",
        [
            _model(
                "tiny-model",
                configured_max_input_tokens=25_000,
            )
        ],
        deployment_name="gpt-5",
    )
    model_map = {
        "azure/gpt-5": {
            "max_input_tokens": 272_000,
            "max_output_tokens": 128_000,
        }
    }

    with (
        patch.object(llm_config, "ONYX_SERVER_URL", "https://onyx.test"),
        patch.object(model_catalog, "get_model_map", return_value=model_map),
    ):
        gateway_config = llm_config.build_onyx_gateway_config([provider])

    assert gateway_config is not None
    opencode_config = build_provider_opencode_config(gateway_config)
    assert opencode_config["provider"]["onyx"]["models"]["7/tiny-model"]["limit"] == {
        "context": 25_000,
        "input": 25_000,
        "output": 128_000,
    }


def test_gateway_selection_renders_storage_columns() -> None:
    assert llm_config.GatewaySelection(17, "anthropic/claude-sonnet").to_columns() == (
        "onyx",
        "17/anthropic/claude-sonnet",
    )


def test_manager_prefers_provider_recommended_default_in_provider_order() -> None:
    anthropic = _provider(
        3,
        "anthropic",
        [_model("claude-sonnet"), _model("claude-opus-5")],
        name="Zulu provider",
    )
    bedrock = _provider(
        7,
        "bedrock",
        [_model("bedrock-lite"), _model("bedrock-pro")],
        name="Alpha provider",
    )
    manager = SessionManager.__new__(SessionManager)
    manager._db_session = cast(Session, MagicMock(spec=Session))
    user = cast(User, MagicMock(spec=User))

    with (
        patch.object(llm_config, "ONYX_SERVER_URL", "https://onyx.test"),
        patch.object(
            manager_module,
            "fetch_all_accessible_llm_providers",
            return_value=[anthropic, bedrock],
        ) as fetch_providers,
    ):
        config = manager.build_llm_configs(user)

    # "Alpha provider" (bedrock) sorts before "Zulu provider"; its recommended
    # default (bedrock-pro) wins over the alphabetically-first visible model.
    assert config.provider == "onyx"
    assert config.model_name == "7/bedrock-pro"
    fetch_providers.assert_called_once_with(manager._db_session, user)


def _gateway_config() -> CraftLLMProviderConfig:
    return CraftLLMProviderConfig(
        provider="onyx",
        model_name="13/gpt-5-mini",
        api_key="proxy-placeholder",
        api_base="https://onyx.test/gateway/v1",
        models=[
            GatewayModelDescriptor(
                id="13/gpt-5-mini",
                display_name="GPT-5 Mini",
                provider="openai",
            )
        ],
    )


def test_gateway_config_falls_back_when_requested_selection_is_stale() -> None:
    provider = _provider(2, "anthropic", [_model("claude-fable-5")])

    with patch.object(llm_config, "ONYX_SERVER_URL", "https://onyx.test"):
        config = llm_config.build_onyx_gateway_config(
            [provider],
            llm_config.GatewaySelection(99, "deleted-model"),
        )

    assert config is not None
    assert config.model_name == "2/claude-fable-5"


def _reconcile_manager(
    config: CraftLLMProviderConfig,
) -> tuple[SessionManager, MagicMock, MagicMock]:
    """(manager, sandbox_manager mock, build_llm_configs mock) — the mocks are
    returned as plain MagicMocks so assertions don't go through the typed
    SessionManager attributes."""
    manager = SessionManager.__new__(SessionManager)
    sandbox_manager = MagicMock()
    build_llm_configs = MagicMock(return_value=config)
    manager._db_session = cast(Session, MagicMock(spec=Session))
    manager._sandbox_manager = sandbox_manager
    manager.build_llm_configs = build_llm_configs
    return manager, sandbox_manager, build_llm_configs


def _fresh_session() -> BuildSession:
    return cast(
        BuildSession,
        MagicMock(id=2, agent_provider=None, agent_model=None),
    )


def test_empty_gateway_session_skips_unchanged_catalog() -> None:
    config = _gateway_config()
    manager, sandbox_manager, build_llm_configs = _reconcile_manager(config)
    expected = json.dumps(
        build_provider_opencode_config(config, disabled_tools=OPENCODE_DISABLED_TOOLS)
    )
    assert expected is not None
    sandbox_manager.read_file.return_value = expected.encode()

    cache = MagicMock()
    cache.get.return_value = None
    with patch.object(manager_module, "get_cache_backend", return_value=cache):
        manager.reconcile_session_llm_config(
            cast(Sandbox, MagicMock(id=1)),
            _fresh_session(),
            cast(User, MagicMock(spec=User)),
        )

    sandbox_manager.regenerate_session_config.assert_not_called()
    sandbox_manager.dispose_opencode_instance.assert_not_called()


def test_unchanged_catalog_retries_pending_dispose() -> None:
    """A matching config file does not prove the running instance reloaded it:
    when a prior reconcile wrote the file but failed the dispose, the pending
    marker must force a dispose retry on the next reconcile."""
    config = _gateway_config()
    manager, sandbox_manager, build_llm_configs = _reconcile_manager(config)
    expected = json.dumps(
        build_provider_opencode_config(config, disabled_tools=OPENCODE_DISABLED_TOOLS)
    )
    assert expected is not None
    sandbox_manager.read_file.return_value = expected.encode()
    session = cast(
        BuildSession,
        MagicMock(
            id=2,
            agent_provider=None,
            agent_model=None,
            opencode_session_id="ses-live",
        ),
    )
    sandbox = cast(Sandbox, MagicMock(id=1))

    cache = MagicMock()
    cache.get.return_value = b"1"
    with patch.object(manager_module, "get_cache_backend", return_value=cache):
        manager.reconcile_session_llm_config(
            sandbox, session, cast(User, MagicMock(spec=User))
        )

    sandbox_manager.dispose_opencode_instance.assert_called_once_with(
        sandbox.id, session.id
    )
    cache.delete.assert_called_once()


def test_reconcile_regenerates_when_config_read_fails_transiently() -> None:
    """A transient exec/API failure while checking the config must not fail
    the turn; the reconcile regenerates defensively."""
    config = _gateway_config()
    manager, sandbox_manager, build_llm_configs = _reconcile_manager(config)
    sandbox_manager.read_file.side_effect = RuntimeError("exec blip")

    cache = MagicMock()
    cache.get.return_value = None
    with patch.object(manager_module, "get_cache_backend", return_value=cache):
        manager.reconcile_session_llm_config(
            cast(Sandbox, MagicMock(id=1)),
            _fresh_session(),
            cast(User, MagicMock(spec=User)),
        )

    sandbox_manager.regenerate_session_config.assert_called_once()


def test_reconcile_parses_stored_gateway_selection() -> None:
    """The persisted "<provider_id>/<model_name>" selection must round-trip
    through the parse — including model names that themselves contain
    slashes."""
    config = _gateway_config()
    manager, sandbox_manager, build_llm_configs = _reconcile_manager(config)
    sandbox_manager.read_file.side_effect = ValueError("no file")
    session = cast(
        BuildSession,
        MagicMock(
            id=2,
            agent_provider="onyx",
            agent_model="17/anthropic/claude-sonnet",
            opencode_session_id=None,
        ),
    )

    cache = MagicMock()
    cache.get.return_value = None
    with (
        patch.object(manager_module, "get_cache_backend", return_value=cache),
        patch.object(manager_module, "get_connectable_apps_for_user", return_value=[]),
    ):
        manager.reconcile_session_llm_config(
            cast(Sandbox, MagicMock(id=1)), session, cast(User, MagicMock(spec=User))
        )

    assert build_llm_configs.call_args.args[1] == llm_config.GatewaySelection(
        17, "anthropic/claude-sonnet"
    )


def test_reconcile_forwards_legacy_provider_selection() -> None:
    """Sessions persisted before the gateway (agent_provider="anthropic")
    must resolve by provider type, not the gateway parse."""
    config = _gateway_config()
    manager, sandbox_manager, build_llm_configs = _reconcile_manager(config)
    sandbox_manager.read_file.side_effect = ValueError("no file")
    session = cast(
        BuildSession,
        MagicMock(
            id=2,
            agent_provider="anthropic",
            agent_model="claude-fable-5",
            opencode_session_id=None,
        ),
    )

    cache = MagicMock()
    cache.get.return_value = None
    with (
        patch.object(manager_module, "get_cache_backend", return_value=cache),
        patch.object(manager_module, "get_connectable_apps_for_user", return_value=[]),
    ):
        manager.reconcile_session_llm_config(
            cast(Sandbox, MagicMock(id=1)), session, cast(User, MagicMock(spec=User))
        )

    assert build_llm_configs.call_args.args[1] == llm_config.LegacySelection(
        "anthropic", "claude-fable-5"
    )


def test_empty_gateway_session_restarts_instance_for_changed_catalog() -> None:
    config = _gateway_config()
    manager, sandbox_manager, build_llm_configs = _reconcile_manager(config)
    sandbox_manager.read_file.return_value = b"stale"
    sandbox = cast(Sandbox, MagicMock(id=1))
    session = cast(
        BuildSession,
        MagicMock(
            id=2,
            agent_provider=None,
            agent_model=None,
            opencode_session_id="ses-old",
            nextjs_port=3010,
        ),
    )
    user = cast(User, MagicMock(spec=User, personal_name="Roshan"))

    cache = MagicMock()
    cache.get.return_value = None
    with (
        patch.object(manager_module, "get_cache_backend", return_value=cache),
        patch.object(manager_module, "get_connectable_apps_for_user", return_value=[]),
    ):
        manager.reconcile_session_llm_config(sandbox, session, user)

    sandbox_manager.regenerate_session_config.assert_called_once()
    sandbox_manager.dispose_opencode_instance.assert_called_once_with(
        sandbox.id, session.id
    )
    cache.set.assert_called_once()
    cache.delete.assert_called_once()


def test_workspace_rebuild_claims_a_dispose_the_next_reconcile_honours() -> None:
    """Restoring a session rewrites opencode.json but cannot dispose the
    running instance itself; it claims the dispose and the next turn performs it.

    Both halves go through the real cache key on purpose. The failure this pins
    is silent: the rebuilt file matches what reconcile would write, so reconcile
    short-circuits, the instance keeps the catalog it started with, and the
    first turn after a wake dies with "model not found" while the config on
    disk looks perfect.
    """
    config = _gateway_config()
    manager, sandbox_manager, _ = _reconcile_manager(config)
    expected = json.dumps(
        build_provider_opencode_config(config, disabled_tools=OPENCODE_DISABLED_TOOLS)
    )
    # Exactly the post-rebuild state: file already correct on disk.
    sandbox_manager.read_file.return_value = expected.encode()

    store: dict[str, str] = {}
    cache = MagicMock()
    cache.set.side_effect = lambda key, value, ex=None: store.__setitem__(  # noqa: ARG005
        key, value
    )
    cache.get.side_effect = store.get
    cache.delete.side_effect = lambda key: store.pop(key, None)

    session = cast(
        BuildSession,
        MagicMock(
            id=2,
            agent_provider=None,
            agent_model=None,
            opencode_session_id="ses_restored",
        ),
    )

    with patch.object(manager_module, "get_cache_backend", return_value=cache):
        # What the restore path does after rebuilding the workspace.
        manager_module.mark_opencode_dispose_pending(session.id)
        assert store, "the claim must be recorded before the next turn runs"

        manager.reconcile_session_llm_config(
            cast(Sandbox, MagicMock(id=1)),
            session,
            cast(User, MagicMock(spec=User)),
        )

    sandbox_manager.dispose_opencode_instance.assert_called_once()
    assert store == {}, "the claim must be cleared once the dispose succeeded"
