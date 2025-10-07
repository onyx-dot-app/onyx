import time
from collections.abc import Generator

import pytest

from onyx.connectors.models import Document
from onyx.connectors.models import SlimDocument
from onyx.connectors.slack.connector import SlackConnector
from onyx.utils.variable_functionality import global_version
from tests.daily.connectors.utils import load_everything_from_checkpoint_connector


PUBLIC_CHANNEL_NAME = "#daily-connector-test-channel"
PRIVATE_CHANNEL_NAME = "#private-channel"
PRIVATE_CHANNEL_USERS = [
    "admin@onyx-test.com",
    "test_user_1@onyx-test.com",
    # user 2 added via a group
    "test_user_2@onyx-test.com",
]


@pytest.fixture(autouse=True)
def set_ee_on() -> Generator[None, None, None]:
    """Need EE to be enabled for these tests to work since
    perm syncing is a an EE-only feature."""
    global_version.set_ee()

    yield

    global_version._is_ee = False


@pytest.mark.parametrize(
    "slack_connector",
    [
        PUBLIC_CHANNEL_NAME,
    ],
    indirect=True,
)
def test_load_from_checkpoint_access__public_channel(
    slack_connector: SlackConnector,
) -> None:
    """Test that load_from_checkpoint returns correct access information for documents."""
    if not slack_connector.client:
        raise RuntimeError("Web client must be defined")

    docs = load_everything_from_checkpoint_connector(
        connector=slack_connector,
        start=0.0,
        end=time.time(),
        include_permissions=True,
    )

    doc_list = list(docs)
    documents = [doc for doc in doc_list if isinstance(doc, Document)]

    # We should have at least some documents
    assert len(documents) > 0, "Expected to find at least one document"

    for doc in documents:
        assert doc.external_access is not None
        assert doc.external_access.is_public is True
        assert doc.external_access.external_user_emails == set()
        assert doc.external_access.external_user_group_ids == set()


@pytest.mark.parametrize(
    "slack_connector",
    [
        PRIVATE_CHANNEL_NAME,
    ],
    indirect=True,
)
def test_load_from_checkpoint_access__private_channel(
    slack_connector: SlackConnector,
) -> None:
    """Test that load_from_checkpoint returns correct access information for documents."""
    if not slack_connector.client:
        raise RuntimeError("Web client must be defined")

    docs = load_everything_from_checkpoint_connector(
        connector=slack_connector,
        start=0.0,
        end=time.time(),
        include_permissions=True,
    )

    doc_list = list(docs)
    documents = [doc for doc in doc_list if isinstance(doc, Document)]

    # We should have at least some documents
    assert len(documents) > 0, "Expected to find at least one document"

    for doc in documents:
        assert doc.external_access is not None
        assert doc.external_access.is_public is False
        assert doc.external_access.external_user_emails == set(PRIVATE_CHANNEL_USERS)
        assert doc.external_access.external_user_group_ids == set()


@pytest.mark.parametrize(
    "slack_connector",
    [
        PUBLIC_CHANNEL_NAME,
    ],
    indirect=True,
)
def test_slim_documents_access__public_channel(
    slack_connector: SlackConnector,
) -> None:
    """Test that retrieve_all_slim_docs_perm_sync returns correct access information for slim documents."""
    if not slack_connector.client:
        raise RuntimeError("Web client must be defined")

    slim_docs_generator = slack_connector.retrieve_all_slim_docs_perm_sync(
        start=0.0,
        end=time.time(),
    )

    # Collect all slim documents from the generator
    all_slim_docs: list[SlimDocument] = []
    for slim_doc_batch in slim_docs_generator:
        all_slim_docs.extend(slim_doc_batch)

    # We should have at least some slim documents
    assert len(all_slim_docs) > 0, "Expected to find at least one slim document"

    for slim_doc in all_slim_docs:
        assert slim_doc.external_access is not None
        assert slim_doc.external_access.is_public is True
        assert slim_doc.external_access.external_user_emails == set()
        assert slim_doc.external_access.external_user_group_ids == set()


@pytest.mark.parametrize(
    "slack_connector",
    [
        PRIVATE_CHANNEL_NAME,
    ],
    indirect=True,
)
def test_slim_documents_access__private_channel(
    slack_connector: SlackConnector,
) -> None:
    """Test that retrieve_all_slim_docs_perm_sync returns correct access information for slim documents."""
    if not slack_connector.client:
        raise RuntimeError("Web client must be defined")

    slim_docs_generator = slack_connector.retrieve_all_slim_docs_perm_sync(
        start=0.0,
        end=time.time(),
    )

    # Collect all slim documents from the generator
    all_slim_docs: list[SlimDocument] = []
    for slim_doc_batch in slim_docs_generator:
        all_slim_docs.extend(slim_doc_batch)

    # We should have at least some slim documents
    assert len(all_slim_docs) > 0, "Expected to find at least one slim document"

    for slim_doc in all_slim_docs:
        assert slim_doc.external_access is not None
        assert slim_doc.external_access.is_public is False
        assert slim_doc.external_access.external_user_emails == set(
            PRIVATE_CHANNEL_USERS
        )
        assert slim_doc.external_access.external_user_group_ids == set()
