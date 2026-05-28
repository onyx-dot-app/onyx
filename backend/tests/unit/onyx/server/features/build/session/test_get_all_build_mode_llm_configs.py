"""Unit tests for ``get_all_build_mode_llm_configs``.

Covers the sandbox-provisioning helper that builds the list of LLM
providers baked into ``OPENCODE_CONFIG_CONTENT``. Bugs here surface as
"Model not found: <provider>/<model>" errors at agent invocation time
because per-prompt overrides can only target providers that were
pre-registered when the pod was created.

Build mode is provider-agnostic: any LLM provider in the DB is eligible,
no naming convention required.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import cast
from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy.orm import Session

from onyx.db.enums import SandboxStatus
from onyx.db.models import Sandbox
from onyx.db.models import User
from onyx.server.features.build.sandbox.models import LLMProviderConfig
from onyx.server.features.build.sandbox.models import SandboxInfo
from onyx.server.features.build.session.manager import get_all_build_mode_llm_configs
from onyx.server.features.build.session.manager import SessionManager


@dataclass
class _FakeModelConfig:
    name: str
    is_visible: bool = True


class _FakeEncryptedApiKey:
    def __init__(self, value: str | None) -> None:
        self._value = value

    def get_value(self, apply_mask: bool = True) -> str | None:  # noqa: ARG002
        return self._value

    def __bool__(self) -> bool:
        return self._value is not None


@dataclass
class _FakeProvider:
    """Stand-in for ``LLMProviderModel`` — only the attributes
    ``get_all_build_mode_llm_configs`` reads."""

    provider: str
    model_configurations: list[_FakeModelConfig]
    api_key: _FakeEncryptedApiKey
    api_base: str | None = None


def _model(name: str, is_visible: bool = True) -> _FakeModelConfig:
    return _FakeModelConfig(name=name, is_visible=is_visible)


def _provider(
    *,
    provider: str,
    models: list[_FakeModelConfig],
    api_key: str | None = "k",
    api_base: str | None = None,
) -> _FakeProvider:
    return _FakeProvider(
        provider=provider,
        model_configurations=models,
        api_key=_FakeEncryptedApiKey(api_key),
        api_base=api_base,
    )


_OPENAI_DEFAULT = LLMProviderConfig(
    provider="openai",
    model_name="gpt-4o",
    api_key="k-openai",
    api_base=None,
)


def _run(rows: list[_FakeProvider]) -> list[LLMProviderConfig]:
    """Invoke under a patched ``fetch_existing_llm_providers``."""
    with patch(
        "onyx.server.features.build.session.manager.fetch_existing_llm_providers",
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
        """If a fetched provider has the same type as the default, we keep
        the default (with its real config) and skip the duplicate."""
        configs = _run(
            [
                _provider(
                    provider="openai",
                    models=[_model("gpt-4o-mini")],
                    api_key="k-build-openai",
                )
            ]
        )
        assert configs == [_OPENAI_DEFAULT]
        # The default's api_key wins; we never overwrite with the fetched row's.
        assert configs[0].api_key == "k-openai"

    def test_multiple_distinct_build_mode_providers(self) -> None:
        configs = _run(
            [
                _provider(
                    provider="anthropic",
                    models=[_model("claude-opus-4-7")],
                ),
                _provider(
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
                    provider="anthropic",
                    models=[_model("claude-opus-4-7")],
                )
            ]
        )
        assert configs[0] == _OPENAI_DEFAULT


class TestSessionManagerProvisionForwardsAllLlmConfigs:
    """``SessionManager._provision_sandbox`` must forward the full
    multi-provider list to ``sandbox_manager.provision()`` — passing only
    the default collapses ``opencode.json`` and per-prompt model
    overrides start failing with "Model not found" until pod restart.
    """

    def test_provision_passes_all_llm_configs(self) -> None:
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

        manager = SessionManager.__new__(SessionManager)
        manager._db_session = cast(Session, MagicMock())  # type: ignore[attr-defined]
        manager._sandbox_manager = sandbox_manager  # type: ignore[attr-defined]

        expected_configs = [
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
                "onyx.server.features.build.session.manager.ensure_sandbox_pat",
                return_value="pat-token",
            ),
            patch(
                "onyx.server.features.build.session.manager.get_all_build_mode_llm_configs",
                return_value=expected_configs,
            ) as mock_get_all_configs,
            patch(
                "onyx.server.features.build.session.manager.update_sandbox_status__no_commit"
            ),
        ):
            manager._provision_sandbox(
                sandbox=sandbox,
                user=user,
                user_id=user_id,
                tenant_id=tenant_id,
                llm_config=_OPENAI_DEFAULT,
            )

        mock_get_all_configs.assert_called_once()
        sandbox_manager.provision.assert_called_once()
        kwargs = sandbox_manager.provision.call_args.kwargs
        assert kwargs["all_llm_configs"] == expected_configs
        assert kwargs["llm_config"] == _OPENAI_DEFAULT
        assert kwargs["sandbox_id"] == sandbox_id
        assert kwargs["onyx_pat"] == "pat-token"
