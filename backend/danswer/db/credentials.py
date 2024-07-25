from typing import Any

from sqlalchemy import Select
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.sql.expression import or_

from danswer.auth.schemas import UserRole
from danswer.connectors.gmail.constants import (
    GMAIL_DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY,
)
from danswer.connectors.google_drive.constants import (
    DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY,
)
from danswer.db.models import ConnectorCredentialPair
from danswer.db.models import Credential
from danswer.db.models import User
from danswer.server.documents.models import CredentialBase
from danswer.utils.logger import setup_logger


logger = setup_logger()


def _attach_user_filters(
    stmt: Select[tuple[Credential]],
    user: User | None,
    assume_admin: bool = False,  # Used with API key
) -> Select:
    """Attaches filters to the statement to ensure that the user can only
    access the appropriate credentials"""
    if user:
        if user.role == UserRole.ADMIN:
            stmt = stmt.where(
                or_(
                    Credential.user_id == user.id,
                    Credential.user_id.is_(None),
                    Credential.admin_public == True,  # noqa: E712
                )
            )
        else:
            stmt = stmt.where(Credential.user_id == user.id)
    elif assume_admin:
        stmt = stmt.where(
            or_(
                Credential.user_id.is_(None),
                Credential.admin_public == True,  # noqa: E712
            )
        )

    return stmt


def fetch_credentials(
    db_session: Session,
    user: User | None = None,
) -> list[Credential]:
    stmt = select(Credential)
    stmt = _attach_user_filters(stmt, user)
    results = db_session.scalars(stmt)
    return list(results.all())


def fetch_credential_by_id(
    credential_id: int,
    user: User | None,
    db_session: Session,
    assume_admin: bool = False,
) -> Credential | None:
    stmt = select(Credential).where(Credential.id == credential_id)
    stmt = _attach_user_filters(stmt, user, assume_admin=assume_admin)
    result = db_session.execute(stmt)
    credential = result.scalar_one_or_none()
    return credential


def create_credential(
    credential_data: CredentialBase,
    user: User | None,
    db_session: Session,
) -> Credential:
    credential = Credential(
        credential_json=credential_data.credential_json,
        user_id=user.id if user else None,
        admin_public=credential_data.admin_public,
    )
    db_session.add(credential)
    db_session.commit()

    return credential


def update_credential(
    credential_id: int,
    credential_data: CredentialBase,
    user: User,
    db_session: Session,
) -> Credential | None:
    credential = fetch_credential_by_id(credential_id, user, db_session)
    if credential is None:
        return None

    credential.credential_json = credential_data.credential_json
    credential.user_id = user.id if user is not None else None

    db_session.commit()
    return credential


def update_credential_json(
    credential_id: int,
    credential_json: dict[str, Any],
    user: User,
    db_session: Session,
) -> Credential | None:
    credential = fetch_credential_by_id(credential_id, user, db_session)
    if credential is None:
        return None
    credential.credential_json = credential_json

    db_session.commit()
    return credential


def backend_update_credential_json(
    credential: Credential,
    credential_json: dict[str, Any],
    db_session: Session,
) -> None:
    """This should not be used in any flows involving the frontend or users"""
    credential.credential_json = credential_json
    db_session.commit()


def delete_credential(
    credential_id: int,
    user: User | None,
    db_session: Session,
) -> None:
    credential = fetch_credential_by_id(credential_id, user, db_session)
    if credential is None:
        raise ValueError(
            f"Credential by provided id {credential_id} does not exist or does not belong to user"
        )

    associated_connectors = (
        db_session.query(ConnectorCredentialPair)
        .filter(ConnectorCredentialPair.credential_id == credential_id)
        .all()
    )

    if associated_connectors:
        raise ValueError(
            f"Cannot delete credential {credential_id} as it is still associated with {len(associated_connectors)} connector(s). "
            "Please delete all associated connectors first."
        )

    db_session.delete(credential)
    db_session.commit()


def create_initial_public_credential(db_session: Session) -> None:
    public_cred_id = 0
    error_msg = (
        "DB is not in a valid initial state."
        "There must exist an empty public credential for data connectors that do not require additional Auth."
    )
    first_credential = fetch_credential_by_id(public_cred_id, None, db_session)

    if first_credential is not None:
        if first_credential.credential_json != {} or first_credential.user is not None:
            raise ValueError(error_msg)
        return

    credential = Credential(
        id=public_cred_id,
        credential_json={},
        user_id=None,
    )
    db_session.add(credential)
    db_session.commit()


def delete_gmail_service_account_credentials(
    user: User | None, db_session: Session
) -> None:
    credentials = fetch_credentials(db_session=db_session, user=user)
    for credential in credentials:
        if credential.credential_json.get(
            GMAIL_DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY
        ):
            db_session.delete(credential)

    db_session.commit()


def delete_google_drive_service_account_credentials(
    user: User | None, db_session: Session
) -> None:
    credentials = fetch_credentials(db_session=db_session, user=user)
    for credential in credentials:
        if credential.credential_json.get(DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY):
            db_session.delete(credential)

    db_session.commit()
