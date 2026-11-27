"""Every route authorizes before any GitHub call."""

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from sqlalchemy.orm import Session

from onyx.auth.permissions import (
    has_global_permission,
    require_permission,
    token_allows,
)
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission, PluginInstallationPolicy
from onyx.db.marketplace import (
    create_github_marketplace__no_commit,
    delete_github_marketplace__no_commit,
    get_github_marketplace,
    list_github_marketplaces,
    list_marketplace_plugins,
    replace_marketplace_login__no_commit,
    source_added_for,
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
    MarketplaceCreateRequest,
    MarketplaceDefaultAccessRequest,
    MarketplaceDetail,
    MarketplaceEntryView,
    MarketplaceList,
    MarketplacePluginView,
    MarketplacePreviewEntry,
    MarketplacePreviewResponse,
    MarketplacePreviewSkill,
    MarketplaceScope,
    MarketplaceSourceRequest,
    MarketplaceSummary,
)
from onyx.server.models import MinimalUserSnapshot
from onyx.skills.marketplace.compare import entry_result
from onyx.skills.marketplace.models import (
    GitHubMarketplaceConfig,
    MarketplaceEntryResult,
    ReadyPlugin,
)
from onyx.skills.marketplace.provider import (
    GitHubMarketplaceAdapter,
    marketplace_config,
)
from onyx.skills.marketplace.sync import (
    marketplace_syncing,
    read_marketplace_repository,
    request_marketplace_sync,
)
from onyx.skills.push import push_skills_and_commit
from onyx.utils.github import (
    GitHubRevision,
    GitHubSource,
    github_default_branch,
    resolve_github_revision,
)

router = APIRouter(prefix="/marketplaces")

_MARKETPLACE_CLEANUP = "marketplace delete cleanup"


def _is_manager(user: User, http_request: Request) -> bool:
    """An organization-wide plugin manager whose token also allows it."""
    return has_global_permission(user, Permission.MANAGE_PLUGINS) and token_allows(
        http_request, Permission.MANAGE_PLUGINS
    )


def _authorize_scope(scope: MarketplaceScope, manager: bool) -> None:
    if scope == MarketplaceScope.COMPANY and not manager:
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "Only an organization-wide plugin manager can add a company marketplace.",
        )


def _authorized_marketplace(
    marketplace_id: UUID,
    user: User,
    manager: bool,
    db_session: Session,
    *,
    read_only: bool = False,
) -> Marketplace:
    marketplace = get_github_marketplace(marketplace_id, db_session)
    if marketplace is None or (
        marketplace.owner_user_id is not None and marketplace.owner_user_id != user.id
    ):
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Marketplace not found.")
    if marketplace.owner_user_id is None and not read_only and not manager:
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "Only an organization-wide plugin manager can manage a company marketplace.",
        )
    return marketplace


def _summary(
    marketplace: Marketplace, plugin_count: int, manager: bool, db_session: Session
) -> MarketplaceSummary:
    config = marketplace_config(marketplace)
    login = (
        fetch_user_by_id(db_session, marketplace.login_user_id)
        if marketplace.login_user_id is not None
        else None
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
        default_installation_policy=(
            marketplace.default_installation_policy
            if marketplace.owner_user_id is None
            else None
        ),
        can_manage=marketplace.owner_user_id is not None or manager,
        login_user=(
            MinimalUserSnapshot(id=login.id, email=login.email)
            if login is not None
            else None
        ),
        plugin_count=plugin_count,
        last_synced_at=marketplace.last_synced_at,
        last_synced_revision=marketplace.last_synced_revision,
        last_error=marketplace.last_error,
        syncing=marketplace_syncing(marketplace.id),
        created_at=marketplace.created_at,
    )


def _detail(
    marketplace: Marketplace, manager: bool, db_session: Session
) -> MarketplaceDetail:
    plugins = {
        plugin.name: plugin
        for plugin in list_marketplace_plugins(marketplace.id, db_session)
    }
    entries = [
        MarketplaceEntryResult.model_validate(item)
        for item in marketplace.last_sync_result or []
    ]
    return MarketplaceDetail(
        **_summary(marketplace, len(plugins), manager, db_session).model_dump(),
        login_has_github=marketplace.login_user_id is not None
        and github_authorization_for(marketplace.login_user_id, db_session) is not None,
        entries=[
            MarketplaceEntryView(
                key=entry.key,
                path=entry.path,
                status=entry.status,
                reason=entry.reason,
                reason_code=entry.reason_code,
                plugin_id=plugins[entry.key].id if entry.key in plugins else None,
            )
            for entry in entries
        ],
        plugins=[
            MarketplacePluginView(id=plugin.id, name=plugin.name)
            for plugin in sorted(plugins.values(), key=lambda plugin: plugin.name)
        ],
    )


def _request_sync(
    marketplace_id: UUID, background_tasks: BackgroundTasks, db_session: Session
) -> None:
    db_session.commit()
    request_marketplace_sync(marketplace_id, background_tasks)


def _source_config(
    request: MarketplaceSourceRequest, authorization: str | None
) -> tuple[GitHubMarketplaceConfig, str]:
    """The source, and the repository's default branch. A ref that names the
    default branch is stored as no ref, so that ``owner/repo`` and
    ``.../tree/main`` are one source."""

    def resolve(source: GitHubSource) -> GitHubRevision:
        return resolve_github_revision(source, authorization)

    config = request.to_config(resolve)
    default_branch = github_default_branch(
        GitHubSource(owner=config.owner, repo=config.repo), authorization
    )
    if config.ref and config.ref == default_branch:
        config = config.model_copy(update={"ref": None})
    return config, default_branch


@router.post("/preview")
def preview_marketplace(
    request: MarketplaceSourceRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> MarketplacePreviewResponse:
    authorization = github_authorization_for(user.id, db_session)
    # End the read transaction before the GitHub calls.
    db_session.commit()
    config, default_branch = _source_config(request, authorization)
    read = read_marketplace_repository(
        GitHubMarketplaceAdapter(config, authorization), config.folder
    )
    integrations = integrations_for_needs(user, db_session)
    added_personal, added_company = source_added_for(
        config, user.id, db_session, default_branch
    )
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
                    reason_code=result.reason_code,
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
        added_personal=added_personal,
        added_company=added_company,
    )


@router.post("")
def create_marketplace(
    http_request: Request,
    request: MarketplaceCreateRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> MarketplaceDetail:
    manager = _is_manager(user, http_request)
    _authorize_scope(request.scope, manager)
    config, default_branch = _source_config(
        request, github_authorization_for(user.id, db_session)
    )
    policy = request.default_installation_policy
    if request.scope == MarketplaceScope.PERSONAL and policy is not None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "A personal marketplace has no default install setting.",
        )
    marketplace = create_github_marketplace__no_commit(
        name=(request.name or "").strip() or config.repository,
        config=config,
        owner_user_id=user.id if request.scope == MarketplaceScope.PERSONAL else None,
        login_user_id=user.id,
        default_installation_policy=policy or PluginInstallationPolicy.AVAILABLE,
        db_session=db_session,
        default_branch=default_branch,
    )
    marketplace_id = marketplace.id
    _request_sync(marketplace_id, background_tasks, db_session)
    return _detail(
        _authorized_marketplace(marketplace_id, user, manager, db_session),
        manager,
        db_session,
    )


@router.get("")
def list_marketplaces(
    http_request: Request,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> MarketplaceList:
    manager = _is_manager(user, http_request)
    return MarketplaceList(
        marketplaces=[
            _summary(marketplace, plugin_count, manager, db_session)
            for marketplace, plugin_count in list_github_marketplaces(
                user.id, db_session
            )
        ]
    )


@router.get("/{marketplace_id}")
def get_marketplace(
    http_request: Request,
    marketplace_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> MarketplaceDetail:
    manager = _is_manager(user, http_request)
    return _detail(
        _authorized_marketplace(
            marketplace_id, user, manager, db_session, read_only=True
        ),
        manager,
        db_session,
    )


@router.post("/{marketplace_id}/sync")
def sync_marketplace_now(
    http_request: Request,
    marketplace_id: UUID,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> MarketplaceDetail:
    manager = _is_manager(user, http_request)
    _authorized_marketplace(marketplace_id, user, manager, db_session)
    _request_sync(marketplace_id, background_tasks, db_session)
    return _detail(
        _authorized_marketplace(marketplace_id, user, manager, db_session),
        manager,
        db_session,
    )


@router.put("/{marketplace_id}/default-access")
def set_marketplace_default_access(
    http_request: Request,
    marketplace_id: UUID,
    request: MarketplaceDefaultAccessRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> MarketplaceDetail:
    manager = _is_manager(user, http_request)
    marketplace = _authorized_marketplace(marketplace_id, user, manager, db_session)
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
        _authorized_marketplace(marketplace_id, user, manager, db_session),
        manager,
        db_session,
    )


@router.post("/{marketplace_id}/replace-login")
def replace_marketplace_login(
    http_request: Request,
    marketplace_id: UUID,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> MarketplaceDetail:
    manager = _is_manager(user, http_request)
    _authorized_marketplace(marketplace_id, user, manager, db_session)
    replace_marketplace_login__no_commit(marketplace_id, user.id, db_session)
    _request_sync(marketplace_id, background_tasks, db_session)
    return _detail(
        _authorized_marketplace(marketplace_id, user, manager, db_session),
        manager,
        db_session,
    )


@router.delete("/{marketplace_id}")
def delete_marketplace(
    http_request: Request,
    marketplace_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> None:
    manager = _is_manager(user, http_request)
    _authorized_marketplace(marketplace_id, user, manager, db_session)
    affected, file_ids = delete_github_marketplace__no_commit(
        marketplace_id, db_session
    )
    db_session.commit()
    push_skills_and_commit(affected, db_session)
    delete_files_best_effort(file_ids, _MARKETPLACE_CLEANUP)
