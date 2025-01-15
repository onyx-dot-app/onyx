import logging

from fastapi_users import exceptions
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.engine import get_session_with_tenant
from onyx.db.engine import get_sqlalchemy_engine
from onyx.db.models import UserTenantMapping
from shared_configs.configs import MULTI_TENANT
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA

logger = logging.getLogger(__name__)


def get_tenant_id_for_email(email: str) -> str:
    if not MULTI_TENANT:
        return POSTGRES_DEFAULT_SCHEMA
    # Implement logic to get tenant_id from the mapping table
    with Session(get_sqlalchemy_engine()) as db_session:
        result = db_session.execute(
            select(UserTenantMapping.tenant_id).where(UserTenantMapping.email == email)
        )
        tenant_id = result.scalar_one_or_none()
    if tenant_id is None:
        raise exceptions.UserNotExists()
    return tenant_id


def user_owns_a_tenant(email: str) -> bool:
    with get_session_with_tenant(POSTGRES_DEFAULT_SCHEMA) as db_session:
        result = (
            db_session.query(UserTenantMapping)
            .filter(UserTenantMapping.email == email)
            .first()
        )
        return result is not None


def add_users_to_tenant(emails: list[str], tenant_id: str) -> None:
    with get_session_with_tenant(POSTGRES_DEFAULT_SCHEMA) as db_session:
        try:
            for email in emails:
                db_session.add(UserTenantMapping(email=email, tenant_id=tenant_id))
        except Exception:
            logger.exception(f"Failed to add users to tenant {tenant_id}")
        db_session.commit()


def remove_users_from_tenant(emails: list[str], tenant_id: str) -> None:
    with get_session_with_tenant(POSTGRES_DEFAULT_SCHEMA) as db_session:
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
    with get_session_with_tenant(POSTGRES_DEFAULT_SCHEMA) as db_session:
        db_session.query(UserTenantMapping).filter(
            UserTenantMapping.tenant_id == tenant_id
        ).delete()
        db_session.commit()
