"""POST /manage/admin/connector-with-credential: a connector and its credential
in one request. A draft credential is promoted here, and a failure leaves no
connector behind and the draft a draft. Also the draft rules of the credential
queries. Not an integration test: validation is stubbed, as
INTEGRATION_TESTS_MODE would skip it."""

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.models import InputType
from onyx.db.credentials import (
    create_draft_credential,
    delete_stale_draft_credentials,
    fetch_credential_by_id_for_user,
    fetch_credentials_for_user,
    fetch_credentials_usable_by_source_for_user,
)
from onyx.db.enums import AccessType
from onyx.db.models import Connector, ConnectorCredentialPair, Credential, User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.documents import connector as connector_api
from onyx.server.documents.connector import create_connector_with_credential
from onyx.server.documents.models import (
    ConnectorCredentialPairMetadata,
    ConnectorUpdateRequest,
    ConnectorWithCredentialCreateRequest,
    CredentialSharing,
)
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user

_SOURCE = DocumentSource.MOCK_CONNECTOR


@pytest.fixture
def users(db_session: Session) -> Generator[tuple[User, User], None, None]:
    owner = create_test_user(db_session, "draft_create_owner", is_admin=True)
    other = create_test_user(db_session, "draft_create_other", is_admin=True)
    yield owner, other
    db_session.rollback()
    credential_ids = select(Credential.id).where(
        Credential.user_id.in_([owner.id, other.id])
    )
    pairs = db_session.scalars(
        select(ConnectorCredentialPair).where(
            ConnectorCredentialPair.credential_id.in_(credential_ids)
        )
    ).all()
    connector_ids = [pair.connector_id for pair in pairs]
    for pair in pairs:
        db_session.delete(pair)
    db_session.flush()
    db_session.execute(delete(Connector).where(Connector.id.in_(connector_ids)))
    db_session.execute(delete(Credential).where(Credential.id.in_(credential_ids)))
    delete_test_user(db_session, owner, other)
    db_session.commit()


@pytest.fixture
def validation() -> Generator[MagicMock, None, None]:
    with (
        patch.object(connector_api, "validate_ccpair_for_user") as validate,
        patch.object(connector_api.client_app, "send_task"),
    ):
        yield validate


def _request(name: str, **credential: Any) -> ConnectorWithCredentialCreateRequest:
    return ConnectorWithCredentialCreateRequest(
        connector=ConnectorUpdateRequest(
            name=name,
            source=_SOURCE,
            input_type=InputType.LOAD_STATE,
            connector_specific_config={
                "mock_server_host": "localhost",
                "mock_server_port": 8001,
            },
            access_type=AccessType.PUBLIC,
        ),
        pairing=ConnectorCredentialPairMetadata(
            name=name, access_type=AccessType.PUBLIC
        ),
        **credential,
    )


def _connector(db_session: Session, name: str) -> Connector | None:
    return db_session.scalar(select(Connector).where(Connector.name == name))


def _credentials_of(db_session: Session, user: User) -> int:
    return db_session.execute(
        select(func.count())
        .select_from(Credential)
        .where(Credential.user_id == user.id)
    ).scalar_one()


def _draft(db_session: Session, user: User, values: dict[str, Any]) -> Credential:
    return create_draft_credential(_SOURCE, values, user, db_session)


def _reloaded(db_session: Session, credential_id: int) -> Credential:
    db_session.expire_all()
    credential = db_session.get(Credential, credential_id)
    assert credential is not None
    return credential


def _paired_credential(db_session: Session, cc_pair_id: int | None) -> Credential:
    pair = db_session.scalar(
        select(ConnectorCredentialPair).where(ConnectorCredentialPair.id == cc_pair_id)
    )
    assert pair is not None
    return _reloaded(db_session, pair.credential_id)


@pytest.mark.usefixtures("tenant_context", "validation")
def test_a_draft_is_promoted_and_paired_with_the_new_connector(
    db_session: Session, users: tuple[User, User]
) -> None:
    owner, _ = users
    name = f"draft-create-{uuid4().hex[:8]}"
    draft = _draft(db_session, owner, {"token": "draft-secret"})
    updated_at = _reloaded(db_session, draft.id).time_updated

    response = create_connector_with_credential(
        _request(
            name,
            credential_id=draft.id,
            credential_sharing=CredentialSharing(admin_public=False, name="Mine"),
        ),
        user=owner,
        db_session=db_session,
    )

    credential = _paired_credential(db_session, response.data)
    assert credential.id == draft.id
    assert not credential.is_draft
    assert credential.admin_public is False
    assert credential.name == "Mine"
    # Unchanged, so check results cached for the draft still apply.
    assert credential.time_updated == updated_at
    assert credential.credential_json is not None
    assert credential.credential_json.get_value(apply_mask=False) == {
        "token": "draft-secret"
    }
    assert _credentials_of(db_session, owner) == 1


@pytest.mark.usefixtures("tenant_context", "validation")
def test_values_alone_are_saved_and_paired(
    db_session: Session, users: tuple[User, User]
) -> None:
    owner, _ = users
    name = f"draft-create-{uuid4().hex[:8]}"

    response = create_connector_with_credential(
        _request(name, credential_json={"token": "typed-secret"}),
        user=owner,
        db_session=db_session,
    )

    credential = _paired_credential(db_session, response.data)
    assert not credential.is_draft
    assert credential.credential_json is not None
    assert credential.credential_json.get_value(apply_mask=False) == {
        "token": "typed-secret"
    }
    assert _credentials_of(db_session, owner) == 1


@pytest.mark.usefixtures("tenant_context", "validation")
def test_changed_values_update_the_draft_before_it_is_paired(
    db_session: Session, users: tuple[User, User]
) -> None:
    owner, _ = users
    name = f"draft-create-{uuid4().hex[:8]}"
    draft = _draft(db_session, owner, {"token": "old"})

    response = create_connector_with_credential(
        _request(name, credential_id=draft.id, credential_json={"token": "new"}),
        user=owner,
        db_session=db_session,
    )

    credential = _paired_credential(db_session, response.data)
    assert credential.id == draft.id
    assert credential.credential_json is not None
    assert credential.credential_json.get_value(apply_mask=False) == {"token": "new"}


@pytest.mark.usefixtures("tenant_context")
def test_a_failed_create_leaves_no_connector_and_keeps_the_draft(
    db_session: Session, users: tuple[User, User], validation: MagicMock
) -> None:
    owner, _ = users
    name = f"draft-create-{uuid4().hex[:8]}"
    draft = _draft(db_session, owner, {})
    validation.side_effect = ConnectorValidationError("bad settings")

    with pytest.raises(OnyxError) as error:
        create_connector_with_credential(
            _request(
                name,
                credential_id=draft.id,
                credential_sharing=CredentialSharing(name="Mine"),
            ),
            user=owner,
            db_session=db_session,
        )

    assert error.value.error_code == OnyxErrorCode.CONNECTOR_VALIDATION_FAILED
    assert _connector(db_session, name) is None
    # A draft again, for the retry.
    kept = _reloaded(db_session, draft.id)
    assert kept.is_draft
    assert kept.admin_public is False
    assert kept.name is None
    assert _credentials_of(db_session, owner) == 1


@pytest.mark.usefixtures("tenant_context")
def test_an_unexpected_failure_also_frees_the_name(
    db_session: Session, users: tuple[User, User], validation: MagicMock
) -> None:
    owner, _ = users
    name = f"draft-create-{uuid4().hex[:8]}"
    validation.side_effect = RuntimeError("unexpected")

    with pytest.raises(RuntimeError):
        create_connector_with_credential(
            _request(name, credential_json={"token": "typed-secret"}),
            user=owner,
            db_session=db_session,
        )

    assert _connector(db_session, name) is None
    db_session.expire_all()
    drafts = db_session.scalars(
        select(Credential).where(Credential.user_id == owner.id)
    ).all()
    assert [draft.is_draft for draft in drafts] == [True]


@pytest.mark.usefixtures("tenant_context", "validation")
def test_another_users_draft_creates_nothing(
    db_session: Session, users: tuple[User, User]
) -> None:
    owner, other = users
    name = f"draft-create-{uuid4().hex[:8]}"
    draft = _draft(db_session, owner, {})

    with pytest.raises(OnyxError) as error:
        create_connector_with_credential(
            _request(name, credential_id=draft.id), user=other, db_session=db_session
        )

    assert error.value.error_code == OnyxErrorCode.CREDENTIAL_NOT_FOUND
    assert _connector(db_session, name) is None
    assert _reloaded(db_session, draft.id).is_draft
    assert _credentials_of(db_session, other) == 0


@pytest.mark.usefixtures("tenant_context", "validation")
def test_a_saved_credential_is_paired_and_kept(
    db_session: Session, users: tuple[User, User]
) -> None:
    owner, _ = users
    credential = Credential(source=_SOURCE, credential_json={}, user_id=owner.id)
    db_session.add(credential)
    db_session.commit()
    name = f"draft-create-{uuid4().hex[:8]}"

    response = create_connector_with_credential(
        _request(name, credential_id=credential.id), user=owner, db_session=db_session
    )

    assert _paired_credential(db_session, response.data).id == credential.id
    assert _credentials_of(db_session, owner) == 1


@pytest.mark.usefixtures("tenant_context", "validation")
def test_sharing_a_saved_credential_is_rejected(
    db_session: Session, users: tuple[User, User]
) -> None:
    owner, _ = users
    credential = Credential(source=_SOURCE, credential_json={}, user_id=owner.id)
    db_session.add(credential)
    db_session.commit()
    name = f"draft-create-{uuid4().hex[:8]}"

    with pytest.raises(OnyxError) as error:
        create_connector_with_credential(
            _request(
                name,
                credential_id=credential.id,
                credential_sharing=CredentialSharing(),
            ),
            user=owner,
            db_session=db_session,
        )

    assert error.value.error_code == OnyxErrorCode.INVALID_INPUT
    assert _connector(db_session, name) is None


@pytest.mark.usefixtures("tenant_context")
def test_drafts_are_hidden_from_credential_listings(
    db_session: Session, users: tuple[User, User]
) -> None:
    owner, other = users
    draft = _draft(db_session, owner, {})

    for user in (owner, other):
        assert draft.id not in {
            credential.id for credential in fetch_credentials_for_user(db_session, user)
        }
        assert draft.id not in {
            credential.id
            for credential in fetch_credentials_usable_by_source_for_user(
                db_session, user, _SOURCE
            )
        }
        assert fetch_credential_by_id_for_user(draft.id, user, db_session) is None
    assert (
        fetch_credential_by_id_for_user(
            draft.id, owner, db_session, include_own_drafts=True
        )
        is not None
    )
    assert (
        fetch_credential_by_id_for_user(
            draft.id, other, db_session, include_own_drafts=True
        )
        is None
    )


@pytest.mark.usefixtures("tenant_context")
def test_only_stale_drafts_are_deleted(
    db_session: Session, users: tuple[User, User]
) -> None:
    owner, _ = users
    stale = _draft(db_session, owner, {})
    fresh = _draft(db_session, owner, {})
    saved = Credential(source=_SOURCE, credential_json={}, user_id=owner.id)
    db_session.add(saved)
    db_session.commit()
    stale_id, fresh_id, saved_id = stale.id, fresh.id, saved.id
    long_ago = datetime.now(timezone.utc) - timedelta(days=30)
    db_session.execute(
        update(Credential)
        .where(Credential.id.in_([stale.id, saved.id]))
        .values(time_updated=long_ago)
    )
    db_session.commit()

    delete_stale_draft_credentials(
        db_session, updated_before=datetime.now(timezone.utc) - timedelta(days=7)
    )

    db_session.expire_all()
    assert db_session.get(Credential, stale_id) is None
    assert db_session.get(Credential, fresh_id) is not None
    assert db_session.get(Credential, saved_id) is not None


def test_a_create_needs_a_credential() -> None:
    with pytest.raises(PydanticValidationError):
        _request("name")
