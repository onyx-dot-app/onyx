"""Unit tests for ``get_all_build_mode_llm_configs``.

Covers the sandbox-provisioning helper that builds the list of LLM
providers baked into ``OPENCODE_CONFIG_CONTENT``. Bugs here surface as
"Model not found: <provider>/<model>" errors at agent invocation time
because per-prompt overrides can only target providers that were
pre-registered when the pod was created.
"""

from __future__ import annotations

import inspect
from typing import Any
from typing import cast
from unittest.mock import patch

from sqlalchemy.orm import Session

from onyx.server.features.build.api import sessions_api
from onyx.server.features.build.sandbox.models import LLMProviderConfig
from onyx.server.features.build.session.manager import get_all_build_mode_llm_configs
from onyx.server.features.build.session.manager import SessionManager
from onyx.server.manage.llm.models import LLMProviderView
from onyx.server.manage.llm.models import ModelConfigurationView


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
    """Invoke under a patched ``fetch_all_build_mode_llm_providers``."""
    with patch(
        "onyx.server.features.build.session.manager.fetch_all_build_mode_llm_providers",
        return_value=rows,
    ):
        # db_session is unused once the fetch is patched.
        return get_all_build_mode_llm_configs(
            db_session=cast(Session, None),
            default=_OPENAI_DEFAULT,
        )


class TestGetAllBuildModeLlmConfigs:
    def test_default_only_when_no_build_mode_rows(self) -> None:
        configs = _run([])
        assert configs == [_OPENAI_DEFAULT]

    def test_includes_build_mode_provider_with_visible_model(self) -> None:
        configs = _run(
            [
                _provider(
                    name="build-mode-anthropic",
                    provider="anthropic",
                    models=[_model("claude-opus-4-7")],
                    api_key="k-anthropic",
                )
            ]
        )
        assert [(c.provider, c.model_name) for c in configs] == [
            ("openai", "gpt-4o"),
            ("anthropic", "claude-opus-4-7"),
        ]
        assert configs[1].api_key == "k-anthropic"

    def test_skips_build_mode_provider_with_no_visible_models(self) -> None:
        configs = _run(
            [
                _provider(
                    name="build-mode-anthropic",
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
                    name="build-mode-anthropic",
                    provider="anthropic",
                    models=[],
                )
            ]
        )
        assert configs == [_OPENAI_DEFAULT]

    def test_picks_first_visible_model_when_multiple_visible(self) -> None:
        configs = _run(
            [
                _provider(
                    name="build-mode-anthropic",
                    provider="anthropic",
                    models=[
                        _model("claude-opus-4-6"),
                        _model("claude-opus-4-7"),
                        _model("claude-sonnet-4-6"),
                    ],
                )
            ]
        )
        assert configs[1].model_name == "claude-opus-4-6"

    def test_skips_hidden_models_when_picking_first(self) -> None:
        configs = _run(
            [
                _provider(
                    name="build-mode-anthropic",
                    provider="anthropic",
                    models=[
                        _model("claude-hidden-1", is_visible=False),
                        _model("claude-opus-4-7"),
                    ],
                )
            ]
        )
        assert configs[1].model_name == "claude-opus-4-7"

    def test_dedupes_when_default_provider_also_in_build_mode_rows(self) -> None:
        """If the default's provider type is also tagged as build-mode, we
        keep the default (with its real config) and skip the duplicate."""
        configs = _run(
            [
                _provider(
                    name="build-mode-openai",
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
                    name="build-mode-anthropic",
                    provider="anthropic",
                    models=[_model("claude-opus-4-7")],
                ),
                _provider(
                    name="build-mode-google",
                    provider="google",
                    models=[_model("gemini-2.5-pro")],
                ),
            ]
        )
        assert [(c.provider, c.model_name) for c in configs] == [
            ("openai", "gpt-4o"),
            ("anthropic", "claude-opus-4-7"),
            ("google", "gemini-2.5-pro"),
        ]

    def test_default_provider_preserved_first(self) -> None:
        """Default always stays at index 0 regardless of fetched-row order."""
        configs = _run(
            [
                _provider(
                    name="build-mode-anthropic",
                    provider="anthropic",
                    models=[_model("claude-opus-4-7")],
                )
            ]
        )
        assert configs[0] == _OPENAI_DEFAULT


class TestProvisionCallsitesPassAllLlmConfigs:
    """Both ``sandbox_manager.provision()`` callsites must pass
    ``all_llm_configs`` — bypassing it causes the multi-provider
    config to collapse to ``[default]`` and per-prompt overrides fail.
    Guards against the regression that motivated this helper.
    """

    def test_session_manager_provision_passes_all_llm_configs(self) -> None:
        source = _get_source(SessionManager._provision_sandbox)
        assert "all_llm_configs=" in source, (
            "_provision_sandbox must forward all_llm_configs to "
            "sandbox_manager.provision()"
        )
        assert "get_all_build_mode_llm_configs" in source, (
            "_provision_sandbox must build all_llm_configs via "
            "get_all_build_mode_llm_configs"
        )

    def test_restore_session_passes_all_llm_configs(self) -> None:
        source = _get_source(sessions_api.restore_session)
        assert "all_llm_configs=" in source, (
            "restore_session must forward all_llm_configs when calling "
            "sandbox_manager.provision() on a sleeping/terminated pod"
        )
        assert "get_all_build_mode_llm_configs" in source, (
            "restore_session must build all_llm_configs via "
            "get_all_build_mode_llm_configs"
        )


def _get_source(fn: Any) -> str:
    return inspect.getsource(fn)
