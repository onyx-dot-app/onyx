from collections.abc import Callable
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import cast

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy.orm import Session

from danswer.auth.users import current_admin_user
from danswer.configs.app_configs import GENERATIVE_MODEL_ACCESS_CHECK_FREQ
from danswer.configs.constants import DocumentSource
from danswer.configs.constants import GEN_AI_API_KEY_STORAGE_KEY
from danswer.configs.constants import GEN_AI_DETECTED_MODEL
from danswer.configs.model_configs import GEN_AI_MODEL_PROVIDER
from danswer.configs.model_configs import GEN_AI_MODEL_VERSION
from danswer.db.connector_credential_pair import get_connector_credential_pair
from danswer.db.deletion_attempt import check_deletion_attempt_is_allowed
from danswer.db.engine import get_session
from danswer.db.feedback import fetch_docs_ranked_by_boost
from danswer.db.feedback import update_document_boost
from danswer.db.feedback import update_document_hidden
from danswer.db.file_store import get_default_file_store
from danswer.db.models import User
from danswer.document_index.document_index_utils import get_both_index_names
from danswer.document_index.factory import get_default_document_index
from danswer.dynamic_configs.factory import get_dynamic_config_store
from danswer.dynamic_configs.interface import ConfigNotFoundError
from danswer.llm.exceptions import GenAIDisabledException
from danswer.llm.factory import get_default_llm
from danswer.llm.factory import get_default_llm_version
from danswer.llm.utils import get_gen_ai_api_key
from danswer.llm.utils import test_llm
from danswer.server.documents.models import ConnectorCredentialPairIdentifier
from danswer.server.manage.models import BoostDoc
from danswer.server.manage.models import BoostUpdateRequest
from danswer.server.manage.models import HiddenUpdateRequest
from danswer.server.models import ApiKey
from danswer.utils.logger import setup_logger
from danswer.utils.threadpool_concurrency import run_functions_tuples_in_parallel

router = APIRouter(prefix="/manage")
logger = setup_logger()

GEN_AI_KEY_CHECK_TIME = "genai_api_key_last_check_time"

"""Admin only API endpoints"""


@router.get("/admin/doc-boosts")
def get_most_boosted_docs(
    ascending: bool,
    limit: int,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> list[BoostDoc]:
    boost_docs = fetch_docs_ranked_by_boost(
        ascending=ascending, limit=limit, db_session=db_session
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
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    curr_ind_name, sec_ind_name = get_both_index_names(db_session)
    document_index = get_default_document_index(
        primary_index_name=curr_ind_name, secondary_index_name=sec_ind_name
    )

    try:
        update_document_boost(
            db_session=db_session,
            document_id=boost_update.document_id,
            boost=boost_update.boost,
            document_index=document_index,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/admin/doc-hidden")
def document_hidden_update(
    hidden_update: HiddenUpdateRequest,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    curr_ind_name, sec_ind_name = get_both_index_names(db_session)
    document_index = get_default_document_index(
        primary_index_name=curr_ind_name, secondary_index_name=sec_ind_name
    )

    try:
        update_document_hidden(
            db_session=db_session,
            document_id=hidden_update.document_id,
            hidden=hidden_update.hidden,
            document_index=document_index,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


def _validate_llm_key(genai_api_key: str | None) -> None:
    # Checking new API key, may change things for this if kv-store is updated
    get_default_llm_version.cache_clear()
    kv_store = get_dynamic_config_store()
    try:
        kv_store.delete(GEN_AI_DETECTED_MODEL)
    except ConfigNotFoundError:
        pass

    gpt_4_version = "gpt-4"  # 32k is not available to most people
    gpt4_llm = None
    try:
        llm = get_default_llm(api_key=genai_api_key, timeout=10)
        if GEN_AI_MODEL_PROVIDER == "openai" and not GEN_AI_MODEL_VERSION:
            gpt4_llm = get_default_llm(
                gen_ai_model_version_override=gpt_4_version,
                api_key=genai_api_key,
                timeout=10,
            )
    except GenAIDisabledException:
        return

    functions_with_args: list[tuple[Callable, tuple]] = [(test_llm, (llm,))]
    if gpt4_llm:
        functions_with_args.append((test_llm, (gpt4_llm,)))

    parallel_results = run_functions_tuples_in_parallel(
        functions_with_args, allow_failures=False
    )

    error_msg = parallel_results[0]

    if error_msg:
        if genai_api_key is None:
            raise HTTPException(status_code=404, detail="Key not found")
        raise HTTPException(status_code=400, detail=error_msg)

    # Mark check as successful
    curr_time = datetime.now(tz=timezone.utc)
    kv_store.store(GEN_AI_KEY_CHECK_TIME, curr_time.timestamp())

    # None for no errors
    if gpt4_llm and parallel_results[1] is None:
        kv_store.store(GEN_AI_DETECTED_MODEL, gpt_4_version)


@router.get("/admin/genai-api-key/validate")
def validate_existing_genai_api_key(
    _: User = Depends(current_admin_user),
) -> None:
    # Only validate every so often
    kv_store = get_dynamic_config_store()
    curr_time = datetime.now(tz=timezone.utc)
    try:
        last_check = datetime.fromtimestamp(
            cast(float, kv_store.load(GEN_AI_KEY_CHECK_TIME)), tz=timezone.utc
        )
        check_freq_sec = timedelta(seconds=GENERATIVE_MODEL_ACCESS_CHECK_FREQ)
        if curr_time - last_check < check_freq_sec:
            return
    except ConfigNotFoundError:
        # First time checking the key, nothing unusual
        pass

    genai_api_key = get_gen_ai_api_key()
    _validate_llm_key(genai_api_key)


@router.get("/admin/genai-api-key", response_model=ApiKey)
def get_gen_ai_api_key_from_dynamic_config_store(
    _: User = Depends(current_admin_user),
) -> ApiKey:
    """
    NOTE: Only gets value from dynamic config store as to not expose env variables.
    """
    try:
        # only get last 4 characters of key to not expose full key
        return ApiKey(
            api_key=cast(
                str, get_dynamic_config_store().load(GEN_AI_API_KEY_STORAGE_KEY)
            )[-4:]
        )
    except ConfigNotFoundError:
        raise HTTPException(status_code=404, detail="Key not found")


@router.put("/admin/genai-api-key")
def store_genai_api_key(
    request: ApiKey,
    _: User = Depends(current_admin_user),
) -> None:
    if not request.api_key:
        raise HTTPException(400, "No API key provided")

    _validate_llm_key(request.api_key)

    get_dynamic_config_store().store(GEN_AI_API_KEY_STORAGE_KEY, request.api_key)


@router.delete("/admin/genai-api-key")
def delete_genai_api_key(
    _: User = Depends(current_admin_user),
) -> None:
    get_dynamic_config_store().delete(GEN_AI_API_KEY_STORAGE_KEY)


@router.post("/admin/deletion-attempt")
def create_deletion_attempt_for_connector_id(
    connector_credential_pair_identifier: ConnectorCredentialPairIdentifier,
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    from danswer.background.celery.celery import cleanup_connector_credential_pair_task

    connector_id = connector_credential_pair_identifier.connector_id
    credential_id = connector_credential_pair_identifier.credential_id

    cc_pair = get_connector_credential_pair(
        db_session=db_session,
        connector_id=connector_id,
        credential_id=credential_id,
    )
    if cc_pair is None:
        raise HTTPException(
            status_code=404,
            detail=f"Connector with ID '{connector_id}' and credential ID "
            f"'{credential_id}' does not exist. Has it already been deleted?",
        )

    if not check_deletion_attempt_is_allowed(connector_credential_pair=cc_pair):
        raise HTTPException(
            status_code=400,
            detail=f"Connector with ID '{connector_id}' and credential ID "
            f"'{credential_id}' is not deletable. It must be both disabled AND have "
            "no ongoing / planned indexing attempts.",
        )

    cleanup_connector_credential_pair_task.apply_async(
        kwargs=dict(connector_id=connector_id, credential_id=credential_id),
    )

    if cc_pair.connector.source == DocumentSource.FILE:
        connector = cc_pair.connector
        file_store = get_default_file_store(db_session)
        for file_name in connector.connector_specific_config["file_locations"]:
            file_store.delete_file(file_name)
