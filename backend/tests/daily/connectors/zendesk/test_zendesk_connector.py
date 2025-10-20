import json
import os
import time
from pathlib import Path
from typing import cast

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import Document
from onyx.connectors.zendesk.connector import ZendeskConnector
from tests.daily.connectors.utils import load_all_docs_from_checkpoint_connector


def load_test_data(file_name: str = "test_zendesk_data.json") -> dict[str, dict]:
    current_dir = Path(__file__).parent
    with open(current_dir / file_name, "r") as f:
        return json.load(f)


@pytest.fixture
def zendesk_article_connector() -> ZendeskConnector:
    connector = ZendeskConnector(content_type="articles")
    connector.load_credentials(get_credentials())
    return connector


@pytest.fixture
def zendesk_ticket_connector() -> ZendeskConnector:
    connector = ZendeskConnector(content_type="tickets")
    connector.load_credentials(get_credentials())
    return connector


def get_credentials() -> dict[str, str]:
    return {
        "zendesk_subdomain": os.environ["ZENDESK_SUBDOMAIN"],
        "zendesk_email": os.environ["ZENDESK_EMAIL"],
        "zendesk_token": os.environ["ZENDESK_TOKEN"],
    }


@pytest.mark.xfail(
    reason=(
        "Cannot get Zendesk developer account to ensure zendesk account does not "
        "expire after 2 weeks"
    )
)
@pytest.mark.parametrize(
    "connector_fixture", ["zendesk_article_connector", "zendesk_ticket_connector"]
)
def test_zendesk_connector_basic(
    request: pytest.FixtureRequest, connector_fixture: str
) -> None:
    connector = cast(ZendeskConnector, request.getfixturevalue(connector_fixture))
    test_data = load_test_data()
    all_docs: list[Document] = []
    target_test_doc_id: str
    if connector.content_type == "articles":
        target_test_doc_id = f"article:{test_data['article']['id']}"
    else:
        target_test_doc_id = f"zendesk_ticket_{test_data['ticket']['id']}"

    target_doc: Document | None = None

    for doc in load_all_docs_from_checkpoint_connector(connector, 0, time.time()):
        all_docs.append(doc)
        if doc.id == target_test_doc_id:
            target_doc = doc
            print(f"target_doc {target_doc}")

    assert len(all_docs) > 0, "No documents were retrieved from the connector"
    assert (
        target_doc is not None
    ), "Target document was not found in the retrieved documents"
    assert target_doc.source == DocumentSource.ZENDESK, "Document source is not ZENDESK"

    if connector.content_type == "articles":
        test_article = test_data["article"]
        assert target_doc.semantic_identifier == test_article["semantic_identifier"]
        assert target_doc.sections[0].link == test_article["sections"][0]["link"]
        assert target_doc.source == test_article["source"]
        assert target_doc.primary_owners is not None
        assert len(target_doc.primary_owners) == 1
        assert (
            target_doc.primary_owners[0].display_name
            == test_article["primary_owners"][0]["display_name"]
        )
        assert (
            target_doc.primary_owners[0].email
            == test_article["primary_owners"][0]["email"]
        )
    else:
        test_ticket = test_data["ticket"]
        assert target_doc.semantic_identifier == test_ticket["semantic_identifier"]
        assert target_doc.sections[0].link == test_ticket["sections"][0]["link"]
        assert target_doc.source == test_ticket["source"]
        assert target_doc.metadata["status"] == test_ticket["metadata"]["status"]
        assert target_doc.metadata["priority"] == test_ticket["metadata"]["priority"]
        assert target_doc.metadata["tags"] == test_ticket["metadata"]["tags"]
        assert (
            target_doc.metadata["ticket_type"] == test_ticket["metadata"]["ticket_type"]
        )


@pytest.mark.xfail(
    reason=(
        "Cannot get Zendesk developer account to ensure zendesk account does not "
        "expire after 2 weeks"
    )
)
def test_zendesk_connector_slim(zendesk_article_connector: ZendeskConnector) -> None:
    # Get full doc IDs
    all_full_doc_ids = set()
    for doc in load_all_docs_from_checkpoint_connector(
        zendesk_article_connector, 0, time.time()
    ):
        all_full_doc_ids.add(doc.id)

    # Get slim doc IDs
    all_slim_doc_ids = set()
    for slim_doc_batch in zendesk_article_connector.retrieve_all_slim_docs_perm_sync():
        all_slim_doc_ids.update([doc.id for doc in slim_doc_batch])

    # Full docs should be subset of slim docs
    assert all_full_doc_ids.issubset(
        all_slim_doc_ids
    ), f"Full doc IDs {all_full_doc_ids} not subset of slim doc IDs {all_slim_doc_ids}"
