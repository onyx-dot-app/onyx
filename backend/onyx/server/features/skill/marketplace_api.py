"""Every route authorizes before any GitHub call."""

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from onyx.auth.permissions import has_global_permission, require_permission
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission, PluginInstallationPolicy
from onyx.db.marketplace import (
    confirm_marketplace_deletes__no_commit,
    create_github_marketplace__no_commit,
    delete_github_marketplace__no_commit,
    find_github_marketplace,
    get_github_marketplace,
    list_github_marketplaces,
    list_marketplace_plugins,
    pending_delete_plugins,
    replace_marketplace_login__no_commit,
    request_marketplace_sync__no_commit,
)
from onyx.db.models import Marketplace, User
from onyx.db.plugin import set_marketplace_default__no_commit
from onyx.db.users import fetch_user_by_id
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.staging import delete_files_best_effort
from onyx.integrations.github_auth import github_authorization_for
from onyx.integrations.plugin_needs import integrations_for_needs, need_views
from onyx.server.features.skill.marketplace_models import (
    MarketplaceConfirmDeletesRequest,
    MarketplaceCreateRequest,
    MarketplaceDefaultAccessRequest,
    MarketplaceDetail,
    MarketplaceEntryView,
    MarketplaceList,
    MarketplacePendingDelete,
    MarketplacePreviewEntry,
    MarketplacePreviewResponse,
    MarketplacePreviewSkill,
    MarketplaceScope,
    MarketplaceSourceRequest,
    MarketplaceSummary,
)
from onyx.server.models import MinimalUserSnapshot
from onyx.skills.marketplace.compare import entry_result
from onyx.skills.marketplace.models import MarketplaceEntryResult, ReadyPlugin
from onyx.skills.marketplace.provider import (
    GitHubMarketplaceAdapter,
    marketplace_config,
)
from onyx.skills.marketplace.sync import (
    SYNC_FAILED_ERROR,
    enqueue_marketplace_sync,
    read_marketplace_repository,
    sync_request_is_live,
)
from onyx.skills.push import push_skills_and_commit

router = APIRouter(prefix="/marketplaces")

_MARKETPLACE_CLEANUP = "marketplace delete cleanup"


def _is_manager(user: User) -> bool:
    return has_global_permission(user, Permission.MANAGE_PLUGINS)


def _authorize_scope(scope: MarketplaceScope, user: User) -> None:
    if scope == MarketplaceScope.COMPANY and not _is_manager(user):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "Only an organization-wide plugin manager can add a company marketplace.",
        )


def _authorized_marketplace(
    marketplace_id: UUID, user: User, db_session: Session
) -> Marketplace:
    marketplace = get_github_marketplace(marketplace_id, db_session)
    if marketplace is None or (
        marketplace.owner_user_id is not None and marketplace.owner_user_id != user.id
    ):
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Marketplace not found.")
    if marketplace.owner_user_id is None and not _is_manager(user):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "Only an organization-wide plugin manager can manage a company marketplace.",
        )
    return marketplace


def _summary(
    marketplace: Marketplace, plugin_count: int, db_session: Session
) -> MarketplaceSummary:
    config = marketplace_config(marketplace)
    login = (
        fetch_user_by_id(db_session, marketplace.login_user_id)
        if marketplace.login_user_id is not None
        else None
    )
    sync_requested = sync_request_is_live(marketplace.sync_requested_at)
    first_sync_died = (
        marketplace.last_synced_at is None
        and not sync_requested
        and not sync_request_is_live(marketplace.created_at)
    )
    return MarketplaceSummary(
        id=marketplace.id,
        name=marketplace.name,
        scope=(
            MarketplaceScope.COMPANY
            if marketplace.owner_user_id is None
            else MarketplaceScope.PERSONAL
        ),
        repository=config.repository,
        folder=config.folder,
        ref=config.ref,
        default_installation_policy=marketplace.default_installation_policy,
        login_user=(
            MinimalUserSnapshot(id=login.id, email=login.email)
            if login is not None
            else None
        ),
        plugin_count=plugin_count,
        last_synced_at=marketplace.last_synced_at,
        last_synced_revision=marketplace.last_synced_revision,
        last_error=(
            SYNC_FAILED_ERROR
            if first_sync_died and marketplace.last_error is None
            else marketplace.last_error
        ),
        sync_requested=sync_requested,
        needs_confirmation=marketplace.pending_delete_revision is not None,
        created_at=marketplace.created_at,
    )


def _detail(marketplace: Marketplace, db_session: Session) -> MarketplaceDetail:
    plugins = {
        plugin.marketplace_entry_key: plugin
        for plugin in list_marketplace_plugins(marketplace.id, db_session)
    }
    entries = [
        MarketplaceEntryResult.model_validate(item)
        for item in marketplace.last_sync_result or []
    ]
    return MarketplaceDetail(
        **_summary(marketplace, len(plugins), db_session).model_dump(),
        entries=[
            MarketplaceEntryView(
                key=entry.key,
                path=entry.path,
                status=entry.status,
                reason=entry.reason,
                plugin_id=plugins[entry.key].id if entry.key in plugins else None,
                plugin_name=plugins[entry.key].name if entry.key in plugins else None,
            )
            for entry in entries
        ],
        pending_delete_revision=marketplace.pending_delete_revision,
        pending_deletes=[
            MarketplacePendingDelete(
                plugin_id=plugin.plugin_id, entry_key=plugin.entry_key, name=plugin.name
            )
            for plugin in pending_delete_plugins(marketplace, db_session)
        ],
    )


def _request_sync(
    marketplace_id: UUID, background_tasks: BackgroundTasks, db_session: Session
) -> None:
    request_marketplace_sync__no_commit(marketplace_id, db_session)
    db_session.commit()
    enqueue_marketplace_sync(marketplace_id, background_tasks)


@router.post("/preview")
def preview_marketplace(
    request: MarketplaceSourceRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> MarketplacePreviewResponse:
    config = request.to_config()
    authorization = github_authorization_for(user.id, db_session)
    # End the read transaction before the GitHub calls.
    db_session.commit()
    read = read_marketplace_repository(
        GitHubMarketplaceAdapter(config, authorization), config.folder
    )
    integrations = integrations_for_needs(user, db_session)
    entries: list[MarketplacePreviewEntry] = []
    for entry in read.entries:
        result = entry_result(entry)
        if not isinstance(entry, ReadyPlugin):
            entries.append(
                MarketplacePreviewEntry(
                    key=result.key,
                    path=result.path,
                    status=result.status,
                    reason=result.reason,
                )
            )
            continue
        manifest = entry.bundle.manifest
        entries.append(
            MarketplacePreviewEntry(
                key=result.key,
                path=result.path,
                status=result.status,
                reason=None,
                name=manifest.name,
                description=manifest.description,
                version=manifest.version,
                skills=[
                    MarketplacePreviewSkill(
                        name=skill.content.name, description=skill.content.description
                    )
                    for skill in entry.bundle.skills
                ],
                needs=need_views(entry.bundle.needs, integrations),
                warnings=entry.bundle.warnings,
            )
        )
    return MarketplacePreviewResponse(
        repository=config.repository,
        folder=config.folder,
        ref=config.ref,
        revision=read.revision,
        status="failed" if read.failure is not None else "complete",
        name=read.name,
        reason=read.failure,
        entries=entries,
    )


@router.post("")
def create_marketplace(
    request: MarketplaceCreateRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> MarketplaceDetail:
    _authorize_scope(request.scope, user)
    config = request.to_config()
    policy = request.default_installation_policy
    if request.scope == MarketplaceScope.PERSONAL and policy is not None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "A personal marketplace has no default install setting.",
        )
    if policy == PluginInstallationPolicy.REQUIRED:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, "A marketplace default cannot be Required."
        )
    owner_user_id = user.id if request.scope == MarketplaceScope.PERSONAL else None
    provider_config = config.model_dump(mode="json")
    if find_github_marketplace(owner_user_id, provider_config, db_session) is not None:
        raise OnyxError(
            OnyxErrorCode.CONFLICT,
            "This marketplace is already added. Sync it to get the newest plugins.",
        )
    marketplace = create_github_marketplace__no_commit(
        name=config.repository,
        provider_config=provider_config,
        owner_user_id=owner_user_id,
        login_user_id=user.id,
        default_installation_policy=policy or PluginInstallationPolicy.AVAILABLE,
        db_session=db_session,
    )
    marketplace_id = marketplace.id
    _request_sync(marketplace_id, background_tasks, db_session)
    return _detail(
        _authorized_marketplace(marketplace_id, user, db_session), db_session
    )


@router.get("")
def list_marketplaces(
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> MarketplaceList:
    return MarketplaceList(
        marketplaces=[
            _summary(marketplace, plugin_count, db_session)
            for marketplace, plugin_count in list_github_marketplaces(
                user.id, _is_manager(user), db_session
            )
        ]
    )


@router.get("/{marketplace_id}")
def get_marketplace(
    marketplace_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> MarketplaceDetail:
    return _detail(
        _authorized_marketplace(marketplace_id, user, db_session), db_session
    )


@router.post("/{marketplace_id}/sync")
def sync_marketplace_now(
    marketplace_id: UUID,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> MarketplaceDetail:
    _authorized_marketplace(marketplace_id, user, db_session)
    _request_sync(marketplace_id, background_tasks, db_session)
    return _detail(
        _authorized_marketplace(marketplace_id, user, db_session), db_session
    )


@router.post("/{marketplace_id}/confirm-deletes")
def confirm_marketplace_deletes(
    marketplace_id: UUID,
    request: MarketplaceConfirmDeletesRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> MarketplaceDetail:
    _authorized_marketplace(marketplace_id, user, db_session)
    affected, file_ids = confirm_marketplace_deletes__no_commit(
        marketplace_id, request.revision, db_session
    )
    _request_sync(marketplace_id, background_tasks, db_session)
    push_skills_and_commit(affected, db_session)
    delete_files_best_effort(file_ids, _MARKETPLACE_CLEANUP)
    return _detail(
        _authorized_marketplace(marketplace_id, user, db_session), db_session
    )


@router.put("/{marketplace_id}/default-access")
def set_marketplace_default_access(
    marketplace_id: UUID,
    request: MarketplaceDefaultAccessRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> MarketplaceDetail:
    marketplace = _authorized_marketplace(marketplace_id, user, db_session)
    if marketplace.owner_user_id is not None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "A personal marketplace has no default install setting.",
        )
    affected = set_marketplace_default__no_commit(
        marketplace_id, request.installation_policy, db_session
    )
    db_session.commit()
    push_skills_and_commit(affected, db_session)
    return _detail(
        _authorized_marketplace(marketplace_id, user, db_session), db_session
    )


@router.post("/{marketplace_id}/replace-login")
def replace_marketplace_login(
    marketplace_id: UUID,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> MarketplaceDetail:
    _authorized_marketplace(marketplace_id, user, db_session)
    if github_authorization_for(user.id, db_session) is None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Connect your GitHub account first, then replace the login.",
        )
    replace_marketplace_login__no_commit(marketplace_id, user.id, db_session)
    _request_sync(marketplace_id, background_tasks, db_session)
    return _detail(
        _authorized_marketplace(marketplace_id, user, db_session), db_session
    )


@router.delete("/{marketplace_id}")
def delete_marketplace(
    marketplace_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> None:
    _authorized_marketplace(marketplace_id, user, db_session)
    affected, file_ids = delete_github_marketplace__no_commit(
        marketplace_id, db_session
    )
    db_session.commit()
    push_skills_and_commit(affected, db_session)
    delete_files_best_effort(file_ids, _MARKETPLACE_CLEANUP)
