import json
import os
import time
from pathlib import Path
from typing import Any
from typing import cast

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import Document
from onyx.connectors.salesforce.connector import SalesforceConnector


def extract_key_value_pairs_to_set(
    list_of_unparsed_key_value_strings: list[str],
) -> set[str]:
    set_of_key_value_pairs = set()
    for string_key_value_pairs in list_of_unparsed_key_value_strings:
        list_of_parsed_key_values = string_key_value_pairs.split("\n")
        for key_value_pair in list_of_parsed_key_values:
            set_of_key_value_pairs.add(key_value_pair.strip())
    return set_of_key_value_pairs


def load_test_data(
    file_name: str = "test_salesforce_data.json",
) -> dict[str, str | list[str] | dict[str, Any] | list[dict[str, Any]]]:
    current_dir = Path(__file__).parent
    with open(current_dir / file_name, "r") as f:
        return json.load(f)


@pytest.fixture
def salesforce_connector() -> SalesforceConnector:
    connector = SalesforceConnector(
        requested_objects=["Account", "Contact", "Opportunity"],
    )

    username = os.environ["SF_USERNAME"]
    password = os.environ["SF_PASSWORD"]
    security_token = os.environ["SF_SECURITY_TOKEN"]

    connector.load_credentials(
        {
            "sf_username": username,
            "sf_password": password,
            "sf_security_token": security_token,
        }
    )
    return connector


# TODO: make the credentials not expire
def test_salesforce_connector_basic(salesforce_connector: SalesforceConnector) -> None:
    test_data = load_test_data()
    target_test_doc: Document | None = None
    all_docs: list[Document] = []
    for doc_batch in salesforce_connector.poll_source(0, time.time()):
        for doc in doc_batch:
            all_docs.append(doc)
            if doc.id == test_data["id"]:
                target_test_doc = doc
                break

    # The number of docs here seems to change actively so do a very loose check
    # as of 2025-03-28 it was around 32472
    assert len(all_docs) > 32000
    assert len(all_docs) < 40000

    assert target_test_doc is not None

    # Set of received links
    received_links: set[str] = set()
    # List of received text fields, which contain key-value pairs seperated by newlines
    received_text: list[str] = []

    # Iterate over the sections of the target test doc to extract the links and text
    for section in target_test_doc.sections:
        assert section.link
        assert section.text
        received_links.add(section.link)
        received_text.append(section.text)

    # Check that the received links match the expected links from the test data json
    expected_links = set(test_data["expected_links"])
    assert received_links == expected_links

    # Check that the received key-value pairs from the text fields match the expected key-value pairs from the test data json
    expected_text = test_data["expected_text"]
    if not isinstance(expected_text, list):
        raise ValueError("Expected text is not a list")

    unparsed_expected_key_value_pairs: list[str] = cast(list[str], expected_text)
    received_key_value_pairs = extract_key_value_pairs_to_set(received_text)
    expected_key_value_pairs = extract_key_value_pairs_to_set(
        unparsed_expected_key_value_pairs
    )
    assert received_key_value_pairs == expected_key_value_pairs

    # Check that the rest of the fields match the expected fields from the test data json
    assert target_test_doc.source == DocumentSource.SALESFORCE
    assert target_test_doc.semantic_identifier == test_data["semantic_identifier"]
    assert target_test_doc.metadata == test_data["metadata"]

    assert target_test_doc.primary_owners is not None
    primary_owner = target_test_doc.primary_owners[0]
    expected_primary_owner = test_data["primary_owners"]
    assert isinstance(expected_primary_owner, dict)
    assert primary_owner.email == expected_primary_owner["email"]
    assert primary_owner.first_name == expected_primary_owner["first_name"]
    assert primary_owner.last_name == expected_primary_owner["last_name"]

    assert target_test_doc.secondary_owners is not None
    secondary_owners = [
        owner.model_dump() for owner in target_test_doc.secondary_owners
    ]
    assert secondary_owners == test_data["secondary_owners"]
    assert target_test_doc.title == test_data["title"]


# TODO: make the credentials not expire
@pytest.mark.skip(
    reason=(
        "Credentials change over time, so this test will fail if run when "
        "the credentials expire."
    )
)
def test_salesforce_connector_slim(salesforce_connector: SalesforceConnector) -> None:
    # Get all doc IDs from the full connector
    all_full_doc_ids = set()
    for doc_batch in salesforce_connector.load_from_state():
        all_full_doc_ids.update([doc.id for doc in doc_batch])

    # Get all doc IDs from the slim connector
    all_slim_doc_ids = set()
    for slim_doc_batch in salesforce_connector.retrieve_all_slim_documents():
        all_slim_doc_ids.update([doc.id for doc in slim_doc_batch])

    # The set of full doc IDs should be always be a subset of the slim doc IDs
    assert all_full_doc_ids.issubset(all_slim_doc_ids)
