import os
from unittest.mock import MagicMock
from unittest.mock import patch
from urllib.parse import parse_qs
from urllib.parse import unquote
from urllib.parse import urlparse

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
    """Fixture requires (BlobType, bucket_name) and optional init kwargs.

    Param format: (BlobType, bucket_name, {optional init kwargs})
    - The 3rd element is optional and, if provided, must be a dict.
    - Extra kwargs are passed to BlobStorageConnector.__init__.

    Example:
      @pytest.mark.parametrize(
          "blob_connector",
          [(BlobType.S3, "my-bucket"), (BlobType.S3, "my-bucket", {"prefix": "foo/"})],
          indirect=True,
      )
    """
    try:
        bucket_type, bucket_name, *rest = request.param  # type: ignore[misc]
    except Exception as e:
        raise AssertionError(
            "blob_connector requires (BlobType, bucket_name, [init_kwargs])"
        ) from e

    init_kwargs = rest[0] if rest else {}
    if rest and not isinstance(init_kwargs, dict):
        raise AssertionError("init_kwargs must be a dict if provided")

    if not isinstance(bucket_type, BlobType):
        bucket_type = BlobType(bucket_type)

    connector = BlobStorageConnector(
        bucket_type=bucket_type, bucket_name=bucket_name, **init_kwargs
    )

    if bucket_type == BlobType.S3:
        creds = {
            "aws_access_key_id": os.environ["AWS_ACCESS_KEY_ID_DAILY_CONNECTOR_TESTS"],
            "aws_secret_access_key": os.environ[
                "AWS_SECRET_ACCESS_KEY_DAILY_CONNECTOR_TESTS"
            ],
        }
    elif bucket_type == BlobType.R2:
        creds = {
            "account_id": os.environ["R2_ACCOUNT_ID_DAILY_CONNECTOR_TESTS"],
            "r2_access_key_id": os.environ["R2_ACCESS_KEY_ID_DAILY_CONNECTOR_TESTS"],
            "r2_secret_access_key": os.environ[
                "R2_SECRET_ACCESS_KEY_DAILY_CONNECTOR_TESTS"
            ],
        }
    elif bucket_type == BlobType.GOOGLE_CLOUD_STORAGE:
        creds = {
            "access_key_id": os.environ["GCS_ACCESS_KEY_ID_DAILY_CONNECTOR_TESTS"],
            "secret_access_key": os.environ[
                "GCS_SECRET_ACCESS_KEY_DAILY_CONNECTOR_TESTS"
            ],
        }
    else:
        # Until we figure out the Oracle log in, this fixture only supports S3, R2, and GCS.
        raise AssertionError(f"Unsupported bucket type: {bucket_type}")

    connector.load_credentials(creds)
    return connector


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
@pytest.mark.parametrize(
    "blob_connector", [(BlobType.S3, "onyx-connector-tests")], indirect=True
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


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
@pytest.mark.parametrize(
    "blob_connector", [(BlobType.S3, "s3-role-connector-test")], indirect=True
)
def test_blob_s3_cross_region_and_citation_link(
    mock_get_api_key: MagicMock,
    blob_connector: BlobStorageConnector,
) -> None:
    """Buckets in a different region should be accessible and links should reflect the correct region.

    Validates that using the same credentials we can access a bucket in a
    different AWS region and that the generated object URL includes the bucket's
    region and is a valid S3 dashboard URL.
    """

    assert blob_connector.bucket_region == "ap-south-1"

    # Load documents and validate the single object + its link
    all_docs: list[Document] = []
    for doc_batch in blob_connector.load_from_state():
        all_docs.extend(doc_batch)

    # The test bucket contains exactly one object named "Chapter 6.pdf"
    assert len(all_docs) == 1
    doc = all_docs[0]
    assert doc.semantic_identifier == "Chapter 6.pdf"

    # Validate link
    assert len(doc.sections) >= 1
    link = doc.sections[0].link
    assert link is not None and isinstance(link, str) and len(link) > 0

    parsed = urlparse(link)
    # Expect the link to be the AWS S3 console object URL
    assert parsed.netloc == "s3.console.aws.amazon.com"
    assert parsed.path == "/s3/object/s3-role-connector-test"

    # Query should include region and prefix
    query = parse_qs(parsed.query)
    assert query.get("region") == ["ap-south-1"]
    assert "prefix" in query and len(query["prefix"]) == 1
    prefix_val = query["prefix"][0]
    # The prefix (object key) should decode to the filename
    decoded_prefix = unquote(prefix_val)
    assert decoded_prefix == "Chapter 6.pdf" or decoded_prefix.endswith(
        "/Chapter 6.pdf"
    )


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
@pytest.mark.parametrize(
    "blob_connector", [(BlobType.R2, "asia-pacific-bucket")], indirect=True
)
def test_blob_r2_connector(
    mock_get_api_key: MagicMock, blob_connector: BlobStorageConnector
) -> None:
    """Validate basic R2 connector creation and document loading"""

    all_docs: list[Document] = []
    for doc_batch in blob_connector.load_from_state():
        all_docs.extend(doc_batch)

    assert len(all_docs) >= 1
    doc = all_docs[0]
    assert len(doc.sections) >= 1


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
@pytest.mark.parametrize(
    "blob_connector",
    [(BlobType.R2, "onyx-daily-connector-tests", {"european_residency": True})],
    indirect=True,
)
def test_blob_r2_eu_residency_connector(
    mock_get_api_key: MagicMock, blob_connector: BlobStorageConnector
) -> None:
    """Validate R2 connector with European residency setting"""

    all_docs: list[Document] = []
    for doc_batch in blob_connector.load_from_state():
        all_docs.extend(doc_batch)

    assert len(all_docs) >= 1
    doc = all_docs[0]
    assert len(doc.sections) >= 1


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
@pytest.mark.parametrize(
    "blob_connector", [(BlobType.GOOGLE_CLOUD_STORAGE, "onyx-test-1")], indirect=True
)
def test_blob_gcs_connector(
    mock_get_api_key: MagicMock, blob_connector: BlobStorageConnector
) -> None:
    all_docs: list[Document] = []
    for doc_batch in blob_connector.load_from_state():
        all_docs.extend(doc_batch)

    # At least one object from the test bucket
    assert len(all_docs) >= 1
    doc = all_docs[0]
    assert len(doc.sections) >= 1
