from fastapi_users import exceptions
from sqlalchemy import select

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
    If a user already has an active mapping to any tenant, the new mapping will be added as inactive.
    """
    with get_session_with_tenant(tenant_id=POSTGRES_DEFAULT_SCHEMA) as db_session:
        try:
            # Start a transaction
            db_session.begin()

            for email in emails:
                # Check if the user already has a mapping to this tenant
                existing_mapping = (
                    db_session.query(UserTenantMapping)
                    .filter(
                        UserTenantMapping.email == email,
                        UserTenantMapping.tenant_id == tenant_id,
                    )
                    .with_for_update()
                    .first()
                )

                # If user already has an active mapping, add this one as inactive
                if not existing_mapping:
                    # Check if the user already has an active mapping to any tenant
                    has_active_mapping = (
                        db_session.query(UserTenantMapping)
                        .filter(
                            UserTenantMapping.email == email,
                            UserTenantMapping.active == True,  # noqa: E712
                        )
                        .first()
                    )

                    db_session.add(
                        UserTenantMapping(
                            email=email,
                            tenant_id=tenant_id,
                            active=False if has_active_mapping else True,
                        )
                    )

            # Commit the transaction
            db_session.commit()
            logger.info(f"Successfully added users {emails} to tenant {tenant_id}")

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
    """
    with get_session_with_shared_schema() as db_session:
        try:
            # First check if there's an active mapping for this user and tenant
            active_mapping = (
                db_session.query(UserTenantMapping)
                .filter(
                    UserTenantMapping.email == email,
                    UserTenantMapping.active == True,  # noqa: E712
                )
                .first()
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
    Get the number of active users for this tenant
    """
    with get_session_with_shared_schema() as db_session:
        # Count the number of active users for this tenant
        user_count = (
            db_session.query(UserTenantMapping)
            .filter(
                UserTenantMapping.tenant_id == tenant_id,
                UserTenantMapping.active == True,  # noqa: E712
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
