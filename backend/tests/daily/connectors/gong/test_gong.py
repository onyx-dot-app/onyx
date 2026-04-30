import time
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.connectors.gong.connector import GongConnector
from onyx.connectors.models import Document
from tests.utils.secret_names import TestSecret

pytestmark = pytest.mark.secrets(
    TestSecret.GONG_ACCESS_KEY,
    TestSecret.GONG_ACCESS_KEY_SECRET,
)


@pytest.fixture
def gong_connector(
    test_secrets: dict[TestSecret, str],
) -> GongConnector:
    connector = GongConnector()

    connector.load_credentials(
        {
            "gong_access_key": test_secrets[TestSecret.GONG_ACCESS_KEY],
            "gong_access_key_secret": test_secrets[TestSecret.GONG_ACCESS_KEY_SECRET],
        }
    )

    return connector


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_gong_basic(
    mock_get_api_key: MagicMock,  # noqa: ARG001
    gong_connector: GongConnector,
) -> None:
    checkpoint = gong_connector.build_dummy_checkpoint()

    docs: list[Document] = []
    while checkpoint.has_more:
        generator = gong_connector.load_from_checkpoint(0, time.time(), checkpoint)
        try:
            while True:
                item = next(generator)
                if isinstance(item, Document):
                    docs.append(item)
        except StopIteration as e:
            checkpoint = e.value

    assert len(docs) == 2

    assert docs[0].semantic_identifier == "test with chris"
    assert docs[1].semantic_identifier == "Testing Gong"
