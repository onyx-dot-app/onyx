import os
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.airtable.airtable_connector import AirtableConnector
from onyx.connectors.models import Document
from onyx.connectors.models import Section


@pytest.fixture(
    params=[
        ("table_name", os.environ["AIRTABLE_TEST_TABLE_NAME"]),
        ("table_id", os.environ["AIRTABLE_TEST_TABLE_ID"]),
    ]
)
def airtable_connector(request: pytest.FixtureRequest) -> AirtableConnector:
    param_type, table_identifier = request.param
    connector = AirtableConnector(
        base_id=os.environ["AIRTABLE_TEST_BASE_ID"],
        table_name_or_id=table_identifier,
    )

    connector.load_credentials(
        {
            "airtable_access_token": os.environ["AIRTABLE_ACCESS_TOKEN"],
        }
    )
    return connector


def create_test_document(
    id: str,
    title: str,
    description: str,
    priority: str,
    status: str,
    # Link to another record is skipped for now
    # category: str,
    ticket_id: str,
    created_time: str,
    status_last_changed: str,
    submitted_by: str,
    assignee: str,
    days_since_status_change: int | None,
    attachments: list | None = None,
) -> Document:
    link_base = f"https://airtable.com/{os.environ['AIRTABLE_TEST_BASE_ID']}/{os.environ['AIRTABLE_TEST_TABLE_ID']}"
    sections = [
        Section(
            text=f"Title:\n------------------------\n{title}\n------------------------",
            link=f"{link_base}/{id}",
        ),
        Section(
            text=f"Description:\n------------------------\n{description}\n------------------------",
            link=f"{link_base}/{id}",
        ),
    ]

    if attachments:
        for attachment in attachments:
            sections.append(
                Section(
                    text=f"Attachment:\n------------------------\n{attachment}\n------------------------",
                    link=f"{link_base}/{id}",
                ),
            )

    return Document(
        id=f"airtable__{id}",
        sections=sections,
        source=DocumentSource.AIRTABLE,
        semantic_identifier=f"{os.environ['AIRTABLE_TEST_TABLE_NAME']}: {title}",
        metadata={
            # "Category": category,
            "Assignee": assignee,
            "Submitted by": submitted_by,
            "Priority": priority,
            "Status": status,
            "Created time": created_time,
            "ID": ticket_id,
            "Status last changed": status_last_changed,
            **(
                {"Days since status change": str(days_since_status_change)}
                if days_since_status_change is not None
                else {}
            ),
        },
        doc_updated_at=None,
        primary_owners=None,
        secondary_owners=None,
        title=None,
        from_ingestion_api=False,
        additional_info=None,
    )


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_airtable_connector_basic(
    mock_get_api_key: MagicMock, airtable_connector: AirtableConnector
) -> None:
    doc_batch_generator = airtable_connector.load_from_state()

    doc_batch = next(doc_batch_generator)
    with pytest.raises(StopIteration):
        next(doc_batch_generator)

    assert len(doc_batch) == 2

    expected_docs = [
        create_test_document(
            id="rec8BnxDLyWeegOuO",
            title="Slow Internet",
            description="The internet connection is very slow.",
            priority="Medium",
            status="In Progress",
            # Link to another record is skipped for now
            # category="Data Science",
            ticket_id="2",
            created_time="2024-12-24T21:02:49.000Z",
            status_last_changed="2024-12-24T21:02:49.000Z",
            days_since_status_change=0,
            assignee="Chris Weaver (chris@onyx.app)",
            submitted_by="Chris Weaver (chris@onyx.app)",
        ),
        create_test_document(
            id="reccSlIA4pZEFxPBg",
            title="Printer Issue",
            description="The office printer is not working.",
            priority="High",
            status="Open",
            # Link to another record is skipped for now
            # category="Software Development",
            ticket_id="1",
            created_time="2024-12-24T21:02:49.000Z",
            status_last_changed="2024-12-24T21:02:49.000Z",
            days_since_status_change=0,
            assignee="Chris Weaver (chris@onyx.app)",
            submitted_by="Chris Weaver (chris@onyx.app)",
            attachments=["Test.pdf:\ntesting!!!"],
        ),
    ]

    # Compare each document field by field
    for actual, expected in zip(doc_batch, expected_docs):
        assert actual.id == expected.id, f"ID mismatch for document {actual.id}"
        assert (
            actual.source == expected.source
        ), f"Source mismatch for document {actual.id}"
        assert (
            actual.semantic_identifier == expected.semantic_identifier
        ), f"Semantic identifier mismatch for document {actual.id}"
        assert (
            actual.metadata == expected.metadata
        ), f"Metadata mismatch for document {actual.id}"
        assert (
            actual.doc_updated_at == expected.doc_updated_at
        ), f"Updated at mismatch for document {actual.id}"
        assert (
            actual.primary_owners == expected.primary_owners
        ), f"Primary owners mismatch for document {actual.id}"
        assert (
            actual.secondary_owners == expected.secondary_owners
        ), f"Secondary owners mismatch for document {actual.id}"
        assert (
            actual.title == expected.title
        ), f"Title mismatch for document {actual.id}"
        assert (
            actual.from_ingestion_api == expected.from_ingestion_api
        ), f"Ingestion API flag mismatch for document {actual.id}"
        assert (
            actual.additional_info == expected.additional_info
        ), f"Additional info mismatch for document {actual.id}"

        # Compare sections
        assert len(actual.sections) == len(
            expected.sections
        ), f"Number of sections mismatch for document {actual.id}"
        for i, (actual_section, expected_section) in enumerate(
            zip(actual.sections, expected.sections)
        ):
            assert (
                actual_section.text == expected_section.text
            ), f"Section {i} text mismatch for document {actual.id}"
            assert (
                actual_section.link == expected_section.link
            ), f"Section {i} link mismatch for document {actual.id}"
