from collections.abc import Callable
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.connectors.google_drive.connector import GoogleDriveConnector
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from tests.daily.connectors.google_drive.consts_and_utils import ADMIN_EMAIL
from tests.daily.connectors.google_drive.consts_and_utils import (
    assert_resource_key_shortcut_target_in_retrieved_docs,
)
from tests.daily.connectors.google_drive.consts_and_utils import load_connector_outputs
from tests.daily.connectors.google_drive.consts_and_utils import (
    RESOURCE_KEY_SHORTCUT_TARGET_DOC_ID,
)
from tests.daily.connectors.google_drive.consts_and_utils import (
    RESOURCE_KEY_SHORTCUT_TARGET_NAME,
)
from tests.daily.connectors.google_drive.consts_and_utils import (
    SHORTCUTS_GALORE_FOLDER_ID,
)
from tests.utils.secret_names import TestSecret

pytestmark = pytest.mark.secrets(TestSecret.GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON_STR)

SHORTCUTS_GALORE_FOLDER_URL = (
    f"https://drive.google.com/drive/folders/{SHORTCUTS_GALORE_FOLDER_ID}"
)

JUST_CHECKING_DOC_ID = "193JrSy0zEzI6We01MeBnWm17puImlMUFqPOUiVQuNUY"
SILLY_GUY_DOC_ID = "1l1eAJy9llAQBa3fcOpjLijswXi2fiDJFGst0EmVONk0"
NUMBER_2_DOC_ID = "1TJN3XJ-rzfnIv0qdyiKdXp__FJt1npRqp3WKLO3R-dM"

EXPECTED_DOC_NAMES = {
    RESOURCE_KEY_SHORTCUT_TARGET_NAME,
    "just checking",
    "file_0.txt",
    "file_1.txt",
    "I'm a silly guy",
    "number 2",
}


def _doc_text(doc: Document) -> str:
    return " ".join(
        section.text
        for section in doc.sections
        if isinstance(section, TextSection) and section.text is not None
    )


def _doc_id_suffix(doc: Document) -> str:
    return doc.id.removesuffix("/").split("/")[-1]


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key",
    return_value=None,
)
def test_shared_folder_shortcuts_resolve_files_and_folders(
    mock_get_api_key: MagicMock,  # noqa: ARG001
    google_drive_service_acct_connector_factory: Callable[..., GoogleDriveConnector],
) -> None:
    connector = google_drive_service_acct_connector_factory(
        primary_admin_email=ADMIN_EMAIL,
        include_shared_drives=False,
        include_my_drives=False,
        include_files_shared_with_me=False,
        shared_drive_urls=None,
        shared_folder_urls=SHORTCUTS_GALORE_FOLDER_URL,
        my_drive_emails=None,
        specific_user_emails=ADMIN_EMAIL,
    )

    output = load_connector_outputs(connector)

    docs_by_name = {doc.semantic_identifier: doc for doc in output.documents}
    assert set(docs_by_name) == EXPECTED_DOC_NAMES
    assert len(docs_by_name) == len(output.documents)

    retrieved_ids = {_doc_id_suffix(doc) for doc in output.documents}
    assert JUST_CHECKING_DOC_ID in retrieved_ids
    assert SILLY_GUY_DOC_ID in retrieved_ids
    assert NUMBER_2_DOC_ID in retrieved_ids
    assert RESOURCE_KEY_SHORTCUT_TARGET_DOC_ID in retrieved_ids
    assert_resource_key_shortcut_target_in_retrieved_docs(output.documents)

    assert _doc_text(docs_by_name["file_0.txt"]) == "This is file 0"
    assert _doc_text(docs_by_name["file_1.txt"]) == "This is file 1"
    assert "At least this guy should start out as indexed." in _doc_text(
        docs_by_name["just checking"]
    )
    assert "recursion depth is exceeded" in _doc_text(docs_by_name["I'm a silly guy"])
    assert "ancient Mongolians used to live in yurts" in _doc_text(
        docs_by_name["number 2"]
    )
