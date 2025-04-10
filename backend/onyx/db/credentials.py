from typing import Any

from sqlalchemy import exists
from sqlalchemy import Select
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.orm import Session
from sqlalchemy.sql.expression import and_
from sqlalchemy.sql.expression import or_

from onyx.auth.schemas import UserRole
from onyx.configs.app_configs import DISABLE_AUTH
from onyx.configs.constants import DocumentSource
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY,
)
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Credential
from onyx.db.models import Credential__UserGroup
from onyx.db.models import DocumentByConnectorCredentialPair
from onyx.db.models import User
from onyx.db.models import User__UserGroup
from onyx.server.documents.models import CredentialBase
from onyx.utils.logger import setup_logger


logger = setup_logger()

# The credentials for these sources are not real so
# permissions are not enforced for them
CREDENTIAL_PERMISSIONS_TO_IGNORE = {
    DocumentSource.FILE,
    DocumentSource.WEB,
    DocumentSource.NOT_APPLICABLE,
    DocumentSource.GOOGLE_SITES,
    DocumentSource.WIKIPEDIA,
    DocumentSource.MEDIAWIKI,
}

PUBLIC_CREDENTIAL_ID = 0


def _add_user_filters(
    stmt: Select,
    user: User | None,
    get_editable: bool = True,
) -> Select:
    """Attaches filters to the statement to ensure that the user can only
    access the appropriate credentials"""
    if user is None:
        if not DISABLE_AUTH:
            raise ValueError("Anonymous users are not allowed to access credentials")
        # If user is None and auth is disabled, assume the user is an admin
        return stmt.where(
            or_(
                Credential.user_id.is_(None),
                Credential.admin_public == True,  # noqa: E712
                Credential.source.in_(CREDENTIAL_PERMISSIONS_TO_IGNORE),
            )
        )

    if user.role == UserRole.ADMIN:
        # Admins can access all credentials that are public or owned by them
        # or are not associated with any user
        return stmt.where(
            or_(
                Credential.user_id == user.id,
                Credential.user_id.is_(None),
                Credential.admin_public == True,  # noqa: E712
                Credential.source.in_(CREDENTIAL_PERMISSIONS_TO_IGNORE),
            )
        )
    if user.role == UserRole.BASIC:
        # Basic users can only access credentials that are owned by them
        return stmt.where(Credential.user_id == user.id)

    stmt = stmt.distinct()
    """
    THIS PART IS FOR CURATORS AND GLOBAL CURATORS
    Here we select cc_pairs by relation:
    User -> User__UserGroup -> Credential__UserGroup -> Credential
    """
    stmt = stmt.outerjoin(Credential__UserGroup).outerjoin(
        User__UserGroup,
        User__UserGroup.user_group_id == Credential__UserGroup.user_group_id,
    )
    """
    Filter Credentials by:
    - if the user is in the user_group that owns the Credential
    - if the user is a curator, they must also have a curator relationship
    to the user_group
    - if editing is being done, we also filter out Credentials that are owned by groups
    that the user isn't a curator for
    - if we are not editing, we show all Credentials in the groups the user is a curator
    for (as well as public Credentials)
    - if we are not editing, we return all Credentials directly connected to the user
    """
    where_clause = User__UserGroup.user_id == user.id
    if user.role == UserRole.CURATOR:
        where_clause &= User__UserGroup.is_curator == True  # noqa: E712

    if get_editable:
        user_groups = select(User__UserGroup.user_group_id).where(
            User__UserGroup.user_id == user.id
        )
        if user.role == UserRole.CURATOR:
            user_groups = user_groups.where(
                User__UserGroup.is_curator == True  # noqa: E712
            )
        where_clause &= (
            ~exists()
            .where(Credential__UserGroup.credential_id == Credential.id)
            .where(~Credential__UserGroup.user_group_id.in_(user_groups))
            .correlate(Credential)
        )
    else:
        where_clause |= Credential.curator_public == True  # noqa: E712
        where_clause |= Credential.user_id == user.id  # noqa: E712

    where_clause |= Credential.source.in_(CREDENTIAL_PERMISSIONS_TO_IGNORE)

    return stmt.where(where_clause)


def _relate_credential_to_user_groups__no_commit(
    db_session: Session,
    credential_id: int,
    user_group_ids: list[int],
) -> None:
    credential_user_groups = []
    for group_id in user_group_ids:
        credential_user_groups.append(
            Credential__UserGroup(
                credential_id=credential_id,
                user_group_id=group_id,
            )
        )
    db_session.add_all(credential_user_groups)


def fetch_credentials_for_user(
    db_session: Session,
    user: User | None,
    get_editable: bool = True,
) -> list[Credential]:
    stmt = select(Credential)
    stmt = _add_user_filters(stmt, user, get_editable=get_editable)
    results = db_session.scalars(stmt)
    return list(results.all())


def fetch_credential_by_id_for_user(
    credential_id: int,
    user: User | None,
    db_session: Session,
    get_editable: bool = True,
) -> Credential | None:
    stmt = select(Credential).distinct()
    stmt = stmt.where(Credential.id == credential_id)
    stmt = _add_user_filters(
        stmt=stmt,
        user=user,
        get_editable=get_editable,
    )
    result = db_session.execute(stmt)
    credential = result.scalar_one_or_none()
    return credential


def fetch_credential_by_id(
    credential_id: int,
    db_session: Session,
) -> Credential | None:
    stmt = select(Credential).distinct()
    stmt = stmt.where(Credential.id == credential_id)
    result = db_session.execute(stmt)
    credential = result.scalar_one_or_none()
    return credential


def fetch_credentials_by_source_for_user(
    db_session: Session,
    user: User | None,
    document_source: DocumentSource | None = None,
    get_editable: bool = True,
) -> list[Credential]:
    base_query = select(Credential).where(Credential.source == document_source)
    base_query = _add_user_filters(base_query, user, get_editable=get_editable)
    credentials = db_session.execute(base_query).scalars().all()
    return list(credentials)


def fetch_credentials_by_source(
    db_session: Session,
    document_source: DocumentSource | None = None,
) -> list[Credential]:
    base_query = select(Credential).where(Credential.source == document_source)
    credentials = db_session.execute(base_query).scalars().all()
    return list(credentials)


def swap_credentials_connector(
    new_credential_id: int, connector_id: int, user: User | None, db_session: Session
) -> ConnectorCredentialPair:
    # Check if the user has permission to use the new credential
    new_credential = fetch_credential_by_id_for_user(
        new_credential_id, user, db_session
    )
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

    # Update ccpair status if it's in INVALID state
    if existing_pair.status == ConnectorCredentialPairStatus.INVALID:
        existing_pair.status = ConnectorCredentialPairStatus.ACTIVE

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
        curator_public=credential_data.curator_public,
    )
    db_session.add(credential)
    db_session.flush()  # This ensures the credential gets an ID
    _relate_credential_to_user_groups__no_commit(
        db_session=db_session,
        credential_id=credential.id,
        user_group_ids=credential_data.groups,
    )

    db_session.commit()
    return credential


def _cleanup_credential__user_group_relationships__no_commit(
    db_session: Session, credential_id: int
) -> None:
    """NOTE: does not commit the transaction."""
    db_session.query(Credential__UserGroup).filter(
        Credential__UserGroup.credential_id == credential_id
    ).delete(synchronize_session=False)


def alter_credential(
    credential_id: int,
    name: str,
    credential_json: dict[str, Any],
    user: User,
    db_session: Session,
) -> Credential | None:
    # TODO: add user group relationship update
    credential = fetch_credential_by_id_for_user(credential_id, user, db_session)

    if credential is None:
        return None

    credential.name = name

    # Assign a new dictionary to credential.credential_json
    credential.credential_json = {
        **credential.credential_json,
        **credential_json,
    }

    credential.user_id = user.id if user is not None else None
    db_session.commit()
    return credential


def update_credential(
    credential_id: int,
    credential_data: CredentialBase,
    user: User,
    db_session: Session,
) -> Credential | None:
    credential = fetch_credential_by_id_for_user(credential_id, user, db_session)
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
    credential = fetch_credential_by_id_for_user(credential_id, user, db_session)
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


def _delete_credential_internal(
    credential: Credential,
    credential_id: int,
    db_session: Session,
    force: bool = False,
) -> None:
    """Internal utility function to handle the actual deletion of a credential"""
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
        logger.warning(f"Force deleting credential {credential_id}")
    else:
        logger.notice(f"Deleting credential {credential_id}")

    _cleanup_credential__user_group_relationships__no_commit(db_session, credential_id)
    db_session.delete(credential)
    db_session.commit()


def delete_credential_for_user(
    credential_id: int,
    user: User,
    db_session: Session,
    force: bool = False,
) -> None:
    """Delete a credential that belongs to a specific user"""
    credential = fetch_credential_by_id_for_user(credential_id, user, db_session)
    if credential is None:
        raise ValueError(
            f"Credential by provided id {credential_id} does not exist or does not belong to user"
        )

    _delete_credential_internal(credential, credential_id, db_session, force)


def delete_credential(
    credential_id: int,
    db_session: Session,
    force: bool = False,
) -> None:
    """Delete a credential regardless of ownership (admin function)"""
    credential = fetch_credential_by_id(credential_id, db_session)
    if credential is None:
        raise ValueError(f"Credential by provided id {credential_id} does not exist")

    _delete_credential_internal(credential, credential_id, db_session, force)


def create_initial_public_credential(db_session: Session) -> None:
    error_msg = (
        "DB is not in a valid initial state."
        "There must exist an empty public credential for data connectors that do not require additional Auth."
    )
    first_credential = fetch_credential_by_id(
        credential_id=PUBLIC_CREDENTIAL_ID,
        db_session=db_session,
    )

    if first_credential is not None:
        if first_credential.credential_json != {} or first_credential.user is not None:
            raise ValueError(error_msg)
        return

    credential = Credential(
        id=PUBLIC_CREDENTIAL_ID,
        credential_json={},
        user_id=None,
    )
    db_session.add(credential)
    db_session.commit()


def cleanup_gmail_credentials(db_session: Session) -> None:
    gmail_credentials = fetch_credentials_by_source(
        db_session=db_session, document_source=DocumentSource.GMAIL
    )
    for credential in gmail_credentials:
        db_session.delete(credential)
    db_session.commit()


def cleanup_google_drive_credentials(db_session: Session) -> None:
    google_drive_credentials = fetch_credentials_by_source(
        db_session=db_session, document_source=DocumentSource.GOOGLE_DRIVE
    )
    for credential in google_drive_credentials:
        db_session.delete(credential)
    db_session.commit()


def delete_service_account_credentials(
    user: User | None, db_session: Session, source: DocumentSource
) -> None:
    credentials = fetch_credentials_for_user(db_session=db_session, user=user)
    for credential in credentials:
        if (
            credential.credential_json.get(DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY)
            and credential.source == source
        ):
            db_session.delete(credential)

    db_session.commit()
