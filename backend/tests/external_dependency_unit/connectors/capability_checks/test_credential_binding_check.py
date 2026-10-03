"""The binding-check endpoint: the bound fields of an unsaved form against a
credential."""

from collections.abc import Generator
from typing import Any

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.factory import CredentialBindingFieldErrorKind
from onyx.db.models import Credential, User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.documents.credential_capabilities import (
    CredentialBindingCheckRequest,
    CredentialBindingCheckResponse,
    CredentialBindingRejectionCode,
    check_credential_binding,
)
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user

_AUTHORIZED_SITE = "https://acme.atlassian.net/wiki"


@pytest.fixture
def users(db_session: Session) -> Generator[tuple[User, User], None, None]:
    admin = create_test_user(db_session, "binding_admin", is_admin=True)
    other = create_test_user(db_session, "binding_other", is_admin=True)
    yield admin, other
    delete_test_user(db_session, admin, other)
    db_session.commit()


def _credential(
    db_session: Session, *, user: User | None = None
) -> Generator[Credential, None, None]:
    credential = Credential(
        source=DocumentSource.CONFLUENCE,
        credential_json={
            "confluence_access_token": "fake_token",
            "wiki_base": _AUTHORIZED_SITE,
        },
        admin_public=user is None,
        user_id=user.id if user is not None else None,
    )
    db_session.add(credential)
    db_session.commit()
    yield credential
    db_session.delete(credential)
    db_session.commit()


@pytest.fixture
def oauth_credential(db_session: Session) -> Generator[Credential, None, None]:
    yield from _credential(db_session)


def _check(
    db_session: Session,
    user: User,
    credential: Credential,
    config: dict[str, Any],
    source: DocumentSource = DocumentSource.CONFLUENCE,
) -> CredentialBindingCheckResponse:
    return check_credential_binding(
        credential.id,
        CredentialBindingCheckRequest(source=source, connector_specific_config=config),
        user=user,
        db_session=db_session,
    )


@pytest.mark.usefixtures("tenant_context")
def test_matching_site_is_valid(
    db_session: Session, users: tuple[User, User], oauth_credential: Credential
) -> None:
    admin, _ = users

    result = _check(
        db_session,
        admin,
        oauth_credential,
        # Other config keys are ignored.
        {"wiki_base": _AUTHORIZED_SITE, "is_cloud": True, "space": "ENG"},
    )

    assert result == CredentialBindingCheckResponse(field_errors={}, rejection=None)


@pytest.mark.usefixtures("tenant_context")
def test_other_site_is_rejected_with_a_message(
    db_session: Session, users: tuple[User, User], oauth_credential: Credential
) -> None:
    admin, _ = users

    result = _check(
        db_session,
        admin,
        oauth_credential,
        {"wiki_base": "https://other.atlassian.net/wiki", "is_cloud": True},
    )

    assert result.field_errors == {}
    assert result.rejection is not None
    assert result.rejection.code == CredentialBindingRejectionCode.BINDING_REJECTED
    assert _AUTHORIZED_SITE in result.rejection.detail


@pytest.mark.usefixtures("tenant_context")
def test_invalid_and_missing_fields_are_field_errors(
    db_session: Session, users: tuple[User, User], oauth_credential: Credential
) -> None:
    admin, _ = users

    result = _check(
        db_session,
        admin,
        oauth_credential,
        {"wiki_base": "  ", "is_cloud": "not a bool"},
    )

    assert {name: error.kind for name, error in result.field_errors.items()} == {
        "wiki_base": CredentialBindingFieldErrorKind.MISSING,
        "is_cloud": CredentialBindingFieldErrorKind.INVALID,
    }
    assert result.rejection is None


@pytest.mark.usefixtures("tenant_context")
def test_credential_the_user_cannot_see_is_not_found(
    db_session: Session, users: tuple[User, User]
) -> None:
    admin, other = users
    hidden = _credential(db_session, user=other)
    credential = next(hidden)
    try:
        with pytest.raises(OnyxError) as error:
            _check(
                db_session,
                admin,
                credential,
                {"wiki_base": _AUTHORIZED_SITE, "is_cloud": True},
            )
        assert error.value.error_code == OnyxErrorCode.CREDENTIAL_NOT_FOUND
    finally:
        next(hidden, None)


@pytest.mark.usefixtures("tenant_context")
def test_credential_of_another_source_is_rejected(
    db_session: Session, users: tuple[User, User], oauth_credential: Credential
) -> None:
    admin, _ = users

    with pytest.raises(OnyxError) as error:
        _check(db_session, admin, oauth_credential, {}, source=DocumentSource.JIRA)

    assert error.value.error_code == OnyxErrorCode.INVALID_INPUT


@pytest.mark.usefixtures("tenant_context")
def test_source_without_a_connector_is_rejected(
    db_session: Session, users: tuple[User, User]
) -> None:
    admin, _ = users
    credential = Credential(
        source=DocumentSource.INGESTION_API, credential_json={}, admin_public=True
    )
    db_session.add(credential)
    db_session.commit()
    try:
        with pytest.raises(OnyxError) as error:
            _check(
                db_session, admin, credential, {}, source=DocumentSource.INGESTION_API
            )
        assert error.value.error_code == OnyxErrorCode.INVALID_INPUT
    finally:
        db_session.delete(credential)
        db_session.commit()
