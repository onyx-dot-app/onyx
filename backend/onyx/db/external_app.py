from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.models import ExternalApp
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError


def get_external_app_by_id(
    *,
    db_session: Session,
    external_app_id: int,
) -> ExternalApp | None:
    stmt = select(ExternalApp).where(ExternalApp.id == external_app_id)
    return db_session.scalar(stmt)


def get_external_apps(
    *,
    db_session: Session,
) -> list[ExternalApp]:
    stmt = select(ExternalApp).order_by(ExternalApp.id)
    return list(db_session.scalars(stmt).all())


def create_external_app__no_commit(
    *,
    db_session: Session,
    name: str,
    description: str,
    upstream_urls: list[str],
    auth_template: dict[str, Any],
    organization_credentials: dict[str, Any],
    enabled: bool,
) -> ExternalApp:
    app = ExternalApp(
        name=name,
        description=description,
        upstream_urls=upstream_urls,
        auth_template=auth_template,
        organization_credentials=organization_credentials,
        enabled=enabled,
    )
    db_session.add(app)
    db_session.flush()
    return app


def update_external_app__no_commit(
    *,
    db_session: Session,
    external_app_id: int,
    name: str,
    description: str,
    upstream_urls: list[str],
    auth_template: dict[str, Any],
    organization_credentials: dict[str, Any],
    enabled: bool,
) -> ExternalApp:
    """Replace all mutable fields of an existing external app.

    Raises OnyxError(NOT_FOUND) if no row with `external_app_id` exists.
    """
    app = get_external_app_by_id(db_session=db_session, external_app_id=external_app_id)
    if app is None:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            f"External app with id {external_app_id} not found.",
        )

    app.name = name
    app.description = description
    app.upstream_urls = upstream_urls
    app.auth_template = auth_template
    app.organization_credentials = organization_credentials
    app.enabled = enabled

    db_session.flush()
    return app


def delete_external_app__no_commit(
    *,
    db_session: Session,
    external_app_id: int,
) -> None:
    """Delete an external app and (via FK ON DELETE CASCADE) its user credentials.

    Raises OnyxError(NOT_FOUND) if no row with `external_app_id` exists.
    """
    app = get_external_app_by_id(db_session=db_session, external_app_id=external_app_id)
    if app is None:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            f"External app with id {external_app_id} not found.",
        )

    db_session.delete(app)
    db_session.flush()
