"""
Unit tests for get_image_processing_llm.

The image processing row is the only source: a row yields that model, no row
yields None. There is no fallback to other vision-capable models.
"""

from unittest.mock import MagicMock, patch

from onyx.llm.factory import get_image_processing_llm

_FACTORY = "onyx.llm.factory"


def _make_settings_row(*, name: str = "gpt-4o", provider: str = "openai") -> MagicMock:
    row = MagicMock()
    row.model_configuration.name = name
    row.model_configuration.llm_provider.provider = provider
    return row


@patch(f"{_FACTORY}.get_session_with_current_tenant")
@patch(f"{_FACTORY}.fetch_image_processing_settings")
@patch(f"{_FACTORY}.llm_from_provider")
@patch(f"{_FACTORY}.LLMProviderView")
@patch(f"{_FACTORY}.logger")
def test_uses_the_configured_model(
    mock_logger: MagicMock,
    mock_provider_view: MagicMock,
    mock_llm_from: MagicMock,
    mock_fetch: MagicMock,
    mock_session: MagicMock,  # noqa: ARG001
) -> None:
    row = _make_settings_row(name="gpt-4o", provider="azure")
    mock_fetch.return_value = row
    headers = {"x-trace": "1"}

    result = get_image_processing_llm(
        timeout=7, temperature=0.2, additional_headers=headers
    )

    assert result is mock_llm_from.return_value
    # The row's own provider is what gets viewed and forwarded, along with
    # the caller's request settings.
    mock_provider_view.from_model.assert_called_once_with(
        row.model_configuration.llm_provider
    )
    kwargs = mock_llm_from.call_args.kwargs
    assert kwargs["model_name"] == "gpt-4o"
    assert kwargs["llm_provider"] is mock_provider_view.from_model.return_value
    assert kwargs["timeout"] == 7
    assert kwargs["temperature"] == 0.2
    assert kwargs["additional_headers"] is headers
    log_msg = mock_logger.info.call_args[0][0]
    assert "image processing model" in log_msg.lower()


@patch(f"{_FACTORY}.get_session_with_current_tenant")
@patch(f"{_FACTORY}.fetch_image_processing_settings", return_value=None)
@patch(f"{_FACTORY}.llm_from_provider")
def test_returns_none_when_off(
    mock_llm_from: MagicMock,
    mock_fetch: MagicMock,  # noqa: ARG001
    mock_session: MagicMock,  # noqa: ARG001
) -> None:
    assert get_image_processing_llm() is None
    mock_llm_from.assert_not_called()
