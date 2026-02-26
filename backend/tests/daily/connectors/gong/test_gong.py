import os
import time
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.connectors.gong.connector import GongConnector
from onyx.connectors.models import Document
from tests.unit.onyx.connectors.utils import load_everything_from_checkpoint_connector


@pytest.fixture
def gong_connector() -> GongConnector:
    connector = GongConnector()

    connector.load_credentials(
        {
            "gong_access_key": os.environ["GONG_ACCESS_KEY"],
            "gong_access_key_secret": os.environ["GONG_ACCESS_KEY_SECRET"],
        }
    )

    return connector


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_gong_basic(
    mock_get_api_key: MagicMock, gong_connector: GongConnector  # noqa: ARG001
) -> None:
    outputs = load_everything_from_checkpoint_connector(gong_connector, 0, time.time())

    docs: list[Document] = []
    for output in outputs:
        for item in output.items:
            if isinstance(item, Document):
                docs.append(item)

    assert len(docs) == 2
    assert docs[0].semantic_identifier == "test with chris"
    assert docs[1].semantic_identifier == "Testing Gong"
