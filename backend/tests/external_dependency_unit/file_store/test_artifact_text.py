"""The text of a published file version (file_store/utils.py:
get_or_extract_artifact_text) against Postgres and the file store: extracted
once by page, cached under ARTIFACT_TEXT_FILE_PREFIX + file_id, and deleted
with its version."""

from io import BytesIO
from unittest.mock import patch
from uuid import uuid4

import pytest
from reportlab.pdfgen import canvas
from sqlalchemy.orm import Session

from onyx.configs.constants import DEFAULT_PERSONA_ID, FileOrigin
from onyx.db.chat import delete_chat_artifact_files, save_chat_artifact
from onyx.db.models import ChatSession
from onyx.file_processing import extract_file_text
from onyx.file_store import utils as file_store_utils
from onyx.file_store.constants import ARTIFACT_TEXT_FILE_PREFIX
from onyx.file_store.file_store import get_default_file_store
from onyx.file_store.utils import get_or_extract_artifact_text
from onyx.tools.tool_implementations.sandbox.models import ArtifactAtPath
from tests.external_dependency_unit.conftest import MakeTestUser

pytestmark = pytest.mark.usefixtures("tenant_context", "initialize_file_store")


def _two_page_pdf() -> bytes:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer)
    for text in ("Page one about herons.", "Page two about egrets."):
        pdf.drawString(72, 720, text)
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def test_the_text_is_extracted_once_and_deleted_with_its_version(
    db_session: Session, make_test_user: MakeTestUser
) -> None:
    owner = make_test_user("artifact_text_owner")
    chat = ChatSession(id=uuid4(), user_id=owner.id, persona_id=DEFAULT_PERSONA_ID)
    db_session.add(chat)
    db_session.commit()
    file = save_chat_artifact(
        _two_page_pdf(),
        name="birds.pdf",
        mime_type="application/pdf",
        target=ArtifactAtPath(chat_session_id=chat.id, path="/workspace/birds.pdf"),
        title=None,
        thumbnail=None,
    )

    first = get_or_extract_artifact_text(file.file_id, file.name, file.size)
    with patch.object(file_store_utils, "extract_text_pages") as extract:
        cached = get_or_extract_artifact_text(file.file_id, file.name, file.size)

    extract.assert_not_called()
    assert first == cached
    assert cached is not None and cached.paged and not cached.truncated
    assert len(cached.pages) == 2
    assert "herons" in cached.pages[0] and "egrets" in cached.pages[1]
    assert get_or_extract_artifact_text(file.file_id, file.name, 60 << 20) is None

    delete_chat_artifact_files([(file.file_id, None)])

    assert not get_default_file_store().has_file(
        f"{ARTIFACT_TEXT_FILE_PREFIX}{file.file_id}",
        file_origin=FileOrigin.PLAINTEXT_CACHE,
        file_type="text/plain",
    )


def test_an_io_error_during_extraction_raises_and_caches_no_text(
    db_session: Session, make_test_user: MakeTestUser
) -> None:
    owner = make_test_user("artifact_text_io_error")
    chat = ChatSession(id=uuid4(), user_id=owner.id, persona_id=DEFAULT_PERSONA_ID)
    db_session.add(chat)
    db_session.commit()
    file = save_chat_artifact(
        b"Notes about herons.\n",
        name="notes.md",
        mime_type="text/markdown",
        target=ArtifactAtPath(chat_session_id=chat.id, path="/workspace/notes.md"),
        title=None,
        thumbnail=None,
    )
    try:
        with (
            patch.object(
                extract_file_text,
                "extract_file_text_locally",
                side_effect=OSError("connection reset"),
            ),
            pytest.raises(OSError),
        ):
            get_or_extract_artifact_text(file.file_id, file.name, file.size)

        retried = get_or_extract_artifact_text(file.file_id, file.name, file.size)
        assert retried is not None
        assert "herons" in retried.pages[0]
    finally:
        delete_chat_artifact_files([(file.file_id, None)])
