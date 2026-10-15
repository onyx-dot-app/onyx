"""A connector config may only name connector files its author uploaded, and
deleting a File connector removes only files that it owns.

The route functions are called directly with the test ``db_session``."""

from collections.abc import Generator
from io import BytesIO
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource, FileOrigin
from onyx.connectors.models import InputType
from onyx.db.enums import AccessType, ConnectorCredentialPairStatus
from onyx.db.models import Connector, ConnectorCredentialPair, Credential, User
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.constants import UPLOADED_BY_USER_ID_METADATA_KEY
from onyx.file_store.postgres_file_store import PostgresBackedFileStore
from onyx.server.documents.connector import (
    create_connector_from_model,
    update_connector_from_model,
)
from onyx.server.documents.models import (
    ConnectorCredentialPairIdentifier,
    ConnectorUpdateRequest,
)
from onyx.server.manage.administrative import create_deletion_attempt_for_connector_id
from tests.external_dependency_unit.conftest import create_test_user


@pytest.fixture
def store(
    db_session: Session,  # noqa: ARG001
    tenant_context: None,  # noqa: ARG001
) -> Generator[PostgresBackedFileStore, None, None]:
    file_store = PostgresBackedFileStore()
    file_store.initialize()
    with patch(
        "onyx.server.manage.administrative.get_default_file_store",
        return_value=file_store,
    ):
        yield file_store


def _upload(
    store: PostgresBackedFileStore,
    origin: FileOrigin,
    uploader: User | None,
) -> str:
    metadata = (
        {UPLOADED_BY_USER_ID_METADATA_KEY: str(uploader.id)} if uploader else None
    )
    return store.save_file(
        content=BytesIO(b"bytes"),
        display_name="a.txt",
        file_origin=origin,
        file_type="text/plain",
        file_metadata=metadata,
    )


def _file_request(
    file_ids: list[str], metadata_file_id: str | None = None
) -> ConnectorUpdateRequest:
    return ConnectorUpdateRequest(
        name=f"file-{uuid4().hex[:8]}",
        source=DocumentSource.FILE,
        input_type=InputType.LOAD_STATE,
        connector_specific_config={
            "file_locations": file_ids,
            "file_names": ["a.txt"] * len(file_ids),
            "zip_metadata_file_id": metadata_file_id,
        },
        refresh_freq=None,
        prune_freq=None,
        indexing_start=None,
        access_type=AccessType.PRIVATE,
    )


def _create(request: ConnectorUpdateRequest, user: User, db_session: Session) -> int:
    return create_connector_from_model(
        connector_data=request, user=user, db_session=db_session
    ).id


def test_connector_config_names_only_own_uploads(
    db_session: Session, store: PostgresBackedFileStore
) -> None:
    manager = create_test_user(db_session, "file_owner")
    other = create_test_user(db_session, "file_other")
    own_upload = _upload(store, FileOrigin.CONNECTOR_FILE_UPLOAD, manager)
    others_upload = _upload(store, FileOrigin.CONNECTOR_FILE_UPLOAD, other)
    chat_upload = _upload(store, FileOrigin.CHAT_UPLOAD, manager)

    for foreign in (others_upload, chat_upload, f"missing-{uuid4()}"):
        with pytest.raises(OnyxError, match="not uploaded by you"):
            _create(_file_request([own_upload, foreign]), manager, db_session)
    # Another user's metadata file supplies the document fields.
    others_metadata = _upload(store, FileOrigin.CONNECTOR_METADATA, other)
    with pytest.raises(OnyxError, match="not uploaded by you"):
        _create(_file_request([own_upload], others_metadata), manager, db_session)

    connector_id = _create(_file_request([own_upload]), manager, db_session)

    # PATCH keeps the files the connector already names, also for an editor
    # who did not upload them, but cannot add a foreign one.
    admin = create_test_user(db_session, "file_admin", is_admin=True)
    update_connector_from_model(
        connector_id=connector_id,
        connector_data=_file_request([own_upload]),
        user=admin,
        db_session=db_session,
    )
    with pytest.raises(OnyxError, match="not uploaded by you"):
        update_connector_from_model(
            connector_id=connector_id,
            connector_data=_file_request([own_upload, others_upload]),
            user=admin,
            db_session=db_session,
        )


def test_google_sites_zip_path_names_only_own_uploads(
    db_session: Session, store: PostgresBackedFileStore
) -> None:
    manager = create_test_user(db_session, "sites_owner")
    others_zip = _upload(
        store,
        FileOrigin.CONNECTOR_FILE_UPLOAD,
        create_test_user(db_session, "sites_other"),
    )
    request = ConnectorUpdateRequest(
        name=f"sites-{uuid4().hex[:8]}",
        source=DocumentSource.GOOGLE_SITES,
        input_type=InputType.LOAD_STATE,
        connector_specific_config={
            "zip_path": others_zip,
            "base_url": "https://sites.example.com",
        },
        refresh_freq=None,
        prune_freq=None,
        indexing_start=None,
        access_type=AccessType.PRIVATE,
    )

    with pytest.raises(OnyxError, match="not uploaded by you"):
        create_connector_from_model(
            connector_data=request, user=manager, db_session=db_session
        )


def _file_cc_pair(
    db_session: Session, user: User, config: dict[str, Any]
) -> ConnectorCredentialPair:
    connector = Connector(
        name=f"file-{uuid4().hex[:8]}",
        source=DocumentSource.FILE,
        input_type=InputType.LOAD_STATE,
        connector_specific_config=config,
        refresh_freq=None,
        prune_freq=None,
        indexing_start=None,
    )
    db_session.add(connector)
    db_session.flush()
    credential = Credential(
        source=DocumentSource.FILE,
        credential_json={},
        user_id=user.id,
        admin_public=True,
    )
    db_session.add(credential)
    db_session.flush()
    cc_pair = ConnectorCredentialPair(
        connector_id=connector.id,
        credential_id=credential.id,
        name=connector.name,
        status=ConnectorCredentialPairStatus.ACTIVE,
        access_type=AccessType.PUBLIC,
        auto_sync_options=None,
    )
    db_session.add(cc_pair)
    db_session.commit()
    return cc_pair


def test_deletion_keeps_files_the_connector_does_not_own(
    db_session: Session, store: PostgresBackedFileStore
) -> None:
    admin = create_test_user(db_session, "delete_admin", is_admin=True)
    own_file = _upload(store, FileOrigin.CONNECTOR_FILE_UPLOAD, admin)
    chat_upload = _upload(store, FileOrigin.CHAT_UPLOAD, admin)
    shared_file = _upload(store, FileOrigin.CONNECTOR_FILE_UPLOAD, admin)
    _file_cc_pair(db_session, admin, {"file_locations": [shared_file]})
    # A config from before the upload check, naming files it does not own.
    planted = _file_cc_pair(
        db_session, admin, {"file_locations": [own_file, chat_upload, shared_file]}
    )

    with patch("onyx.server.manage.administrative.client_app"):
        create_deletion_attempt_for_connector_id(
            ConnectorCredentialPairIdentifier(
                connector_id=planted.connector_id,
                credential_id=planted.credential_id,
            ),
            user=admin,
            db_session=db_session,
        )

    remaining = {
        record.file_id
        for record in (
            store.read_file_record(file_id) for file_id in (chat_upload, shared_file)
        )
    }
    assert remaining == {chat_upload, shared_file}
    assert not store.has_file(own_file, FileOrigin.CONNECTOR_FILE_UPLOAD, "text/plain")
