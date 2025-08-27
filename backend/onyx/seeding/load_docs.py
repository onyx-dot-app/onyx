import datetime
import json
import os
from typing import cast

from sqlalchemy import update
from sqlalchemy.orm import Session

from onyx.access.models import default_public_access
from onyx.configs.constants import DEFAULT_BOOST
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import KV_DOCUMENTS_SEEDED_KEY
from onyx.configs.constants import RETURN_SEPARATOR
from onyx.configs.model_configs import DEFAULT_DOCUMENT_ENCODER_MODEL
from onyx.connectors.models import Document
from onyx.connectors.models import IndexAttemptMetadata
from onyx.connectors.models import InputType
from onyx.connectors.models import TextSection
from onyx.db.connector import check_connectors_exist
from onyx.db.connector import create_connector
from onyx.db.connector_credential_pair import add_credential_to_connector
from onyx.db.credentials import PUBLIC_CREDENTIAL_ID
from onyx.db.document import check_docs_exist
from onyx.db.document import mark_document_as_indexed_for_cc_pair__no_commit
from onyx.db.enums import AccessType
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.index_attempt import mock_successful_index_attempt
from onyx.db.models import Document as DbDocument
from onyx.db.search_settings import get_current_search_settings
from onyx.document_index.factory import get_default_document_index
from onyx.document_index.interfaces import IndexBatchParams
from onyx.document_index.vespa.shared_utils.utils import wait_for_vespa_with_timeout
from onyx.indexing.indexing_pipeline import index_doc_batch_prepare
from onyx.indexing.models import ChunkEmbedding
from onyx.indexing.models import DocMetadataAwareIndexChunk
from onyx.key_value_store.factory import get_kv_store
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.server.documents.models import ConnectorBase
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import fetch_versioned_implementation
from shared_configs.configs import MULTI_TENANT
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA

logger = setup_logger()


def _create_indexable_chunks(
    preprocessed_docs: list[dict],
    tenant_id: str,
) -> tuple[list[Document], list[DocMetadataAwareIndexChunk]]:
    ids_to_documents = {}
    chunks = []
    for preprocessed_doc in preprocessed_docs:
        document = Document(
            id=preprocessed_doc["url"],  # For Web connector, the URL is the ID
            # The section is not really used past this point since we have already done the other processing
            # for the chunking and embedding.
            sections=[
                TextSection(
                    text=preprocessed_doc["content"],
                    link=preprocessed_doc["url"],
                    image_file_id=None,
                )
            ],
            source=DocumentSource.WEB,
            semantic_identifier=preprocessed_doc["title"],
            metadata={},
            doc_updated_at=None,
            primary_owners=[],
            secondary_owners=[],
            chunk_count=preprocessed_doc["chunk_ind"] + 1,
        )

        ids_to_documents[document.id] = document

        chunk = DocMetadataAwareIndexChunk(
            chunk_id=preprocessed_doc["chunk_ind"],
            blurb=preprocessed_doc["content"]
            .split(".", 1)[0]
            .split("!", 1)[0]
            .split("?", 1)[0],
            content=preprocessed_doc["content"],
            source_links={0: preprocessed_doc["url"]},
            section_continuation=False,
            source_document=document,
            title_prefix=preprocessed_doc["title"] + RETURN_SEPARATOR,
            metadata_suffix_semantic="",
            metadata_suffix_keyword="",
            mini_chunk_texts=None,
            large_chunk_reference_ids=[],
            doc_summary="",
            chunk_context="",
            contextual_rag_reserved_tokens=0,
            embeddings=ChunkEmbedding(
                full_embedding=preprocessed_doc["content_embedding"],
                mini_chunk_embeddings=[],
            ),
            title_embedding=preprocessed_doc["title_embedding"],
            tenant_id=tenant_id if MULTI_TENANT else POSTGRES_DEFAULT_SCHEMA,
            access=default_public_access,
            document_sets=set(),
            user_file=None,
            user_folder=None,
            boost=DEFAULT_BOOST,
            large_chunk_id=None,
            image_file_id=None,
            aggregated_chunk_boost_factor=1.0,
        )

        chunks.append(chunk)

    return list(ids_to_documents.values()), chunks


# Cohere is used in EE version
def load_processed_docs(cohere_enabled: bool) -> list[dict]:
    initial_docs_path = os.path.join(
        os.getcwd(),
        "onyx",
        "seeding",
        "initial_docs.json",
    )
    processed_docs = json.load(open(initial_docs_path))
    return processed_docs


def seed_initial_documents(
    db_session: Session, tenant_id: str, cohere_enabled: bool = False
) -> None:
    """
    Seed initial documents so users don't have an empty index to start

    Documents are only loaded if:
    - This is the first setup (if the user deletes the docs, we don't load them again)
    - The index is empty, there are no docs and no (non-default) connectors
    - The user has not updated the embedding models
        - If they do, then we have to actually index the website
        - If the embedding model is already updated on server startup, they're not a new user

    Note that regardless of any search settings, the default documents are always loaded with
    the predetermined chunk sizes and single pass embedding.

    Steps are as follows:
    - Check if this needs to run
    - Create the connector representing this
    - Create the cc-pair (attaching the public credential) and mocking values like the last success
    - Indexing the documents into Postgres
    - Indexing the documents into Vespa
    - Create a fake index attempt with fake times
    """
    logger.info("Seeding initial documents")

    kv_store = get_kv_store()
    try:
        kv_store.load(KV_DOCUMENTS_SEEDED_KEY)
        logger.info("Documents already seeded, skipping")
        return
    except KvKeyNotFoundError:
        pass

    if check_docs_exist(db_session):
        logger.info("Documents already exist, skipping")
        return

    if check_connectors_exist(db_session):
        logger.info("Connectors already exist, skipping")
        return

    search_settings = get_current_search_settings(db_session)
    if search_settings.model_name != DEFAULT_DOCUMENT_ENCODER_MODEL and not (
        search_settings.model_name == "embed-english-v3.0" and cohere_enabled
    ):
        logger.info("Embedding model has been updated, skipping")
        return

    document_index = get_default_document_index(search_settings, None)

    # Create a connector so the user can delete it if they want
    # or reindex it with a new search model if they want
    connector_data = ConnectorBase(
        name="Sample Use Cases",
        source=DocumentSource.WEB,
        input_type=InputType.LOAD_STATE,
        connector_specific_config={
            "base_url": "https://docs.onyx.app/more/use_cases",
            "web_connector_type": "recursive",
        },
        refresh_freq=None,  # Never refresh by default
        prune_freq=None,
        indexing_start=None,
    )

    connector = create_connector(db_session, connector_data)
    connector_id = cast(int, connector.id)

    last_index_time = datetime.datetime.now(datetime.timezone.utc)

    result = add_credential_to_connector(
        db_session=db_session,
        user=None,
        connector_id=connector_id,
        credential_id=PUBLIC_CREDENTIAL_ID,
        access_type=AccessType.PUBLIC,
        cc_pair_name=connector_data.name,
        groups=None,
        initial_status=ConnectorCredentialPairStatus.PAUSED,
        last_successful_index_time=last_index_time,
        seeding_flow=True,
    )

    cc_pair_id = cast(int, result.data)
    processed_docs = fetch_versioned_implementation(
        "onyx.seeding.load_docs",
        "load_processed_docs",
    )(cohere_enabled)

    docs, chunks = _create_indexable_chunks(processed_docs, tenant_id)

    index_doc_batch_prepare(
        documents=docs,
        index_attempt_metadata=IndexAttemptMetadata(
            connector_id=connector_id,
            credential_id=PUBLIC_CREDENTIAL_ID,
        ),
        db_session=db_session,
        ignore_time_skip=True,  # Doesn't actually matter here
    )

    # In this case since there are no other connectors running in the background
    # and this is a fresh deployment, there is no need to grab any locks
    logger.info(
        "Indexing seeding documents into Vespa "
        "(Vespa may take a few seconds to become ready after receiving the schema)"
    )

    # Retries here because the index may take a few seconds to become ready
    # as we just sent over the Vespa schema and there is a slight delay
    if not wait_for_vespa_with_timeout():
        logger.error("Vespa did not become ready within the timeout")
        raise ValueError("Vespa failed to become ready within the timeout")

    document_index.index(
        chunks=chunks,
        index_batch_params=IndexBatchParams(
            doc_id_to_previous_chunk_cnt={},
            doc_id_to_new_chunk_cnt={},
            large_chunks_enabled=False,
            tenant_id=tenant_id,
        ),
    )

    # Mock a run for the UI even though it did not actually call out to anything
    mock_successful_index_attempt(
        connector_credential_pair_id=cc_pair_id,
        search_settings_id=search_settings.id,
        docs_indexed=len(docs),
        db_session=db_session,
    )

    # Since we bypass the indexing flow, we need to manually update the chunk count
    for doc in docs:
        db_session.execute(
            update(DbDocument)
            .where(DbDocument.id == doc.id)
            .values(chunk_count=doc.chunk_count)
        )

    # Since we bypass the indexing flow, we need to manually mark the document as indexed
    mark_document_as_indexed_for_cc_pair__no_commit(
        connector_id=connector_id,
        credential_id=PUBLIC_CREDENTIAL_ID,
        document_ids=[doc.id for doc in docs],
        db_session=db_session,
    )

    db_session.commit()
    kv_store.store(KV_DOCUMENTS_SEEDED_KEY, True)
