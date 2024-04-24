import secrets

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Header
from fastapi import HTTPException
from sqlalchemy.orm import Session

from danswer.configs.constants import DocumentSource
from danswer.connectors.models import Document
from danswer.connectors.models import IndexAttemptMetadata
from danswer.db.connector import fetch_connector_by_id
from danswer.db.connector import fetch_ingestion_connector_by_name
from danswer.db.connector_credential_pair import get_connector_credential_pair
from danswer.db.credentials import fetch_credential_by_id
from danswer.db.embedding_model import get_current_db_embedding_model
from danswer.db.embedding_model import get_secondary_db_embedding_model
from danswer.db.engine import get_session
from danswer.document_index.document_index_utils import get_both_index_names
from danswer.document_index.factory import get_default_document_index
from danswer.dynamic_configs.factory import get_dynamic_config_store
from danswer.dynamic_configs.interface import ConfigNotFoundError
from danswer.indexing.embedder import DefaultIndexingEmbedder
from danswer.indexing.indexing_pipeline import build_indexing_pipeline
from danswer.server.danswer_api.models import IngestionDocument
from danswer.server.danswer_api.models import IngestionResult
from danswer.utils.logger import setup_logger

logger = setup_logger()

# not using /api to avoid confusion with nginx api path routing
router = APIRouter(prefix="/danswer-api")

# Assumes this gives admin privileges, basic users should not be allowed to call any Danswer apis
_DANSWER_API_KEY = "danswer_api_key"


def get_danswer_api_key(key_len: int = 30, dont_regenerate: bool = False) -> str | None:
    kv_store = get_dynamic_config_store()
    try:
        return str(kv_store.load(_DANSWER_API_KEY))
    except ConfigNotFoundError:
        if dont_regenerate:
            return None

    logger.info("Generating Danswer API Key")

    api_key = "dn_" + secrets.token_urlsafe(key_len)
    kv_store.store(_DANSWER_API_KEY, api_key)

    return api_key


def delete_danswer_api_key() -> None:
    kv_store = get_dynamic_config_store()
    try:
        kv_store.delete(_DANSWER_API_KEY)
    except ConfigNotFoundError:
        pass


def api_key_dep(authorization: str = Header(...)) -> str:
    saved_key = get_danswer_api_key(dont_regenerate=True)
    token = authorization.removeprefix("Bearer ").strip()
    if token != saved_key or not saved_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return token


@router.post("/doc-ingestion")
def document_ingestion(
    doc_info: IngestionDocument,
    _: str = Depends(api_key_dep),
    db_session: Session = Depends(get_session),
) -> IngestionResult:
    """Currently only attaches docs to existing connectors (cc-pairs).
    Or to the default ingestion connector that is accessible to all users

    Things to note:
    - The document id if not provided is automatically generated from the semantic identifier
      so if the document source type etc is updated, it won't create a duplicate
    """
    if doc_info.credential_id:
        credential_id = doc_info.credential_id
        credential = fetch_credential_by_id(
            credential_id=credential_id,
            user=None,
            db_session=db_session,
            assume_admin=True,
        )
        if credential is None:
            raise ValueError("Invalid Credential for doc, does not exist.")
    else:
        credential_id = 0

    connector_id = doc_info.connector_id
    # If user provides id and name, id takes precedence
    if connector_id is not None:
        connector = fetch_connector_by_id(connector_id, db_session)
        if connector is None:
            raise ValueError("Invalid Connector for doc, id does not exist.")
    elif doc_info.connector_name:
        connector = fetch_ingestion_connector_by_name(
            doc_info.connector_name, db_session
        )
        if connector is None:
            raise ValueError("Invalid Connector for doc, name does not exist.")
        connector_id = connector.id
    else:
        connector_id = 0

    cc_pair = get_connector_credential_pair(
        connector_id=connector_id, credential_id=credential_id, db_session=db_session
    )
    if cc_pair is None:
        raise ValueError("Connector and Credential not associated.")

    # Disregard whatever value is passed, this must be True
    doc_info.document.from_ingestion_api = True

    document = Document.from_base(doc_info.document)

    # TODO once the frontend is updated with this enum, remove this logic
    if document.source == DocumentSource.INGESTION_API:
        document.source = DocumentSource.FILE

    # Need to index for both the primary and secondary index if possible
    curr_ind_name, sec_ind_name = get_both_index_names(db_session)
    curr_doc_index = get_default_document_index(
        primary_index_name=curr_ind_name, secondary_index_name=None
    )

    db_embedding_model = get_current_db_embedding_model(db_session)

    index_embedding_model = DefaultIndexingEmbedder(
        model_name=db_embedding_model.model_name,
        normalize=db_embedding_model.normalize,
        query_prefix=db_embedding_model.query_prefix,
        passage_prefix=db_embedding_model.passage_prefix,
    )

    indexing_pipeline = build_indexing_pipeline(
        embedder=index_embedding_model,
        document_index=curr_doc_index,
        ignore_time_skip=True,
        db_session=db_session,
    )

    new_doc, chunks = indexing_pipeline(
        documents=[document],
        index_attempt_metadata=IndexAttemptMetadata(
            connector_id=connector_id,
            credential_id=credential_id,
        ),
    )

    # If there's a secondary index being built, index the doc but don't use it for return here
    if sec_ind_name:
        sec_doc_index = get_default_document_index(
            primary_index_name=curr_ind_name, secondary_index_name=None
        )

        sec_db_embedding_model = get_secondary_db_embedding_model(db_session)

        if sec_db_embedding_model is None:
            # Should not ever happen
            raise RuntimeError(
                "Secondary index exists but no embedding model configured"
            )

        new_index_embedding_model = DefaultIndexingEmbedder(
            model_name=sec_db_embedding_model.model_name,
            normalize=sec_db_embedding_model.normalize,
            query_prefix=sec_db_embedding_model.query_prefix,
            passage_prefix=sec_db_embedding_model.passage_prefix,
        )

        sec_ind_pipeline = build_indexing_pipeline(
            embedder=new_index_embedding_model,
            document_index=sec_doc_index,
            ignore_time_skip=True,
            db_session=db_session,
        )

        sec_ind_pipeline(
            documents=[document],
            index_attempt_metadata=IndexAttemptMetadata(
                connector_id=connector_id,
                credential_id=credential_id,
            ),
        )

    return IngestionResult(document_id=document.id, already_existed=not bool(new_doc))
