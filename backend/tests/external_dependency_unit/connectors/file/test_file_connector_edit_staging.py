"""Connector uploads record a content hash; files uploaded for an edit are
staged for their pair, claimed by apply, and deleted by cleanup when no apply
claims them in time."""

import hashlib
from datetime import timedelta

import pytest
from sqlalchemy import func, update
from sqlalchemy.orm import Session

from onyx.configs.constants import FileOrigin
from onyx.connectors.file.config import LocalFileConnectorConfig
from onyx.connectors.file.edit_staging import (
    claim_staged_files__no_commit,
    delete_expired_staged_files,
    ensure_files_staged_for_edit,
)
from onyx.db.file_record import (
    get_filerecord_by_file_id_optional,
    get_stored_file_facts,
)
from onyx.db.models import FileRecord
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import get_default_file_store
from onyx.server.documents.connector import upload_files
from tests.external_dependency_unit.connectors.file.file_edit_helpers import (
    FilePair,
    read_json_file,
    staged_file_ids,
    text_upload,
    zip_upload,
)

_A = b"alpha content"
_B = b"bravo content"


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _age(db_session: Session, file_id: str, age: timedelta) -> None:
    db_session.execute(
        update(FileRecord)
        .where(FileRecord.file_id == file_id)
        .values(created_at=func.now() - age)
    )
    db_session.commit()


def _config(file_pair: FilePair) -> LocalFileConnectorConfig:
    return LocalFileConnectorConfig.model_validate(
        file_pair.pair.connector.connector_specific_config
    )


def test_connector_uploads_record_a_content_hash(
    db_session: Session,
    file_pair: FilePair,
) -> None:
    uploaded = upload_files(
        [text_upload("a.txt", _A), zip_upload({"b.txt": _B}, [])],
        FileOrigin.CONNECTOR_FILE_UPLOAD,
    )
    user_upload = upload_files([text_upload("c.txt", _A)], FileOrigin.USER_FILE)
    file_pair.file_ids.extend(
        [*uploaded.file_paths, *user_upload.file_paths]
        + ([uploaded.zip_metadata_file_id] if uploaded.zip_metadata_file_id else [])
    )

    facts = get_stored_file_facts(db_session, uploaded.file_paths)
    assert [facts[file_id].content_sha256 for file_id in uploaded.file_paths] == [
        _sha256(_A),
        _sha256(_B),
    ]
    # The stream was read back to its start before saving.
    assert get_default_file_store().read_file(uploaded.file_paths[0]).read() == _A

    user_record = get_filerecord_by_file_id_optional(
        user_upload.file_paths[0], db_session
    )
    assert user_record is not None
    assert user_record.file_metadata is None


def test_staging_marks_new_files_and_reuses_current_ones(
    db_session: Session,
    file_pair: FilePair,
) -> None:
    [current_a] = file_pair.save_current_files(db_session, {"a.txt": _A})

    staged = file_pair.stage(
        db_session,
        [text_upload("a.txt", _A), text_upload("b.txt", _B)],
    )

    assert staged.file_paths[0] == current_a
    new_b = staged.file_paths[1]
    assert staged.file_names == ["a.txt", "b.txt"]
    assert staged.zip_metadata_file_id is None
    # The duplicate upload of a.txt was deleted.
    assert staged_file_ids(db_session, file_pair.pair.id) == {new_b}
    assert get_stored_file_facts(db_session, [new_b])[new_b].content_sha256 == (
        _sha256(_B)
    )


def test_staging_merges_zip_metadata_into_the_current_metadata(
    db_session: Session,
    file_pair: FilePair,
) -> None:
    file_pair.save_current_files(
        db_session,
        {"a.txt": _A},
        zip_metadata={"a.txt": {"filename": "a.txt", "title": "A"}},
    )

    staged = file_pair.stage(
        db_session,
        [zip_upload({"b.txt": _B}, [{"filename": "b.txt", "title": "B"}])],
    )

    assert staged.zip_metadata_file_id is not None
    assert read_json_file(staged.zip_metadata_file_id) == {
        "a.txt": {"filename": "a.txt", "title": "A"},
        "b.txt": {"filename": "b.txt", "title": "B"},
    }
    # Only the merged metadata file and b.txt stay staged.
    assert staged_file_ids(db_session, file_pair.pair.id) == {
        staged.file_paths[0],
        staged.zip_metadata_file_id,
    }


def test_apply_claims_only_the_files_staged_for_its_pair(
    db_session: Session,
    file_pair: FilePair,
) -> None:
    file_pair.save_current_files(db_session, {"a.txt": _A})
    old = _config(file_pair)
    staged = file_pair.stage(db_session, [text_upload("b.txt", _B)])
    new = old.model_copy(
        update={"file_locations": [*old.file_locations, *staged.file_paths]}
    )

    with pytest.raises(OnyxError) as exc:
        claim_staged_files__no_commit(db_session, file_pair.pair.id + 1, old, new)
    assert exc.value.error_code == OnyxErrorCode.INVALID_INPUT
    db_session.rollback()

    claim_staged_files__no_commit(db_session, file_pair.pair.id, old, new)
    db_session.commit()
    assert staged_file_ids(db_session, file_pair.pair.id) == set()

    # A claimed file is no longer staged, so it cannot be claimed again.
    with pytest.raises(OnyxError):
        claim_staged_files__no_commit(db_session, file_pair.pair.id, old, new)


def test_staged_files_expire(
    db_session: Session,
    file_pair: FilePair,
) -> None:
    file_pair.save_current_files(db_session, {"a.txt": _A})
    old = _config(file_pair)
    staged = file_pair.stage(
        db_session,
        [
            text_upload("fresh.txt", b"fresh"),
            text_upload("late.txt", b"late"),
            text_upload("expired.txt", b"expired"),
            text_upload("claimed.txt", b"claimed"),
        ],
    )
    fresh, late, expired, claimed = staged.file_paths
    _age(db_session, late, timedelta(days=1, hours=1))
    _age(db_session, expired, timedelta(days=2, hours=2))

    # A day after the upload, a plan can no longer use the file ...
    ensure_files_staged_for_edit(db_session, file_pair.pair.id, [fresh])
    with pytest.raises(OnyxError):
        ensure_files_staged_for_edit(db_session, file_pair.pair.id, [late])
    # ... but a plan made before then can still claim it.
    claim_staged_files__no_commit(
        db_session,
        file_pair.pair.id,
        old,
        old.model_copy(update={"file_locations": [late, claimed]}),
    )
    db_session.commit()
    _age(db_session, claimed, timedelta(days=3))

    delete_expired_staged_files()

    db_session.expire_all()
    remaining = {
        file_id
        for file_id in staged.file_paths
        if get_filerecord_by_file_id_optional(file_id, db_session) is not None
    }
    # Only the expired, unclaimed file is deleted.
    assert remaining == {fresh, late, claimed}
