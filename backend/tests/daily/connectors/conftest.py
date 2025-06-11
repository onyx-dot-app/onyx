from collections.abc import Generator
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.utils.variable_functionality import global_version


@pytest.fixture
def mock_get_unstructured_api_key() -> Generator[MagicMock, None, None]:
    with patch(
        "onyx.file_processing.extract_file_text.get_unstructured_api_key",
        return_value=None,
    ) as mock:
        yield mock


@pytest.fixture
def set_ee_on() -> Generator[None, None, None]:
    """Need EE to be enabled for these tests to work since
    perm syncing is a an EE-only feature."""
    global_version.set_ee()

    yield

    global_version._is_ee = False
