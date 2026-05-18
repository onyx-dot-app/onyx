from fastapi import APIRouter
from fastapi import Depends
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import ExternalAppType
from onyx.db.enums import Permission
from onyx.db.external_app import create_external_app__no_commit
from onyx.db.external_app import delete_external_app__no_commit
from onyx.db.external_app import get_external_apps
from onyx.db.external_app import get_user_credentials_by_app_id
from onyx.db.external_app import required_user_credential_keys
from onyx.db.external_app import update_external_app__no_commit
from onyx.db.external_app import upsert_external_app_user_credential__no_commit
from onyx.db.models import ExternalApp
from onyx.db.models import ExternalAppUserCredential
from onyx.db.models import User
from onyx.external_apps.providers import fetch_available_built_in_apps
from onyx.external_apps.providers import fetch_built_in_app
from onyx.server.features.build.api.models import BuiltInExternalAppDescriptor
from onyx.server.features.build.api.models import ExternalAppAdminResponse
from onyx.server.features.build.api.models import ExternalAppUserResponse
from onyx.server.features.build.api.models import UpsertExternalAppRequest
from onyx.server.features.build.api.models import UpsertUserCredentialsRequest

router = APIRouter()


def _to_admin_response(app: ExternalApp) -> ExternalAppAdminResponse:
    return ExternalAppAdminResponse(
        id=app.id,
        name=app.name,
        description=app.description,
        app_type=app.app_type,
        upstream_url_patterns=list(app.upstream_url_patterns),
        auth_template=app.auth_template,
        organization_credentials=app.organization_credentials,
        enabled=app.enabled,
    )


def _to_user_response(
    app: ExternalApp, user_cred: ExternalAppUserCredential | None
) -> ExternalAppUserResponse:
    """Strip admin-only fields (auth_template, org_credentials) from
    the row and filter stored creds to keys the current template
    still requires, so stale entries from prior templates don't show."""
    required_keys = required_user_credential_keys(
        app.auth_template, app.organization_credentials
    )
    stored = user_cred.user_credentials if user_cred is not None else {}
    credential_values = {key: stored[key] for key in required_keys if key in stored}
    authenticated = all(key in credential_values for key in required_keys)

    return ExternalAppUserResponse(
        id=app.id,
        name=app.name,
        description=app.description,
        app_type=app.app_type,
        credential_keys=required_keys,
        credential_values=credential_values,
        authenticated=authenticated,
    )


# ── Admin endpoints ────────────────────────────────────────────────


@router.post("/admin/apps")
def upsert_external_app(
    request: UpsertExternalAppRequest,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> ExternalAppAdminResponse:
    """Create or update if `request.id` is set. 404 if id doesn't exist."""
    if request.id is not None:
        app = update_external_app__no_commit(
            db_session=db_session,
            external_app_id=request.id,
            name=request.name,
            description=request.description,
            app_type=request.app_type,
            upstream_url_patterns=request.upstream_url_patterns,
            auth_template=request.auth_template,
            organization_credentials=request.organization_credentials,
            enabled=request.enabled,
        )
    else:
        app = create_external_app__no_commit(
            db_session=db_session,
            name=request.name,
            description=request.description,
            app_type=request.app_type,
            upstream_url_patterns=request.upstream_url_patterns,
            auth_template=request.auth_template,
            organization_credentials=request.organization_credentials,
            enabled=request.enabled,
        )

    db_session.commit()
    return _to_admin_response(app)


@router.get("/admin/apps")
def list_external_apps_admin(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> list[ExternalAppAdminResponse]:
    apps = get_external_apps(db_session=db_session)
    return [_to_admin_response(app) for app in apps]


@router.get("/admin/apps/built-in/options")
def list_built_in_external_apps(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
) -> list[BuiltInExternalAppDescriptor]:
    """Backend-defined presets for the admin "Configure" UI."""
    return fetch_available_built_in_apps()


@router.get("/admin/apps/built-in/options/{app_type}")
def get_built_in_external_app(
    app_type: ExternalAppType,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
) -> BuiltInExternalAppDescriptor:
    return fetch_built_in_app(app_type)


@router.delete("/admin/apps/{external_app_id}")
def delete_external_app(
    external_app_id: int,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> None:
    """Cascades to user-credential rows via FK ON DELETE CASCADE."""
    delete_external_app__no_commit(
        db_session=db_session, external_app_id=external_app_id
    )
    db_session.commit()


# ── User endpoints ─────────────────────────────────────────────────


@router.post("/apps/{external_app_id}/credentials")
def upsert_user_credentials(
    external_app_id: int,
    request: UpsertUserCredentialsRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> None:
    upsert_external_app_user_credential__no_commit(
        db_session=db_session,
        external_app_id=external_app_id,
        user_id=user.id,
        user_credentials=request.user_credentials,
    )
    db_session.commit()

    # Connecting/disconnecting changes which external-app skill bundles
    # the user's sandbox should have.
    from onyx.skills.push import push_skills_for_users

    push_skills_for_users({user.id}, db_session)


@router.get("/apps")
def list_external_apps(
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> list[ExternalAppUserResponse]:
    apps = get_external_apps(db_session=db_session)
    user_creds_by_app = get_user_credentials_by_app_id(
        db_session=db_session, user_id=user.id
    )
    return [
        _to_user_response(app, user_creds_by_app.get(app.id))
        for app in apps
        if app.enabled
    ]
