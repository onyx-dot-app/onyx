from datetime import datetime
from typing import Any

from sqlalchemy import Select, delete, exists, select, update
from sqlalchemy.orm import Session
from sqlalchemy.sql.expression import and_, or_

from onyx.auth.permissions import get_effective_permissions
from onyx.configs.constants import DocumentSource, NotificationType
from onyx.connectors.credential_families import (
    credential_family_for_source,
    family_sources,
    is_credential_usable_for_source,
    stored_credential_family,
    to_source_credential_json,
    to_stored_credential_json,
)
from onyx.db.connector_alerts import clear_connector_alerts__no_commit
from onyx.db.enums import ConnectorCredentialPairStatus, Permission
from onyx.db.models import (
    ConnectorCredentialPair,
    Credential,
    Credential__UserGroup,
    DocumentByConnectorCredentialPair,
    User,
)
from onyx.db.user_group import assert_not_shared_with_default_group
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
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
    user: User,
    include_own_drafts: bool = False,
) -> Select:
    """Attaches filters to ensure the user can only access appropriate credentials.

    Drafts are hidden; ``include_own_drafts`` shows the user's own, for the
    connector form that made them."""
    if user.is_anonymous:
        raise ValueError("Anonymous users are not allowed to access credentials")

    stmt = stmt.where(
        or_(Credential.is_draft.is_(False), Credential.user_id == user.id)
        if include_own_drafts
        else Credential.is_draft.is_(False)
    )

    effective = get_effective_permissions(user)

    if Permission.MANAGE_CONNECTORS in effective:
        return stmt.where(
            or_(
                Credential.user_id == user.id,
                Credential.user_id.is_(None),
                Credential.admin_public == True,  # noqa: E712
                Credential.source.in_(CREDENTIAL_PERMISSIONS_TO_IGNORE),
            )
        )

    # All other users: only their own credentials
    return stmt.where(Credential.user_id == user.id)


def _relate_credential_to_user_groups__no_commit(
    db_session: Session,
    credential_id: int,
    user_group_ids: list[int],
) -> None:
    assert_not_shared_with_default_group(db_session, user_group_ids)

    credential_user_groups = [
        Credential__UserGroup(
            credential_id=credential_id,
            user_group_id=group_id,
        )
        # A repeated group would break the link table's primary key.
        for group_id in dict.fromkeys(user_group_ids)
    ]
    db_session.add_all(credential_user_groups)


def fetch_credentials_for_user(
    db_session: Session,
    user: User,
) -> list[Credential]:
    stmt = select(Credential)
    stmt = _add_user_filters(stmt, user)
    results = db_session.scalars(stmt)
    return list(results.all())


def fetch_credential_by_id_for_user(
    credential_id: int,
    user: User,
    db_session: Session,
    include_own_drafts: bool = False,
) -> Credential | None:
    stmt = select(Credential).distinct()
    stmt = stmt.where(Credential.id == credential_id)
    stmt = _add_user_filters(
        stmt=stmt,
        user=user,
        include_own_drafts=include_own_drafts,
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


def fetch_credential_by_id_for_update(
    credential_id: int,
    db_session: Session,
) -> Credential | None:
    """Row-locked until the session commits, so one caller at a time reads
    and rewrites a credential whose OAuth refresh token is spent on use."""
    stmt = select(Credential).where(Credential.id == credential_id).with_for_update()
    return db_session.execute(stmt).scalar_one_or_none()


def fetch_credentials_by_source_for_user(
    db_session: Session,
    user: User,
    document_source: DocumentSource | None = None,
) -> list[Credential]:
    base_query = select(Credential).where(Credential.source == document_source)
    base_query = _add_user_filters(base_query, user)
    credentials = db_session.execute(base_query).scalars().all()
    return list(credentials)


def fetch_credentials_usable_by_source_for_user(
    db_session: Session,
    user: User,
    document_source: DocumentSource,
) -> list[Credential]:
    """The source's own credentials, plus the family credentials of the other
    sources in its family."""
    family = credential_family_for_source(document_source)
    sources = family_sources(family) if family else [document_source]
    base_query = select(Credential).where(Credential.source.in_(sources))
    base_query = _add_user_filters(base_query, user)
    return [
        credential
        for credential in db_session.execute(base_query).scalars().all()
        if is_credential_usable_for_source(
            credential.source, _stored_json(credential), document_source
        )
    ]


def fetch_credentials_by_source(
    db_session: Session,
    document_source: DocumentSource | None = None,
) -> list[Credential]:
    base_query = select(Credential).where(Credential.source == document_source)
    credentials = db_session.execute(base_query).scalars().all()
    return list(credentials)


def credential_usable_for_source(
    credential: Credential, source: DocumentSource
) -> bool:
    """True when a ``source`` connector can use the credential: its own
    source, or a family credential the source accepts."""
    return is_credential_usable_for_source(
        credential.source, _stored_json(credential), source
    )


def swap_cc_pair_credential__no_commit(
    db_session: Session, cc_pair: ConnectorCredentialPair, new_credential: Credential
) -> None:
    """Moves the pair and its indexed documents to ``new_credential``. Rows
    are keyed by (connector, credential), so another pair of the connector
    that already uses the credential is a CONFLICT. Hierarchy rows follow the
    pair by their ON UPDATE CASCADE key."""
    if (
        db_session.scalar(
            select(ConnectorCredentialPair.id).where(
                ConnectorCredentialPair.connector_id == cc_pair.connector_id,
                ConnectorCredentialPair.credential_id == new_credential.id,
                ConnectorCredentialPair.id != cc_pair.id,
            )
        )
        is not None
    ):
        raise OnyxError(
            OnyxErrorCode.CONFLICT,
            f"Connector {cc_pair.connector_id} already uses credential "
            f"{new_credential.id} in another connection.",
        )
    db_session.execute(
        update(DocumentByConnectorCredentialPair)
        .where(
            and_(
                DocumentByConnectorCredentialPair.connector_id == cc_pair.connector_id,
                DocumentByConnectorCredentialPair.credential_id
                == cc_pair.credential_id,
            )
        )
        .values(credential_id=new_credential.id)
    )
    cc_pair.credential_id = new_credential.id
    cc_pair.credential = new_credential


def swap_credentials_connector(
    new_credential_id: int, connector_id: int, user: User, db_session: Session
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
    if not credential_usable_for_source(new_credential, existing_pair.connector.source):
        raise ValueError(
            f"New credential source {new_credential.source} cannot be used by connector source {existing_pair.connector.source}"
        )

    swap_cc_pair_credential__no_commit(db_session, existing_pair, new_credential)

    # Update ccpair status if it's in INVALID state
    if existing_pair.status == ConnectorCredentialPairStatus.INVALID:
        existing_pair.status = ConnectorCredentialPairStatus.ACTIVE
        clear_connector_alerts__no_commit(
            db_session=db_session,
            cc_pair_id=existing_pair.id,
            notif_type=NotificationType.CONNECTOR_INVALID,
        )

    # Commit the changes
    db_session.commit()

    # Refresh the object to ensure all relationships are up-to-date
    db_session.refresh(existing_pair)
    return existing_pair


def _stored_json(credential: Credential) -> dict[str, Any]:
    return (
        credential.credential_json.get_value(apply_mask=False)
        if credential.credential_json
        else {}
    )


def create_credential(
    credential_data: CredentialBase,
    user: User,
    db_session: Session,
) -> Credential:
    credential = Credential(
        credential_json=to_stored_credential_json(
            credential_data.source, credential_data.credential_json, None
        ),
        user_id=user.id,
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
    # Expire to ensure credential_json is reloaded as SensitiveValue from DB
    db_session.expire(credential)
    return credential


def create_draft_credential(
    source: DocumentSource,
    credential_json: dict[str, Any],
    user: User,
    db_session: Session,
) -> Credential:
    """Saves a connector form's new account as a draft: private to ``user``
    and hidden from every listing until its connector is created."""
    credential = Credential(
        credential_json=to_stored_credential_json(source, credential_json, None),
        user_id=user.id,
        admin_public=False,
        curator_public=False,
        source=source,
        is_draft=True,
    )
    db_session.add(credential)
    db_session.commit()
    # Expire to ensure credential_json is reloaded as SensitiveValue from DB
    db_session.expire(credential)
    return credential


def update_draft_credential_json(
    credential: Credential,
    source: DocumentSource,
    credential_json: dict[str, Any],
    db_session: Session,
) -> None:
    """Replaces a draft's values. Writes only when they changed: an edit
    changes ``time_updated``, which names the draft in the check-result
    cache."""
    if not credential.is_draft:
        raise ValueError(f"Credential {credential.id} is not a draft.")
    stored_json = to_stored_credential_json(source, credential_json, None)
    if stored_json == _stored_json(credential):
        return
    credential.credential_json = stored_json  # ty: ignore[invalid-assignment]
    db_session.commit()
    # Expire to ensure credential_json is reloaded as SensitiveValue from DB
    db_session.expire(credential)


def promote_draft_credential(
    credential: Credential,
    admin_public: bool,
    curator_public: bool,
    groups: list[int],
    name: str | None,
    db_session: Session,
) -> None:
    """Makes a draft a saved credential with the given sharing. Keeps
    ``time_updated``, so check results cached for the draft still apply."""
    _set_draft_state__no_commit(
        db_session,
        credential.id,
        is_draft=False,
        admin_public=admin_public,
        curator_public=curator_public,
        name=name,
    )
    _relate_credential_to_user_groups__no_commit(
        db_session=db_session, credential_id=credential.id, user_group_ids=groups
    )
    db_session.commit()
    db_session.expire(credential)


def restore_draft_credential(db_session: Session, credential_id: int) -> None:
    """Undoes ``promote_draft_credential`` after a failed connector creation,
    so the form can retry with the same draft. Leaves a credential that a
    pair took meanwhile alone. Never raises: the caller's error is what the
    user needs."""
    try:
        with db_session.begin():
            credential = db_session.execute(
                select(Credential)
                .where(Credential.id == credential_id)
                .with_for_update()
            ).scalar_one_or_none()
            if credential is None or db_session.scalar(
                select(
                    exists().where(
                        ConnectorCredentialPair.credential_id == credential_id
                    )
                )
            ):
                return
            _cleanup_credential__user_group_relationships__no_commit(
                db_session, credential_id
            )
            _set_draft_state__no_commit(
                db_session,
                credential_id,
                is_draft=True,
                admin_public=False,
                curator_public=False,
                name=None,
            )
    except Exception:
        logger.exception(
            "Left credential %s saved after a failed connector creation",
            credential_id,
        )
        db_session.rollback()


def _set_draft_state__no_commit(
    db_session: Session,
    credential_id: int,
    *,
    is_draft: bool,
    admin_public: bool,
    curator_public: bool,
    name: str | None,
) -> None:
    db_session.execute(
        update(Credential)
        .where(Credential.id == credential_id)
        .values(
            is_draft=is_draft,
            admin_public=admin_public,
            curator_public=curator_public,
            name=name,
            # Setting the column skips its ``onupdate``.
            time_updated=Credential.time_updated,
        )
        .execution_options(synchronize_session=False)
    )


def delete_stale_draft_credentials(
    db_session: Session, updated_before: datetime
) -> int:
    """Deletes drafts last changed before ``updated_before``: accounts typed
    into a connector form that was never submitted. Returns how many."""
    credential_ids = list(
        db_session.scalars(
            select(Credential.id)
            .where(
                Credential.is_draft.is_(True),
                Credential.time_updated < updated_before,
            )
            .with_for_update(skip_locked=True)
        ).all()
    )
    if not credential_ids:
        return 0
    db_session.query(Credential__UserGroup).filter(
        Credential__UserGroup.credential_id.in_(credential_ids)
    ).delete(synchronize_session=False)
    db_session.execute(
        delete(Credential)
        .where(Credential.id.in_(credential_ids), Credential.is_draft.is_(True))
        .execution_options(synchronize_session=False)
    )
    db_session.commit()
    return len(credential_ids)


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

    # Get existing credential_json and merge with new values
    existing_json = (
        credential.credential_json.get_value(apply_mask=False)
        if credential.credential_json
        else {}
    )
    # Merge in the credential's own source keys; a family credential is stored
    # in its family's shape.
    source = credential.source or DocumentSource.NOT_APPLICABLE
    credential.credential_json = (  # ty: ignore[invalid-assignment]
        to_stored_credential_json(
            source,
            {**to_source_credential_json(source, existing_json), **credential_json},
            existing_json,
        )
    )

    credential.user_id = user.id
    db_session.commit()
    # Expire to ensure credential_json is reloaded as SensitiveValue from DB
    db_session.expire(credential)
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

    current_stored_json = _stored_json(credential)
    # A family credential is written in its own source's keys: another member
    # source's shape would drop state only the own source keeps (e.g. OAuth).
    if (
        stored_credential_family(current_stored_json) is not None
        and credential_data.source != credential.source
    ):
        raise ValueError(
            f"Credential {credential_id} is a {credential.source.value} "
            f"credential; update it as {credential.source.value}, not "
            f"{credential_data.source.value}."
        )
    credential.credential_json = (  # ty: ignore[invalid-assignment]
        to_stored_credential_json(
            credential_data.source, credential_data.credential_json, current_stored_json
        )
    )
    credential.user_id = user.id if user is not None else None

    db_session.commit()
    # Expire to ensure credential_json is reloaded as SensitiveValue from DB
    db_session.expire(credential)
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

    credential.credential_json = (  # ty: ignore[invalid-assignment]
        to_stored_credential_json(
            credential.source or DocumentSource.NOT_APPLICABLE,
            credential_json,
            _stored_json(credential),
        )
    )
    db_session.commit()
    # Expire to ensure credential_json is reloaded as SensitiveValue from DB
    db_session.expire(credential)
    return credential


def backend_update_credential_json(
    credential: Credential,
    source: DocumentSource,
    credential_json: dict[str, Any],
    db_session: Session,
) -> None:
    """This should not be used in any flows involving the frontend or users.

    ``credential_json`` is in ``source``'s own keys: the source of the connector
    that wrote it, which for a family credential may not be ``credential.source``.
    """
    credential.credential_json = (  # ty: ignore[invalid-assignment]
        to_stored_credential_json(source, credential_json, _stored_json(credential))
    )
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
                "Force deleting credential %s and its associated records", credential_id
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
            raise OnyxError(
                OnyxErrorCode.RESOURCE_IN_USE,
                f"Cannot delete credential as it is still associated with "
                f"{len(associated_connectors)} connector(s) and "
                f"{len(associated_doc_cc_pairs)} document(s).",
            )

    if force:
        logger.warning("Force deleting credential %s", credential_id)
    else:
        logger.notice("Deleting credential %s", credential_id)

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
        raise OnyxError(
            OnyxErrorCode.CREDENTIAL_NOT_FOUND,
            f"Credential {credential_id} does not exist or does not belong to user",
        )

    _delete_credential_internal(credential, credential_id, db_session, force)


def discard_credential_if_unpaired(db_session: Session, credential_id: int) -> bool:
    """The cleanup behind a failed creation validation: its own transaction, a
    row lock so a pair landing concurrently is never cascaded, and it never
    raises, because the caller's validation error is what the user needs."""
    try:
        with db_session.begin():
            credential = db_session.execute(
                select(Credential)
                .where(Credential.id == credential_id)
                .with_for_update()
            ).scalar_one_or_none()
            if credential is None:
                return True
            paired = db_session.scalar(
                select(
                    exists().where(
                        ConnectorCredentialPair.credential_id == credential_id
                    )
                )
            )
            if paired:
                return False
            _cleanup_credential__user_group_relationships__no_commit(
                db_session, credential_id
            )
            db_session.delete(credential)
            return True
    except Exception:
        logger.exception(
            "Left credential %s behind after a failed validation", credential_id
        )
        db_session.rollback()
        return False


def delete_credential(
    credential_id: int,
    db_session: Session,
    force: bool = False,
) -> None:
    """Delete a credential regardless of ownership (admin function)"""
    credential = fetch_credential_by_id(credential_id, db_session)
    if credential is None:
        raise OnyxError(
            OnyxErrorCode.CREDENTIAL_NOT_FOUND,
            f"Credential {credential_id} does not exist",
        )

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
        credential_json_value = (
            first_credential.credential_json.get_value(apply_mask=False)
            if first_credential.credential_json
            else {}
        )
        if credential_json_value != {} or first_credential.user is not None:
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
