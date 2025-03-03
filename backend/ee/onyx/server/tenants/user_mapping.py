import logging

from fastapi_users import exceptions
from sqlalchemy import select

from onyx.auth.invited_users import get_pending_users
from onyx.auth.invited_users import write_pending_users
from onyx.db.engine import get_session_with_shared_schema
from onyx.db.engine import get_session_with_tenant
from onyx.db.models import UserTenantMapping
from shared_configs.configs import MULTI_TENANT
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

logger = logging.getLogger(__name__)


def get_tenant_id_for_email(email: str) -> str:
    if not MULTI_TENANT:
        return POSTGRES_DEFAULT_SCHEMA
    # Implement logic to get tenant_id from the mapping table
    with get_session_with_shared_schema() as db_session:
        # First try to get an active tenant
        result = db_session.execute(
            select(UserTenantMapping.tenant_id).where(
                UserTenantMapping.email == email,
                UserTenantMapping.active == True,  # noqa: E712
            )
        )
        tenant_id = result.scalar_one_or_none()

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
    with get_session_with_tenant(tenant_id=POSTGRES_DEFAULT_SCHEMA) as db_session:
        try:
            for email in emails:
                db_session.add(
                    UserTenantMapping(email=email, tenant_id=tenant_id, active=False)
                )
        except Exception:
            logger.exception(f"Failed to add users to tenant {tenant_id}")
        db_session.commit()


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
        print("inviting self to tenant", email, tenant_id)
        pending_users = get_pending_users()
        if email in pending_users:
            print("email already in pending users")
            return
        print("writing pending users", pending_users + [email])
        write_pending_users(pending_users + [email])
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


def approve_user_invite(email: str, tenant_id: str) -> None:
    with get_session_with_shared_schema() as db_session:
        # Create a new mapping entry for the user in this tenant
        new_mapping = UserTenantMapping(email=email, tenant_id=tenant_id, active=True)
        db_session.add(new_mapping)
        db_session.commit()

        # Also remove the user from pending users list
        token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
        try:
            pending_users = get_pending_users()
            if email in pending_users:
                pending_users.remove(email)
                write_pending_users(pending_users)
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
