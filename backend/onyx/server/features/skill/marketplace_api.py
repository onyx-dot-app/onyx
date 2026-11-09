"""Marketplace source preview and authorized management reads."""

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission, token_allows_permission
from onyx.auth.scoped_permissions import assert_global
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.marketplace_management import (
    fetch_managed_marketplace,
    list_managed_marketplaces,
)
from onyx.db.models import Marketplace, User
from onyx.db.resource_access import fetch_resource_access_user
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.skill.marketplace_models import (
    MarketplaceCompletePreview,
    MarketplaceFailedPreview,
    MarketplaceReadyPreview,
    MarketplaceSourceRequest,
)
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
from shared_configs.contextvars import get_current_tenant_id

router = APIRouter(prefix="/marketplaces")


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
