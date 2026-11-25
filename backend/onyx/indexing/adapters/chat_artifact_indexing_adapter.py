from __future__ import annotations

import contextlib
from collections.abc import Generator

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from onyx.access.models import DocumentAccess
from onyx.configs.constants import DEFAULT_BOOST
from onyx.connectors.models import ConnectorStopSignal, Document
from onyx.db.chat import (
    lock_chat_artifact_for_indexing_nowait,
    mark_chat_artifact_indexed__no_commit,
)
from onyx.indexing.indexing_pipeline import DocumentBatchPrepareContext
from onyx.indexing.models import (
    ChatArtifactIndexInput,
    ChunkEnrichmentContext,
    DocAwareChunk,
    DocMetadataAwareIndexChunk,
    IndexChunk,
    IndexingBatchAdapter,
    UpdatableChunkData,
)


class ChatArtifactIndexSkip(ConnectorStopSignal):
    """The artifact is gone, its chat is deleted, a publish or a newer pickup
    changed it since this pickup, or another transaction holds its row (a
    publish or a delete): skip the write. The delete owns removal from the
    index, a publish makes the artifact PENDING again, and a newer pickup
    writes its own document."""


class ChatArtifactIndexingAdapter(IndexingBatchAdapter):
    """Writes one published file (`indexed`, the newest available version of
    its artifact) as the document `str(artifact_id)`, visible only to its
    owner: the ACL is the owner's current email, with no document sets,
    projects or personas, so knowledge-scoped searches never match it."""

    index_attempt_metadata = None
    connector_id: int | None = None
    credential_id: int | None = None

    def __init__(
        self, tenant_id: str, db_session: Session, indexed: ChatArtifactIndexInput
    ) -> None:
        self.tenant_id = tenant_id
        self.db_session = db_session
        self.indexed = indexed

    def prepare(
        self,
        documents: list[Document],
        ignore_time_skip: bool,  # noqa: ARG002
        index_to_secondary: bool,  # noqa: ARG002
        force_update: bool = False,  # noqa: ARG002
        skip_document_row_writes: bool = False,  # noqa: ARG002
    ) -> DocumentBatchPrepareContext:
        return DocumentBatchPrepareContext(updatable_docs=documents, id_to_boost_map={})

    @contextlib.contextmanager
    def lock_context(self, documents: list[Document]) -> Generator[Session, None, None]:  # noqa: ARG002
        self.db_session.commit()  # ensure that we're not in a transaction
        with self.db_session.begin():
            try:
                locked = lock_chat_artifact_for_indexing_nowait(
                    self.db_session, self.indexed
                )
            except OperationalError as e:
                raise ChatArtifactIndexSkip("published file row is busy") from e
            if not locked:
                raise ChatArtifactIndexSkip(
                    "published file or its chat is deleted, or it changed since the pickup"
                )
            yield self.db_session

    def prepare_enrichment(
        self,
        context: DocumentBatchPrepareContext,
        tenant_id: str,
        chunks: list[DocAwareChunk],
        db_session: Session,  # noqa: ARG002
    ) -> ChatArtifactChunkEnricher:
        document_ids = [doc.id for doc in context.updatable_docs]
        new_chunk_counts = dict.fromkeys(document_ids, 0)
        for chunk in chunks:
            new_chunk_counts[chunk.source_document.id] += 1
        return ChatArtifactChunkEnricher(
            access=DocumentAccess.build(
                user_emails=[self.indexed.owner_email],
                user_groups=[],
                external_user_emails=[],
                external_user_group_ids=[],
                is_public=False,
            ),
            doc_id_to_new_chunk_cnt=new_chunk_counts,
            tenant_id=tenant_id,
        )

    def post_index(
        self,
        context: DocumentBatchPrepareContext,  # noqa: ARG002
        updatable_chunk_data: list[UpdatableChunkData],  # noqa: ARG002
        filtered_documents: list[Document],  # noqa: ARG002
        enrichment: ChunkEnrichmentContext,  # noqa: ARG002
        db_session: Session,
        index_to_secondary: bool,  # noqa: ARG002
        failed_document_ids: set[str],
    ) -> None:
        if str(self.indexed.artifact_id) not in failed_document_ids:
            mark_chat_artifact_indexed__no_commit(db_session, self.indexed)


class ChatArtifactChunkEnricher(ChunkEnrichmentContext):
    """The owner-only access of a published file's chunks."""

    def __init__(
        self,
        access: DocumentAccess,
        doc_id_to_new_chunk_cnt: dict[str, int],
        tenant_id: str,
    ) -> None:
        self._access = access
        self._tenant_id = tenant_id
        # Required by ChunkEnrichmentContext. Always empty: the write deletes
        # every chunk of the document first, so no old count is needed.
        self.doc_id_to_previous_chunk_cnt: dict[str, int] = {}
        self.doc_id_to_new_chunk_cnt = doc_id_to_new_chunk_cnt

    def enrich_chunk(
        self, chunk: IndexChunk, score: float
    ) -> DocMetadataAwareIndexChunk:
        return DocMetadataAwareIndexChunk.from_index_chunk(
            index_chunk=chunk,
            access=self._access,
            document_sets=set(),
            user_project=[],
            personas=[],
            boost=DEFAULT_BOOST,
            tenant_id=self._tenant_id,
            aggregated_chunk_boost_factor=score,
        )
