"""
Unit tests for vision model selection logging in get_default_llm_with_vision.

Verifies that operators get clear feedback about:
1. Which vision model was selected and why
2. When the default vision model doesn't support image input
3. When no vision-capable model exists at all
"""

from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.llm.factory import get_default_llm_with_vision


_FACTORY = "onyx.llm.factory"


def _make_mock_model(
    *,
    name: str = "gpt-4o",
    provider: str = "openai",
    provider_id: int = 1,
    flow_types: list[str] | None = None,
) -> MagicMock:
    model = MagicMock()
    model.name = name
    model.llm_provider_id = provider_id
    model.llm_provider.provider = provider
    model.llm_model_flow_types = flow_types or []
    return model


@patch(f"{_FACTORY}.get_session_with_current_tenant")
@patch(f"{_FACTORY}.fetch_default_vision_model")
@patch(f"{_FACTORY}.model_supports_image_input", return_value=True)
@patch(f"{_FACTORY}.llm_from_provider")
@patch(f"{_FACTORY}.LLMProviderView")
@patch(f"{_FACTORY}.logger")
def test_logs_when_using_default_vision_model(
    mock_logger: MagicMock,
    mock_provider_view: MagicMock,  # noqa: ARG001
    mock_llm_from: MagicMock,  # noqa: ARG001
    mock_supports: MagicMock,  # noqa: ARG001
    mock_fetch_default: MagicMock,
    mock_session: MagicMock,  # noqa: ARG001
) -> None:
    mock_fetch_default.return_value = _make_mock_model(name="gpt-4o", provider="azure")

    get_default_llm_with_vision()

    mock_logger.info.assert_called_once()
    log_msg = mock_logger.info.call_args[0][0]
    assert "default vision model" in log_msg.lower()


@patch(f"{_FACTORY}.get_session_with_current_tenant")
@patch(f"{_FACTORY}.fetch_default_vision_model")
@patch(f"{_FACTORY}.model_supports_image_input", return_value=False)
@patch(f"{_FACTORY}.fetch_existing_models", return_value=[])
@patch(f"{_FACTORY}.logger")
def test_warns_when_default_model_lacks_vision(
    mock_logger: MagicMock,
    mock_fetch_models: MagicMock,  # noqa: ARG001
    mock_supports: MagicMock,  # noqa: ARG001
    mock_fetch_default: MagicMock,
    mock_session: MagicMock,  # noqa: ARG001
) -> None:
    mock_fetch_default.return_value = _make_mock_model(
        name="text-only-model", provider="azure"
    )

    result = get_default_llm_with_vision()

    assert result is None
    # Should have warned about the default model not supporting vision
    warning_calls = [
        call
        for call in mock_logger.warning.call_args_list
        if "does not support" in str(call)
    ]
    assert len(warning_calls) >= 1


@patch(f"{_FACTORY}.get_session_with_current_tenant")
@patch(f"{_FACTORY}.fetch_default_vision_model", return_value=None)
@patch(f"{_FACTORY}.fetch_existing_models", return_value=[])
@patch(f"{_FACTORY}.logger")
def test_warns_when_no_models_exist(
    mock_logger: MagicMock,
    mock_fetch_models: MagicMock,  # noqa: ARG001
    mock_fetch_default: MagicMock,  # noqa: ARG001
    mock_session: MagicMock,  # noqa: ARG001
) -> None:
    result = get_default_llm_with_vision()

    assert result is None
    mock_logger.warning.assert_called_once()
    log_msg = mock_logger.warning.call_args[0][0]
    assert "no llm models" in log_msg.lower()


@patch(f"{_FACTORY}.get_session_with_current_tenant")
@patch(f"{_FACTORY}.fetch_default_vision_model", return_value=None)
@patch(f"{_FACTORY}.fetch_existing_models")
@patch(f"{_FACTORY}.model_supports_image_input", return_value=False)
@patch(f"{_FACTORY}.LLMProviderView")
@patch(f"{_FACTORY}.logger")
def test_warns_when_no_model_supports_vision(
    mock_logger: MagicMock,
    mock_provider_view: MagicMock,  # noqa: ARG001
    mock_supports: MagicMock,  # noqa: ARG001
    mock_fetch_models: MagicMock,
    mock_fetch_default: MagicMock,  # noqa: ARG001
    mock_session: MagicMock,  # noqa: ARG001
) -> None:
    mock_fetch_models.return_value = [
        _make_mock_model(name="text-model-1", provider="openai"),
        _make_mock_model(name="text-model-2", provider="azure", provider_id=2),
    ]

    result = get_default_llm_with_vision()

    assert result is None
    warning_calls = [
        call
        for call in mock_logger.warning.call_args_list
        if "no vision-capable model" in str(call).lower()
    ]
    assert len(warning_calls) == 1
