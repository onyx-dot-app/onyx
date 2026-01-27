from fastapi_users import exceptions
from sqlalchemy import select

from ee.onyx.db.license import invalidate_license_cache
from onyx.auth.invited_users import get_invited_users
from onyx.auth.invited_users import get_pending_users
from onyx.auth.invited_users import write_invited_users
from onyx.auth.invited_users import write_pending_users
from onyx.db.engine.sql_engine import get_session_with_shared_schema
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.models import UserTenantMapping
from onyx.server.manage.models import TenantSnapshot
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

logger = setup_logger()


def get_tenant_id_for_email(email: str) -> str:
    if not MULTI_TENANT:
        return POSTGRES_DEFAULT_SCHEMA
    # Implement logic to get tenant_id from the mapping table
    try:
        with get_session_with_shared_schema() as db_session:
            # First try to get an active tenant
            result = db_session.execute(
                select(UserTenantMapping).where(
                    UserTenantMapping.email == email,
                    UserTenantMapping.active == True,  # noqa: E712
                )
            )
            mapping = result.scalar_one_or_none()
            tenant_id = mapping.tenant_id if mapping else None

            # If no active tenant found, try to get the first inactive one
            if tenant_id is None:
                result = db_session.execute(
                    select(UserTenantMapping).where(
                        UserTenantMapping.email == email,
                        UserTenantMapping.active == False,  # noqa: E712
                    )
                )
                mapping = result.scalar_one_or_none()
                if mapping:
                    # Mark this mapping as active
                    mapping.active = True
                    db_session.commit()
                    tenant_id = mapping.tenant_id
                    # Invalidate license cache so used_seats reflects the new count
                    invalidate_license_cache(tenant_id)
    except Exception as e:
        logger.exception(f"Error getting tenant id for email {email}: {e}")
        raise exceptions.UserNotExists()

    if tenant_id is None:
        raise exceptions.UserNotExists()
    return tenant_id


def user_owns_a_tenant(email: str) -> bool:
    with get_session_with_tenant(tenant_id=POSTGRES_DEFAULT_SCHEMA) as db_session:
        result = (
            db_session.query(UserTenantMapping)
            .filter(UserTenantMapping.email == email)
            .first()
        )
        return result is not None


def add_users_to_tenant(emails: list[str], tenant_id: str) -> None:
    """
    Add users to a tenant with proper transaction handling.
    Checks if users already have a tenant mapping to avoid duplicates.

    If a user already has an active mapping to a different tenant, they receive
    an inactive mapping (invitation) to this tenant. They can accept the
    invitation later to switch tenants.

    Raises:
        HTTPException: 402 if adding active users would exceed seat limit
    """
    from fastapi import HTTPException

    from ee.onyx.db.license import check_seat_availability
    from onyx.db.engine.sql_engine import get_session_with_tenant as get_tenant_session

    unique_emails = set(emails)
    if not unique_emails:
        return

    with get_session_with_tenant(tenant_id=POSTGRES_DEFAULT_SCHEMA) as db_session:
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

            # Determine which users will consume a new seat.
            # Users with active mappings elsewhere get INACTIVE mappings (invitations)
            # and don't consume seats until they accept. Only users without any active
            # mapping will get an ACTIVE mapping and consume a seat immediately.
            emails_consuming_seats = {
                email
                for email in unique_emails
                if email not in emails_with_mapping
                and email not in emails_with_active_mapping
            }

            # Check seat availability inside the transaction to prevent race conditions.
            # Note: ALL users in unique_emails still get added below - this check only
            # validates we have capacity for users who will consume seats immediately.
            if emails_consuming_seats:
                with get_tenant_session(tenant_id=tenant_id) as tenant_session:
                    result = check_seat_availability(
                        tenant_session,
                        seats_needed=len(emails_consuming_seats),
                        tenant_id=tenant_id,
                    )
                    if not result.available:
                        raise HTTPException(
                            status_code=402,
                            detail=result.error_message or "Seat limit exceeded",
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
            logger.info(f"Successfully added users {emails} to tenant {tenant_id}")

            # Invalidate license cache so used_seats reflects the new count
            invalidate_license_cache(tenant_id)

        except HTTPException:
            db_session.rollback()
            raise
        except Exception:
            logger.exception(f"Failed to add users to tenant {tenant_id}")
            db_session.rollback()
            raise


def remove_users_from_tenant(emails: list[str], tenant_id: str) -> None:
    with get_session_with_tenant(tenant_id=POSTGRES_DEFAULT_SCHEMA) as db_session:
        try:
            mappings_to_delete = (
                db_session.query(UserTenantMapping)
                .filter(
                    UserTenantMapping.email.in_(emails),
                    UserTenantMapping.tenant_id == tenant_id,
                )
                .all()
            )

            for mapping in mappings_to_delete:
                db_session.delete(mapping)

            db_session.commit()

            # Invalidate license cache so used_seats reflects the new count
            invalidate_license_cache(tenant_id)
        except Exception as e:
            logger.exception(
                f"Failed to remove users from tenant {tenant_id}: {str(e)}"
            )
            db_session.rollback()


def remove_all_users_from_tenant(tenant_id: str) -> None:
    with get_session_with_tenant(tenant_id=POSTGRES_DEFAULT_SCHEMA) as db_session:
        db_session.query(UserTenantMapping).filter(
            UserTenantMapping.tenant_id == tenant_id
        ).delete()
        db_session.commit()

    # Invalidate license cache so used_seats reflects the new count
    invalidate_license_cache(tenant_id)


def invite_self_to_tenant(email: str, tenant_id: str) -> None:
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
    try:
        pending_users = get_pending_users()
        if email in pending_users:
            return
        write_pending_users(pending_users + [email])
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


def approve_user_invite(email: str, tenant_id: str) -> None:
    """
    Approve a user invite to a tenant.
    This will delete all existing records for this email and create a new mapping entry for the user in this tenant.
    """
    with get_session_with_shared_schema() as db_session:
        # Delete all existing records for this email
        db_session.query(UserTenantMapping).filter(
            UserTenantMapping.email == email
        ).delete()

        # Create a new mapping entry for the user in this tenant
        new_mapping = UserTenantMapping(email=email, tenant_id=tenant_id, active=True)
        db_session.add(new_mapping)
        db_session.commit()

    # Invalidate license cache so used_seats reflects the new count
    invalidate_license_cache(tenant_id)

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


def accept_user_invite(email: str, tenant_id: str) -> None:
    """
    Accept an invitation to join a tenant.
    This activates the user's mapping to the tenant.

    Raises:
        HTTPException: 402 if accepting would exceed seat limit
    """
    from fastapi import HTTPException

    from ee.onyx.db.license import check_seat_availability
    from onyx.db.engine.sql_engine import get_session_with_tenant

    with get_session_with_shared_schema() as db_session:
        try:
            # Lock the user's mappings first to prevent race conditions.
            # This ensures no concurrent request can modify this user's mappings
            # while we check seats and activate.
            active_mapping = (
                db_session.query(UserTenantMapping)
                .filter(
                    UserTenantMapping.email == email,
                    UserTenantMapping.active == True,  # noqa: E712
                )
                .with_for_update()
                .first()
            )

            # Check seat availability within the same logical operation.
            # Note: This queries fresh data from DB, not cache.
            with get_session_with_tenant(tenant_id=tenant_id) as tenant_session:
                result = check_seat_availability(
                    tenant_session, seats_needed=1, tenant_id=tenant_id
                )
                if not result.available:
                    raise HTTPException(
                        status_code=402,
                        detail=result.error_message or "Seat limit exceeded",
                    )

            # If an active mapping exists, delete it
            if active_mapping:
                db_session.delete(active_mapping)
                logger.info(
                    f"Deleted existing active mapping for user {email} in tenant {tenant_id}"
                )

            # Find the inactive mapping for this user and tenant
            mapping = (
                db_session.query(UserTenantMapping)
                .filter(
                    UserTenantMapping.email == email,
                    UserTenantMapping.tenant_id == tenant_id,
                    UserTenantMapping.active == False,  # noqa: E712
                )
                .first()
            )

            if mapping:
                # Set all other mappings for this user to inactive
                db_session.query(UserTenantMapping).filter(
                    UserTenantMapping.email == email,
                    UserTenantMapping.active == True,  # noqa: E712
                ).update({"active": False})

                # Activate this mapping
                mapping.active = True
                db_session.commit()
                logger.info(f"User {email} accepted invitation to tenant {tenant_id}")

                # Invalidate license cache so used_seats reflects the new count
                invalidate_license_cache(tenant_id)
            else:
                logger.warning(
                    f"No invitation found for user {email} in tenant {tenant_id}"
                )

        except Exception as e:
            db_session.rollback()
            logger.exception(
                f"Failed to accept invitation for user {email} to tenant {tenant_id}: {str(e)}"
            )
            raise

    # Remove from invited users list since they've accepted
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
    try:
        invited_users = get_invited_users()
        if email in invited_users:
            invited_users.remove(email)
            write_invited_users(invited_users)
            logger.info(f"Removed {email} from invited users list after acceptance")
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


def deny_user_invite(email: str, tenant_id: str) -> None:
    """
    Deny an invitation to join a tenant.
    This removes the user's mapping to the tenant.
    """
    with get_session_with_shared_schema() as db_session:
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
            logger.info(f"User {email} denied invitation to tenant {tenant_id}")
        else:
            logger.warning(
                f"No invitation found for user {email} in tenant {tenant_id}"
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

    TODO: Exclude API key dummy users from seat counting. API keys create
    users with emails like `__DANSWER_API_KEY_*` that should not count toward
    seat limits. See: https://linear.app/onyx-app/issue/ENG-3518
    """
    from onyx.db.models import User

    # First get all emails with active mappings to this tenant
    with get_session_with_shared_schema() as db_session:
        active_mapping_emails = (
            db_session.query(UserTenantMapping.email)
            .filter(
                UserTenantMapping.tenant_id == tenant_id,
                UserTenantMapping.active == True,  # noqa: E712
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
                User.email.in_(emails),  # type: ignore
                User.is_active == True,  # type: ignore  # noqa: E712
            )
            .count()
        )

        return user_count


def get_tenant_invitation(email: str) -> TenantSnapshot | None:
    """
    Get the first tenant invitation for this user
    """
    with get_session_with_shared_schema() as db_session:
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
