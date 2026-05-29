from typing import Any

from fastapi import APIRouter
from fastapi import Depends
from fastapi import File
from fastapi import Form
from fastapi import UploadFile
from pydantic import TypeAdapter
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import ExternalAppType
from onyx.db.enums import Permission
from onyx.db.external_app import create_external_app
from onyx.db.external_app import delete_external_app
from onyx.db.external_app import get_external_app_by_id
from onyx.db.external_app import get_external_apps
from onyx.db.external_app import get_policies
from onyx.db.external_app import get_user_credentials_by_app_id
from onyx.db.external_app import required_user_credential_keys
from onyx.db.external_app import update_external_app
from onyx.db.external_app import upsert_external_app_user_credential
from onyx.db.external_app import validate_auth_template
from onyx.db.models import ExternalApp
from onyx.db.models import ExternalAppUserCredential
from onyx.db.models import User
from onyx.db.skill import affected_user_ids_for_skill
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.providers.registry import action_policy_views
from onyx.external_apps.providers.registry import build_action_policies
from onyx.external_apps.providers.registry import fetch_available_built_in_apps
from onyx.external_apps.providers.registry import fetch_built_in_app
from onyx.file_store.file_store import FileStore
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.build.api.models import BuiltInExternalAppDescriptor
from onyx.server.features.build.api.models import ExternalAppAdminResponse
from onyx.server.features.build.api.models import ExternalAppUserResponse
from onyx.server.features.build.api.models import UpsertExternalAppRequest
from onyx.server.features.build.api.models import UpsertUserCredentialsRequest
from onyx.skills.ingest import delete_bundle_blob
from onyx.skills.ingest import ingest_skill_bundle
from onyx.skills.push import push_skill_to_affected_sandboxes
from onyx.skills.push import push_skills_for_users
from onyx.utils.pydantic_util import parse_json_form_field

router = APIRouter()

# Adapters for the structured custom-app form fields, which arrive as JSON
# strings (multipart can't carry native lists/objects).
_STR_LIST_ADAPTER = TypeAdapter(list[str])
_STR_DICT_ADAPTER: TypeAdapter[dict[str, str]] = TypeAdapter(dict[str, str])


def _to_admin_response(app: ExternalApp) -> ExternalAppAdminResponse:
    # Display + lifecycle fields live on the linked Skill row.
    stored = {policy.action_id: policy.policy for policy in app.policies}
    return ExternalAppAdminResponse(
        id=app.id,
        name=app.skill.name,
        description=app.skill.description,
        app_type=app.app_type,
        upstream_url_patterns=list(app.upstream_url_patterns),
        auth_template=app.auth_template,
        # Mask secrets (e.g. client_secret) so they're never sent to the client.
        # The write path restores masked values the form echoes back unchanged.
        organization_credentials=app.organization_credentials.get_value(
            apply_mask=True
        ),
        enabled=app.skill.enabled,
        actions=action_policy_views(app.app_type, stored),
    )


def _to_user_response(
    app: ExternalApp, user_cred: ExternalAppUserCredential | None
) -> ExternalAppUserResponse:
    """User-facing view of an app. ``credential_keys`` = auth_template keys the
    org hasn't pre-filled; ``credential_values`` = the user's stored values for
    those keys (stale keys filtered out).
    """
    required_keys = required_user_credential_keys(
        app.auth_template, app.organization_credentials.get_value(apply_mask=False)
    )
    stored = (
        user_cred.user_credentials.get_value(apply_mask=False)
        if user_cred is not None
        else {}
    )
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
    """Create a new external app, or update the one with `id` if set (404 if
    absent). Built-in providers only — custom apps use ``/admin/apps/custom``;
    ``app_type=CUSTOM`` here is rejected.
    """
    if request.app_type == ExternalAppType.CUSTOM:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Custom apps must be managed via POST /admin/apps/custom.",
        )
    # Build the complete policy set to persist: one row per catalog action so
    # the stored rows are the full source of truth. The admin's submitted
    # choices win, unmentioned actions keep their stored value, and anything
    # still unset defaults to ASK. Validation (unknown ids) happens here, before
    # any mutation.
    existing = get_policies(db_session, request.id) if request.id is not None else {}
    action_policies = build_action_policies(
        request.app_type, request.action_policies, existing
    )

    if request.id is not None:
        # Built-in apps have no bundle to swap; ignore the returned old-blob id.
        app, _old = update_external_app(
            db_session=db_session,
            external_app_id=request.id,
            name=request.name,
            description=request.description,
            enabled=request.enabled,
            app_type=request.app_type,
            upstream_url_patterns=request.upstream_url_patterns,
            auth_template=request.auth_template,
            organization_credentials=request.organization_credentials,
            action_policies=action_policies,
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
            action_policies=action_policies,
        )

    # create/update wrote the rows out-of-band (bulk delete + insert) within
    # their own commit, so the app's loaded ``policies`` collection is stale.
    # With ``expire_on_commit=False`` the commit won't refresh it; expire so the
    # response reflects what was just persisted.
    db_session.expire(app, ["policies"])

    # Refresh already-running sandboxes so an enable/disable (or content/grant
    # change) takes effect live, not just on the next sandbox. The rebuilt
    # per-user fileset filters on enabled + credentials, so disabling removes
    # the skill and a user who hasn't authenticated yet still sees nothing.
    push_skill_to_affected_sandboxes(app.skill, db_session)

    return _to_admin_response(app)


@router.post("/admin/apps/custom")
def upsert_custom_external_app(
    name: str = Form(...),
    description: str = Form(""),
    upstream_url_patterns: str = Form(...),
    auth_template: str = Form(...),
    organization_credentials: str = Form(...),
    app_id: int | None = Form(None),
    enabled: bool = Form(True),
    bundle: UploadFile | None = File(None),
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> ExternalAppAdminResponse:
    """Create or edit a CUSTOM (bundle-backed) external app + gateway config.

    Multipart (for the bundle); structured fields ride as JSON-encoded form
    strings. Form ``name`` overrides the bundle's; blank ``description`` falls
    back to the bundle's.

    - **Create** (`app_id` omitted): bundle required; ingested + persisted
      alongside the backing skill. Default-public.
    - **Edit** (`app_id` set): updates config; a supplied bundle replaces the
      existing one (keeping the slug), otherwise the current bundle is kept.
    """
    parsed_patterns = parse_json_form_field(
        upstream_url_patterns, _STR_LIST_ADAPTER, "upstream_url_patterns"
    )
    parsed_auth_template = parse_json_form_field(
        auth_template, _STR_DICT_ADAPTER, "auth_template"
    )
    parsed_org_credentials = parse_json_form_field(
        organization_credentials, _STR_DICT_ADAPTER, "organization_credentials"
    )

    if not name.strip():
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "name is required.")
    if not parsed_patterns:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "At least one upstream URL pattern is required.",
        )
    if any(not p.strip() for p in parsed_patterns):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "upstream_url_patterns must not contain empty entries.",
        )
    validate_auth_template(parsed_auth_template, parsed_org_credentials)

    file_store = get_default_file_store()

    if app_id is None:
        return _create_custom_app(
            db_session=db_session,
            file_store=file_store,
            name=name.strip(),
            description=description.strip(),
            enabled=enabled,
            upstream_url_patterns=parsed_patterns,
            auth_template=parsed_auth_template,
            organization_credentials=parsed_org_credentials,
            bundle=bundle,
        )

    return _edit_custom_app(
        db_session=db_session,
        file_store=file_store,
        app_id=app_id,
        name=name.strip(),
        description=description.strip(),
        enabled=enabled,
        upstream_url_patterns=parsed_patterns,
        auth_template=parsed_auth_template,
        organization_credentials=parsed_org_credentials,
        bundle=bundle,
    )


def _create_custom_app(
    *,
    db_session: Session,
    file_store: FileStore,
    name: str,
    description: str,
    enabled: bool,
    upstream_url_patterns: list[str],
    auth_template: dict[str, Any],
    organization_credentials: dict[str, Any],
    bundle: UploadFile | None,
) -> ExternalAppAdminResponse:
    if bundle is None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "A bundle (.zip) is required when creating a custom app.",
        )
    ingested = ingest_skill_bundle(bundle.file.read(), bundle.filename, file_store)
    try:
        app = create_external_app(
            db_session=db_session,
            name=name,
            description=description or ingested.description,
            bundle_file_id=ingested.bundle_file_id,
            bundle_sha256=ingested.bundle_sha256,
            app_type=ExternalAppType.CUSTOM,
            upstream_url_patterns=upstream_url_patterns,
            auth_template=auth_template,
            organization_credentials=organization_credentials,
            enabled=enabled,
            is_public=True,
            slug=ingested.slug,
        )
    except Exception:
        delete_bundle_blob(file_store, ingested.bundle_file_id)
        raise

    push_skill_to_affected_sandboxes(app.skill, db_session)
    return _to_admin_response(app)


def _edit_custom_app(
    *,
    db_session: Session,
    file_store: FileStore,
    app_id: int,
    name: str,
    description: str,
    enabled: bool,
    upstream_url_patterns: list[str],
    auth_template: dict[str, Any],
    organization_credentials: dict[str, Any],
    bundle: UploadFile | None,
) -> ExternalAppAdminResponse:
    existing = get_external_app_by_id(db_session, app_id)
    if existing is None:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            f"External app with id {app_id} not found.",
        )

    # Optionally replace the bundle, keeping the existing slug (stable identity).
    new_bundle_file_id: str | None = None
    new_bundle_sha256: str | None = None
    final_description = description
    if bundle is not None:
        ingested = ingest_skill_bundle(
            bundle.file.read(),
            bundle.filename,
            file_store,
            slug=existing.skill.slug,
        )
        new_bundle_file_id = ingested.bundle_file_id
        new_bundle_sha256 = ingested.bundle_sha256
        if not final_description:
            final_description = ingested.description

    try:
        app, old_bundle_file_id = update_external_app(
            db_session=db_session,
            external_app_id=app_id,
            name=name,
            description=final_description,
            enabled=enabled,
            app_type=ExternalAppType.CUSTOM,
            upstream_url_patterns=upstream_url_patterns,
            auth_template=auth_template,
            organization_credentials=organization_credentials,
            new_bundle_file_id=new_bundle_file_id,
            new_bundle_sha256=new_bundle_sha256,
        )
    except Exception:
        # Roll back the freshly-stored bundle blob if the update failed.
        if new_bundle_file_id:
            delete_bundle_blob(file_store, new_bundle_file_id)
        raise

    # Drop the superseded bundle blob only after the swap committed.
    if old_bundle_file_id:
        delete_bundle_blob(file_store, old_bundle_file_id)

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
    """Delete an external app, cascading to its user-credential rows. 404 if
    absent.
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
    """List enabled external apps with the calling user's credential state: the
    keys the user must supply, the values already stored, and an
    ``authenticated`` flag. Org credentials and the raw auth template aren't
    exposed.
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
