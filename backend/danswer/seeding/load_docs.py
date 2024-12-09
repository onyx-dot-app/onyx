import datetime
import json
import os
from typing import cast

from sqlalchemy.orm import Session

from danswer.access.models import default_public_access
from danswer.configs.constants import DEFAULT_BOOST
from danswer.configs.constants import DocumentSource
from danswer.configs.constants import KV_DOCUMENTS_SEEDED_KEY
from danswer.configs.model_configs import DEFAULT_DOCUMENT_ENCODER_MODEL
from danswer.connectors.models import Document
from danswer.connectors.models import IndexAttemptMetadata
from danswer.connectors.models import InputType
from danswer.connectors.models import Section
from danswer.db.connector import check_connectors_exist
from danswer.db.connector import create_connector
from danswer.db.connector_credential_pair import add_credential_to_connector
from danswer.db.credentials import PUBLIC_CREDENTIAL_ID
from danswer.db.document import check_docs_exist
from danswer.db.enums import AccessType
from danswer.db.enums import ConnectorCredentialPairStatus
from danswer.db.index_attempt import mock_successful_index_attempt
from danswer.db.search_settings import get_current_search_settings
from danswer.document_index.factory import get_default_document_index
from danswer.indexing.indexing_pipeline import index_doc_batch_prepare
from danswer.indexing.models import ChunkEmbedding
from danswer.indexing.models import DocMetadataAwareIndexChunk
from danswer.key_value_store.factory import get_kv_store
from danswer.key_value_store.interface import KvKeyNotFoundError
from danswer.server.documents.models import ConnectorBase
from danswer.utils.logger import setup_logger
from danswer.utils.retry_wrapper import retry_builder
from danswer.utils.variable_functionality import fetch_versioned_implementation

logger = setup_logger()


def _create_indexable_chunks(
    preprocessed_docs: list[dict],
    tenant_id: str | None,
) -> tuple[list[Document], list[DocMetadataAwareIndexChunk]]:
    ids_to_documents = {}
    chunks = []
    for preprocessed_doc in preprocessed_docs:
        document = Document(
            id=preprocessed_doc["url"],  # For Web connector, the URL is the ID
            # The section is not really used past this point since we have already done the other processing
            # for the chunking and embedding.
            sections=[
                Section(text=preprocessed_doc["content"], link=preprocessed_doc["url"])
            ],
            source=DocumentSource.WEB,
            semantic_identifier=preprocessed_doc["title"],
            metadata={},
            doc_updated_at=None,
            primary_owners=[],
            secondary_owners=[],
        )
        if preprocessed_doc["chunk_ind"] == 0:
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
            title_prefix=preprocessed_doc["title"],
            metadata_suffix_semantic="",
            metadata_suffix_keyword="",
            mini_chunk_texts=None,
            large_chunk_reference_ids=[],
            embeddings=ChunkEmbedding(
                full_embedding=preprocessed_doc["content_embedding"],
                mini_chunk_embeddings=[],
            ),
            title_embedding=preprocessed_doc["title_embedding"],
            tenant_id=tenant_id,
            access=default_public_access,
            document_sets=set(),
            boost=DEFAULT_BOOST,
        )
        chunks.append(chunk)

    return list(ids_to_documents.values()), chunks


# Cohere is used in EE version
def load_processed_docs(cohere_enabled: bool) -> list[dict]:
    initial_docs_path = os.path.join(
        os.getcwd(),
        "danswer",
        "seeding",
        "initial_docs.json",
    )
    processed_docs = json.load(open(initial_docs_path))
    return processed_docs


def seed_initial_documents(
    db_session: Session, tenant_id: str | None, cohere_enabled: bool = False
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

    document_index = get_default_document_index(
        primary_index_name=search_settings.index_name, secondary_index_name=None
    )

    # Create a connector so the user can delete it if they want
    # or reindex it with a new search model if they want
    connector_data = ConnectorBase(
        name="Sample Use Cases",
        source=DocumentSource.WEB,
        input_type=InputType.LOAD_STATE,
        connector_specific_config={
            "base_url": "https://docs.danswer.dev/more/use_cases",
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
    )
    cc_pair_id = cast(int, result.data)
    processed_docs = fetch_versioned_implementation(
        "danswer.seeding.load_docs",
        "load_processed_docs",
    )(cohere_enabled)

    docs, chunks = _create_indexable_chunks(processed_docs, tenant_id)

    index_doc_batch_prepare(
        document_batch=docs,
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

    index_with_retries = retry_builder()(document_index.index)
    index_with_retries(chunks=chunks)

    # Mock a run for the UI even though it did not actually call out to anything
    mock_successful_index_attempt(
        connector_credential_pair_id=cc_pair_id,
        search_settings_id=search_settings.id,
        docs_indexed=len(docs),
        db_session=db_session,
    )

    kv_store.store(KV_DOCUMENTS_SEEDED_KEY, True)
