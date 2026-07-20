import os
import time

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import Document
from onyx.connectors.seafile.connector import SEAFILE_API_TOKEN_KEY
from onyx.connectors.seafile.connector import SeafileConnector
from tests.daily.connectors.utils import load_all_from_connector


@pytest.fixture
def seafile_connector() -> SeafileConnector:
    base_url = os.environ.get("SEAFILE_BASE_URL")
    api_token = os.environ.get("SEAFILE_API_TOKEN")
    repo_id = os.environ.get("SEAFILE_REPO_ID")

    if not base_url or not api_token or not repo_id:
        pytest.skip(
            "SEAFILE_BASE_URL, SEAFILE_API_TOKEN, and SEAFILE_REPO_ID must be set"
        )

    path_prefixes = [
        path.strip()
        for path in os.environ.get("SEAFILE_PATH_PREFIXES", "/").split(",")
        if path.strip()
    ]
    allowed_extensions = [
        extension.strip()
        for extension in os.environ.get(
            "SEAFILE_ALLOWED_EXTENSIONS", ".txt,.md,.pdf"
        ).split(",")
        if extension.strip()
    ]

    connector = SeafileConnector(
        base_url=base_url,
        repo_ids=[repo_id],
        path_prefixes=path_prefixes,
        allowed_extensions=allowed_extensions,
        batch_size=10,
    )
    connector.load_credentials({SEAFILE_API_TOKEN_KEY: api_token})
    return connector


def test_seafile_connector_validates_settings(
    seafile_connector: SeafileConnector,
) -> None:
    seafile_connector.validate_connector_settings()


def test_seafile_checkpointed_load_returns_documents(
    seafile_connector: SeafileConnector,
    mock_get_unstructured_api_key: object,  # noqa: ARG001
) -> None:
    output = load_all_from_connector(
        connector=seafile_connector,
        start=0,
        end=time.time(),
    )

    assert output.documents
    assert not output.failures

    for document in output.documents:
        assert isinstance(document, Document)
        assert document.source == DocumentSource.SEAFILE
        assert document.id.startswith("seafile:")
        assert document.semantic_identifier
        assert document.metadata["repo_id"]
        assert document.metadata["path"]
        assert document.sections
