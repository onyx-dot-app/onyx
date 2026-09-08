from typing import Any

from pydantic import BaseModel
from sqlalchemy import Select, select, update
from sqlalchemy.orm import Session
from sqlalchemy.sql.expression import and_, or_

from onyx.auth.permissions import get_effective_permissions
from onyx.configs.constants import DocumentSource, NotificationType
from onyx.db.connector_alerts import clear_connector_alerts__no_commit
from onyx.db.enums import AccessType, ConnectorCredentialPairStatus, Permission
from onyx.db.models import (
    ConnectorCredentialPair,
    Credential,
    Credential__UserGroup,
    DocumentByConnectorCredentialPair,
    User,
    User__UserGroup,
    UserGroup__ConnectorCredentialPair,
)
from onyx.db.user_group import assert_not_shared_with_default_group
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.documents.models import CredentialBase
from onyx.utils.credential_audit import emit_credential_access
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
) -> Select:
    """Attaches filters to ensure the user can only access appropriate credentials."""
    if user.is_anonymous:
        raise ValueError("Anonymous users are not allowed to access credentials")

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
        for group_id in user_group_ids
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
) -> Credential | None:
    stmt = select(Credential).distinct()
    stmt = stmt.where(Credential.id == credential_id)
    stmt = _add_user_filters(
        stmt=stmt,
        user=user,
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
    user: User,
    document_source: DocumentSource | None = None,
) -> list[Credential]:
    base_query = select(Credential).where(Credential.source == document_source)
    base_query = _add_user_filters(base_query, user)
    credentials = db_session.execute(base_query).scalars().all()
    return list(credentials)


def fetch_credentials_by_source(
    db_session: Session,
    document_source: DocumentSource | None = None,
) -> list[Credential]:
    base_query = select(Credential).where(Credential.source == document_source)
    credentials = db_session.execute(base_query).scalars().all()
    return list(credentials)


class ConnectorRepoAccess(BaseModel):
    """What a connector lends the coding agent for one repository."""

    token: str
    # The connector's configured branch, or None for the repo's default. The
    # grant covers what the connector indexes, so the caller reads this branch
    # rather than one the LLM asked for.
    branch: str | None


def _group_shared_cc_pair_ids(db_session: Session, user: User) -> set[int]:
    """cc-pair ids the user reaches through their own group membership."""
    return set(
        db_session.scalars(
            select(UserGroup__ConnectorCredentialPair.cc_pair_id)
            .join(
                User__UserGroup,
                User__UserGroup.user_group_id
                == UserGroup__ConnectorCredentialPair.user_group_id,
            )
            .where(
                User__UserGroup.user_id == user.id,
                UserGroup__ConnectorCredentialPair.is_current.is_(True),
            )
        )
    )


def fetch_github_repo_access(
    db_session: Session,
    repo_owner: str,
    repo_name: str,
    user: User,
) -> ConnectorRepoAccess | None:
    """Access a GitHub connector lends for the repo: its credential's token
    and the branch it indexes.

    A connector that indexes a repo's source code is treated as making that
    code available to whoever may read the connector, and the coding agent
    works on the same repo on that user's behalf. So the grant follows the
    user's own access rather than a separate admin toggle.

    A pair qualifies only when:
    - `user` may read the pair: public, or a user group they belong to.
      `get_connector_credential_pairs_for_user` answers most of that, but it
      hands every pair to anyone with READ_CONNECTORS — right for a picker,
      wrong for handing out a PAT — so group membership is checked here for
      anyone who does not manage connectors outright;
    - the pair is NOT permission-synced. SYNC pairs carry per-document ACLs, so
      a user entitled to some of a repo's files can be entitled to few of them
      — and a repo archive is all-or-nothing, so cc-pair access cannot stand in
      for it;
    - the connector indexes source code (`include_code_files`). One that
      indexes only PRs, issues, or docs never exposed the tree;
    - the repo is named explicitly in `repositories`. Owner-wide connectors do
      NOT qualify: they would extend one PAT to every repo of the owner;
    - the pair is active. A paused or invalid pair stops granting its
      credential.

    Known asymmetry: indexing exposes a filtered subset (sensitive files
    skipped, document extensions subtracted, size caps), while the token reads
    the whole tree. The caller filters the tree it hands on; the checks above
    bound who can ask.

    `user` is the actor recorded in the credential-access audit line.

    Returns None when no eligible pair matches (public-repo access only).
    """
    # An anonymous visitor is not a person the audit line can name, and a
    # PUBLIC connector says nothing about who may hold its credential.
    if user.is_anonymous:
        return None

    # Imported lazily: connector_credential_pair imports this module, and the
    # GitHub connector utils pull in PyGithub.
    from onyx.connectors.github.utils import parse_repositories_config
    from onyx.db.connector_credential_pair import (
        get_connector_credential_pairs_for_user,
    )

    owner_lower = repo_owner.lower()
    repo_lower = repo_name.lower()

    # get_editable=False is read access, not manage access: a pair the user may
    # see because it is public or attached to one of their groups.
    cc_pairs = get_connector_credential_pairs_for_user(
        db_session=db_session,
        user=user,
        get_editable=False,
        source=DocumentSource.GITHUB,
    )
    manages_connectors = Permission.MANAGE_CONNECTORS in get_effective_permissions(user)
    group_shared_ids = (
        set() if manages_connectors else _group_shared_cc_pair_ids(db_session, user)
    )

    def _ineligible_reason(cc_pair: ConnectorCredentialPair) -> str | None:
        """Why this pair cannot lend its credential for the repo, or None.

        Every rejection is logged: a user who expects repo access and does not
        get it leaves no other trace, since the caller only sees None.
        """
        if (
            not manages_connectors
            and cc_pair.access_type != AccessType.PUBLIC
            and cc_pair.id not in group_shared_ids
        ):
            return "not public and not shared with one of the user's groups"
        # Per-document ACLs cannot gate an all-or-nothing repo archive.
        if cc_pair.access_type == AccessType.SYNC:
            return "access is permission-synced, which a repo archive cannot honor"
        # Active pairs only: a paused or invalid pair must not keep granting
        # its PAT (and its index is going stale anyway).
        if not cc_pair.status.is_active():
            return f"status is {cc_pair.status.value}"

        config = cc_pair.connector.connector_specific_config or {}
        if not config.get("include_code_files"):
            return "connector does not index code files"
        if str(config.get("repo_owner", "")).lower() != owner_lower:
            return f"indexes owner {config.get('repo_owner')!r}"

        named_repos = {
            name.lower()
            for name in parse_repositories_config(config.get("repositories"))
        }
        if repo_lower not in named_repos:
            return "repository is not one the connector indexes"
        return None

    # Newest pair first, so several connectors indexing the same repo resolve
    # to the same credential every time and the audit trail reproduces.
    for cc_pair in sorted(cc_pairs, key=lambda pair: pair.id, reverse=True):
        reason = _ineligible_reason(cc_pair)
        if reason is not None:
            logger.debug(
                "cc_pair %s cannot lend a credential for %s/%s: %s",
                cc_pair.id,
                repo_owner,
                repo_name,
                reason,
            )
            continue

        config = cc_pair.connector.connector_specific_config or {}
        credential = cc_pair.credential
        credential_json = credential.credential_json
        token = (
            credential_json.get_value(apply_mask=False).get("github_access_token")
            if credential_json is not None
            else None
        )
        if token:
            emit_credential_access(
                credential_type="connector",
                provider=DocumentSource.GITHUB.value,
                row_id=credential.id,
                user_id=str(user.id),
                resource=f"{repo_owner}/{repo_name}",
            )
            branch = str(config.get("branch") or "").strip()
            return ConnectorRepoAccess(token=token, branch=branch or None)
        logger.debug(
            "cc_pair %s cannot lend a credential for %s/%s: no GitHub access token",
            cc_pair.id,
            repo_owner,
            repo_name,
        )

    logger.debug(
        "No connector lends %s a credential for %s/%s (%s GitHub pairs considered)",
        user.id,
        repo_owner,
        repo_name,
        len(cc_pairs),
    )
    return None


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


def create_credential(
    credential_data: CredentialBase,
    user: User,
    db_session: Session,
) -> Credential:
    credential = Credential(
        credential_json=credential_data.credential_json,
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
    credential.credential_json = {  # ty: ignore[invalid-assignment]
        **existing_json,
        **credential_json,
    }

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

    credential.credential_json = (  # ty: ignore[invalid-assignment]
        credential_data.credential_json
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

    credential.credential_json = credential_json  # ty: ignore[invalid-assignment]
    db_session.commit()
    # Expire to ensure credential_json is reloaded as SensitiveValue from DB
    db_session.expire(credential)
    return credential


def backend_update_credential_json(
    credential: Credential,
    credential_json: dict[str, Any],
    db_session: Session,
) -> None:
    """This should not be used in any flows involving the frontend or users"""
    credential.credential_json = credential_json  # ty: ignore[invalid-assignment]
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
