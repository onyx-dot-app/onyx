"""
Unit tests for get_default_llm_with_vision.

Only the designated default vision model is ever used. With none set, or with
one that cannot take images, captioning is off. There is no fallback scan.
"""

from unittest.mock import MagicMock, patch

from onyx.llm.factory import get_default_llm_with_vision

_FACTORY = "onyx.llm.factory"


def _make_mock_model(
    *,
    name: str = "gpt-4o",
    provider: str = "openai",
    provider_id: int = 1,
) -> MagicMock:
    model = MagicMock()
    model.name = name
    model.llm_provider_id = provider_id
    model.llm_provider.provider = provider
    return model


@patch(f"{_FACTORY}.get_session_with_current_tenant")
@patch(f"{_FACTORY}.fetch_default_vision_model")
@patch(f"{_FACTORY}.model_supports_image_input", return_value=True)
@patch(f"{_FACTORY}.llm_from_provider")
@patch(f"{_FACTORY}.LLMProviderView")
@patch(f"{_FACTORY}.logger")
def test_uses_the_default_vision_model(
    mock_logger: MagicMock,
    mock_provider_view: MagicMock,  # noqa: ARG001
    mock_llm_from: MagicMock,
    mock_supports: MagicMock,  # noqa: ARG001
    mock_fetch_default: MagicMock,
    mock_session: MagicMock,  # noqa: ARG001
) -> None:
    mock_fetch_default.return_value = _make_mock_model(name="gpt-4o", provider="azure")

    result = get_default_llm_with_vision()

    assert result is mock_llm_from.return_value
    mock_logger.info.assert_called_once()
    log_msg = mock_logger.info.call_args[0][0]
    assert "default vision model" in log_msg.lower()


@patch(f"{_FACTORY}.get_session_with_current_tenant")
@patch(f"{_FACTORY}.fetch_default_vision_model")
@patch(f"{_FACTORY}.model_supports_image_input", return_value=False)
@patch(f"{_FACTORY}.llm_from_provider")
@patch(f"{_FACTORY}.logger")
def test_returns_none_when_default_model_lacks_vision(
    mock_logger: MagicMock,
    mock_llm_from: MagicMock,
    mock_supports: MagicMock,  # noqa: ARG001
    mock_fetch_default: MagicMock,
    mock_session: MagicMock,  # noqa: ARG001
) -> None:
    mock_fetch_default.return_value = _make_mock_model(
        name="text-only-model", provider="azure"
    )

    result = get_default_llm_with_vision()

    assert result is None
    mock_llm_from.assert_not_called()
    warning_calls = [
        call
        for call in mock_logger.warning.call_args_list
        if "does not support" in str(call)
    ]
    assert len(warning_calls) == 1


@patch(f"{_FACTORY}.get_session_with_current_tenant")
@patch(f"{_FACTORY}.fetch_default_vision_model", return_value=None)
@patch(f"{_FACTORY}.llm_from_provider")
@patch(f"{_FACTORY}.logger")
def test_returns_none_when_no_default_is_set(
    mock_logger: MagicMock,
    mock_llm_from: MagicMock,
    mock_fetch_default: MagicMock,  # noqa: ARG001
    mock_session: MagicMock,  # noqa: ARG001
) -> None:
    """No default means no captioning. Nothing else is tried."""
    result = get_default_llm_with_vision()

    assert result is None
    mock_llm_from.assert_not_called()
    mock_logger.warning.assert_called_once()
    log_msg = mock_logger.warning.call_args[0][0]
    assert "no default vision model" in log_msg.lower()
