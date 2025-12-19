from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import cast

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy.orm import Session

from onyx.auth.users import current_admin_user
from onyx.auth.users import current_curator_or_admin_user
from onyx.background.celery.versioned_apps.client import app as client_app
from onyx.configs.app_configs import GENERATIVE_MODEL_ACCESS_CHECK_FREQ
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import KV_GEN_AI_KEY_CHECK_TIME
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryTask
from onyx.db.connector_credential_pair import get_connector_credential_pair_for_user
from onyx.db.connector_credential_pair import (
    update_connector_credential_pair_from_id,
)
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.feedback import fetch_docs_ranked_by_boost_for_user
from onyx.db.feedback import update_document_boost_for_user
from onyx.db.feedback import update_document_hidden_for_user
from onyx.db.index_attempt import cancel_indexing_attempts_for_ccpair
from onyx.db.models import User
from onyx.file_store.file_store import get_default_file_store
from onyx.key_value_store.factory import get_kv_store
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.llm.factory import get_default_llms
from onyx.llm.utils import test_llm
from onyx.server.documents.models import ConnectorCredentialPairIdentifier
from onyx.server.manage.models import BoostDoc
from onyx.server.manage.models import BoostUpdateRequest
from onyx.server.manage.models import HiddenUpdateRequest
from onyx.server.models import StatusResponse
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

router = APIRouter(prefix="/manage")
logger = setup_logger()

"""Admin only API endpoints"""


@router.get("/admin/doc-boosts")
def get_most_boosted_docs(
    ascending: bool,
    limit: int,
    user: User | None = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> list[BoostDoc]:
    boost_docs = fetch_docs_ranked_by_boost_for_user(
        ascending=ascending,
        limit=limit,
        db_session=db_session,
        user=user,
    )
    return [
        BoostDoc(
            document_id=doc.id,
            semantic_id=doc.semantic_id,
            # source=doc.source,
            link=doc.link or "",
            boost=doc.boost,
            hidden=doc.hidden,
        )
        for doc in boost_docs
    ]


@router.post("/admin/doc-boosts")
def document_boost_update(
    boost_update: BoostUpdateRequest,
    user: User | None = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> StatusResponse:
    update_document_boost_for_user(
        db_session=db_session,
        document_id=boost_update.document_id,
        boost=boost_update.boost,
        user=user,
    )
    return StatusResponse(success=True, message="Updated document boost")


@router.post("/admin/doc-hidden")
def document_hidden_update(
    hidden_update: HiddenUpdateRequest,
    user: User | None = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> StatusResponse:
    update_document_hidden_for_user(
        db_session=db_session,
        document_id=hidden_update.document_id,
        hidden=hidden_update.hidden,
        user=user,
    )
    return StatusResponse(success=True, message="Updated document boost")


@router.get("/admin/genai-api-key/validate")
def validate_existing_genai_api_key(
    _: User = Depends(current_admin_user),
) -> None:
    # Only validate every so often
    kv_store = get_kv_store()
    curr_time = datetime.now(tz=timezone.utc)
    try:
        last_check = datetime.fromtimestamp(
            cast(float, kv_store.load(KV_GEN_AI_KEY_CHECK_TIME)), tz=timezone.utc
        )
        check_freq_sec = timedelta(seconds=GENERATIVE_MODEL_ACCESS_CHECK_FREQ)
        if curr_time - last_check < check_freq_sec:
            return
    except KvKeyNotFoundError:
        # First time checking the key, nothing unusual
        pass

    try:
        llm, __ = get_default_llms(timeout=10)
    except ValueError:
        raise HTTPException(status_code=404, detail="LLM not setup")

    error = test_llm(llm)
    if error:
        raise HTTPException(status_code=400, detail=error)

    # Mark check as successful
    curr_time = datetime.now(tz=timezone.utc)
    kv_store.store(KV_GEN_AI_KEY_CHECK_TIME, curr_time.timestamp())


@router.post("/admin/deletion-attempt")
def create_deletion_attempt_for_connector_id(
    connector_credential_pair_identifier: ConnectorCredentialPairIdentifier,
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    tenant_id = get_current_tenant_id()

    connector_id = connector_credential_pair_identifier.connector_id
    credential_id = connector_credential_pair_identifier.credential_id

    cc_pair = get_connector_credential_pair_for_user(
        db_session=db_session,
        connector_id=connector_id,
        credential_id=credential_id,
        user=user,
        get_editable=True,
    )
    if cc_pair is None:
        error = (
            f"Connector with ID '{connector_id}' and credential ID "
            f"'{credential_id}' does not exist. Has it already been deleted?"
        )
        logger.error(error)
        raise HTTPException(
            status_code=404,
            detail=error,
        )

    # Cancel any scheduled indexing attempts
    cancel_indexing_attempts_for_ccpair(
        cc_pair_id=cc_pair.id, db_session=db_session, include_secondary_index=True
    )

    # TODO(rkuo): 2024-10-24 - check_deletion_attempt_is_allowed shouldn't be necessary
    # any more due to background locking improvements.
    # Remove the below permanently if everything is behaving for 30 days.

    # Check if the deletion attempt should be allowed
    # deletion_attempt_disallowed_reason = check_deletion_attempt_is_allowed(
    #     connector_credential_pair=cc_pair, db_session=db_session
    # )
    # if deletion_attempt_disallowed_reason:
    #     raise HTTPException(
    #         status_code=400,
    #         detail=deletion_attempt_disallowed_reason,
    #     )

    # mark as deleting
    update_connector_credential_pair_from_id(
        db_session=db_session,
        cc_pair_id=cc_pair.id,
        status=ConnectorCredentialPairStatus.DELETING,
    )

    db_session.commit()

    # run the beat task to pick up this deletion from the db immediately
    client_app.send_task(
        OnyxCeleryTask.CHECK_FOR_CONNECTOR_DELETION,
        priority=OnyxCeleryPriority.HIGH,
        kwargs={"tenant_id": tenant_id},
    )

    logger.info(
        f"create_deletion_attempt_for_connector_id - running check_for_connector_deletion: "
        f"cc_pair={cc_pair.id}"
    )

    if cc_pair.connector.source == DocumentSource.FILE:
        connector = cc_pair.connector
        file_store = get_default_file_store()
        for file_id in connector.connector_specific_config.get("file_locations", []):
            file_store.delete_file(file_id)
