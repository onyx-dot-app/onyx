import os
import time
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.connectors.gong.connector import GongConnector
from onyx.connectors.models import Document


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


# @patch(
#     "onyx.file_processing.extract_file_text.get_unstructured_api_key",
#     return_value=None,
# )
# def test_gong_basic(mock_get_api_key: MagicMock, gong_connector: GongConnector) -> None:
#     doc_batch_generator = gong_connector.poll_source(0, time.time())

#     doc_batch = next(doc_batch_generator)
#     with pytest.raises(StopIteration):
#         next(doc_batch_generator)

#     assert len(doc_batch) == 2

#     docs: list[Document] = []
#     for doc in doc_batch:
#         docs.append(doc)

#     assert docs[0].semantic_identifier == "test with chris"
#     assert docs[1].semantic_identifier == "Testing Gong"


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_gong_stub(mock_get_api_key: MagicMock, gong_connector: GongConnector) -> None:
    end = time.time()
    start = end - 86400

    doc_batch_generator = gong_connector.poll_source(start, end)

    docs: list[Document] = []

    for doc_batch in doc_batch_generator:
        for doc in doc_batch:
            # print(doc.semantic_identifier)
            docs.append(doc)
