"""Unit tests for ``get_all_build_mode_llm_configs``.

Covers the sandbox-provisioning helper that builds the list of LLM
providers baked into ``OPENCODE_CONFIG_CONTENT``. Bugs here surface as
"Model not found: <provider>/<model>" errors at agent invocation time
because per-prompt overrides can only target providers that were
pre-registered when the pod was created.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager
from datetime import datetime
from typing import cast
from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import SandboxStatus
from onyx.db.models import Sandbox
from onyx.db.models import User
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.build.sandbox.models import LLMProviderConfig
from onyx.server.features.build.sandbox.models import SandboxInfo
from onyx.server.features.build.session.llm_config import get_all_build_mode_llm_configs
from onyx.server.features.build.session.manager import SessionManager
from onyx.server.manage.llm.models import LLMProviderView
from onyx.server.manage.llm.models import ModelConfigurationView

# The recommended default model per provider type is sourced from the shared
# recommended-models config (GitHub-or-bundled) at runtime. Stub it here so
# these unit tests are deterministic and don't hit the network.
_TEST_RECOMMENDED_BY_TYPE = {
    "anthropic": "claude-opus-4-8",
    "openai": "gpt-5.5",
    "openrouter": "minimax/minimax-m3",
}


@pytest.fixture(autouse=True)
def _stub_recommended_default() -> Iterator[None]:
    with patch(
        "onyx.server.features.build.session.llm_config."
        "fetch_default_model_for_provider",
        side_effect=lambda provider_name: _TEST_RECOMMENDED_BY_TYPE.get(provider_name),
    ):
        yield


def _model(name: str, is_visible: bool = True) -> ModelConfigurationView:
    return ModelConfigurationView(
        name=name,
        is_visible=is_visible,
        supports_image_input=False,
    )


def _provider(
    *,
    name: str,
    provider: str,
    models: list[ModelConfigurationView],
    api_key: str | None = "k",
    api_base: str | None = None,
) -> LLMProviderView:
    return LLMProviderView(
        id=1,
        name=name,
        provider=provider,
        api_key=api_key,
        api_base=api_base,
        model_configurations=models,
    )


_OPENAI_DEFAULT = LLMProviderConfig(
    provider="openai",
    model_name="gpt-4o",
    api_key="k-openai",
    api_base=None,
)


def _run(rows: list[LLMProviderView]) -> list[LLMProviderConfig]:
    """``get_all_build_mode_llm_configs`` is pure over an already-fetched list."""
    return get_all_build_mode_llm_configs(rows, _OPENAI_DEFAULT)


class TestGetAllBuildModeLlmConfigs:
    def test_default_only_when_no_build_mode_rows(self) -> None:
        configs = _run([])
        assert configs == [_OPENAI_DEFAULT]

    def test_includes_build_mode_provider_with_visible_model(self) -> None:
        configs = _run(
            [
                _provider(
                    name="Anthropic",
                    provider="anthropic",
                    models=[_model("claude-opus-4-8")],
                    api_key="k-anthropic",
                )
            ]
        )
        assert [(c.provider, c.model_name) for c in configs] == [
            ("openai", "gpt-4o"),
            ("anthropic", "claude-opus-4-8"),
        ]
        assert configs[1].api_key == "k-anthropic"

    def test_skips_build_mode_provider_with_no_visible_models(self) -> None:
        configs = _run(
            [
                _provider(
                    name="Anthropic",
                    provider="anthropic",
                    models=[_model("claude-hidden", is_visible=False)],
                )
            ]
        )
        assert configs == [_OPENAI_DEFAULT]

    def test_skips_build_mode_provider_with_empty_model_list(self) -> None:
        configs = _run(
            [
                _provider(
                    name="Anthropic",
                    provider="anthropic",
                    models=[],
                )
            ]
        )
        assert configs == [_OPENAI_DEFAULT]

    def test_prefers_recommended_model_over_first_visible(self) -> None:
        # Anthropic's recommended model wins even though it isn't first in the list.
        configs = _run(
            [
                _provider(
                    name="Anthropic",
                    provider="anthropic",
                    models=[
                        _model("claude-opus-4-6"),
                        _model("claude-opus-4-8"),
                        _model("claude-sonnet-4-6"),
                    ],
                )
            ]
        )
        assert configs[1].model_name == "claude-opus-4-8"

    def test_uses_first_visible_for_type_without_recommended(self) -> None:
        # A provider type with no recommended-model entry falls back to first visible.
        configs = _run(
            [
                _provider(
                    name="Google",
                    provider="google",
                    models=[_model("gemini-2.5-pro"), _model("gemini-2.5-flash")],
                )
            ]
        )
        assert configs[1].model_name == "gemini-2.5-pro"

    def test_skips_hidden_models_when_picking_first(self) -> None:
        # A provider type without a recommended-model entry falls back to the
        # first *visible* model, skipping hidden ones.
        configs = _run(
            [
                _provider(
                    name="Google",
                    provider="google",
                    models=[
                        _model("gemini-hidden", is_visible=False),
                        _model("gemini-2.5-pro"),
                    ],
                )
            ]
        )
        assert configs[1].model_name == "gemini-2.5-pro"

    def test_dedupes_when_default_provider_also_in_build_mode_rows(self) -> None:
        """If the default's provider type is also tagged as build-mode, we
        keep the default (with its real config) and skip the duplicate."""
        configs = _run(
            [
                _provider(
                    name="OpenAI",
                    provider="openai",
                    models=[_model("gpt-4o-mini")],
                    api_key="k-build-openai",
                )
            ]
        )
        assert configs == [_OPENAI_DEFAULT]
        # The default's api_key wins; we never overwrite with the build-mode row's.
        assert configs[0].api_key == "k-openai"

    def test_multiple_distinct_build_mode_providers(self) -> None:
        configs = _run(
            [
                _provider(
                    name="Anthropic",
                    provider="anthropic",
                    models=[_model("claude-opus-4-8")],
                ),
                _provider(
                    name="Google",
                    provider="google",
                    models=[_model("gemini-2.5-pro")],
                ),
            ]
        )
        assert [(c.provider, c.model_name) for c in configs] == [
            ("openai", "gpt-4o"),
            ("anthropic", "claude-opus-4-8"),
            ("google", "gemini-2.5-pro"),
        ]

    def test_default_provider_preserved_first(self) -> None:
        """Default always stays at index 0 regardless of fetched-row order."""
        configs = _run(
            [
                _provider(
                    name="Anthropic",
                    provider="anthropic",
                    models=[_model("claude-opus-4-7")],
                )
            ]
        )
        assert configs[0] == _OPENAI_DEFAULT


class TestGetLlmConfigFallback:
    """``SessionManager.build_llm_configs(user)[0]`` (the default config)
    resolves to the highest-priority accessible provider of a supported type
    (anthropic > openai > openrouter), using that provider's first visible
    model."""

    @staticmethod
    def _manager() -> SessionManager:
        manager = SessionManager.__new__(SessionManager)
        manager._db_session = cast(Session, MagicMock())  # type: ignore[attr-defined]
        return manager

    @staticmethod
    def _user() -> User:
        return cast(User, MagicMock())

    @staticmethod
    def _patch_providers(
        providers: list[LLMProviderView],
    ) -> AbstractContextManager[MagicMock]:
        return patch(
            "onyx.server.features.build.session.manager."
            "fetch_all_supported_build_llm_providers",
            return_value=providers,
        )

    def test_uses_highest_priority_provider_first_visible_model(self) -> None:
        provider = _provider(
            name="Anthropic",
            provider="anthropic",
            models=[_model("claude-opus-4-8")],
            api_key="k-anthropic",
        )
        with self._patch_providers([provider]):
            config = self._manager().build_llm_configs(self._user(), None, None)[0]
        assert (config.provider, config.model_name) == (
            "anthropic",
            "claude-opus-4-8",
        )
        assert config.api_key == "k-anthropic"

    def test_type_priority_anthropic_over_openai(self) -> None:
        with self._patch_providers(
            [
                _provider(name="o", provider="openai", models=[_model("gpt-5.5")]),
                _provider(
                    name="a",
                    provider="anthropic",
                    models=[_model("claude-opus-4-7")],
                ),
            ]
        ):
            config = self._manager().build_llm_configs(self._user(), None, None)[0]
        assert config.provider == "anthropic"

    def test_ignores_unsupported_provider_type(self) -> None:
        # An azure provider is not a supported type -> treated as none.
        with self._patch_providers(
            [_provider(name="az", provider="azure", models=[_model("gpt-5.5")])]
        ):
            try:
                self._manager().build_llm_configs(self._user(), None, None)
            except OnyxError as e:
                assert e.status_code == 400
            else:
                raise AssertionError("expected OnyxError")

    def test_skips_provider_without_visible_model(self) -> None:
        with self._patch_providers(
            [
                _provider(
                    name="a",
                    provider="anthropic",
                    models=[_model("claude-opus-4-7", is_visible=False)],
                ),
                _provider(name="o", provider="openai", models=[_model("gpt-5.5")]),
            ]
        ):
            config = self._manager().build_llm_configs(self._user(), None, None)[0]
        assert (config.provider, config.model_name) == ("openai", "gpt-5.5")

    def test_raises_onyx_error_when_no_supported_provider(self) -> None:
        with self._patch_providers([]):
            try:
                self._manager().build_llm_configs(self._user(), None, None)
            except OnyxError as e:
                assert e.status_code == 400
            else:
                raise AssertionError("expected OnyxError")

    def test_requested_provider_and_model_used_verbatim(self) -> None:
        # The interactive path supplies the model via cookie; honor it as-is
        # (even a model not marked visible) as long as the type is accessible.
        provider = _provider(
            name="Anthropic",
            provider="anthropic",
            models=[_model("claude-opus-4-7")],
            api_key="k-anthropic",
        )
        with self._patch_providers([provider]):
            config = self._manager().build_llm_configs(
                self._user(), "anthropic", "claude-sonnet-4-6"
            )[0]
        assert (config.provider, config.model_name) == (
            "anthropic",
            "claude-sonnet-4-6",
        )

    def test_requested_unsupported_type_falls_back(self) -> None:
        # A stale cookie pointing at a non-supported type is ignored; we fall
        # back to the highest-priority accessible supported provider.
        with self._patch_providers(
            [
                _provider(
                    name="a", provider="anthropic", models=[_model("claude-opus-4-8")]
                )
            ]
        ):
            config = self._manager().build_llm_configs(
                self._user(), "azure", "some-azure-model"
            )[0]
        assert (config.provider, config.model_name) == (
            "anthropic",
            "claude-opus-4-8",
        )


class TestProvisionSandboxForwardsAllLlmConfigs:
    """``sandbox_lifecycle.provision_sandbox`` must forward the full
    multi-provider list to ``sandbox_manager.provision()`` — passing only
    the default collapses ``opencode.json`` and per-prompt model
    overrides start failing with "Model not found" until pod restart.
    """

    def test_provision_passes_all_llm_configs(self) -> None:
        from onyx.server.features.build.session.sandbox_lifecycle import (
            provision_sandbox,
        )

        sandbox_id = uuid4()
        user_id = uuid4()
        tenant_id = "tenant-x"

        sandbox = MagicMock(spec=Sandbox)
        sandbox.id = sandbox_id
        user = MagicMock(spec=User)

        sandbox_manager = MagicMock()
        sandbox_manager.provision.return_value = SandboxInfo(
            sandbox_id=sandbox_id,
            directory_path="/workspace/sessions",
            status=SandboxStatus.RUNNING,
            last_heartbeat=datetime.now(),
        )

        all_configs = [
            _OPENAI_DEFAULT,
            LLMProviderConfig(
                provider="anthropic",
                model_name="claude-opus-4-7",
                api_key="k-anthropic",
                api_base=None,
            ),
        ]

        with (
            patch(
                "onyx.server.features.build.session.sandbox_lifecycle."
                "ensure_sandbox_pat",
                return_value="pat-token",
            ),
            patch(
                "onyx.server.features.build.session.sandbox_lifecycle."
                "update_sandbox_status__no_commit"
            ),
        ):
            provision_sandbox(
                db_session=cast(Session, MagicMock()),
                sandbox_manager=sandbox_manager,
                sandbox=sandbox,
                user=user,
                user_id=user_id,
                tenant_id=tenant_id,
                all_llm_configs=all_configs,
            )

        sandbox_manager.provision.assert_called_once()
        kwargs = sandbox_manager.provision.call_args.kwargs
        assert kwargs["all_llm_configs"] == all_configs
        # default model is the first entry
        assert kwargs["llm_config"] == _OPENAI_DEFAULT
        assert kwargs["sandbox_id"] == sandbox_id
        assert kwargs["onyx_pat"] == "pat-token"
