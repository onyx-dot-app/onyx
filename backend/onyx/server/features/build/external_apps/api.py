from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.cache.factory import get_cache_backend
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import (
    EndpointPolicy,
    ExternalAppType,
    GatedAppKind,
    Permission,
    SandboxStatus,
)
from onyx.db.external_app import (
    associate_built_in_skill__no_commit,
    create_external_app,
    delete_external_app,
    disconnect_external_app_for_user,
    get_external_app_by_id,
    get_external_apps,
    get_skills_for_external_app,
    get_user_credentials_by_app_id,
    replace_custom_skill_associations__no_commit,
    required_user_credential_keys,
    update_external_app,
    upsert_external_app_user_credential,
    validate_auth_template,
)
from onyx.db.gated_app import get_action_policies
from onyx.db.models import ExternalApp, ExternalAppUserCredential, User
from onyx.db.skill import affected_user_ids_for_skill
from onyx.db.utils import UNSET, none_as_unset
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.models import BuiltInExternalAppDescriptor
from onyx.external_apps.providers.base import OAuthExternalAppProvider
from onyx.external_apps.providers.registry import (
    action_policy_views,
    fetch_available_built_in_apps,
    get_onyx_managed_provider,
    get_provider_for_app,
    resolve_action_overrides,
)
from onyx.external_apps.url_glob import UrlGlob
from onyx.server.features.build import connect_app
from onyx.server.features.build.db.build_session import get_build_session
from onyx.server.features.build.db.sandbox import get_sandbox_by_user_id
from onyx.server.features.build.external_apps.models import (
    ConnectAppDecisionRequest,
    CreateBuiltInExternalAppRequest,
    CreateCustomExternalAppRequest,
    ExternalAppAdminResponse,
    ExternalAppAssociatedSkill,
    ExternalAppUserResponse,
    UpdateExternalAppRequest,
    UpsertUserCredentialsRequest,
)
from onyx.server.features.build.sandbox.factory import get_sandbox_manager
from onyx.skills.push import push_skill_to_affected_sandboxes, push_skills_for_users
from onyx.utils.encryption import mask_string
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id

router = APIRouter()

admin_router = APIRouter()


def _get_app_or_404(db_session: Session, external_app_id: int) -> ExternalApp:
    app = get_external_app_by_id(db_session, external_app_id)
    if app is None:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            f"External app with id {external_app_id} not found.",
        )
    return app


def _to_admin_response(
    app: ExternalApp,
    *,
    stored: dict[str, EndpointPolicy],
) -> ExternalAppAdminResponse:
    # ``stored`` is the app's per-action policy overrides.
    managed = MULTI_TENANT and get_onyx_managed_provider(app.app_type) is not None
    return ExternalAppAdminResponse(
        id=app.id,
        name=app.name,
        app_type=app.app_type,
        # Managed built-ins: hide Onyx-owned config/creds. Else mask secrets — the
        # write path restores masked values echoed back unchanged.
        upstream_url_patterns=[] if managed else list(app.upstream_url_patterns),
        auth_template={} if managed else app.auth_template,
        organization_credentials=(
            {} if managed else app.organization_credentials.get_value(apply_mask=True)
        ),
        enabled=app.enabled,
        actions=action_policy_views(app.app_type, stored),
        associated_skills=[
            ExternalAppAssociatedSkill(
                id=skill.id,
                name=skill.name,
                is_valid=skill.is_valid,
            )
            for skill in sorted(
                (skill for skill in app.associated_skills if skill.is_custom),
                key=lambda skill: (skill.name, str(skill.id)),
            )
        ],
        is_onyx_managed=managed,
    )


def _to_user_response(
    app: ExternalApp, user_cred: ExternalAppUserCredential | None
) -> ExternalAppUserResponse:
    """User-facing view of an app. ``credential_keys`` = auth_template keys the
    org hasn't pre-filled; ``credential_values`` = the user's masked stored
    values for those keys (stale keys filtered out).
    """
    required_keys = required_user_credential_keys(
        app.auth_template, app.organization_credentials.get_value(apply_mask=False)
    )
    stored_raw = (
        user_cred.user_credentials.get_value(apply_mask=False)
        if user_cred is not None
        else {}
    )
    credential_values = {
        key: mask_string(str(stored_raw[key]))
        for key in required_keys
        if key in stored_raw
    }
    authenticated = all(key in stored_raw for key in required_keys)

    return ExternalAppUserResponse(
        id=app.id,
        name=app.name,
        app_type=app.app_type,
        credential_keys=required_keys,
        credential_values=credential_values,
        authenticated=authenticated,
        supports_oauth=isinstance(get_provider_for_app(app), OAuthExternalAppProvider),
    )


# =============================================================================
# Admin Endpoints
# =============================================================================


@admin_router.post("/apps/built-in")
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
            "set action policies.",
        )

    action_policies = resolve_action_overrides(
        request.app_type, request.action_policies, {}
    )

    app = create_external_app(
        db_session=db_session,
        name=request.name,
        app_type=request.app_type,
        upstream_url_patterns=request.upstream_url_patterns,
        auth_template=request.auth_template,
        organization_credentials=request.organization_credentials,
        action_policies=action_policies,
    )
    skill = associate_built_in_skill__no_commit(db_session, app)

    # Push before commit so a push failure rolls back the create.
    push_skill_to_affected_sandboxes(skill, db_session)
    db_session.commit()
    # ``action_policies`` is exactly what was persisted — no need to re-read.
    return _to_admin_response(app, stored=action_policies)


@admin_router.patch("/apps/{external_app_id}")
def update_external_app_admin(
    external_app_id: int,
    request: UpdateExternalAppRequest,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> ExternalAppAdminResponse:
    """Partial update of any app (404 if absent). ``None`` fields are left
    untouched. For Onyx-managed built-ins (cloud) the gateway-config fields
    are Onyx-owned and ignored — only ``enabled`` and ``action_policies`` apply.
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
        get_action_policies(db_session, GatedAppKind.EXTERNAL_APP, external_app_id),
    )
    affected_skills_by_id = {
        skill.id: skill for skill in get_skills_for_external_app(db_session, app.id)
    }
    app = update_external_app(
        db_session=db_session,
        external_app_id=external_app_id,
        app_type=app.app_type,
        enabled=none_as_unset(request.enabled),
        name=none_as_unset(request.name),
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
    if request.associated_skill_ids is not None:
        affected_skills_by_id.update(
            {
                skill.id: skill
                for skill in replace_custom_skill_associations__no_commit(
                    db_session,
                    external_app_id=external_app_id,
                    skill_ids=request.associated_skill_ids,
                )
            }
        )
    affected: set[UUID] = set()
    for skill in affected_skills_by_id.values():
        affected.update(affected_user_ids_for_skill(skill, db_session))

    # The database is the source of truth; sandbox files are a derived,
    # best-effort projection of the committed app and association state.
    db_session.commit()
    push_skills_for_users(affected, db_session)
    db_session.commit()
    if request.associated_skill_ids is not None:
        db_session.expire(app, ["associated_skills"])
    # ``action_policies`` is exactly what was persisted — no need to re-read.
    return _to_admin_response(app, stored=action_policies)


@admin_router.post("/apps/custom")
def create_custom_external_app(
    request: CreateCustomExternalAppRequest,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> ExternalAppAdminResponse:
    """Create a CUSTOM gateway without creating or ingesting a skill."""
    if not request.name.strip():
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "name is required.")
    if not request.upstream_url_patterns:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "At least one upstream URL pattern is required.",
        )
    if any(not pattern.strip() for pattern in request.upstream_url_patterns):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "upstream_url_patterns must not contain empty entries.",
        )
    for pattern in request.upstream_url_patterns:
        UrlGlob.parse(pattern)
    validate_auth_template(request.auth_template, request.organization_credentials)

    app = create_external_app(
        db_session=db_session,
        name=request.name.strip(),
        app_type=ExternalAppType.CUSTOM,
        upstream_url_patterns=request.upstream_url_patterns,
        auth_template=request.auth_template,
        organization_credentials=request.organization_credentials,
    )
    db_session.commit()

    # A freshly created custom app has no stored policy overrides.
    return _to_admin_response(app, stored={})


@admin_router.get("/apps")
def list_external_apps_admin(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> list[ExternalAppAdminResponse]:
    """List all external apps with admin-only fields (org credentials, auth template)."""
    apps = get_external_apps(db_session=db_session)
    # One policy query per app; admin app lists are small.
    return [
        _to_admin_response(
            app,
            stored=get_action_policies(db_session, GatedAppKind.EXTERNAL_APP, app.id),
        )
        for app in apps
    ]


@admin_router.get("/apps/built-in/options")
def list_built_in_external_apps(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
) -> list[BuiltInExternalAppDescriptor]:
    """Backend-defined presets for the admin "Configure" UI."""
    return fetch_available_built_in_apps()


@admin_router.delete("/apps/{external_app_id}")
def delete_external_app_admin(
    external_app_id: int,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> None:
    """Delete an app and its provider-owned skills. Associated custom skills
    are detached and left disabled. Returns 404 if the app is absent.
    """
    # Resolve affected users before deleting the associations.
    app = _get_app_or_404(db_session, external_app_id)
    if MULTI_TENANT and get_onyx_managed_provider(app.app_type) is not None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Built-in apps are provided by Onyx and cannot be deleted.",
        )
    affected: set[UUID] = set()
    for skill in get_skills_for_external_app(db_session, app.id):
        affected.update(affected_user_ids_for_skill(skill, db_session))

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
    app = _get_app_or_404(db_session, external_app_id)
    if not app.enabled:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "This app is currently disabled by an admin.",
        )

    upsert_external_app_user_credential(
        db_session=db_session,
        external_app_id=external_app_id,
        user_id=user.id,
        user_credentials=request.user_credentials,
        resolve_masked_values=True,
    )

    # Authenticating opens this user's per-user gate; refresh their sandboxes now.
    push_skills_for_users({user.id}, db_session)
    db_session.commit()


@router.delete("/apps/{external_app_id}/credentials")
def disconnect_user_from_external_app(
    external_app_id: int,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> None:
    """Disconnect the calling user and disable the app's associated skills."""
    _get_app_or_404(db_session, external_app_id)
    disconnect_external_app_for_user(
        db_session,
        external_app_id=external_app_id,
        user_id=user.id,
    )
    push_skills_for_users({user.id}, db_session)
    db_session.commit()


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
    apps = get_external_apps(db_session=db_session, enabled_only=True)
    user_creds_by_app = get_user_credentials_by_app_id(
        db_session=db_session, user_id=user.id
    )
    return [_to_user_response(app, user_creds_by_app.get(app.id)) for app in apps]


@router.post("/apps/connect/{request_id}/decision")
def resolve_connect_app_request(
    request_id: str,
    body: ConnectAppDecisionRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> None:
    """Answer a pending ``connect_app`` request: load the stashed context and
    answer opencode on the user's sandbox — connected (allow) / declined
    (reject). Idempotent; an expired or already-answered request is a no-op.
    """
    cache = get_cache_backend(tenant_id=get_current_tenant_id())
    pending = connect_app.load_pending(request_id, cache)
    if pending is None:
        return

    # Scope to the caller's own session before touching their sandbox.
    if get_build_session(UUID(pending.build_session_id), user.id, db_session) is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Connect request not found.")
    sandbox = get_sandbox_by_user_id(db_session, user.id)
    if sandbox is None or sandbox.status != SandboxStatus.RUNNING:
        raise OnyxError(OnyxErrorCode.SERVICE_UNAVAILABLE, "Sandbox is not running.")

    answered = get_sandbox_manager().answer_connect_app_permission(
        sandbox.id,
        opencode_session_id=pending.opencode_session_id,
        perm_id=pending.perm_id,
        directory=pending.directory,
        allow=body.decision == connect_app.ConnectAppDecision.CONNECTED,
    )
    if not answered:
        # Leave the pending record intact (TTL) so the user can retry
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY,
            "Could not reach the sandbox to apply your choice — please try again.",
        )
    connect_app.clear_pending(request_id, cache)
