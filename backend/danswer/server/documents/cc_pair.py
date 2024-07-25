from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from danswer.auth.users import current_admin_user
from danswer.auth.users import current_user
from danswer.background.celery.celery_utils import get_deletion_status
from danswer.db.connector_credential_pair import add_credential_to_connector
from danswer.db.connector_credential_pair import get_connector_credential_pair_from_id
from danswer.db.connector_credential_pair import remove_credential_from_connector
from danswer.db.document import get_document_cnts_for_cc_pairs
from danswer.db.engine import get_session
from danswer.db.index_attempt import get_index_attempts_for_cc_pair
from danswer.db.models import User
from danswer.server.documents.models import CCPairFullInfo
from danswer.server.documents.models import ConnectorCredentialPairIdentifier
from danswer.server.documents.models import ConnectorCredentialPairMetadata
from danswer.server.models import StatusResponse

router = APIRouter(prefix="/manage")


@router.get("/admin/cc-pair/{cc_pair_id}")
def get_cc_pair_full_info(
    cc_pair_id: int,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> CCPairFullInfo:
    cc_pair = get_connector_credential_pair_from_id(
        cc_pair_id=cc_pair_id,
        db_session=db_session,
    )
    if cc_pair is None:
        raise HTTPException(
            status_code=400,
            detail=f"Connector with ID {cc_pair_id} not found. Has it been deleted?",
        )

    cc_pair_identifier = ConnectorCredentialPairIdentifier(
        connector_id=cc_pair.connector_id,
        credential_id=cc_pair.credential_id,
    )

    index_attempts = get_index_attempts_for_cc_pair(
        db_session=db_session,
        cc_pair_identifier=cc_pair_identifier,
    )

    document_count_info_list = list(
        get_document_cnts_for_cc_pairs(
            db_session=db_session,
            cc_pair_identifiers=[cc_pair_identifier],
        )
    )
    documents_indexed = (
        document_count_info_list[0][-1] if document_count_info_list else 0
    )

    latest_deletion_attempt = get_deletion_status(
        connector_id=cc_pair.connector.id,
        credential_id=cc_pair.credential.id,
        db_session=db_session,
    )

    return CCPairFullInfo.from_models(
        cc_pair_model=cc_pair,
        index_attempt_models=list(index_attempts),
        latest_deletion_attempt=latest_deletion_attempt,
        num_docs_indexed=documents_indexed,
    )


@router.put("/connector/{connector_id}/credential/{credential_id}")
def associate_credential_to_connector(
    connector_id: int,
    credential_id: int,
    metadata: ConnectorCredentialPairMetadata,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> StatusResponse[int]:
    try:
        return add_credential_to_connector(
            connector_id=connector_id,
            credential_id=credential_id,
            cc_pair_name=metadata.name,
            is_public=metadata.is_public,
            user=user,
            db_session=db_session,
        )
    except IntegrityError:
        raise HTTPException(status_code=400, detail="Name must be unique")


@router.delete("/connector/{connector_id}/credential/{credential_id}")
def dissociate_credential_from_connector(
    connector_id: int,
    credential_id: int,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> StatusResponse[int]:
    return remove_credential_from_connector(
        connector_id, credential_id, user, db_session
    )
