from typing import Any

from sqlalchemy import Select
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.orm import Session
from sqlalchemy.sql.expression import and_
from sqlalchemy.sql.expression import or_

from danswer.auth.schemas import UserRole
from danswer.configs.constants import DocumentSource
from danswer.connectors.gmail.constants import (
    GMAIL_DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY,
)
from danswer.connectors.google_drive.constants import (
    DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY,
)
from danswer.db.models import ConnectorCredentialPair
from danswer.db.models import Credential
from danswer.db.models import DocumentByConnectorCredentialPair
from danswer.db.models import User
from danswer.server.documents.models import CredentialBase
from danswer.server.documents.models import CredentialDataUpdateRequest
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


def fetch_credentials_by_source(
    db_session: Session,
    user: User | None,
    document_source: DocumentSource | None = None,
) -> list[Credential]:
    base_query = select(Credential).where(Credential.source == document_source)
    base_query = _attach_user_filters(base_query, user)
    credentials = db_session.execute(base_query).scalars().all()
    return list(credentials)


def swap_credentials_connector(
    new_credential_id: int, connector_id: int, user: User | None, db_session: Session
) -> ConnectorCredentialPair:
    # Check if the user has permission to use the new credential
    new_credential = fetch_credential_by_id(new_credential_id, user, db_session)
    if not new_credential:
        raise ValueError(
            f"No Credential found with id {new_credential_id} or user doesn't have permission to use it"
        )

    # Existing pair
    existing_pair = db_session.execute(
        select(ConnectorCredentialPair).where(
            ConnectorCredentialPair.connector_id == connector_id
        )
    ).scalar_one_or_none()

    if not existing_pair:
        raise ValueError(
            f"No ConnectorCredentialPair found for connector_id {connector_id}"
        )

    # Check if the new credential is compatible with the connector
    if new_credential.source != existing_pair.connector.source:
        raise ValueError(
            f"New credential source {new_credential.source} does not match connector source {existing_pair.connector.source}"
        )

    db_session.execute(
        update(DocumentByConnectorCredentialPair)
        .where(
            and_(
                DocumentByConnectorCredentialPair.connector_id == connector_id,
                DocumentByConnectorCredentialPair.credential_id
                == existing_pair.credential_id,
            )
        )
        .values(credential_id=new_credential_id)
    )

    # Update the existing pair with the new credential
    existing_pair.credential_id = new_credential_id
    existing_pair.credential = new_credential

    # Commit the changes
    db_session.commit()

    # Refresh the object to ensure all relationships are up-to-date
    db_session.refresh(existing_pair)
    return existing_pair


def create_credential(
    credential_data: CredentialBase,
    user: User | None,
    db_session: Session,
) -> Credential:
    credential = Credential(
        credential_json=credential_data.credential_json,
        user_id=user.id if user else None,
        admin_public=credential_data.admin_public,
        source=credential_data.source,
        name=credential_data.name,
    )
    db_session.add(credential)
    db_session.commit()

    return credential


def alter_credential(
    credential_id: int,
    credential_data: CredentialDataUpdateRequest,
    user: User,
    db_session: Session,
) -> Credential | None:
    credential = fetch_credential_by_id(credential_id, user, db_session)

    if credential is None:
        return None

    credential.name = credential_data.name
    credential.name = credential_data.name

    # Update only the keys present in credential_data.credential_json
    for key, value in credential_data.credential_json.items():
        credential.credential_json[key] = value

    credential.user_id = user.id if user is not None else None

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
    force: bool = False,
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

    associated_doc_cc_pairs = (
        db_session.query(DocumentByConnectorCredentialPair)
        .filter(DocumentByConnectorCredentialPair.credential_id == credential_id)
        .all()
    )

    if associated_connectors or associated_doc_cc_pairs:
        if force:
            logger.warning(
                f"Force deleting credential {credential_id} and its associated records"
            )

            # Delete DocumentByConnectorCredentialPair records first
            for doc_cc_pair in associated_doc_cc_pairs:
                db_session.delete(doc_cc_pair)

            # Then delete ConnectorCredentialPair records
            for connector in associated_connectors:
                db_session.delete(connector)

            # Commit these deletions before deleting the credential
            db_session.flush()
        else:
            raise ValueError(
                f"Cannot delete credential as it is still associated with "
                f"{len(associated_connectors)} connector(s) and {len(associated_doc_cc_pairs)} document(s). "
            )

    if force:
        logger.info(f"Force deleting credential {credential_id}")
    else:
        logger.info(f"Deleting credential {credential_id}")

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
