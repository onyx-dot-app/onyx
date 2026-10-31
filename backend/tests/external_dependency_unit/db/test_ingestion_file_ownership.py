from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.connectors.models import DocumentBase, ImageSection, TextSection
from onyx.db.models import User, UserFile
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.onyx_api.ingestion import upsert_ingestion_doc
from onyx.server.onyx_api.models import IngestionDocument


@pytest.mark.parametrize("reference", ["foreign", "missing"])
@pytest.mark.parametrize("section_type", ["image", "text"])
def test_ingestion_only_accepts_owned_image_references(
    db_session: Session, reference: str, section_type: str
) -> None:
    user = User(
        id=uuid4(), email=f"ingestion-{uuid4()}@example.com", hashed_password="unused"
    )
    other = User(
        id=uuid4(), email=f"ingestion-{uuid4()}@example.com", hashed_password="unused"
    )
    file_id = str(uuid4())
    db_session.add_all([user, other])
    db_session.flush()
    upload = UserFile(
        id=uuid4(),
        user_id=other.id,
        file_id=file_id,
        name="image.png",
        file_type="image/png",
    )
    if reference == "foreign":
        db_session.add(upload)
        db_session.flush()
    section = (
        ImageSection(image_file_id=file_id)
        if section_type == "image"
        else TextSection(text="Uploaded image", image_file_id=file_id)
    )
    payload = IngestionDocument(
        document=DocumentBase(
            id="image-document",
            semantic_identifier="Image document",
            metadata={},
            sections=[section],
        )
    )
    try:
        with patch(
            "onyx.server.onyx_api.ingestion.get_connector_credential_pair_from_id",
            return_value=None,
        ) as get_connection:
            with pytest.raises(OnyxError) as error:
                upsert_ingestion_doc(payload, user, db_session)
            assert error.value.error_code == OnyxErrorCode.VALIDATION_ERROR
            get_connection.assert_not_called()

            upload.user_id = user.id
            db_session.add(upload)
            db_session.flush()
            with pytest.raises(OnyxError) as error:
                upsert_ingestion_doc(payload, user, db_session)
            assert error.value.error_code == OnyxErrorCode.CONNECTOR_NOT_FOUND
            get_connection.assert_called_once()
    finally:
        db_session.rollback()
