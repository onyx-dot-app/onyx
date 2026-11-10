"""Marketplace management with provider I/O before writes and dispatch after commit."""

from urllib.parse import urlparse
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission, token_allows_permission
from onyx.auth.scoped_permissions import assert_global
from onyx.background.celery.tasks.marketplace_sync.tasks import (
    dispatch_marketplace_sync,
)
from onyx.configs.app_configs import WEBHOOK_PUBLIC_URL
from onyx.db.engine.sql_engine import get_session, get_session_with_current_tenant
from onyx.db.enums import Permission
from onyx.db.marketplace import confirm_marketplace_retirement__no_commit
from onyx.db.marketplace_management import (
    create_marketplace__no_commit,
    fetch_managed_marketplace,
    list_managed_marketplaces,
    remove_marketplace__no_commit,
    replace_marketplace_login__no_commit,
    request_managed_marketplace_sync__no_commit,
    set_marketplace_default_access__no_commit,
)
from onyx.db.marketplace_webhook_setup import (
    finish_marketplace_webhook__no_commit,
    prepare_marketplace_webhook__no_commit,
)
from onyx.db.models import Marketplace, User
from onyx.db.resource_access import fetch_resource_access_user
from onyx.db.skill_version import delete_unreferenced_skill_bundles
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.redis.redis_tenant_work_gating import maybe_mark_tenant_active
from onyx.server.features.skill.marketplace_models import (
    MarketplaceAccessRequest,
    MarketplaceCompletePreview,
    MarketplaceConfirmationRequest,
    MarketplaceCreateRequest,
    MarketplaceFailedPreview,
    MarketplaceReadyPreview,
    MarketplaceSourceRequest,
)
from onyx.server.settings.tier_order import get_current_tier
from onyx.skills.ingest import prepare_skill_bundle
from onyx.skills.marketplace.models import (
    MarketplaceManagementDetail,
    MarketplaceManagementSnapshot,
)
from onyx.skills.marketplace.provider import get_marketplace_adapter
from onyx.skills.marketplace.read_models import (
    BlockedSkill,
    FailedMarketplace,
    ReadySkill,
)
from onyx.skills.marketplace.reader import read_marketplace_archive
from onyx.skills.push import push_skills_for_users
from onyx.utils.logger import setup_logger
from onyx.utils.url import SSRFException, validate_outbound_http_url
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id

router = APIRouter(prefix="/marketplaces")
logger = setup_logger()


def _public_webhook_base_url(value: str) -> str | None:
    try:
        normalized = validate_outbound_http_url(
            value, https_only=True, resolve_dns=False
        )
        parsed = urlparse(normalized)
        if (
            parsed.path in ("", "/")
            and not (parsed.query or parsed.fragment)
            and (parsed.port is None or parsed.port > 0)
        ):
            return normalized.rstrip("/")
    except (SSRFException, ValueError):
        pass
    return None


MARKETPLACE_WEBHOOK_BASE_URL = _public_webhook_base_url(WEBHOOK_PUBLIC_URL)


@router.post("/{marketplace_id}/webhook")
def setup_marketplace_webhook(
    marketplace_id: UUID,
    request: Request,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> MarketplaceManagementSnapshot:
    if MULTI_TENANT:
        raise OnyxError(OnyxErrorCode.NOT_FOUND)
    snapshot = get_marketplace(marketplace_id, request, user, db_session).marketplace
    if MARKETPLACE_WEBHOOK_BASE_URL is None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Set WEBHOOK_PUBLIC_URL to the public HTTPS address of this Onyx installation before enabling push updates.",
        )
    candidate = Marketplace(
        provider=snapshot.provider,
        provider_config=snapshot.provider_config,
        login_user_id=snapshot.login_user_id,
    )
    db_session.commit()
    adapter = get_marketplace_adapter(candidate, get_current_tenant_id())
    full_ref = adapter.resolve_webhook_ref()
    prepared = prepare_marketplace_webhook__no_commit(
        marketplace_id, user, db_session, expected=snapshot, full_ref=full_ref
    )
    db_session.commit()
    hook_id = get_marketplace_adapter(
        prepared, get_current_tenant_id()
    ).register_webhook(
        f"{MARKETPLACE_WEBHOOK_BASE_URL}/webhook/marketplaces/{marketplace_id}/github"
    )
    try:
        finish_marketplace_webhook__no_commit(prepared, hook_id, user, db_session)
    except OnyxError as exc:
        db_session.rollback()
        if exc.error_code == OnyxErrorCode.NOT_FOUND:
            prepared.webhook_id = hook_id
            try:
                get_marketplace_adapter(
                    prepared, get_current_tenant_id()
                ).remove_webhook()
            except Exception:
                logger.warning(
                    "Marketplace deleted during setup; provider webhook cleanup failed: %s",
                    marketplace_id,
                )
        raise
    result = fetch_managed_marketplace(marketplace_id, user, db_session).marketplace
    db_session.commit()
    return result


def _authorize_source(
    personal: bool, request: Request, user: User, db_session: Session
) -> None:
    actor = fetch_resource_access_user(user.id, db_session)
    if not personal:
        assert_global(actor, permission=Permission.MANAGE_SKILLS)
        if not token_allows_permission(request, Permission.MANAGE_SKILLS):
            raise OnyxError(OnyxErrorCode.INSUFFICIENT_PERMISSIONS)
    # End the authority read before provider I/O. Recheck after the response.
    db_session.commit()


@router.post("/preview")
def preview_marketplace(
    source: MarketplaceSourceRequest,
    request: Request,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> MarketplaceCompletePreview | MarketplaceFailedPreview:
    return _preview_source(source, request, user, db_session)


def _preview_source(
    source: MarketplaceSourceRequest, request: Request, user: User, db_session: Session
) -> MarketplaceCompletePreview | MarketplaceFailedPreview:
    user_id = user.id
    _authorize_source(source.personal, request, user, db_session)
    candidate = Marketplace(
        provider=source.provider,
        provider_config=source.provider_config,
        login_user_id=user_id,
    )
    archive = get_marketplace_adapter(
        candidate, get_current_tenant_id()
    ).fetch_if_changed(force=True)
    if archive is None:
        raise OnyxError(OnyxErrorCode.BAD_GATEWAY, "The source returned no archive.")
    read = read_marketplace_archive(archive.archive_bytes, folder=archive.folder)
    if isinstance(read, FailedMarketplace):
        response = MarketplaceFailedPreview(
            revision=archive.revision, reason=read.reason
        )
    else:
        response = MarketplaceCompletePreview(revision=archive.revision, entries=[])
        for entry in read.entries:
            if not isinstance(entry, ReadySkill):
                response.entries.append(entry)
                continue
            try:
                prepared = prepare_skill_bundle(
                    entry.bundle_bytes,
                    None,
                    expected_name=entry.path.rsplit("/", 1)[-1],
                )
            except (ValueError, OnyxError) as exc:
                response.entries.append(
                    BlockedSkill(
                        entry_key=entry.entry_key, path=entry.path, reason=str(exc)
                    )
                )
            else:
                response.entries.append(
                    MarketplaceReadyPreview(
                        entry_key=entry.entry_key,
                        path=entry.path,
                        name=prepared.canonical_name,
                        description=prepared.description,
                    )
                )
    _authorize_source(source.personal, request, user, db_session)
    return response


@router.get("")
def list_marketplaces(
    request: Request,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> list[MarketplaceManagementSnapshot]:
    rows = list_managed_marketplaces(user, db_session)
    if not token_allows_permission(request, Permission.MANAGE_SKILLS):
        rows = [row for row in rows if row.owner_user_id == user.id]
    return rows


@router.get("/{marketplace_id}")
def get_marketplace(
    marketplace_id: UUID,
    request: Request,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> MarketplaceManagementDetail:
    detail = fetch_managed_marketplace(marketplace_id, user, db_session)
    if detail.marketplace.owner_user_id != user.id and not token_allows_permission(
        request, Permission.MANAGE_SKILLS
    ):
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Marketplace not found")
    return detail


def _commit_and_dispatch(
    marketplace_id: UUID, user: User, db_session: Session
) -> MarketplaceManagementSnapshot:
    snapshot = fetch_managed_marketplace(marketplace_id, user, db_session).marketplace
    db_session.commit()
    try:
        dispatch_marketplace_sync(get_current_tenant_id(), marketplace_id)
    except Exception:
        logger.warning("Marketplace dispatch deferred to recovery: %s", marketplace_id)
    return snapshot


def _push_after_commit(affected: set[UUID]) -> None:
    if not affected:
        return
    try:
        with get_session_with_current_tenant() as session:
            push_skills_for_users(affected, session)
            session.commit()
    except Exception:
        logger.warning("Marketplace sandbox push failed after commit")


@router.post("")
def create_marketplace(
    source: MarketplaceCreateRequest,
    request: Request,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> MarketplaceManagementSnapshot:
    preview = _preview_source(source, request, user, db_session)
    if isinstance(preview, MarketplaceFailedPreview):
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, preview.reason)
    maybe_mark_tenant_active(get_current_tenant_id(), caller="marketplace_sync")
    tier = get_current_tier() if source.access is not None else None
    with db_session.begin_nested():
        marketplace = create_marketplace__no_commit(
            name=source.name,
            provider=source.provider,
            config=source.provider_config,
            personal=source.personal,
            user=user,
            db_session=db_session,
        )
        if source.access is not None and tier is not None:
            set_marketplace_default_access__no_commit(
                marketplace.id, source.access.to_change(), user, db_session, tier=tier
            )
    return _commit_and_dispatch(marketplace.id, user, db_session)


@router.post("/{marketplace_id}/sync")
def request_marketplace_sync(
    marketplace_id: UUID,
    request: Request,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> MarketplaceManagementSnapshot:
    maybe_mark_tenant_active(get_current_tenant_id(), caller="marketplace_sync")
    get_marketplace(marketplace_id, request, user, db_session)
    request_managed_marketplace_sync__no_commit(marketplace_id, user, db_session)
    return _commit_and_dispatch(marketplace_id, user, db_session)


@router.post("/{marketplace_id}/confirm-retirements")
def confirm_marketplace_retirements(
    marketplace_id: UUID,
    confirmation: MarketplaceConfirmationRequest,
    request: Request,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> MarketplaceManagementSnapshot:
    maybe_mark_tenant_active(get_current_tenant_id(), caller="marketplace_sync")
    get_marketplace(marketplace_id, request, user, db_session)
    confirm_marketplace_retirement__no_commit(
        marketplace_id,
        expected_revision=confirmation.revision,
        expected_skill_ids=confirmation.skill_ids,
        user=user,
        db_session=db_session,
    )
    return _commit_and_dispatch(marketplace_id, user, db_session)


@router.post("/{marketplace_id}/replace-login")
def replace_marketplace_login(
    marketplace_id: UUID,
    request: Request,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> MarketplaceManagementSnapshot:
    snapshot = get_marketplace(marketplace_id, request, user, db_session).marketplace
    candidate = Marketplace(
        provider=snapshot.provider,
        provider_config=snapshot.provider_config,
        login_user_id=user.id,
    )
    db_session.commit()
    get_marketplace_adapter(candidate, get_current_tenant_id()).resolve_revision()
    maybe_mark_tenant_active(get_current_tenant_id(), caller="marketplace_sync")
    replace_marketplace_login__no_commit(marketplace_id, user, db_session)
    return _commit_and_dispatch(marketplace_id, user, db_session)


@router.patch("/{marketplace_id}/access")
def set_marketplace_access(
    marketplace_id: UUID,
    access: MarketplaceAccessRequest,
    user: User = Depends(require_permission(Permission.MANAGE_SKILLS)),
    db_session: Session = Depends(get_session),
) -> MarketplaceManagementSnapshot:
    tier = get_current_tier()
    affected = set_marketplace_default_access__no_commit(
        marketplace_id, access.to_change(), user, db_session, tier=tier
    )
    snapshot = fetch_managed_marketplace(marketplace_id, user, db_session).marketplace
    db_session.commit()
    _push_after_commit(affected)
    return snapshot


@router.delete("/{marketplace_id}")
def remove_marketplace(
    marketplace_id: UUID,
    request: Request,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> None:
    get_marketplace(marketplace_id, request, user, db_session)
    removed = remove_marketplace__no_commit(marketplace_id, user, db_session)
    db_session.commit()
    _push_after_commit(removed.affected_user_ids)
    try:
        with get_session_with_current_tenant() as session:
            delete_unreferenced_skill_bundles(list(removed.cleanup_file_ids), session)
    except Exception:
        logger.warning(
            "Marketplace cleanup deferred to orphan sweep: %s", marketplace_id
        )
    if removed.webhook is not None:
        hook = removed.webhook
        try:
            get_marketplace_adapter(
                Marketplace(
                    provider=hook.provider,
                    provider_config=hook.provider_config,
                    login_user_id=hook.login_user_id,
                    webhook_id=hook.webhook_id,
                ),
                get_current_tenant_id(),
            ).remove_webhook()
        except Exception:
            logger.warning(
                "Marketplace removed; provider webhook cleanup failed: %s",
                marketplace_id,
            )
