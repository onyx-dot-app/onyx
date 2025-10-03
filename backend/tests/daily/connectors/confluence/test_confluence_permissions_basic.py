import os
import time
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from ee.onyx.external_permissions.confluence.doc_sync import confluence_doc_sync
from onyx.configs.constants import DocumentSource
from onyx.connectors.confluence.connector import ConfluenceConnector
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.db.models import ConnectorCredentialPair
from onyx.db.utils import DocumentRow
from onyx.db.utils import SortOrder
from tests.daily.connectors.utils import load_all_docs_from_checkpoint_connector


@pytest.fixture
def confluence_connector() -> ConfluenceConnector:
    connector = ConfluenceConnector(
        wiki_base="https://danswerai.atlassian.net",
        is_cloud=True,
    )

    credentials_provider = OnyxStaticCredentialsProvider(
        None,
        DocumentSource.CONFLUENCE,
        {
            "confluence_username": os.environ["CONFLUENCE_USER_NAME"],
            "confluence_access_token": os.environ["CONFLUENCE_ACCESS_TOKEN"],
        },
    )
    connector.set_credentials_provider(credentials_provider)
    return connector


# This should never fail because even if the docs in the cloud change,
# the full doc ids retrieved should always be a subset of the slim doc ids
@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_confluence_connector_permissions(
    mock_get_api_key: MagicMock,
    confluence_connector: ConfluenceConnector,
    set_ee_on: None,
) -> None:
    # Get all doc IDs from the full connector
    all_full_doc_ids = set()
    doc_batch = load_all_docs_from_checkpoint_connector(
        confluence_connector, 0, time.time()
    )
    all_full_doc_ids.update([doc.id for doc in doc_batch])

    # Get all doc IDs from the slim connector
    all_slim_doc_ids = set()
    for slim_doc_batch in confluence_connector.retrieve_all_slim_docs_perm_sync():
        all_slim_doc_ids.update([doc.id for doc in slim_doc_batch])

    # Find IDs that are in full but not in slim
    difference = all_full_doc_ids - all_slim_doc_ids

    # The set of full doc IDs should be always be a subset of the slim doc IDs
    assert all_full_doc_ids.issubset(
        all_slim_doc_ids
    ), f"Full doc IDs are not a subset of slim doc IDs. Found {len(difference)} IDs in full docs but not in slim docs."


@patch("ee.onyx.external_permissions.confluence.doc_sync.OnyxDBCredentialsProvider")
@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_confluence_connector_restriction_handling(
    mock_get_api_key: MagicMock,
    mock_db_provider_class: MagicMock,
    set_ee_on: None,
) -> None:
    # Test space key
    test_space_key = "DailyPermS"

    # Configure the mock provider instance that will be returned
    mock_provider_instance = MagicMock()
    mock_provider_instance.get_credentials.return_value = {
        "confluence_username": os.environ["CONFLUENCE_USER_NAME"],
        "confluence_access_token": os.environ["CONFLUENCE_ACCESS_TOKEN"],
    }
    # this prevents redis calls inside of OnyxConfluence
    mock_provider_instance.is_dynamic.return_value = False
    # Make the class return our configured instance when called
    mock_db_provider_class.return_value = mock_provider_instance

    # Mock the cc_pair to pass to the function
    mock_cc_pair = MagicMock(spec=ConnectorCredentialPair)
    # Mock the nested connector attribute and its config
    mock_cc_pair.connector = MagicMock()
    mock_cc_pair.connector.connector_specific_config = {
        "wiki_base": "https://danswerai.atlassian.net",
        "is_cloud": True,
        "space": test_space_key,
    }
    # Set a mock credential ID
    mock_cc_pair.credential_id = 1

    # Call the confluence_doc_sync function directly with the mock cc_pair
    def mock_fetch_all_docs_fn(
        sort_order: SortOrder | None = None,
    ) -> list[DocumentRow]:
        return []

    def mock_fetch_all_docs_ids_fn() -> list[str]:
        return []

    doc_access_generator = confluence_doc_sync(
        mock_cc_pair, mock_fetch_all_docs_fn, mock_fetch_all_docs_ids_fn, None
    )
    doc_access_list = list(doc_access_generator)
    assert len(doc_access_list) == 7
    assert all(
        not doc_access.external_access.is_public for doc_access in doc_access_list
    )

    # if no restriction is applied, the groups should give access, so no need
    # for more emails outside of the owner
    non_restricted_emails = {"chris@onyx.app"}
    non_restricted_user_groups = {
        "confluence-admins-danswerai",
        "org-admins",
        "atlassian-addons-admin",
        "confluence-users-danswerai",
    }

    # if restriction is applied, only should be visible to shared users / groups
    restricted_emails = {"chris@onyx.app", "hagen@danswer.ai", "oauth@onyx.app"}
    restricted_user_groups = {"confluence-admins-danswerai"}

    extra_restricted_emails = {"chris@onyx.app", "oauth@onyx.app"}
    extra_restricted_user_groups: set[str] = set()

    # note that this is only allowed since yuhong@onyx.app is a member of the
    # confluence-admins-danswerai group
    special_restricted_emails = {"chris@onyx.app", "yuhong@onyx.app", "oauth@onyx.app"}
    special_restricted_user_groups: set[str] = set()

    # Check Root+Page+2 is public
    root_page_2 = next(d for d in doc_access_list if d.doc_id.endswith("Root+Page+2"))
    assert root_page_2.external_access.external_user_emails == non_restricted_emails
    assert (
        root_page_2.external_access.external_user_group_ids
        == non_restricted_user_groups
    )

    # Check Overview page is public
    overview_page = next(
        d for d in doc_access_list if d.doc_id.lower().endswith("overview")
    )
    assert (
        overview_page.external_access.external_user_emails == non_restricted_emails
    ), "Overview page emails do not match expected values"
    assert (
        overview_page.external_access.external_user_group_ids
        == non_restricted_user_groups
    ), "Overview page groups do not match expected values"

    # check root page is restricted
    root_page = next(d for d in doc_access_list if d.doc_id.endswith("Root+Page"))
    assert (
        root_page.external_access.external_user_emails == restricted_emails
    ), "Root page emails do not match expected values"
    assert (
        root_page.external_access.external_user_group_ids == restricted_user_groups
    ), "Root page groups do not match expected values"

    # check child page has restriction propagated
    child_page = next(d for d in doc_access_list if d.doc_id.endswith("Child+Page"))
    assert (
        child_page.external_access.external_user_emails == restricted_emails
    ), "Child page emails do not match expected values"
    assert (
        child_page.external_access.external_user_group_ids == restricted_user_groups
    ), "Child page groups do not match expected values"

    # check doubly nested child page has restriction propagated
    child_page_2 = next(d for d in doc_access_list if d.doc_id.endswith("Child+Page+2"))
    assert (
        child_page_2.external_access.external_user_emails == restricted_emails
    ), "Child page 2 emails do not match expected values"
    assert (
        child_page_2.external_access.external_user_group_ids == restricted_user_groups
    ), "Child page 2 groups do not match expected values"

    # check child page w/ specific restrictions have those applied
    child_page_3 = next(d for d in doc_access_list if d.doc_id.endswith("Child+Page+3"))
    assert (
        child_page_3.external_access.external_user_emails == extra_restricted_emails
    ), "Child page 3 emails do not match expected values"
    assert (
        child_page_3.external_access.external_user_group_ids
        == extra_restricted_user_groups
    ), "Child page 3 groups do not match expected values"

    # check child page w/ specific restrictions have those applied
    child_page_4 = next(d for d in doc_access_list if d.doc_id.endswith("Child+Page+4"))
    assert (
        child_page_4.external_access.external_user_emails == special_restricted_emails
    ), "Child page 4 emails do not match expected values"
    assert (
        child_page_4.external_access.external_user_group_ids
        == special_restricted_user_groups
    ), "Child page 4 groups do not match expected values"
