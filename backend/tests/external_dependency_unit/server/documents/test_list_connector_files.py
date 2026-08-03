"""Tests for GET /manage/admin/connector/{connector_id}/files.

The endpoint used to issue a file-record query plus an object-store size
lookup per file (O(N) round-trips), which made it unusably slow for large
file connectors. It now resolves every file in a single batched query
against ``file_record``, using the persisted ``file_size`` column.

We invoke the FastAPI route function directly with a constructed admin
``User`` and the test ``db_session``, matching the pattern used elsewhere
in ``external_dependency_unit``.
"""

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource, FileOrigin
from onyx.connectors.models import InputType
from onyx.db.enums import AccessType, ConnectorCredentialPairStatus
from onyx.db.file_record import delete_filerecord_by_file_id, upsert_filerecord
from onyx.db.models import Connector, ConnectorCredentialPair, Credential, UserRole
from onyx.server.documents.connector import list_connector_files
from tests.external_dependency_unit.conftest import create_test_user


def test_list_connector_files_batched_lookup(db_session: Session) -> None:
    admin_user = create_test_user(db_session, "files_admin", role=UserRole.ADMIN)

    suffix = uuid4().hex[:8]
    sized_id_a = f"test-files-{suffix}-a"
    sized_id_b = f"test-files-{suffix}-b"
    legacy_id = f"test-files-{suffix}-legacy"
    missing_id = f"test-files-{suffix}-missing"

    for file_id, file_size in [
        (sized_id_a, 123),
        (sized_id_b, 45678),
        (legacy_id, None),  # pre-migration row: no persisted size
    ]:
        upsert_filerecord(
            file_id=file_id,
            display_name=file_id,
            file_origin=FileOrigin.CONNECTOR,
            file_type="text/plain",
            bucket_name="test-bucket",
            object_key=f"test/{file_id}",
            db_session=db_session,
            file_size=file_size,
        )

    connector = Connector(
        name=f"test-file-connector-{suffix}",
        source=DocumentSource.FILE,
        input_type=InputType.LOAD_STATE,
        connector_specific_config={
            "file_locations": [sized_id_a, sized_id_b, legacy_id, missing_id],
            # Only 3 names for 4 locations: the legacy normalization must pad
            # the last entry with its file_id.
            "file_names": ["a.txt", "b.pdf", "legacy.md"],
        },
        refresh_freq=None,
        prune_freq=None,
        indexing_start=None,
    )
    db_session.add(connector)
    db_session.flush()

    credential = Credential(
        source=DocumentSource.FILE,
        credential_json={},
        user_id=admin_user.id,
        admin_public=True,
    )
    db_session.add(credential)
    db_session.flush()

    cc_pair = ConnectorCredentialPair(
        connector_id=connector.id,
        credential_id=credential.id,
        name=f"test-file-cc-pair-{suffix}",
        status=ConnectorCredentialPairStatus.ACTIVE,
        access_type=AccessType.PUBLIC,
        auto_sync_options=None,
    )
    db_session.add(cc_pair)
    db_session.commit()

    try:
        response = list_connector_files(
            connector_id=connector.id,
            user=admin_user,
            db_session=db_session,
        )

        assert [f.file_id for f in response.files] == [
            sized_id_a,
            sized_id_b,
            legacy_id,
            missing_id,
        ]
        assert [f.file_name for f in response.files] == [
            "a.txt",
            "b.pdf",
            "legacy.md",
            missing_id,
        ]
        assert [f.file_size for f in response.files] == [123, 45678, None, None]

        # Seeded records carry their creation timestamp; the missing record
        # falls back to bare file info.
        for seeded in response.files[:3]:
            assert seeded.upload_date is not None
        assert response.files[3].upload_date is None
    finally:
        db_session.delete(cc_pair)
        db_session.delete(credential)
        db_session.delete(connector)
        for file_id in [sized_id_a, sized_id_b, legacy_id]:
            delete_filerecord_by_file_id(file_id=file_id, db_session=db_session)
        db_session.commit()


def test_list_connector_files_degrades_to_basic_info_on_lookup_failure(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A record-lookup failure must not fail the listing — entries degrade to
    id + name with no size/date, matching the old per-file fallback."""
    admin_user = create_test_user(db_session, "files_admin_fb", role=UserRole.ADMIN)

    suffix = uuid4().hex[:8]
    file_id = f"test-files-{suffix}-fb"

    connector = Connector(
        name=f"test-file-connector-{suffix}",
        source=DocumentSource.FILE,
        input_type=InputType.LOAD_STATE,
        connector_specific_config={
            "file_locations": [file_id],
            "file_names": ["fb.txt"],
        },
        refresh_freq=None,
        prune_freq=None,
        indexing_start=None,
    )
    db_session.add(connector)
    db_session.flush()

    credential = Credential(
        source=DocumentSource.FILE,
        credential_json={},
        user_id=admin_user.id,
        admin_public=True,
    )
    db_session.add(credential)
    db_session.flush()

    cc_pair = ConnectorCredentialPair(
        connector_id=connector.id,
        credential_id=credential.id,
        name=f"test-file-cc-pair-{suffix}",
        status=ConnectorCredentialPairStatus.ACTIVE,
        access_type=AccessType.PUBLIC,
        auto_sync_options=None,
    )
    db_session.add(cc_pair)
    db_session.commit()

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("simulated record-lookup failure")

    monkeypatch.setattr(
        "onyx.server.documents.connector.get_filerecords_by_file_ids", _boom
    )

    try:
        response = list_connector_files(
            connector_id=connector.id,
            user=admin_user,
            db_session=db_session,
        )

        assert len(response.files) == 1
        assert response.files[0].file_id == file_id
        assert response.files[0].file_name == "fb.txt"
        assert response.files[0].file_size is None
        assert response.files[0].upload_date is None
    finally:
        db_session.delete(cc_pair)
        db_session.delete(credential)
        db_session.delete(connector)
        db_session.commit()
