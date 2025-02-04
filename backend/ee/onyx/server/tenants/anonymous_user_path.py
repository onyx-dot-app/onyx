from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.models import TenantAnonymousUserPath


def get_anonymous_user_path(tenant_id: str, db_session: Session) -> str | None:
    result = db_session.execute(
        select(TenantAnonymousUserPath).where(
            TenantAnonymousUserPath.tenant_id == tenant_id
        )
    )
    result_scalar = result.scalar_one_or_none()
    if result_scalar:
        return result_scalar.anonymous_user_path
    else:
        return None


def modify_anonymous_user_path(
    tenant_id: str, anonymous_user_path: str, db_session: Session
) -> None:
    # Enforce lowercase path at DB operation level
    anonymous_user_path = anonymous_user_path.lower()

    existing_entry = (
        db_session.query(TenantAnonymousUserPath).filter_by(tenant_id=tenant_id).first()
    )

    if existing_entry:
        existing_entry.anonymous_user_path = anonymous_user_path

    else:
        new_entry = TenantAnonymousUserPath(
            tenant_id=tenant_id, anonymous_user_path=anonymous_user_path
        )
        db_session.add(new_entry)

    db_session.commit()


def get_tenant_id_for_anonymous_user_path(
    anonymous_user_path: str, db_session: Session
) -> str | None:
    result = db_session.execute(
        select(TenantAnonymousUserPath).where(
            TenantAnonymousUserPath.anonymous_user_path == anonymous_user_path
        )
    )
    result_scalar = result.scalar_one_or_none()
    if result_scalar:
        return result_scalar.tenant_id
    else:
        return None


def validate_anonymous_user_path(path: str) -> None:
    if not path or "/" in path or not path.replace("-", "").isalnum():
        raise ValueError("Invalid path. Use only letters, numbers, and hyphens.")
