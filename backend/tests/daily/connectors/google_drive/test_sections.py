import time
from collections.abc import Callable
from unittest.mock import MagicMock
from unittest.mock import patch

from danswer.connectors.google_drive.connector import GoogleDriveConnector
from danswer.connectors.models import Document
from tests.daily.connectors.google_drive.consts_and_utils import ADMIN_EMAIL
from tests.daily.connectors.google_drive.consts_and_utils import SECTIONS_FOLDER_URL


@patch(
    "danswer.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_google_drive_sections(
    mock_get_api_key: MagicMock,
    google_drive_oauth_connector_factory: Callable[..., GoogleDriveConnector],
    google_drive_service_acct_connector_factory: Callable[..., GoogleDriveConnector],
) -> None:
    oauth_connector = google_drive_oauth_connector_factory(
        primary_admin_email=ADMIN_EMAIL,
        include_shared_drives=False,
        include_my_drives=False,
        include_files_shared_with_me=False,
        shared_folder_urls=SECTIONS_FOLDER_URL,
        shared_drive_urls=None,
        my_drive_emails=None,
    )
    service_acct_connector = google_drive_service_acct_connector_factory(
        primary_admin_email=ADMIN_EMAIL,
        include_shared_drives=False,
        include_my_drives=False,
        include_files_shared_with_me=False,
        shared_folder_urls=SECTIONS_FOLDER_URL,
        shared_drive_urls=None,
        my_drive_emails=None,
    )
    for connector in [oauth_connector, service_acct_connector]:
        retrieved_docs: list[Document] = []
        for doc_batch in connector.poll_source(0, time.time()):
            retrieved_docs.extend(doc_batch)

        # Verify we got the 1 doc with sections
        assert len(retrieved_docs) == 1

        # Verify each section has the expected structure
        doc = retrieved_docs[0]
        assert len(doc.sections) == 5

        header_section = doc.sections[0]
        assert header_section.text == "Title\n\nThis is a Google Doc with sections"
        assert header_section.link is not None
        assert header_section.link.endswith(
            "?tab=t.0#heading=h.hfjc17k6qwzt"
        ) or header_section.link.endswith("?tab=t.0#heading=h.hfjc17k6qwzt")

        section_1 = doc.sections[1]
        assert section_1.text == "Section 1\n\nSection 1 content"
        assert section_1.link is not None
        assert section_1.link.endswith("?tab=t.0#heading=h.8slfx752a3g5")

        section_2 = doc.sections[2]
        assert section_2.text == "Sub-Section 1-1\n\nSub-Section 1-1 content"
        assert section_2.link is not None
        assert section_2.link.endswith("?tab=t.0#heading=h.4kj3ayade1bp")

        section_3 = doc.sections[3]
        assert section_3.text == "Sub-Section 1-2\n\nSub-Section 1-2 content"
        assert section_3.link is not None
        assert section_3.link.endswith("?tab=t.0#heading=h.pm6wrpzgk69l")

        section_4 = doc.sections[4]
        assert section_4.text == "Section 2\n\nSection 2 content"
        assert section_4.link is not None
        assert section_4.link.endswith("?tab=t.0#heading=h.2m0s9youe2k9")
