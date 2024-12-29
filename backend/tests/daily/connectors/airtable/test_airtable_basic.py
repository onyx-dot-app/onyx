import os
import time

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.airtable.airtable_connector import AirtableConnector
from onyx.connectors.models import Document
from onyx.connectors.models import Section


@pytest.fixture
def airtable_connector() -> AirtableConnector:
    connector = AirtableConnector(
        base_id=os.environ["AIRTABLE_TEST_BASE_ID"],
        table_name_or_id=os.environ["AIRTABLE_TEST_TABLE_NAME"],
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
    link_base = f"https://airtable.com/{os.environ['AIRTABLE_TEST_BASE_ID']}/{os.environ['AIRTABLE_TEST_TABLE_NAME']}"
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
        id=id,
        sections=sections,
        source=DocumentSource.AIRTABLE,
        semantic_identifier="Title",
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


def test_airtable_connector_basic(airtable_connector: AirtableConnector) -> None:
    doc_batch_generator = airtable_connector.poll_source(0, time.time())

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
            attachments=[
                "Attachment invoice.pdf:\n"
                "CALL 1-800-WEBPASS Invoice\n"
                "Bill to:\n"
                "DanswerAI Inc.\n"
                "2175 Market St #C303\n"
                "San Francisco, CA 94114\n"
                "Invoice #:\n"
                "160167106\n"
                "Invoice date:\n"
                "7/01/2024\n"
                "Due date:\n"
                "7/15/2024\n"
                "Please note: if you have\n"
                "a previous balance, your\n"
                "payment will be applied\n"
                "to the oldest invoice.\n"
                "Contact us:\n"
                "gfiber.com/support\n"
                "Webpass, Inc.\n"
                "PO Box 889046\n"
                "Los Angeles, CA 90088-9046"
                "Account summary\n"
                "Previous balance $260.00\n"
                "Payments & credits received \n"
                "since previous invoice-$260.00\n"
                "Previous unpaid balance $0.00\n"
                "New charges for 7/01/2024 — 8/01/2024:\n"
                "Business 1 Gig\n"
                "Service for: 244 Kearny St 5th Floor, San Francisco CA 94108 $100.00\n"
                "Public /29 Address Range\n"
                "Service for: 244 Kearny St 5th Floor, San Francisco CA 94108 $30.00\n"
                "New charges due 7/15/2024 $130.00\n"
                "Total amount due $130.00\n"
                "enrolled in Autopay - your card will automatically be charged this amount"
            ],
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
