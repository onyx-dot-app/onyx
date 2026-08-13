from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from onyx.auth.permission_projection import document_set_permissions
from onyx.auth.permissions import (
    has_permission,
    require_permission,
)
from onyx.auth.scoped_permissions import (
    assert_within_scope,
)
from onyx.background.celery.versioned_apps.client import app as client_app
from onyx.configs.app_configs import DISABLE_VECTOR_DB
from onyx.configs.constants import OnyxCeleryPriority, OnyxCeleryTask
from onyx.db.connector_credential_pair import (
    get_connector_credential_pairs_for_user,
)
from onyx.db.document_set import (
    check_document_sets_are_public,
    fetch_all_document_sets_for_user,
    get_document_set_by_id,
    get_group_ids_for_document_set,
    insert_document_set,
    mark_document_set_as_to_be_deleted,
    update_document_set,
    user_owns_groupless_document_set,
)
from onyx.db.document_set import delete_document_set as db_delete_document_set
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission, PermissionAuthority
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.document_set.models import (
    CheckDocSetPublicRequest,
    CheckDocSetPublicResponse,
    DocumentSetCreationRequest,
    DocumentSetSummary,
    DocumentSetUpdateRequest,
)
from shared_configs.contextvars import get_current_tenant_id

router = APIRouter(prefix="/manage")


@router.post("/admin/document-set")
def create_document_set(
    document_set_creation_request: DocumentSetCreationRequest,
    user: User = Depends(
        require_permission(Permission.MANAGE_DOCUMENT_SETS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
    tenant_id: str = Depends(get_current_tenant_id),
) -> int:
    # GATE 2 write authorization (see assert_within_scope).
    assert_within_scope(
        user,
        db_session,
        permission=Permission.MANAGE_DOCUMENT_SETS,
        current_group_ids=[],
        requested_group_ids=document_set_creation_request.groups or [],
        is_non_public=not document_set_creation_request.is_public,
    )
    try:
        document_set_db_model, _ = insert_document_set(
            document_set_creation_request=document_set_creation_request,
            user_id=user.id,
            db_session=db_session,
        )
    except Exception as e:
        raise OnyxError(OnyxErrorCode.VALIDATION_ERROR, str(e))

    if not DISABLE_VECTOR_DB:
        client_app.send_task(
            OnyxCeleryTask.CHECK_FOR_VESPA_SYNC_TASK,
            kwargs={"tenant_id": tenant_id},
            priority=OnyxCeleryPriority.HIGH,
        )

    return document_set_db_model.id


@router.patch("/admin/document-set")
def patch_document_set(
    document_set_update_request: DocumentSetUpdateRequest,
    user: User = Depends(
        require_permission(Permission.MANAGE_DOCUMENT_SETS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
    tenant_id: str = Depends(get_current_tenant_id),
) -> None:
    document_set = get_document_set_by_id(db_session, document_set_update_request.id)
    if document_set is None:
        raise OnyxError(
            OnyxErrorCode.DOCUMENT_SET_NOT_FOUND,
            f"Document set {document_set_update_request.id} does not exist",
        )

    current_group_ids = get_group_ids_for_document_set(
        db_session, document_set_update_request.id
    )
    stays_non_public = (
        not document_set.is_public and not document_set_update_request.is_public
    )
    # within_scope unions current and requested, so a groupless set never passes — its
    # creator could see it but not rename it; adding a group still hits the gate below
    creator_editing_in_place = (
        document_set.user_id == user.id
        and not current_group_ids
        and not document_set_update_request.groups
        and stays_non_public
    )

    # GATE 2 write authorization (see assert_within_scope). Current groups AND
    # current privacy are re-read from the DB, not the client, so a manager can
    # neither capture-by-reassignment nor convert a currently-PUBLIC set to PRIVATE.
    if creator_editing_in_place:
        # update_document_set gates attachments with check_if_cc_pairs_are_owned_by_groups,
        # which is vacuous on an empty group list, so bound them to what the user can see
        visible_cc_pair_ids = {
            cc_pair.id
            for cc_pair in get_connector_credential_pairs_for_user(
                db_session=db_session,
                user=user,
                get_editable=False,
                ids=document_set_update_request.cc_pair_ids,
                processing_mode=None,
            )
        }
        if set(document_set_update_request.cc_pair_ids) - visible_cc_pair_ids:
            raise OnyxError(
                OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
                "Document set references a connector you do not have access to.",
            )
    else:
        assert_within_scope(
            user,
            db_session,
            permission=Permission.MANAGE_DOCUMENT_SETS,
            current_group_ids=current_group_ids,
            requested_group_ids=document_set_update_request.groups,
            is_non_public=stays_non_public,
        )

    try:
        update_document_set(
            document_set_update_request=document_set_update_request,
            db_session=db_session,
            user=user,
        )
    except Exception as e:
        raise OnyxError(OnyxErrorCode.VALIDATION_ERROR, str(e))

    if not DISABLE_VECTOR_DB:
        client_app.send_task(
            OnyxCeleryTask.CHECK_FOR_VESPA_SYNC_TASK,
            kwargs={"tenant_id": tenant_id},
            priority=OnyxCeleryPriority.HIGH,
        )


@router.delete("/admin/document-set/{document_set_id}")
def delete_document_set(
    document_set_id: int,
    user: User = Depends(
        require_permission(Permission.MANAGE_DOCUMENT_SETS, allow_scope=True)
    ),
    db_session: Session = Depends(get_session),
    tenant_id: str = Depends(get_current_tenant_id),
) -> None:
    document_set = get_document_set_by_id(db_session, document_set_id)
    if document_set is None:
        raise OnyxError(
            OnyxErrorCode.DOCUMENT_SET_NOT_FOUND,
            f"Document set {document_set_id} does not exist",
        )

    # GATE 2: delete is admin-only (it triggers index cleanup), except a groupless set
    # its creator made — that one is shared with nobody
    is_admin = (
        has_permission(user, Permission.MANAGE_DOCUMENT_SETS)
        is PermissionAuthority.GLOBAL
    )
    if not is_admin and not user_owns_groupless_document_set(document_set, user):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "Deleting a shared document set is restricted to administrators.",
        )

    try:
        mark_document_set_as_to_be_deleted(
            db_session=db_session,
            document_set_id=document_set_id,
            user=user,
        )
    except Exception as e:
        raise OnyxError(OnyxErrorCode.VALIDATION_ERROR, str(e))

    if DISABLE_VECTOR_DB:
        db_session.refresh(document_set)
        db_delete_document_set(document_set, db_session)
    else:
        client_app.send_task(
            OnyxCeleryTask.CHECK_FOR_VESPA_SYNC_TASK,
            kwargs={"tenant_id": tenant_id},
            priority=OnyxCeleryPriority.HIGH,
        )


"""Endpoints for non-admins"""


@router.get("/document-set")
def list_document_sets_for_user(
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
    get_editable: bool = Query(
        False, description="If true, return editable document sets"
    ),
) -> list[DocumentSetSummary]:
    readable = fetch_all_document_sets_for_user(
        db_session=db_session, user=user, get_editable=get_editable
    )
    authority = has_permission(user, Permission.MANAGE_DOCUMENT_SETS)
    is_document_sets_admin = authority is PermissionAuthority.GLOBAL

    # Union the two result sets and stamp from membership, like the connector listing.
    # The editable query is the only one that surfaces a creator's groupless set, and
    # recomputing editability with within_scope instead would drift from the filter.
    if authority is PermissionAuthority.NONE:
        editable = []  # GATE 1 refuses their PATCH regardless
    elif get_editable or is_document_sets_admin:
        editable = list(readable)
    else:
        editable = list(
            fetch_all_document_sets_for_user(
                db_session=db_session, user=user, get_editable=True
            )
        )
    editable_ids = {ds.id for ds in editable}
    by_id = {ds.id: ds for ds in readable}
    by_id.update({ds.id: ds for ds in editable})
    document_sets = list(by_id.values())

    summaries: list[DocumentSetSummary] = []
    for ds in document_sets:
        is_editable = ds.id in editable_ids
        summaries.append(
            DocumentSetSummary.from_model(
                ds,
                permissions=document_set_permissions(
                    is_editable=is_editable,
                    is_document_sets_admin=is_document_sets_admin,
                    owns_groupless=is_editable
                    and user_owns_groupless_document_set(ds, user),
                ),
            )
        )
    return summaries


@router.get("/document-set-public")
def document_set_public(
    check_public_request: CheckDocSetPublicRequest,
    _: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> CheckDocSetPublicResponse:
    is_public = check_document_sets_are_public(
        document_set_ids=check_public_request.document_set_ids, db_session=db_session
    )
    return CheckDocSetPublicResponse(is_public=is_public)
