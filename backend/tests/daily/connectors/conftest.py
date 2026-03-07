from collections.abc import Generator
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest


@pytest.fixture
def mock_get_unstructured_api_key() -> Generator[MagicMock, None, None]:
    with patch(
        "onyx.file_processing.extract_file_text.get_unstructured_api_key",
        return_value=None,
    ) as mock:
        yield mock
