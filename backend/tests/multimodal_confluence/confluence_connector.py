from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from danswer.connectors.confluence.connector import ConfluenceConnector

CONFLUENCE_IMAGE_SUMMARIZATION_ENABLED = True


@pytest.mark.parametrize(
    "vision_support_value",
    [
        True,  # Should not raise an error
        # False,  # Should raise a ValueError
        # None    # Should raise a ValueError
    ],
)
@patch("danswer.llm.factory.get_default_llms")
def test_vision_support(mock_get_default_llms, vision_support_value):
    """Test different cases for vision support."""
    mock_llm = MagicMock()
    mock_llm.vision_support.return_value = vision_support_value
    mock_get_default_llms.return_value = (mock_llm, None)

    if vision_support_value:
        confluence_connector = ConfluenceConnector(
            wiki_base="https://example.com",
            is_cloud=True,
        )
        assert confluence_connector is not None  # Ensure the connector is instantiated
    else:  # If vision support is False or None
        with pytest.raises(
            ValueError,
            match="The configured default LLM doesn't seem to have vision support for image summarization.",
        ):
            ConfluenceConnector(
                wiki_base="https://example.com",
                is_cloud=True,
            )
