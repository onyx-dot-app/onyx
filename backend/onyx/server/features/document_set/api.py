from fastapi import APIRouter
from fastapi import Depends
from fastapi import Query
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.auth.scoped_permissions import assert_within_scope
from onyx.background.celery.versioned_apps.client import app as client_app
from onyx.configs.app_configs import DISABLE_VECTOR_DB
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryTask
from onyx.db.document_set import check_document_sets_are_public
from onyx.db.document_set import delete_document_set as db_delete_document_set
from onyx.db.document_set import fetch_all_document_sets_for_user
from onyx.db.document_set import get_document_set_by_id
from onyx.db.document_set import get_group_ids_for_document_set
from onyx.db.document_set import insert_document_set
from onyx.db.document_set import mark_document_set_as_to_be_deleted
from onyx.db.document_set import update_document_set
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.document_set.models import CheckDocSetPublicRequest
from onyx.server.features.document_set.models import CheckDocSetPublicResponse
from onyx.server.features.document_set.models import DocumentSetCreationRequest
from onyx.server.features.document_set.models import DocumentSetSummary
from onyx.server.features.document_set.models import DocumentSetUpdateRequest
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

    # GATE 2 write authorization (see assert_within_scope). Current groups AND
    # current privacy are re-read from the DB, not the client, so a manager can
    # neither capture-by-reassignment nor convert a currently-PUBLIC set to PRIVATE.
    assert_within_scope(
        user,
        db_session,
        permission=Permission.MANAGE_DOCUMENT_SETS,
        current_group_ids=get_group_ids_for_document_set(
            db_session, document_set_update_request.id
        ),
        requested_group_ids=document_set_update_request.groups,
        is_non_public=not document_set.is_public
        and not document_set_update_request.is_public,
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
    user: User = Depends(require_permission(Permission.MANAGE_DOCUMENT_SETS)),
    db_session: Session = Depends(get_session),
    tenant_id: str = Depends(get_current_tenant_id),
) -> None:
    document_set = get_document_set_by_id(db_session, document_set_id)
    if document_set is None:
        raise OnyxError(
            OnyxErrorCode.DOCUMENT_SET_NOT_FOUND,
            f"Document set {document_set_id} does not exist",
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
    document_sets = fetch_all_document_sets_for_user(
        db_session=db_session, user=user, get_editable=get_editable
    )
    return [DocumentSetSummary.from_model(ds) for ds in document_sets]


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
