import json

from fastapi import APIRouter
from fastapi import Depends
from fastapi import File
from fastapi import Form
from fastapi import HTTPException
from fastapi import Query
from fastapi import UploadFile
from sqlalchemy.orm import Session

from onyx.auth.users import current_admin_user
from onyx.auth.users import current_curator_or_admin_user
from onyx.auth.users import current_user
from onyx.connectors.factory import validate_ccpair_for_user
from onyx.db.credentials import alter_credential
from onyx.db.credentials import cleanup_gmail_credentials
from onyx.db.credentials import create_credential
from onyx.db.credentials import CREDENTIAL_PERMISSIONS_TO_IGNORE
from onyx.db.credentials import delete_credential
from onyx.db.credentials import delete_credential_for_user
from onyx.db.credentials import fetch_credential_by_id_for_user
from onyx.db.credentials import fetch_credentials_by_source_for_user
from onyx.db.credentials import fetch_credentials_for_user
from onyx.db.credentials import swap_credentials_connector
from onyx.db.credentials import update_credential
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import DocumentSource
from onyx.db.models import User
from onyx.server.documents.models import CredentialBase
from onyx.server.documents.models import CredentialDataUpdateRequest
from onyx.server.documents.models import CredentialSnapshot
from onyx.server.documents.models import CredentialSwapRequest
from onyx.server.documents.models import ObjectCreationIdResponse
from onyx.server.documents.private_key_types import FILE_TYPE_TO_FILE_PROCESSOR
from onyx.server.documents.private_key_types import PrivateKeyFileTypes
from onyx.server.documents.private_key_types import ProcessPrivateKeyFileProtocol
from onyx.server.models import StatusResponse
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import fetch_ee_implementation_or_noop

logger = setup_logger()


router = APIRouter(prefix="/manage")


def _ignore_credential_permissions(source: DocumentSource) -> bool:
    return source in CREDENTIAL_PERMISSIONS_TO_IGNORE


"""Admin-only endpoints"""


@router.get("/admin/credential")
def list_credentials_admin(
    user: User | None = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> list[CredentialSnapshot]:
    """Lists all public credentials"""
    credentials = fetch_credentials_for_user(
        db_session=db_session,
        user=user,
        get_editable=False,
    )
    return [
        CredentialSnapshot.from_credential_db_model(credential)
        for credential in credentials
    ]


@router.get("/admin/similar-credentials/{source_type}")
def get_cc_source_full_info(
    source_type: DocumentSource,
    user: User | None = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
    get_editable: bool = Query(
        False, description="If true, return editable credentials"
    ),
) -> list[CredentialSnapshot]:
    credentials = fetch_credentials_by_source_for_user(
        db_session=db_session,
        user=user,
        document_source=source_type,
        get_editable=get_editable,
    )

    return [
        CredentialSnapshot.from_credential_db_model(credential)
        for credential in credentials
    ]


@router.delete("/admin/credential/{credential_id}")
def delete_credential_by_id_admin(
    credential_id: int,
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> StatusResponse:
    """Same as the user endpoint, but can delete any credential (not just the user's own)"""
    delete_credential(db_session=db_session, credential_id=credential_id)
    return StatusResponse(
        success=True, message="Credential deleted successfully", data=credential_id
    )


@router.put("/admin/credential/swap")
def swap_credentials_for_connector(
    credential_swap_req: CredentialSwapRequest,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> StatusResponse:
    validate_ccpair_for_user(
        credential_swap_req.connector_id,
        credential_swap_req.new_credential_id,
        credential_swap_req.access_type,
        db_session,
    )

    connector_credential_pair = swap_credentials_connector(
        new_credential_id=credential_swap_req.new_credential_id,
        connector_id=credential_swap_req.connector_id,
        db_session=db_session,
        user=user,
    )

    return StatusResponse(
        success=True,
        message="Credential swapped successfully",
        data=connector_credential_pair.id,
    )


@router.post("/credential")
def create_credential_from_model(
    credential_info: CredentialBase,
    user: User | None = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> ObjectCreationIdResponse:
    if not _ignore_credential_permissions(credential_info.source):
        fetch_ee_implementation_or_noop(
            "onyx.db.user_group", "validate_object_creation_for_user", None
        )(
            db_session=db_session,
            user=user,
            target_group_ids=credential_info.groups,
            object_is_public=credential_info.curator_public,
        )

    # Temporary fix for empty Google App credentials
    if credential_info.source == DocumentSource.GMAIL:
        cleanup_gmail_credentials(db_session=db_session)

    credential = create_credential(credential_info, user, db_session)
    return ObjectCreationIdResponse(
        id=credential.id,
        credential=CredentialSnapshot.from_credential_db_model(credential),
    )


@router.post("/credential/private-key")
def create_credential_with_private_key(
    credential_json: str = Form(...),
    admin_public: bool = Form(False),
    curator_public: bool = Form(False),
    groups: list[int] = Form([]),
    name: str | None = Form(None),
    source: str = Form(...),
    user: User | None = Depends(current_curator_or_admin_user),
    uploaded_file: UploadFile = File(...),
    field_key: str = Form(...),
    type_definition_key: str = Form(...),
    db_session: Session = Depends(get_session),
) -> ObjectCreationIdResponse:
    try:
        credential_data = json.loads(credential_json)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid JSON in credential_json: {str(e)}",
        )

    private_key_processor: ProcessPrivateKeyFileProtocol | None = (
        FILE_TYPE_TO_FILE_PROCESSOR.get(PrivateKeyFileTypes(type_definition_key))
    )
    if private_key_processor is None:
        raise HTTPException(
            status_code=400,
            detail="Invalid type definition key for private key file",
        )
    private_key_content: str = private_key_processor(uploaded_file)

    credential_data[field_key] = private_key_content

    credential_info = CredentialBase(
        credential_json=credential_data,
        admin_public=admin_public,
        curator_public=curator_public,
        groups=groups,
        name=name,
        source=DocumentSource(source),
    )

    if not _ignore_credential_permissions(DocumentSource(source)):
        fetch_ee_implementation_or_noop(
            "onyx.db.user_group", "validate_object_creation_for_user", None
        )(
            db_session=db_session,
            user=user,
            target_group_ids=groups,
            object_is_public=curator_public,
        )

    # Temporary fix for empty Google App credentials
    if DocumentSource(source) == DocumentSource.GMAIL:
        cleanup_gmail_credentials(db_session=db_session)

    credential = create_credential(credential_info, user, db_session)
    return ObjectCreationIdResponse(
        id=credential.id,
        credential=CredentialSnapshot.from_credential_db_model(credential),
    )


"""Endpoints for all"""


@router.get("/credential")
def list_credentials(
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> list[CredentialSnapshot]:
    credentials = fetch_credentials_for_user(db_session=db_session, user=user)
    return [
        CredentialSnapshot.from_credential_db_model(credential)
        for credential in credentials
    ]


@router.get("/credential/{credential_id}")
def get_credential_by_id(
    credential_id: int,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> CredentialSnapshot | StatusResponse[int]:
    credential = fetch_credential_by_id_for_user(
        credential_id,
        user,
        db_session,
        get_editable=False,
    )
    if credential is None:
        raise HTTPException(
            status_code=401,
            detail=f"Credential {credential_id} does not exist or does not belong to user",
        )

    return CredentialSnapshot.from_credential_db_model(credential)


@router.put("/admin/credential/{credential_id}")
def update_credential_data(
    credential_id: int,
    credential_update: CredentialDataUpdateRequest,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> CredentialBase:
    credential = alter_credential(
        credential_id,
        credential_update.name,
        credential_update.credential_json,
        user,
        db_session,
    )

    if credential is None:
        raise HTTPException(
            status_code=401,
            detail=f"Credential {credential_id} does not exist or does not belong to user",
        )

    return CredentialSnapshot.from_credential_db_model(credential)


@router.put("/admin/credential/private-key/{credential_id}")
def update_credential_private_key(
    credential_id: int,
    name: str = Form(...),
    credential_json: str = Form(...),
    uploaded_file: UploadFile = File(...),
    field_key: str = Form(...),
    type_definition_key: str = Form(...),
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> CredentialBase:
    try:
        credential_data = json.loads(credential_json)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid JSON in credential_json: {str(e)}",
        )

    private_key_processor: ProcessPrivateKeyFileProtocol | None = (
        FILE_TYPE_TO_FILE_PROCESSOR.get(PrivateKeyFileTypes(type_definition_key))
    )
    if private_key_processor is None:
        raise HTTPException(
            status_code=400,
            detail="Invalid type definition key for private key file",
        )
    private_key_content: str = private_key_processor(uploaded_file)
    credential_data[field_key] = private_key_content

    credential = alter_credential(
        credential_id,
        name,
        credential_data,
        user,
        db_session,
    )

    if credential is None:
        raise HTTPException(
            status_code=401,
            detail=f"Credential {credential_id} does not exist or does not belong to user",
        )

    return CredentialSnapshot.from_credential_db_model(credential)


@router.patch("/credential/{credential_id}")
def update_credential_from_model(
    credential_id: int,
    credential_data: CredentialBase,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> CredentialSnapshot | StatusResponse[int]:
    updated_credential = update_credential(
        credential_id, credential_data, user, db_session
    )
    if updated_credential is None:
        raise HTTPException(
            status_code=401,
            detail=f"Credential {credential_id} does not exist or does not belong to user",
        )

    return CredentialSnapshot(
        source=updated_credential.source,
        id=updated_credential.id,
        credential_json=updated_credential.credential_json,
        user_id=updated_credential.user_id,
        name=updated_credential.name,
        admin_public=updated_credential.admin_public,
        time_created=updated_credential.time_created,
        time_updated=updated_credential.time_updated,
        curator_public=updated_credential.curator_public,
    )


@router.delete("/credential/{credential_id}")
def delete_credential_by_id(
    credential_id: int,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> StatusResponse:
    delete_credential_for_user(
        credential_id,
        user,
        db_session,
    )

    return StatusResponse(
        success=True, message="Credential deleted successfully", data=credential_id
    )


@router.delete("/credential/force/{credential_id}")
def force_delete_credential_by_id(
    credential_id: int,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> StatusResponse:
    delete_credential_for_user(credential_id, user, db_session, True)

    return StatusResponse(
        success=True, message="Credential deleted successfully", data=credential_id
    )
