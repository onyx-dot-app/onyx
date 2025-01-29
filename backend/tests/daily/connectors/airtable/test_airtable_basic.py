import os
from collections.abc import Generator
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.airtable.airtable_connector import AirtableConnector
from onyx.connectors.models import Document
from onyx.connectors.models import Section


@pytest.fixture(
    params=[
        ("table_name", "table_name"),
        ("table_id", "table_id"),
    ]
)
def airtable_connector(request: pytest.FixtureRequest) -> AirtableConnector:
    param_type, param_key = request.param
    table_identifier = os.environ.get(f"AIRTABLE_TEST_{param_key.upper()}")
    base_id = os.environ.get("AIRTABLE_TEST_BASE_ID")
    access_token = os.environ.get("AIRTABLE_ACCESS_TOKEN")

    missing_vars = []
    if not table_identifier:
        missing_vars.append(f"AIRTABLE_TEST_{param_key.upper()}")
    if not base_id:
        missing_vars.append("AIRTABLE_TEST_BASE_ID")
    if not access_token:
        missing_vars.append("AIRTABLE_ACCESS_TOKEN")

    if missing_vars:
        raise RuntimeError(
            f"Required environment variables not set: {', '.join(missing_vars)}. "
            "These variables are required to run Airtable connector tests."
        )

    connector = AirtableConnector(
        base_id=str(base_id),
        table_name_or_id=str(table_identifier),
        treat_all_non_attachment_fields_as_metadata=False,
    )

    connector.load_credentials(
        {
            "airtable_access_token": str(access_token),
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
    attachments: list[tuple[str, str]] | None = None,
    all_fields_as_metadata: bool = False,
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
    link_base = f"https://airtable.com/{base_id}/{table_id}"
    sections = []

    if not all_fields_as_metadata:
        sections.extend(
            [
                Section(
                    text=f"Title:\n------------------------\n{title}\n------------------------",
                    link=f"{link_base}/{id}",
                ),
                Section(
                    text=f"Description:\n------------------------\n{description}\n------------------------",
                    link=f"{link_base}/{id}",
                ),
            ]
        )

    if attachments:
        for attachment_text, attachment_link in attachments:
            sections.append(
                Section(
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
        sections=sections,
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


@pytest.fixture
def mock_get_api_key() -> Generator[MagicMock, None, None]:
    with patch(
        "onyx.file_processing.extract_file_text.get_unstructured_api_key",
        return_value=None,
    ) as mock:
        yield mock


def test_airtable_connector_parameter_validation() -> None:
    """Test that treat_all_non_attachment_fields_as_metadata is required and has no default."""
    with pytest.raises(
        TypeError,
        match=r"AirtableConnector\.__init__\(\) missing 1 required positional argument: 'treat_all_non_attachment_fields_as_metadata'",
    ):
        AirtableConnector(
            base_id="test_base",
            table_name_or_id="test_table",
        )


def test_airtable_connector_all_metadata(
    mock_get_api_key: MagicMock, request: pytest.FixtureRequest
) -> None:
    """Test behavior when all non-attachment fields are treated as metadata."""
    table_name = os.environ.get("AIRTABLE_TEST_TABLE_NAME")
    base_id = os.environ.get("AIRTABLE_TEST_BASE_ID")
    access_token = os.environ.get("AIRTABLE_ACCESS_TOKEN")
    if not all([table_name, base_id, access_token]):
        pytest.skip("Required environment variables not set")
    connector = AirtableConnector(
        base_id=str(base_id),
        table_name_or_id=str(table_name),
        treat_all_non_attachment_fields_as_metadata=True,
    )
    connector.load_credentials(
        {
            "airtable_access_token": str(access_token),
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
            all_fields_as_metadata=True,
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
            all_fields_as_metadata=True,
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

        # Compare sections - should only contain attachments
        for section in actual.sections:
            assert (
                "Attachment:" in section.text
            ), f"Non-attachment section found in document {actual.id}"
            assert (
                section.link and "blocks=hide" in section.link
            ), f"Non-attachment link found in document {actual.id}"


def test_airtable_connector_with_attachments(
    mock_get_api_key: MagicMock, airtable_connector: AirtableConnector
) -> None:
    """Test the default behavior where only specific field types are treated as metadata."""
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
            attachments=[
                (
                    "Test.pdf:\ntesting!!!",
                    # hard code link for now
                    "https://airtable.com/appCXJqDFS4gea8tn/tblRxFQsTlBBZdRY1/viwVUEJjWPd8XYjh8/reccSlIA4pZEFxPBg/fld1u21zkJACIvAEF/attlj2UBWNEDZngCc?blocks=hide",
                )
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
