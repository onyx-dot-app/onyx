from fastapi import APIRouter
from fastapi import Depends
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import ExternalAppType
from onyx.db.enums import Permission
from onyx.db.external_app import create_external_app
from onyx.db.external_app import delete_external_app
from onyx.db.external_app import get_external_app_by_id
from onyx.db.external_app import get_external_apps
from onyx.db.external_app import get_user_credentials_by_app_id
from onyx.db.external_app import required_user_credential_keys
from onyx.db.external_app import update_external_app
from onyx.db.external_app import upsert_external_app_user_credential
from onyx.db.models import ExternalApp
from onyx.db.models import ExternalAppUserCredential
from onyx.db.models import User
from onyx.db.skill import affected_user_ids_for_skill
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.providers import fetch_available_built_in_apps
from onyx.external_apps.providers import fetch_built_in_app
from onyx.server.features.build.api.models import BuiltInExternalAppDescriptor
from onyx.server.features.build.api.models import ExternalAppAdminResponse
from onyx.server.features.build.api.models import ExternalAppUserResponse
from onyx.server.features.build.api.models import UpsertExternalAppRequest
from onyx.server.features.build.api.models import UpsertUserCredentialsRequest
from onyx.skills.push import push_skill_to_affected_sandboxes
from onyx.skills.push import push_skills_for_users

router = APIRouter()


def _to_admin_response(app: ExternalApp) -> ExternalAppAdminResponse:
    # Display + lifecycle fields live on the linked Skill row.
    return ExternalAppAdminResponse(
        id=app.id,
        name=app.skill.name,
        description=app.skill.description,
        app_type=app.app_type,
        upstream_url_patterns=list(app.upstream_url_patterns),
        auth_template=app.auth_template,
        organization_credentials=app.organization_credentials,
        enabled=app.skill.enabled,
    )


def _to_user_response(
    app: ExternalApp, user_cred: ExternalAppUserCredential | None
) -> ExternalAppUserResponse:
    """Compute the user-facing view of an app.

    `credential_keys` = keys the auth_template references that the org has
    not pre-filled. `credential_values` is the user's stored values for
    those same keys (stale keys from prior templates are filtered out so
    the frontend never renders a field that's no longer relevant).
    """
    required_keys = required_user_credential_keys(
        app.auth_template, app.organization_credentials
    )
    stored = user_cred.user_credentials if user_cred is not None else {}
    credential_values = {key: stored[key] for key in required_keys if key in stored}
    authenticated = all(key in credential_values for key in required_keys)

    return ExternalAppUserResponse(
        id=app.id,
        name=app.skill.name,
        description=app.skill.description,
        app_type=app.app_type,
        credential_keys=required_keys,
        credential_values=credential_values,
        authenticated=authenticated,
    )


# =============================================================================
# Admin Endpoints
# =============================================================================


@router.post("/admin/apps")
def upsert_external_app(
    request: UpsertExternalAppRequest,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> ExternalAppAdminResponse:
    """Create a new external app, or update an existing one if `id` is set.

    If `id` is provided but no app with that id exists, returns 404.
    """
    if request.id is not None:
        app = update_external_app(
            db_session=db_session,
            external_app_id=request.id,
            name=request.name,
            description=request.description,
            enabled=request.enabled,
            app_type=request.app_type,
            upstream_url_patterns=request.upstream_url_patterns,
            auth_template=request.auth_template,
            organization_credentials=request.organization_credentials,
        )
    else:
        # Skill identity is server-derived from app_type: built-in providers
        # bind to their built-in skill content (and slug), CUSTOM apps get a
        # fresh per-instance slug + empty bundle. Default-public so every org
        # user sees it once it's connected (then gated per-user on credentials).
        app = create_external_app(
            db_session=db_session,
            name=request.name,
            description=request.description,
            bundle_file_id="",
            bundle_sha256="",
            enabled=request.enabled,
            is_public=True,
            app_type=request.app_type,
            upstream_url_patterns=request.upstream_url_patterns,
            auth_template=request.auth_template,
            organization_credentials=request.organization_credentials,
        )

    # Refresh already-running sandboxes so an enable/disable (or content/grant
    # change) takes effect live, not just on the next sandbox. The rebuilt
    # per-user fileset filters on enabled + credentials, so disabling removes
    # the skill and a user who hasn't authenticated yet still sees nothing.
    push_skill_to_affected_sandboxes(app.skill, db_session)

    return _to_admin_response(app)


@router.get("/admin/apps")
def list_external_apps_admin(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> list[ExternalAppAdminResponse]:
    """List all external apps with admin-only fields (org credentials, auth template)."""
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
def delete_external_app_admin(
    external_app_id: int,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> None:
    """Delete an external app. Cascades to all user-credential rows for the app.

    Returns 404 if no app with `external_app_id` exists.
    """
    # Resolve affected users *before* the delete cascades the skill row away,
    # then refresh their sandboxes so the skill is removed live.
    app = get_external_app_by_id(db_session, external_app_id)
    if app is None:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            f"External app with id {external_app_id} not found.",
        )
    affected = affected_user_ids_for_skill(app.skill, db_session)

    delete_external_app(db_session=db_session, external_app_id=external_app_id)

    push_skills_for_users(affected, db_session)


# =============================================================================
# User Endpoints
# =============================================================================


@router.post("/apps/{external_app_id}/credentials")
def upsert_user_credentials(
    external_app_id: int,
    request: UpsertUserCredentialsRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> None:
    """Set or replace the calling user's credentials for the given external app.

    Returns 404 if no app with `external_app_id` exists.
    """
    upsert_external_app_user_credential(
        db_session=db_session,
        external_app_id=external_app_id,
        user_id=user.id,
        user_credentials=request.user_credentials,
    )

    # Authenticating flips this user's per-user gate from blocked to allowed,
    # so refresh their running sandboxes now rather than waiting for the next
    # one. Scoped to the calling user — credentials are per-user.
    push_skills_for_users({user.id}, db_session)


@router.get("/apps")
def list_external_apps(
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> list[ExternalAppUserResponse]:
    """List enabled external apps with the calling user's credential state.

    For each app, returns the credential keys the user must supply (auth
    template keys not pre-filled by the org), the values the user has
    already stored for those keys, and an `authenticated` flag. Org-level
    credentials and the raw auth template are never exposed here.
    """
    apps = get_external_apps(db_session=db_session)
    user_creds_by_app = get_user_credentials_by_app_id(
        db_session=db_session, user_id=user.id
    )
    return [
        _to_user_response(app, user_creds_by_app.get(app.id))
        for app in apps
        if app.skill.enabled
    ]
