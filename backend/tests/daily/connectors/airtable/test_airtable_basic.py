import os
from typing import cast
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from onyx.configs.constants import DocumentSource
from onyx.connectors.airtable.airtable_connector import AirtableConnector
from onyx.connectors.models import Document
from onyx.connectors.models import ImageSection
from onyx.connectors.models import TextSection

BASE_VIEW_ID = "viwVUEJjWPd8XYjh8"


class AirtableConfig(BaseModel):
    base_id: str
    table_identifier: str
    access_token: str


@pytest.fixture(params=[True, False])
def airtable_config(request: pytest.FixtureRequest) -> AirtableConfig:
    table_identifier = (
        os.environ["AIRTABLE_TEST_TABLE_NAME"]
        if request.param
        else os.environ["AIRTABLE_TEST_TABLE_ID"]
    )
    return AirtableConfig(
        base_id=os.environ["AIRTABLE_TEST_BASE_ID"],
        table_identifier=table_identifier,
        access_token=os.environ["AIRTABLE_ACCESS_TOKEN"],
    )


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
    attachments: list[tuple[str, str]] | None = None,
    all_fields_as_metadata: bool = False,
    share_id: str | None = None,
    view_id: str | None = None,
) -> Document:
    base_id = os.environ.get("AIRTABLE_TEST_BASE_ID")
    table_id = os.environ.get("AIRTABLE_TEST_TABLE_ID")
    missing_vars = []
    if not base_id:
        missing_vars.append("AIRTABLE_TEST_BASE_ID")
    if not table_id:
        missing_vars.append("AIRTABLE_TEST_TABLE_ID")

    if missing_vars:
        raise RuntimeError(
            f"Required environment variables not set: {', '.join(missing_vars)}. "
            "These variables are required to run Airtable connector tests."
        )
    link_base = f"https://airtable.com/{base_id}"
    if share_id:
        link_base = f"{link_base}/{share_id}"
    link_base = f"{link_base}/{table_id}"
    if view_id:
        link_base = f"{link_base}/{view_id}"

    sections = []

    if not all_fields_as_metadata:
        sections.extend(
            [
                TextSection(
                    text=f"Title:\n------------------------\n{title}\n------------------------",
                    link=f"{link_base}/{id}",
                ),
                TextSection(
                    text=f"Description:\n------------------------\n{description}\n------------------------",
                    link=f"{link_base}/{id}",
                ),
            ]
        )

    if attachments:
        for attachment_text, attachment_link in attachments:
            sections.append(
                TextSection(
                    text=f"Attachment:\n------------------------\n{attachment_text}\n------------------------",
                    link=attachment_link,
                ),
            )

    metadata: dict[str, str | list[str]] = {
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
    }

    if all_fields_as_metadata:
        metadata.update(
            {
                "Title": title,
                "Description": description,
            }
        )

    return Document(
        id=f"airtable__{id}",
        sections=cast(list[TextSection | ImageSection], sections),
        source=DocumentSource.AIRTABLE,
        semantic_identifier=f"{os.environ.get('AIRTABLE_TEST_TABLE_NAME', '')}: {title}",
        metadata=metadata,
        doc_updated_at=None,
        primary_owners=None,
        secondary_owners=None,
        title=None,
        from_ingestion_api=False,
        additional_info=None,
    )


def compare_documents(
    actual_docs: list[Document], expected_docs: list[Document]
) -> None:
    """Utility function to compare actual and expected documents, ignoring order."""
    actual_docs_dict = {doc.id: doc for doc in actual_docs}
    expected_docs_dict = {doc.id: doc for doc in expected_docs}

    assert actual_docs_dict.keys() == expected_docs_dict.keys(), "Document ID mismatch"

    for doc_id in actual_docs_dict:
        actual = actual_docs_dict[doc_id]
        expected = expected_docs_dict[doc_id]

        assert (
            actual.source == expected.source
        ), f"Source mismatch for document {doc_id}"
        assert (
            actual.semantic_identifier == expected.semantic_identifier
        ), f"Semantic identifier mismatch for document {doc_id}"
        assert (
            actual.metadata == expected.metadata
        ), f"Metadata mismatch for document {doc_id}"
        assert (
            actual.doc_updated_at == expected.doc_updated_at
        ), f"Updated at mismatch for document {doc_id}"
        assert (
            actual.primary_owners == expected.primary_owners
        ), f"Primary owners mismatch for document {doc_id}"
        assert (
            actual.secondary_owners == expected.secondary_owners
        ), f"Secondary owners mismatch for document {doc_id}"
        assert actual.title == expected.title, f"Title mismatch for document {doc_id}"
        assert (
            actual.from_ingestion_api == expected.from_ingestion_api
        ), f"Ingestion API flag mismatch for document {doc_id}"
        assert (
            actual.additional_info == expected.additional_info
        ), f"Additional info mismatch for document {doc_id}"

        # Compare sections
        assert len(actual.sections) == len(
            expected.sections
        ), f"Number of sections mismatch for document {doc_id}"
        for i, (actual_section, expected_section) in enumerate(
            zip(actual.sections, expected.sections)
        ):
            assert (
                actual_section.text == expected_section.text
            ), f"Section {i} text mismatch for document {doc_id}"
            assert (
                actual_section.link == expected_section.link
            ), f"Section {i} link mismatch for document {doc_id}"


def test_airtable_connector_basic(
    mock_get_unstructured_api_key: MagicMock, airtable_config: AirtableConfig
) -> None:
    """Test behavior when all non-attachment fields are treated as metadata."""
    connector = AirtableConnector(
        base_id=airtable_config.base_id,
        table_name_or_id=airtable_config.table_identifier,
        treat_all_non_attachment_fields_as_metadata=False,
    )
    connector.load_credentials(
        {
            "airtable_access_token": airtable_config.access_token,
        }
    )
    doc_batch_generator = connector.load_from_state()
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
            ticket_id="2",
            created_time="2024-12-24T21:02:49.000Z",
            status_last_changed="2024-12-24T21:02:49.000Z",
            days_since_status_change=0,
            assignee="Chris Weaver (chris@onyx.app)",
            submitted_by="Chris Weaver (chris@onyx.app)",
            all_fields_as_metadata=False,
            view_id=BASE_VIEW_ID,
        ),
        create_test_document(
            id="reccSlIA4pZEFxPBg",
            title="Printer Issue",
            description="The office printer is not working.",
            priority="High",
            status="Open",
            ticket_id="1",
            created_time="2024-12-24T21:02:49.000Z",
            status_last_changed="2024-12-24T21:02:49.000Z",
            days_since_status_change=0,
            assignee="Chris Weaver (chris@onyx.app)",
            submitted_by="Chris Weaver (chris@onyx.app)",
            attachments=[
                (
                    "Test.pdf:\ntesting!!!",
                    "https://airtable.com/appCXJqDFS4gea8tn/tblRxFQsTlBBZdRY1/viwVUEJjWPd8XYjh8/reccSlIA4pZEFxPBg/fld1u21zkJACIvAEF/attlj2UBWNEDZngCc?blocks=hide",
                )
            ],
            all_fields_as_metadata=False,
            view_id=BASE_VIEW_ID,
        ),
    ]

    # Compare documents using the utility function
    compare_documents(doc_batch, expected_docs)


def test_airtable_connector_all_metadata(
    mock_get_unstructured_api_key: MagicMock, airtable_config: AirtableConfig
) -> None:
    connector = AirtableConnector(
        base_id=airtable_config.base_id,
        table_name_or_id=airtable_config.table_identifier,
        treat_all_non_attachment_fields_as_metadata=True,
    )
    connector.load_credentials(
        {
            "airtable_access_token": airtable_config.access_token,
        }
    )
    doc_batch_generator = connector.load_from_state()
    doc_batch = next(doc_batch_generator)
    with pytest.raises(StopIteration):
        next(doc_batch_generator)

    # NOTE: one of the rows has no attachments -> no content -> no document
    assert len(doc_batch) == 1

    expected_docs = [
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
                (
                    "Test.pdf:\ntesting!!!",
                    # hard code link for now
                    "https://airtable.com/appCXJqDFS4gea8tn/tblRxFQsTlBBZdRY1/viwVUEJjWPd8XYjh8/reccSlIA4pZEFxPBg/fld1u21zkJACIvAEF/attlj2UBWNEDZngCc?blocks=hide",
                )
            ],
            all_fields_as_metadata=True,
            view_id=BASE_VIEW_ID,
        ),
    ]

    # Compare documents using the utility function
    compare_documents(doc_batch, expected_docs)


def test_airtable_connector_with_share_and_view(
    mock_get_unstructured_api_key: MagicMock, airtable_config: AirtableConfig
) -> None:
    """Test behavior when using share_id and view_id for URL generation."""
    SHARE_ID = "shrkfjEzDmLaDtK83"

    connector = AirtableConnector(
        base_id=airtable_config.base_id,
        table_name_or_id=airtable_config.table_identifier,
        treat_all_non_attachment_fields_as_metadata=False,
        share_id=SHARE_ID,
        view_id=BASE_VIEW_ID,
    )
    connector.load_credentials(
        {
            "airtable_access_token": airtable_config.access_token,
        }
    )
    doc_batch_generator = connector.load_from_state()
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
            ticket_id="2",
            created_time="2024-12-24T21:02:49.000Z",
            status_last_changed="2024-12-24T21:02:49.000Z",
            days_since_status_change=0,
            assignee="Chris Weaver (chris@onyx.app)",
            submitted_by="Chris Weaver (chris@onyx.app)",
            all_fields_as_metadata=False,
            share_id=SHARE_ID,
            view_id=BASE_VIEW_ID,
        ),
        create_test_document(
            id="reccSlIA4pZEFxPBg",
            title="Printer Issue",
            description="The office printer is not working.",
            priority="High",
            status="Open",
            ticket_id="1",
            created_time="2024-12-24T21:02:49.000Z",
            status_last_changed="2024-12-24T21:02:49.000Z",
            days_since_status_change=0,
            assignee="Chris Weaver (chris@onyx.app)",
            submitted_by="Chris Weaver (chris@onyx.app)",
            attachments=[
                (
                    "Test.pdf:\ntesting!!!",
                    (
                        f"https://airtable.com/{airtable_config.base_id}/{SHARE_ID}/"
                        f"{os.environ['AIRTABLE_TEST_TABLE_ID']}/{BASE_VIEW_ID}/reccSlIA4pZEFxPBg/"
                        "fld1u21zkJACIvAEF/attlj2UBWNEDZngCc?blocks=hide"
                    ),
                )
            ],
            all_fields_as_metadata=False,
            share_id=SHARE_ID,
            view_id=BASE_VIEW_ID,
        ),
    ]

    # Compare documents using the utility function
    compare_documents(doc_batch, expected_docs)
