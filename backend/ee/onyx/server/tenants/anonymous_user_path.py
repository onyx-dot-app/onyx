from sqlalchemy.orm import Session

from ee.onyx.db.tenant_provisioning import (
    get_tenant_anonymous_user_path,
    get_tenant_id_by_anonymous_user_path,
    upsert_tenant_anonymous_user_path__no_commit,
)


def get_anonymous_user_path(tenant_id: str, db_session: Session) -> str | None:
    return get_tenant_anonymous_user_path(db_session, tenant_id)


def modify_anonymous_user_path(
    tenant_id: str, anonymous_user_path: str, db_session: Session
) -> None:
    # Enforce lowercase path at DB operation level
    anonymous_user_path = anonymous_user_path.lower()

    upsert_tenant_anonymous_user_path__no_commit(
        db_session, tenant_id, anonymous_user_path
    )

    db_session.commit()


def get_tenant_id_for_anonymous_user_path(
    anonymous_user_path: str, db_session: Session
) -> str | None:
    return get_tenant_id_by_anonymous_user_path(db_session, anonymous_user_path)


def validate_anonymous_user_path(path: str) -> None:
    if not path or "/" in path or not path.replace("-", "").isalnum():
        raise ValueError("Invalid path. Use only letters, numbers, and hyphens.")
