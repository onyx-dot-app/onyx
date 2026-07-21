"""Creating a Gmail credential preserves existing Gmail credential rows."""

from collections.abc import Generator
from dataclasses import dataclass, field
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.auth.schemas import UserRole
from onyx.configs.constants import DocumentSource
from onyx.db.models import Credential, User
from onyx.server.documents.credential import create_credential_from_model
from onyx.server.documents.models import CredentialBase
from tests.external_dependency_unit.conftest import create_test_user


@dataclass
class CreatedGmailCredentialState:
    credential_ids: list[int] = field(default_factory=list)
    user_id: UUID | None = None


def _current_gmail_credential_ids(db_session: Session) -> set[int]:
    credential_ids = db_session.scalars(
        select(Credential.id).where(Credential.source == DocumentSource.GMAIL)
    ).all()
    return set(credential_ids)


def _gmail_credential_request(*, name: str, suffix: str) -> CredentialBase:
    return CredentialBase(
        source=DocumentSource.GMAIL,
        credential_json={
            "client_id": f"gmail-client-{suffix}.apps.googleusercontent.com",
            "client_secret": f"gmail-secret-{suffix}",
            "project_id": f"gmail-project-{suffix}",
        },
        admin_public=True,
        name=name,
    )


@pytest.fixture
def created_gmail_credentials_cleanup(
    db_session: Session,
) -> Generator[CreatedGmailCredentialState, None, None]:
    state = CreatedGmailCredentialState()
    yield state

    db_session.rollback()

    for credential_id in state.credential_ids:
        credential = db_session.get(Credential, credential_id)
        if credential is not None:
            db_session.delete(credential)

    if state.user_id is not None:
        user = db_session.get(User, state.user_id)
        if user is not None:
            db_session.delete(user)

    db_session.commit()


def test_second_gmail_credential_preserves_first(
    db_session: Session,
    created_gmail_credentials_cleanup: CreatedGmailCredentialState,
) -> None:
    # Gmail creation enforces the EE creation hook unless the user is ADMIN.
    admin = create_test_user(
        db_session,
        "gmail_multi_credential_admin",
        role=UserRole.ADMIN,
    )
    created_gmail_credentials_cleanup.user_id = admin.id

    baseline_gmail_credential_ids = _current_gmail_credential_ids(db_session)
    unique_suffix = uuid4().hex[:8]

    # Exercise the endpoint handler directly to cover the real creation path.
    first_response = create_credential_from_model(
        _gmail_credential_request(
            name=f"gmail-multi-first-{unique_suffix}",
            suffix=f"{unique_suffix}-first",
        ),
        admin,
        db_session,
    )
    created_gmail_credentials_cleanup.credential_ids.append(first_response.id)

    gmail_credential_ids_after_first = _current_gmail_credential_ids(db_session)
    assert first_response.id in gmail_credential_ids_after_first
    assert (
        len(gmail_credential_ids_after_first) == len(baseline_gmail_credential_ids) + 1
    )

    second_response = create_credential_from_model(
        _gmail_credential_request(
            name=f"gmail-multi-second-{unique_suffix}",
            suffix=f"{unique_suffix}-second",
        ),
        admin,
        db_session,
    )
    created_gmail_credentials_cleanup.credential_ids.append(second_response.id)

    gmail_credential_ids_after_second = _current_gmail_credential_ids(db_session)
    assert first_response.id in gmail_credential_ids_after_second
    assert second_response.id in gmail_credential_ids_after_second
    assert (
        len(gmail_credential_ids_after_second) == len(baseline_gmail_credential_ids) + 2
    )
