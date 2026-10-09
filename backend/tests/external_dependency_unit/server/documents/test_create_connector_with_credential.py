"""POST /manage/admin/connector-with-credential: a connector and its credential
in one request. A draft credential is saved here for the first time, and a
failure leaves neither row behind. Not an integration test: validation is
stubbed, as INTEGRATION_TESTS_MODE would skip it."""

from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from onyx.auth.sealed import seal_draft_credential
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.models import InputType
from onyx.db.enums import AccessType
from onyx.db.models import Connector, ConnectorCredentialPair, Credential, User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.documents import connector as connector_api
from onyx.server.documents.connector import create_connector_with_credential
from onyx.server.documents.draft_credentials import resolve_draft_credential
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


@pytest.mark.usefixtures("tenant_context", "validation")
def test_a_draft_is_saved_once_and_paired_with_the_new_connector(
    db_session: Session, users: tuple[User, User]
) -> None:
    owner, _ = users
    name = f"draft-create-{uuid4().hex[:8]}"
    draft = seal_draft_credential(
        {"token": "draft-secret"}, user_id=owner.id, source=_SOURCE
    )

    response = create_connector_with_credential(
        _request(
            name,
            draft_credential=draft,
            credential_sharing=CredentialSharing(admin_public=False, name="Mine"),
        ),
        user=owner,
        db_session=db_session,
    )

    pair = db_session.scalar(
        select(ConnectorCredentialPair).where(
            ConnectorCredentialPair.id == response.data
        )
    )
    assert pair is not None
    connector = _connector(db_session, name)
    assert connector is not None and pair.connector_id == connector.id
    credential = db_session.get(Credential, pair.credential_id)
    assert credential is not None
    assert credential.user_id == owner.id
    assert credential.admin_public is False
    assert credential.name == "Mine"
    assert credential.credential_json is not None
    assert credential.credential_json.get_value(apply_mask=False) == {
        "token": "draft-secret"
    }
    assert _credentials_of(db_session, owner) == 1


@pytest.mark.usefixtures("tenant_context", "validation")
def test_typed_values_are_saved_once_and_paired(
    db_session: Session, users: tuple[User, User]
) -> None:
    owner, _ = users
    name = f"draft-create-{uuid4().hex[:8]}"

    response = create_connector_with_credential(
        _request(name, credential_json={"token": "typed-secret"}),
        user=owner,
        db_session=db_session,
    )

    pair = db_session.scalar(
        select(ConnectorCredentialPair).where(
            ConnectorCredentialPair.id == response.data
        )
    )
    assert pair is not None
    credential = db_session.get(Credential, pair.credential_id)
    assert credential is not None and credential.credential_json is not None
    assert credential.credential_json.get_value(apply_mask=False) == {
        "token": "typed-secret"
    }
    assert _credentials_of(db_session, owner) == 1


@pytest.mark.usefixtures("tenant_context")
def test_a_failed_create_leaves_no_connector_and_no_credential(
    db_session: Session, users: tuple[User, User], validation: MagicMock
) -> None:
    owner, _ = users
    name = f"draft-create-{uuid4().hex[:8]}"
    draft = seal_draft_credential({}, user_id=owner.id, source=_SOURCE)
    validation.side_effect = ConnectorValidationError("bad settings")

    with pytest.raises(OnyxError) as error:
        create_connector_with_credential(
            _request(name, draft_credential=draft), user=owner, db_session=db_session
        )

    assert error.value.error_code == OnyxErrorCode.CONNECTOR_VALIDATION_FAILED
    assert _connector(db_session, name) is None
    assert _credentials_of(db_session, owner) == 0


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
    assert _credentials_of(db_session, owner) == 0


@pytest.mark.usefixtures("tenant_context")
def test_typed_values_are_sealed_in_the_shape_a_save_gives(
    users: tuple[User, User],
) -> None:
    owner, _ = users

    resolved = resolve_draft_credential(
        credential_json={"confluence_access_token": "typed-secret"},
        draft_credential=None,
        source=DocumentSource.CONFLUENCE,
        user=owner,
    )

    assert resolved is not None
    draft, _ = resolved
    # The account check reads the keys the family codec adds on a save.
    assert draft.credential_json == {
        "confluence_username": None,
        "confluence_access_token": "typed-secret",
    }


@pytest.mark.usefixtures("tenant_context", "validation")
def test_another_users_draft_creates_nothing(
    db_session: Session, users: tuple[User, User]
) -> None:
    owner, other = users
    name = f"draft-create-{uuid4().hex[:8]}"
    draft = seal_draft_credential({}, user_id=owner.id, source=_SOURCE)

    with pytest.raises(OnyxError) as error:
        create_connector_with_credential(
            _request(name, draft_credential=draft), user=other, db_session=db_session
        )

    assert error.value.error_code == OnyxErrorCode.INVALID_INPUT
    assert _connector(db_session, name) is None
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

    pair = db_session.scalar(
        select(ConnectorCredentialPair).where(
            ConnectorCredentialPair.id == response.data
        )
    )
    assert pair is not None and pair.credential_id == credential.id
    assert _credentials_of(db_session, owner) == 1


@pytest.mark.parametrize(
    "credential_fields",
    [
        {},
        {"credential_id": 1, "draft_credential": "sealed"},
        {"credential_id": 1, "credential_sharing": CredentialSharing()},
    ],
)
def test_a_create_needs_exactly_one_credential(
    credential_fields: dict[str, Any],
) -> None:
    with pytest.raises(PydanticValidationError):
        _request("name", **credential_fields)
