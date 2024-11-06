"""
launch:
- api server
- postgres
- vespa
- model server (this is only needed so the api server can startup, no embedding is done)

Run this script to seed the database with dummy documents.
Then run test_query_times.py to test query times.
"""
import random
from datetime import datetime

from danswer.access.models import DocumentAccess
from danswer.configs.constants import DocumentSource
from danswer.connectors.models import Document
from danswer.db.engine import get_session_context_manager
from danswer.db.search_settings import get_current_search_settings
from danswer.document_index.vespa.index import VespaIndex
from danswer.indexing.models import ChunkEmbedding
from danswer.indexing.models import DocMetadataAwareIndexChunk
from danswer.indexing.models import IndexChunk
from danswer.utils.timing import log_function_time
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from shared_configs.model_server_models import Embedding


TOTAL_DOC_SETS = 8
TOTAL_ACL_ENTRIES_PER_CATEGORY = 80


def generate_random_embedding(dim: int) -> Embedding:
    return [random.uniform(-1, 1) for _ in range(dim)]


def generate_random_identifier() -> str:
    return f"dummy_doc_{random.randint(1, 1000)}"


def generate_dummy_chunk(
    doc_id: str,
    chunk_id: int,
    embedding_dim: int,
    number_of_acl_entries: int,
    number_of_document_sets: int,
) -> DocMetadataAwareIndexChunk:
    document = Document(
        id=doc_id,
        source=DocumentSource.GOOGLE_DRIVE,
        sections=[],
        metadata={},
        semantic_identifier=generate_random_identifier(),
    )

    chunk = IndexChunk(
        chunk_id=chunk_id,
        blurb=f"Blurb for chunk {chunk_id} of document {doc_id}.",
        content=f"Content for chunk {chunk_id} of document {doc_id}. This is dummy text for testing purposes.",
        source_links={},
        section_continuation=False,
        source_document=document,
        title_prefix=f"Title prefix for doc {doc_id}",
        metadata_suffix_semantic="",
        metadata_suffix_keyword="",
        mini_chunk_texts=None,
        embeddings=ChunkEmbedding(
            full_embedding=generate_random_embedding(embedding_dim),
            mini_chunk_embeddings=[],
        ),
        title_embedding=generate_random_embedding(embedding_dim),
    )

    document_set_names = []
    for i in range(number_of_document_sets):
        document_set_names.append(f"Document Set {i}")

    user_emails: set[str | None] = set()
    user_groups: set[str] = set()
    external_user_emails: set[str] = set()
    external_user_group_ids: set[str] = set()
    for i in range(number_of_acl_entries):
        user_emails.add(f"user_{i}@example.com")
        user_groups.add(f"group_{i}")
        external_user_emails.add(f"external_user_{i}@example.com")
        external_user_group_ids.add(f"external_group_{i}")

    return DocMetadataAwareIndexChunk.from_index_chunk(
        index_chunk=chunk,
        access=DocumentAccess(
            user_emails=user_emails,
            user_groups=user_groups,
            external_user_emails=external_user_emails,
            external_user_group_ids=external_user_group_ids,
            is_public=random.choice([True, False]),
        ),
        document_sets={document_set for document_set in document_set_names},
        boost=random.randint(-1, 1),
        tenant_id=POSTGRES_DEFAULT_SCHEMA,
    )


@log_function_time()
def do_insertion(
    vespa_index: VespaIndex, all_chunks: list[DocMetadataAwareIndexChunk]
) -> None:
    insertion_records = vespa_index.index(all_chunks)
    print(f"Indexed {len(insertion_records)} documents.")
    print(
        f"New documents: {sum(1 for record in insertion_records if not record.already_existed)}"
    )
    print(
        f"Existing documents updated: {sum(1 for record in insertion_records if record.already_existed)}"
    )


@log_function_time()
def seed_dummy_docs(
    number_of_document_sets: int,
    number_of_acl_entries: int,
    num_docs: int = 1000,
    chunks_per_doc: int = 5,
    batch_size: int = 100,
) -> None:
    with get_session_context_manager() as db_session:
        search_settings = get_current_search_settings(db_session)
        index_name = search_settings.index_name
        embedding_dim = search_settings.model_dim

    vespa_index = VespaIndex(index_name=index_name, secondary_index_name=None)
    print(index_name)

    all_chunks = []
    chunk_count = 0
    for doc_num in range(num_docs):
        doc_id = f"dummy_doc_{doc_num}_{datetime.now().isoformat()}"
        for chunk_num in range(chunks_per_doc):
            chunk = generate_dummy_chunk(
                doc_id=doc_id,
                chunk_id=chunk_num,
                embedding_dim=embedding_dim,
                number_of_acl_entries=number_of_acl_entries,
                number_of_document_sets=number_of_document_sets,
            )
            all_chunks.append(chunk)
            chunk_count += 1

            if len(all_chunks) >= chunks_per_doc * batch_size:
                do_insertion(vespa_index, all_chunks)
                print(
                    f"Indexed {chunk_count} chunks out of {num_docs * chunks_per_doc}."
                )
                print(
                    f"percentage: {chunk_count / (num_docs * chunks_per_doc) * 100:.2f}% \n"
                )
                all_chunks = []

    if all_chunks:
        do_insertion(vespa_index, all_chunks)


if __name__ == "__main__":
    seed_dummy_docs(
        number_of_document_sets=TOTAL_DOC_SETS,
        number_of_acl_entries=TOTAL_ACL_ENTRIES_PER_CATEGORY,
        num_docs=100000,
        chunks_per_doc=5,
        batch_size=1000,
    )
