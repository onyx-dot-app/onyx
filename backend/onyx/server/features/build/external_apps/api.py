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
from onyx.db.utils import none_as_unset
from onyx.db.utils import UNSET
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.models import BuiltInExternalAppDescriptor
from onyx.external_apps.providers.registry import action_policy_views
from onyx.external_apps.providers.registry import fetch_available_built_in_apps
from onyx.external_apps.providers.registry import get_onyx_managed_provider
from onyx.external_apps.providers.registry import resolve_action_overrides
from onyx.external_apps.url_glob import UrlGlob
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.build.external_apps.models import (
    CreateBuiltInExternalAppRequest,
)
from onyx.server.features.build.external_apps.models import ExternalAppAdminResponse
from onyx.server.features.build.external_apps.models import ExternalAppUserResponse
from onyx.server.features.build.external_apps.models import UpdateExternalAppRequest
from onyx.server.features.build.external_apps.models import UpsertUserCredentialsRequest
from onyx.skills.ingest import delete_bundle_blob
from onyx.skills.ingest import ingest_skill_bundle
from onyx.skills.push import push_skill_to_affected_sandboxes
from onyx.skills.push import push_skills_for_users
from onyx.utils.pydantic_util import parse_json_form_field
from shared_configs.configs import MULTI_TENANT

router = APIRouter()

# Adapters for the structured custom-app form fields, which arrive as JSON
# strings (multipart can't carry native lists/objects).
_STR_LIST_ADAPTER = TypeAdapter(list[str])
_STR_DICT_ADAPTER: TypeAdapter[dict[str, str]] = TypeAdapter(dict[str, str])


def _get_app_or_404(db_session: Session, external_app_id: int) -> ExternalApp:
    app = get_external_app_by_id(db_session, external_app_id)
    if app is None:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            f"External app with id {external_app_id} not found.",
        )
    return app


def _to_admin_response(app: ExternalApp) -> ExternalAppAdminResponse:
    stored = {policy.action_id: policy.policy for policy in app.policies}
    managed = MULTI_TENANT and get_onyx_managed_provider(app.app_type) is not None
    return ExternalAppAdminResponse(
        id=app.id,
        name=app.skill.name,
        description=app.skill.description,
        app_type=app.app_type,
        # Managed built-ins: hide Onyx-owned config/creds. Else mask secrets — the
        # write path restores masked values echoed back unchanged.
        upstream_url_patterns=[] if managed else list(app.upstream_url_patterns),
        auth_template={} if managed else app.auth_template,
        organization_credentials=(
            {} if managed else app.organization_credentials.get_value(apply_mask=True)
        ),
        enabled=app.skill.enabled,
        actions=action_policy_views(app.app_type, stored),
        is_onyx_managed=managed,
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
        slug=app.skill.slug,
        app_type=app.app_type,
        credential_keys=required_keys,
        credential_values=credential_values,
        authenticated=authenticated,
    )


# =============================================================================
# Admin Endpoints
# =============================================================================


@router.post("/admin/apps/built-in")
def create_built_in_external_app(
    request: CreateBuiltInExternalAppRequest,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> ExternalAppAdminResponse:
    """Create a built-in external app. Built-in providers only (CUSTOM rejected);
    custom apps use ``POST /admin/apps/custom``, updates use ``PATCH``. On cloud,
    Onyx-managed built-ins are Onyx-provisioned and can't be created here.
    """
    if request.app_type == ExternalAppType.CUSTOM:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Custom apps must be managed via POST /admin/apps/custom.",
        )

    if MULTI_TENANT and get_onyx_managed_provider(request.app_type) is not None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Built-in apps are provided by Onyx; use PATCH /admin/apps/{id} to "
            "enable/disable them or set action policies.",
        )

    action_policies = resolve_action_overrides(
        request.app_type, request.action_policies, {}
    )

    # Default-public; skill identity is server-derived from app_type.
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

    # Push before commit so a push failure rolls back the create.
    push_skill_to_affected_sandboxes(app.skill, db_session)
    db_session.commit()
    return _to_admin_response(app)


@router.patch("/admin/apps/{external_app_id}")
def update_external_app_admin(
    external_app_id: int,
    request: UpdateExternalAppRequest,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> ExternalAppAdminResponse:
    """Partial update of any app (404 if absent). ``None`` fields are left
    untouched. For Onyx-managed built-ins (cloud) the gateway-config fields
    are Onyx-owned and ignored — only ``enabled`` + ``action_policies`` apply.
    A custom app's bundle bytes are swapped via ``PUT /admin/apps/{id}/bundle``.
    """
    app = _get_app_or_404(db_session, external_app_id)
    managed = MULTI_TENANT and get_onyx_managed_provider(app.app_type) is not None

    # Custom apps author URL patterns as globs; validate them (built-ins author
    # regexes, which the matcher uses as-is).
    if (
        not managed
        and app.app_type == ExternalAppType.CUSTOM
        and request.upstream_url_patterns is not None
    ):
        for pattern in request.upstream_url_patterns:
            UrlGlob.parse(pattern)

    action_policies = resolve_action_overrides(
        app.app_type,
        request.action_policies,
        get_policies(db_session, external_app_id),
    )
    app, _old = update_external_app(
        db_session=db_session,
        external_app_id=external_app_id,
        app_type=app.app_type,
        name=none_as_unset(request.name),
        description=none_as_unset(request.description),
        enabled=none_as_unset(request.enabled),
        # Gateway config is Onyx-owned for managed built-ins; leave it untouched.
        upstream_url_patterns=(
            UNSET if managed else none_as_unset(request.upstream_url_patterns)
        ),
        auth_template=UNSET if managed else none_as_unset(request.auth_template),
        organization_credentials=(
            UNSET if managed else none_as_unset(request.organization_credentials)
        ),
        action_policies=action_policies,
    )
    # Push before commit so a push failure rolls back the change.
    push_skill_to_affected_sandboxes(app.skill, db_session)
    db_session.commit()
    return _to_admin_response(app)


@router.post("/admin/apps/custom")
def create_custom_external_app(
    name: str = Form(...),
    description: str = Form(""),
    upstream_url_patterns: str = Form(...),
    auth_template: str = Form(...),
    organization_credentials: str = Form(...),
    enabled: bool = Form(True),
    bundle: UploadFile | None = File(None),
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> ExternalAppAdminResponse:
    """Create a CUSTOM (bundle-backed) external app. Multipart; structured fields
    are JSON-encoded form strings, bundle required, blank ``description`` falls
    back to the bundle's. Field edits use ``PATCH /admin/apps/{id}``, bundle
    replacement ``PUT /admin/apps/{id}/bundle``.
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
    # Custom app globs; validate before ingesting the bundle so a bad
    # pattern fails fast.
    for pattern in parsed_patterns:
        UrlGlob.parse(pattern)
    validate_auth_template(parsed_auth_template, parsed_org_credentials)

    if bundle is None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "A bundle (.zip) is required when creating a custom app.",
        )

    file_store = get_default_file_store()
    ingested = ingest_skill_bundle(bundle.file.read(), bundle.filename, file_store)
    try:
        app = create_external_app(
            db_session=db_session,
            name=name.strip(),
            description=description.strip() or ingested.description,
            bundle_file_id=ingested.bundle_file_id,
            bundle_sha256=ingested.bundle_sha256,
            app_type=ExternalAppType.CUSTOM,
            upstream_url_patterns=parsed_patterns,
            auth_template=parsed_auth_template,
            organization_credentials=parsed_org_credentials,
            enabled=enabled,
            is_public=True,
            slug=ingested.slug,
        )
        # Push before commit so a failure rolls back the create + orphaned blob.
        push_skill_to_affected_sandboxes(app.skill, db_session)
        db_session.commit()
    except Exception:
        delete_bundle_blob(file_store, ingested.bundle_file_id)
        raise

    return _to_admin_response(app)


@router.put("/admin/apps/{external_app_id}/bundle")
def replace_custom_app_bundle(
    external_app_id: int,
    bundle: UploadFile = File(...),
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> ExternalAppAdminResponse:
    """Replace a CUSTOM app's bundle bytes, keeping its slug. Multipart-only
    channel for bundle swaps; field edits use ``PATCH /admin/apps/{id}``. 404 if
    absent; rejects built-in apps (no bundle).
    """
    app = _get_app_or_404(db_session, external_app_id)
    if app.app_type != ExternalAppType.CUSTOM:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Only custom apps have a replaceable bundle.",
        )

    file_store = get_default_file_store()
    ingested = ingest_skill_bundle(
        bundle.file.read(), bundle.filename, file_store, slug=app.skill.slug
    )
    try:
        app, old_bundle_file_id = update_external_app(
            db_session=db_session,
            external_app_id=external_app_id,
            app_type=ExternalAppType.CUSTOM,
            new_bundle_file_id=ingested.bundle_file_id,
            new_bundle_sha256=ingested.bundle_sha256,
        )
        # Push before commit so a failure rolls back the swap + orphaned blob.
        push_skill_to_affected_sandboxes(app.skill, db_session)
        db_session.commit()
    except Exception:
        delete_bundle_blob(file_store, ingested.bundle_file_id)
        raise

    # Drop the superseded blob only after the swap committed.
    if old_bundle_file_id:
        delete_bundle_blob(file_store, old_bundle_file_id)

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


@router.delete("/admin/apps/{external_app_id}")
def delete_external_app_admin(
    external_app_id: int,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> None:
    """Delete an external app, cascading to its user-credential rows. 404 if
    absent.
    """
    # Resolve affected users before the delete cascades the skill row away.
    app = _get_app_or_404(db_session, external_app_id)
    if MULTI_TENANT and get_onyx_managed_provider(app.app_type) is not None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Built-in apps are provided by Onyx and cannot be deleted.",
        )
    affected = affected_user_ids_for_skill(app.skill, db_session)

    delete_external_app(db_session=db_session, external_app_id=external_app_id)

    # Push before commit so a push failure rolls back the delete.
    push_skills_for_users(affected, db_session)
    db_session.commit()


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

    # Authenticating opens this user's per-user gate; refresh their sandboxes now.
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
