"""Startup warning for a custom self-hosted model that has the exact name of a
registry model but another dimension (added with "Add Custom Model" before the
registry existed)."""

from unittest.mock import MagicMock, patch

import pytest

from onyx.db.enums import IndexModelStatus
from onyx.setup import warn_on_custom_models_with_registry_names
from shared_configs.enums import EmbeddingProvider

_VOYAGE = "voyageai/voyage-4-nano"


def _settings(
    model_name: str,
    model_dim: int,
    provider_type: EmbeddingProvider | None = None,
) -> MagicMock:
    settings = MagicMock()
    settings.id = 7
    settings.status = IndexModelStatus.PRESENT
    settings.model_name = model_name
    settings.model_dim = model_dim
    settings.provider_type = provider_type
    return settings


def test_custom_model_with_registry_name_and_other_dim_is_reported() -> None:
    with patch("onyx.setup.logger") as logger:
        warn_on_custom_models_with_registry_names([_settings(_VOYAGE, 1024), None])

    logger.warning.assert_called_once()
    args = logger.warning.call_args.args
    assert _VOYAGE in args
    assert 1024 in args
    assert 2048 in args


@pytest.mark.parametrize(
    "settings",
    [
        _settings(_VOYAGE, 2048),
        _settings("nomic-ai/nomic-embed-text-v1", 768),
        _settings("my-org/custom-model", 1024),
        _settings("VoyageAI/Voyage-4-Nano", 1024),
        _settings("embed-v5.0-pro", 1024, EmbeddingProvider.COHERE),
    ],
    ids=["registry-dim", "legacy", "custom", "name-variant", "cloud"],
)
def test_other_models_are_not_reported(settings: MagicMock) -> None:
    with patch("onyx.setup.logger") as logger:
        warn_on_custom_models_with_registry_names([settings])

    logger.warning.assert_not_called()
