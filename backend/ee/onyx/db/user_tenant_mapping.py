"""Membership routing for the shared `public.user_tenant_mapping` catalog.

"Subject" throughout this module means the OAuth subject: the provider-issued
identifier for an account, which survives the user renaming their email address
at that provider. It is the `(oauth_name, account_id)` pair.
"""

from collections.abc import Sequence

from fastapi_users import exceptions
from sqlalchemy import or_, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.sql.elements import ColumnElement

from onyx.auth.invited_users import (
    get_invited_users,
    get_pending_users,
    write_invited_users,
    write_pending_users,
)
from onyx.db.engine.sql_engine import (
    get_catalog_session,
    get_session_with_tenant,
)
from onyx.db.models import UserTenantMapping, UserTenantMappingOAuthAccount
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage.models import TenantSnapshot
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT, POSTGRES_DEFAULT_SCHEMA
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

logger = setup_logger()


def _oauth_identity_matches_mapping(
    oauth_name: str, account_id: str
) -> ColumnElement[bool]:
    return (
        select(UserTenantMappingOAuthAccount.oauth_name)
        .where(
            UserTenantMappingOAuthAccount.oauth_name == oauth_name,
            UserTenantMappingOAuthAccount.account_id == account_id,
            UserTenantMappingOAuthAccount.email == UserTenantMapping.email,
            UserTenantMappingOAuthAccount.tenant_id == UserTenantMapping.tenant_id,
        )
        .exists()
    )


def get_tenant_id_for_email(email: str) -> str:
    if not MULTI_TENANT:
        return POSTGRES_DEFAULT_SCHEMA

    email = email.lower()
    with get_catalog_session() as db_session:
        result = db_session.execute(
            select(UserTenantMapping.tenant_id).where(
                UserTenantMapping.email == email,
                UserTenantMapping.active == True,  # noqa: E712
            )
        )
        tenant_id = result.scalar_one_or_none()

        # Only auto-join a single pending invitation. Choosing among several
        # would enroll the user in a workspace they never accepted.
        if tenant_id is None:
            inactive_tenant_ids = (
                db_session.execute(
                    select(UserTenantMapping.tenant_id).where(
                        UserTenantMapping.email == email,
                        UserTenantMapping.active == False,  # noqa: E712
                    )
                )
                .scalars()
                .all()
            )
            if len(inactive_tenant_ids) == 1:
                tenant_id = inactive_tenant_ids[0]
                db_session.query(UserTenantMapping).filter(
                    UserTenantMapping.email == email,
                    UserTenantMapping.tenant_id == tenant_id,
                ).update({"active": True}, synchronize_session=False)
                db_session.commit()
            elif inactive_tenant_ids:
                logger.warning(
                    "Multiple pending invitations for one address require selection"
                )
                raise OnyxError(
                    OnyxErrorCode.CONFLICT,
                    "Multiple pending workspace invitations require an explicit "
                    "selection.",
                )

    if tenant_id is None:
        raise exceptions.UserNotExists()
    return tenant_id


def resolve_tenant_id(
    email: str, oauth_name: str | None = None, account_id: str | None = None
) -> str | None:
    """Tenant this login belongs to, or None when it maps nowhere.

    An active subject membership wins because only the subject survives an
    address change. A superseded one ranks behind an active email membership,
    which is where an admin-initiated workspace move lands, and ahead of an
    address that maps nowhere or to several pending invitations.
    """
    superseded_tenant_id: str | None = None
    if oauth_name and account_id:
        tenant_id = get_tenant_id_for_oauth_account(oauth_name, account_id)
        if tenant_id:
            return tenant_id
        superseded_tenant_id = get_superseded_tenant_id_for_oauth_account(
            oauth_name, account_id
        )

    try:
        return get_tenant_id_for_email(email)
    except exceptions.UserNotExists:
        return superseded_tenant_id
    except OnyxError:
        # A linked subject names exactly one workspace, so it settles an address
        # the caller would otherwise have to disambiguate.
        if superseded_tenant_id is None:
            raise
        return superseded_tenant_id


def _oauth_account_tenant_id(
    oauth_name: str, account_id: str, *, active: bool
) -> str | None:
    # A subject links to at most one mapping row, so this cannot be ambiguous.
    with get_catalog_session() as db_session:
        return db_session.scalar(
            select(UserTenantMapping.tenant_id).where(
                _oauth_identity_matches_mapping(oauth_name, account_id),
                UserTenantMapping.active.is_(active),
            )
        )


def get_tenant_id_for_oauth_account(oauth_name: str, account_id: str) -> str | None:
    """Active workspace of an IdP subject, or None when it maps nowhere.

    Returns the default schema outside multi-tenant.
    """
    if not MULTI_TENANT:
        return POSTGRES_DEFAULT_SCHEMA

    return _oauth_account_tenant_id(oauth_name, account_id, active=True)


def get_superseded_tenant_id_for_oauth_account(
    oauth_name: str, account_id: str
) -> str | None:
    """Workspace of a membership that yielded the email address it was filed under.

    Leaving a workspace deletes the mapping, so an inactive linked row is still a
    real membership. It yields when its owner joins another workspace under the
    same address, or when a different person takes that address over.
    """
    if not MULTI_TENANT:
        return None

    return _oauth_account_tenant_id(oauth_name, account_id, active=False)


def user_owns_a_tenant(email: str) -> bool:
    email = email.lower()
    with get_catalog_session() as db_session:
        result = (
            db_session.query(UserTenantMapping)
            .filter(UserTenantMapping.email == email)
            .first()
        )
        return result is not None


def record_oauth_identity(
    email: str, tenant_id: str, oauth_name: str, account_id: str
) -> None:
    """Link the IdP subject to this user's mapping row so resolution survives
    an address change at the provider.

    A subject links to one mapping, and the first linked row wins: a later
    login whose address maps elsewhere never re-links it, so address
    reassignment cannot steal a linked identity.

    No-op outside multi-tenant, where the mapping tables are not provisioned.
    """
    if not MULTI_TENANT:
        return

    normalized_email = email.lower()
    with get_catalog_session() as db_session:
        if db_session.get(UserTenantMapping, (normalized_email, tenant_id)) is None:
            logger.info("No mapping row to link in tenant %s", tenant_id)
            return

        inserted = db_session.execute(
            pg_insert(UserTenantMappingOAuthAccount)
            .values(
                oauth_name=oauth_name,
                account_id=account_id,
                email=normalized_email,
                tenant_id=tenant_id,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    UserTenantMappingOAuthAccount.oauth_name,
                    UserTenantMappingOAuthAccount.account_id,
                ]
            )
            .returning(
                UserTenantMappingOAuthAccount.email,
                UserTenantMappingOAuthAccount.tenant_id,
            )
        ).one_or_none()
        if inserted is None:
            owner = db_session.execute(
                select(
                    UserTenantMappingOAuthAccount.email,
                    UserTenantMappingOAuthAccount.tenant_id,
                ).where(
                    UserTenantMappingOAuthAccount.oauth_name == oauth_name,
                    UserTenantMappingOAuthAccount.account_id == account_id,
                )
            ).one_or_none()
            if owner is None or tuple(owner) != (normalized_email, tenant_id):
                logger.warning(
                    "OAuth identity is already linked to another tenant mapping"
                )
                return
        db_session.commit()


def _association_ownership_filter(
    identities: Sequence[tuple[str, str]],
) -> ColumnElement[bool]:
    association_mapping_keys = select(
        UserTenantMappingOAuthAccount.email,
        UserTenantMappingOAuthAccount.tenant_id,
    ).where(
        tuple_(
            UserTenantMappingOAuthAccount.oauth_name,
            UserTenantMappingOAuthAccount.account_id,
        ).in_(identities)
    )
    return tuple_(UserTenantMapping.email, UserTenantMapping.tenant_id).in_(
        association_mapping_keys
    )


def rekey_user_mapping_email(
    new_email: str,
    tenant_id: str,
    oauth_identities: Sequence[tuple[str, str]],
    previous_email: str | None = None,
) -> None:
    """Collapse this tenant's membership rows for the user's linked subjects
    onto their new address, keeping one row and deleting the rest.

    An unmapped new address links no further subjects and resolves nowhere for
    a login that presents none, which is what provisions a second tenant.
    Ownership is matched by any linked subject, since the provider used for this
    login may not be the one that linked the row. ``previous_email`` names the
    row the caller is moving, since a tenant can hold several of this user's.

    No-op outside multi-tenant, where the mapping tables are not provisioned.
    """
    if not MULTI_TENANT:
        return

    identities = list(dict.fromkeys(oauth_identities))
    if not identities:
        logger.warning("No linked OAuth identity to rekey in tenant %s", tenant_id)
        return

    normalized_new_email = new_email.lower()
    with get_catalog_session() as db_session:
        # uq_user_active_email_idx spans tenants, so the address may already be
        # held. Moving the row onto it anyway would make the other tenant's row
        # answer this user's next login, and the subject link still resolves it.
        held_elsewhere = db_session.scalar(
            select(UserTenantMapping.tenant_id).where(
                UserTenantMapping.email == normalized_new_email,
                UserTenantMapping.tenant_id != tenant_id,
                UserTenantMapping.active == True,  # noqa: E712
            )
        )
        if held_elsewhere is not None:
            logger.warning(
                "Renamed address is active in another workspace, leaving the "
                "tenant %s mapping under its current address",
                tenant_id,
            )
            return

        matched_mappings = (
            db_session.query(UserTenantMapping)
            .filter(
                UserTenantMapping.tenant_id == tenant_id,
                _association_ownership_filter(identities),
            )
            .with_for_update()
            .all()
        )
        if not matched_mappings:
            logger.warning("No mapping row to rekey in tenant %s", tenant_id)
            return

        destination = (
            db_session.query(UserTenantMapping)
            .filter(
                UserTenantMapping.tenant_id == tenant_id,
                UserTenantMapping.email == normalized_new_email,
            )
            .with_for_update()
            .one_or_none()
        )
        # A row carries someone else's subject once a declined rekey parks it
        # and an invite hands the address on. Renaming one promotes them into a
        # workspace, and deleting one cascades their membership away.
        candidate_keys = {(row.email, row.tenant_id) for row in matched_mappings}
        if destination is not None:
            candidate_keys.add((destination.email, destination.tenant_id))
        if db_session.scalar(
            select(UserTenantMappingOAuthAccount.account_id).where(
                tuple_(
                    UserTenantMappingOAuthAccount.email,
                    UserTenantMappingOAuthAccount.tenant_id,
                ).in_(list(candidate_keys)),
                ~tuple_(
                    UserTenantMappingOAuthAccount.oauth_name,
                    UserTenantMappingOAuthAccount.account_id,
                ).in_(identities),
            )
        ):
            logger.warning(
                "Mapping rows in tenant %s carry another identity's subject, "
                "leaving them as they are",
                tenant_id,
            )
            return

        if destination is None:
            normalized_previous = previous_email.lower() if previous_email else None
            destination = next(
                (
                    mapping
                    for mapping in matched_mappings
                    if mapping.email == normalized_previous
                ),
                None,
            ) or next(
                # No caller-named row, so fall back to keeping an active
                # membership active rather than reviving a retired one.
                (mapping for mapping in matched_mappings if mapping.active),
                matched_mappings[0],
            )
            destination.email = normalized_new_email

        source_mappings = [
            mapping for mapping in matched_mappings if mapping is not destination
        ]
        if source_mappings:
            association_accounts = (
                db_session.query(UserTenantMappingOAuthAccount)
                .filter(
                    tuple_(
                        UserTenantMappingOAuthAccount.email,
                        UserTenantMappingOAuthAccount.tenant_id,
                    ).in_(
                        [
                            (mapping.email, mapping.tenant_id)
                            for mapping in source_mappings
                        ]
                    ),
                    # A row can carry a stranger's subject, so scope the move to
                    # this user's. `identities` is every provider they have
                    # linked, not just the one used today, so none is stranded.
                    tuple_(
                        UserTenantMappingOAuthAccount.oauth_name,
                        UserTenantMappingOAuthAccount.account_id,
                    ).in_(identities),
                )
                .with_for_update()
                .all()
            )
            for account in association_accounts:
                account.email = destination.email
                account.tenant_id = destination.tenant_id

            # Land the FK moves before the source mappings are deleted, or
            # ON DELETE CASCADE takes the links with them.
            db_session.flush()

        destination.active = destination.active or any(
            mapping.active for mapping in source_mappings
        )
        for mapping in source_mappings:
            db_session.delete(mapping)

        db_session.commit()


def add_users_to_tenant(emails: list[str], tenant_id: str) -> None:
    """
    Add users to a tenant. If a user has an active mapping elsewhere,
    they get an inactive (invitation) mapping until they accept.

    Calls ``enforce_cloud_seat_limit`` before inserting any new active
    mapping so Stripe auto-billing fails the request closed on decline.
    """
    unique_emails = {email.lower() for email in emails}
    if not unique_emails:
        return

    with get_catalog_session() as db_session:
        try:
            # Start a transaction
            db_session.begin()

            # Batch query 1: Get all existing mappings for these emails to this tenant
            # Lock rows to prevent concurrent modifications
            existing_mappings = (
                db_session.query(UserTenantMapping)
                .filter(
                    UserTenantMapping.email.in_(unique_emails),
                    UserTenantMapping.tenant_id == tenant_id,
                )
                .with_for_update()
                .all()
            )
            emails_with_mapping = {m.email for m in existing_mappings}

            # Batch query 2: Get all active mappings for these emails (any tenant)
            active_mappings = (
                db_session.query(UserTenantMapping)
                .filter(
                    UserTenantMapping.email.in_(unique_emails),
                    UserTenantMapping.active == True,  # noqa: E712
                )
                .all()
            )
            emails_with_active_mapping = {m.email for m in active_mappings}

            # Emails that will produce a NEW active mapping (consume a
            # seat). Invitations to other tenants don't count.
            new_active_seat_emails = [
                email
                for email in unique_emails
                if email not in emails_with_mapping
                and email not in emails_with_active_mapping
            ]

            if new_active_seat_emails:
                from ee.onyx.server.tenants.billing import enforce_cloud_seat_limit

                # Lock + bill held across the inserts below. Rolled back
                # on Stripe decline by the outer ``except Exception``.
                enforce_cloud_seat_limit(
                    seats_needed=len(new_active_seat_emails),
                    tenant_id=tenant_id,
                    db_session=db_session,
                )

            # Add mappings for emails that don't already have one to this tenant
            for email in unique_emails:
                if email in emails_with_mapping:
                    continue

                # Create mapping: inactive if user belongs to another tenant (invitation),
                # active otherwise
                db_session.add(
                    UserTenantMapping(
                        email=email,
                        tenant_id=tenant_id,
                        active=email not in emails_with_active_mapping,
                    )
                )

            # Commit the transaction
            db_session.commit()
            logger.info("Successfully added users %s to tenant %s", emails, tenant_id)

        except Exception:
            logger.exception("Failed to add users to tenant %s", tenant_id)
            db_session.rollback()
            raise


def remove_users_from_tenant(emails: list[str], tenant_id: str) -> None:
    normalized_emails = [email.lower() for email in emails]
    with get_catalog_session() as db_session:
        try:
            mappings_to_delete = (
                db_session.query(UserTenantMapping)
                .filter(
                    UserTenantMapping.email.in_(normalized_emails),
                    UserTenantMapping.tenant_id == tenant_id,
                )
                .all()
            )

            for mapping in mappings_to_delete:
                db_session.delete(mapping)

            db_session.commit()
        except Exception as e:
            logger.exception(
                "Failed to remove users from tenant %s: %s", tenant_id, str(e)
            )
            db_session.rollback()


def remove_all_users_from_tenant(tenant_id: str) -> None:
    with get_catalog_session() as db_session:
        db_session.query(UserTenantMapping).filter(
            UserTenantMapping.tenant_id == tenant_id
        ).delete()
        db_session.commit()


def approve_user_invite(email: str, tenant_id: str) -> None:
    """
    Approve a user invite to a tenant.
    This makes the user active in this tenant and inactive everywhere else.
    """
    email = email.lower()
    with get_catalog_session() as db_session:
        existing_mappings = (
            db_session.query(UserTenantMapping)
            .filter(UserTenantMapping.email == email)
            .with_for_update()
            .all()
        )
        destination = next(
            (
                candidate
                for candidate in existing_mappings
                if candidate.tenant_id == tenant_id
            ),
            None,
        )
        # Approving by email address proves nothing about identity, since that
        # address may have been reassigned. Rival rows are deactivated rather than
        # deleted so their owner's subject links are not cascaded away.
        for mapping in existing_mappings:
            if mapping is not destination:
                mapping.active = False

        # uq_user_active_email_idx is immediate, so free the email address
        # before this tenant's row becomes active.
        db_session.flush()
        if destination is None:
            # A fresh mapping starts unlinked: subjects attach on the next login.
            destination = UserTenantMapping(
                email=email,
                tenant_id=tenant_id,
                active=True,
            )
            db_session.add(destination)
        else:
            destination.active = True
        db_session.commit()

    # Also remove the user from pending users list
    # Remove from pending users
    pending_users = get_pending_users()
    if email in pending_users:
        pending_users.remove(email)
        write_pending_users(pending_users)

    # Add to invited users
    invited_users = get_invited_users()
    if email not in invited_users:
        invited_users.append(email)
        write_invited_users(invited_users)


def accept_user_invite(
    email: str,
    tenant_id: str,
    oauth_identities: Sequence[tuple[str, str]] = (),
) -> None:
    """Activate this user's invitation and retire their other memberships.

    ``oauth_identities`` are the ``(oauth_name, account_id)`` subjects the caller
    authenticated as. Only rows those already link to are provably this
    identity's, since an address may have been reassigned.
    """
    email = email.lower()
    identities = list(dict.fromkeys(oauth_identities))
    ownership_filter = UserTenantMapping.email == email
    if identities:
        ownership_filter = or_(
            ownership_filter,
            _association_ownership_filter(identities),
        )

    with get_catalog_session() as db_session:
        try:
            mappings = (
                db_session.query(UserTenantMapping)
                .filter(ownership_filter)
                .with_for_update()
                .all()
            )
            mapping = next(
                (
                    candidate
                    for candidate in mappings
                    if candidate.email == email
                    and candidate.tenant_id == tenant_id
                    and not candidate.active
                ),
                None,
            )

            if mapping:
                presented_links = (
                    db_session.execute(
                        select(
                            UserTenantMappingOAuthAccount.oauth_name,
                            UserTenantMappingOAuthAccount.account_id,
                            UserTenantMappingOAuthAccount.email,
                            UserTenantMappingOAuthAccount.tenant_id,
                        ).where(
                            tuple_(
                                UserTenantMappingOAuthAccount.oauth_name,
                                UserTenantMappingOAuthAccount.account_id,
                            ).in_(identities)
                        )
                    ).all()
                    if identities
                    else []
                )
                linked_identities = {
                    (oauth_name, account_id)
                    for oauth_name, account_id, _, _ in presented_links
                }
                # Rows this login's OAuth subjects are already linked to. Matching
                # on the email address alone would also catch rows belonging to
                # whoever held that address before this user.
                owned_mapping_keys = {
                    (owner_email, owner_tenant_id)
                    for _, _, owner_email, owner_tenant_id in presented_links
                } - {(mapping.email, mapping.tenant_id)}
                # The owned row is deleted below, so all of its links move
                # first or ON DELETE CASCADE takes the providers not presented.
                association_accounts = (
                    db_session.query(UserTenantMappingOAuthAccount)
                    .filter(
                        tuple_(
                            UserTenantMappingOAuthAccount.email,
                            UserTenantMappingOAuthAccount.tenant_id,
                        ).in_(list(owned_mapping_keys))
                    )
                    .with_for_update()
                    .all()
                    if owned_mapping_keys
                    else []
                )
                for account in association_accounts:
                    account.email = mapping.email
                    account.tenant_id = mapping.tenant_id

                db_session.add_all(
                    [
                        UserTenantMappingOAuthAccount(
                            oauth_name=oauth_name,
                            account_id=account_id,
                            email=mapping.email,
                            tenant_id=mapping.tenant_id,
                        )
                        for oauth_name, account_id in identities
                        if (oauth_name, account_id) not in linked_identities
                    ]
                )
                # Every subject presented today that was not already linked now
                # links to the destination row.
                db_session.flush()

                for candidate in mappings:
                    if candidate is mapping or not candidate.active:
                        continue
                    # One active row per email address, so a rival yields. A row
                    # this user does not own is only deactivated, because its
                    # OAuth subject links belong to that address's previous holder.
                    if (candidate.email, candidate.tenant_id) in owned_mapping_keys:
                        db_session.delete(candidate)
                    else:
                        candidate.active = False

                # uq_user_active_email_idx is immediate, so free the email
                # address before the destination becomes active.
                db_session.flush()
                mapping.active = True
                db_session.commit()
                logger.info(
                    "User %s accepted invitation to tenant %s", email, tenant_id
                )
            else:
                logger.warning(
                    "No invitation found for user %s in tenant %s", email, tenant_id
                )

        except Exception as e:
            db_session.rollback()
            logger.exception(
                "Failed to accept invitation for user %s to tenant %s: %s",
                email,
                tenant_id,
                str(e),
            )
            raise

    # Remove from invited users list since they've accepted
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
    try:
        invited_users = get_invited_users()
        if email in invited_users:
            invited_users.remove(email)
            write_invited_users(invited_users)
            logger.info("Removed %s from invited users list after acceptance", email)
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


def deny_user_invite(email: str, tenant_id: str) -> None:
    """
    Deny an invitation to join a tenant.
    This removes the user's mapping to the tenant.
    """
    email = email.lower()
    with get_catalog_session() as db_session:
        # Delete the mapping for this user and tenant
        result = (
            db_session.query(UserTenantMapping)
            .filter(
                UserTenantMapping.email == email,
                UserTenantMapping.tenant_id == tenant_id,
                UserTenantMapping.active == False,  # noqa: E712
            )
            .delete()
        )

        db_session.commit()
        if result:
            logger.info("User %s denied invitation to tenant %s", email, tenant_id)
        else:
            logger.warning(
                "No invitation found for user %s in tenant %s", email, tenant_id
            )
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
    try:
        pending_users = get_invited_users()
        if email in pending_users:
            pending_users.remove(email)
            write_invited_users(pending_users)
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


def get_tenant_count(tenant_id: str) -> int:
    """
    Get the number of active users for this tenant.

    A user counts toward the seat count if:
    1. They have an active mapping to this tenant (UserTenantMapping.active == True)
    2. AND the User is active (User.is_active == True)
    3. AND the User is not the anonymous system user

    TODO: Exclude API key dummy users from seat counting. API keys create
    users with emails like `__DANSWER_API_KEY_*` that should not count toward
    seat limits. See: https://linear.app/onyx-app/issue/ENG-3518
    """
    from onyx.configs.constants import ANONYMOUS_USER_EMAIL
    from onyx.db.models import User

    # First get all emails with active mappings to this tenant
    with get_catalog_session() as db_session:
        active_mapping_emails = (
            db_session.query(UserTenantMapping.email)
            .filter(
                UserTenantMapping.tenant_id == tenant_id,
                UserTenantMapping.active == True,  # noqa: E712
                UserTenantMapping.email != ANONYMOUS_USER_EMAIL,
            )
            .all()
        )
        emails = [email for (email,) in active_mapping_emails]

    if not emails:
        return 0

    # Now count how many of those users are actually active in the tenant's User table
    with get_session_with_tenant(tenant_id=tenant_id) as db_session:
        user_count = (
            db_session.query(User)
            .filter(
                User.email.in_(emails),  # ty: ignore[unresolved-attribute]
                User.is_active  # noqa: E712  # ty: ignore[invalid-argument-type]
                == True,
            )
            .count()
        )

        return user_count


def get_tenant_invitation(email: str) -> TenantSnapshot | None:
    """
    Get the first tenant invitation for this user
    """
    email = email.lower()
    with get_catalog_session() as db_session:
        # Get the first tenant invitation for this user
        invitation = (
            db_session.query(UserTenantMapping)
            .filter(
                UserTenantMapping.email == email,
                UserTenantMapping.active == False,  # noqa: E712
            )
            .first()
        )

        if invitation:
            # Get the user count for this tenant
            user_count = (
                db_session.query(UserTenantMapping)
                .filter(
                    UserTenantMapping.tenant_id == invitation.tenant_id,
                    UserTenantMapping.active == True,  # noqa: E712
                )
                .count()
            )
            return TenantSnapshot(
                tenant_id=invitation.tenant_id, number_of_users=user_count
            )

        return None
