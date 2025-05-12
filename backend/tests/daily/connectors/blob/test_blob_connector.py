import os
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.configs.constants import BlobType
from onyx.connectors.blob.connector import BlobStorageConnector
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.file_processing.extract_file_text import ACCEPTED_DOCUMENT_FILE_EXTENSIONS
from onyx.file_processing.extract_file_text import ACCEPTED_PLAIN_TEXT_FILE_EXTENSIONS
from onyx.file_processing.extract_file_text import get_file_ext


@pytest.fixture
def blob_connector(request: pytest.FixtureRequest) -> BlobStorageConnector:
    connector = BlobStorageConnector(
        bucket_type=BlobType.S3, bucket_name="onyx-connector-tests"
    )

    connector.load_credentials(
        {
            "aws_access_key_id": os.environ["AWS_ACCESS_KEY_ID_DAILY_CONNECTOR_TESTS"],
            "aws_secret_access_key": os.environ[
                "AWS_SECRET_ACCESS_KEY_DAILY_CONNECTOR_TESTS"
            ],
        }
    )

    return connector


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_blob_s3_connector(
    mock_get_api_key: MagicMock, blob_connector: BlobStorageConnector
) -> None:
    """
    Plain and document file types should be fully indexed.

    Multimedia and unknown file types will be indexed be skipped unless `set_allow_images`
    is called with `True`.

    This is intentional in order to allow searching by just the title even if we can't
    index the file content.
    """
    all_docs: list[Document] = []
    document_batches = blob_connector.load_from_state()
    for doc_batch in document_batches:
        for doc in doc_batch:
            all_docs.append(doc)

    assert len(all_docs) == 15

    for doc in all_docs:
        section = doc.sections[0]
        assert isinstance(section, TextSection)

        file_extension = get_file_ext(doc.semantic_identifier)
        if file_extension in ACCEPTED_PLAIN_TEXT_FILE_EXTENSIONS:
            assert len(section.text) > 0
            continue

        if file_extension in ACCEPTED_DOCUMENT_FILE_EXTENSIONS:
            assert len(section.text) > 0
            continue

        # unknown extension
        assert len(section.text) == 0
