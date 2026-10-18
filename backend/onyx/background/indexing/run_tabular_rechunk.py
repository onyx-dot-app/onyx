"""Re-chunk tabular documents that predate the current chunker.

The connector is never called: the raw workbook stays in the file store, and
the fields Postgres does not keep - title and metadata - are read back from the
document's own stored chunk, as the reindex port does. Writes go through the
normal indexing pipeline, which replaces a document's chunks in one call.

Holding more chunks than the current chunker could produce is what marks a
document as stale, so the scan skips its own output, skips anything an
in-flight crawl writes, and - because a failed write no longer commits its
chunk count - finds its own failures again on a later pass.
"""

import time
from collections import defaultdict
from collections.abc import Callable

from pydantic import BaseModel

from onyx.configs.app_configs import (
    INDEX_BATCH_SIZE,
    LARGE_CHUNK_RATIO,
    TABULAR_MAX_CHUNKS_PER_WORKBOOK,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import (
    experts_from_stores_representations,
)
from onyx.connectors.cross_connector_utils.tabular_section_utils import (
    is_tabular_file,
    tabular_file_to_sections,
)
from onyx.connectors.models import (
    Document,
    IndexAttemptMetadata,
    convert_metadata_list_of_strings_to_dict,
)
from onyx.db.document import TabularRechunkTarget, get_oversized_tabular_documents
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import Document as DbDocument
from onyx.db.search_settings import get_current_search_settings
from onyx.document_index.factory import build_opensearch_document_index
from onyx.document_index.opensearch.opensearch_document_index import (
    OpenSearchDocumentIndex,
)
from onyx.document_index.opensearch.schema import DocumentChunkWithoutVectors
from onyx.file_processing.file_types import SPREADSHEET_MIME_TYPES, OnyxMimeTypes
from onyx.file_store.file_store import get_default_file_store
from onyx.file_store.staging import (
    RawFileCallback,
    build_tracking_raw_file_callback,
    delete_files_best_effort,
)
from onyx.indexing.adapters.document_indexing_adapter import (
    DocumentIndexingBatchAdapter,
)
from onyx.indexing.embedder import DefaultIndexingEmbedder, IndexingEmbedder
from onyx.indexing.indexing_pipeline import run_indexing_pipeline
from onyx.utils.logger import setup_logger
from onyx.utils.middleware import make_randomized_onyx_request_id

logger = setup_logger()

# After this the run returns its cursor and the next tick resumes from it.
TABULAR_RECHUNK_TIME_BUDGET_S = 4 * 60

# Per-workbook cap plus the large chunks multipass derives from it. Counting
# those when multipass is off only loosens the bound.
TABULAR_CHUNK_CEILING = TABULAR_MAX_CHUNKS_PER_WORKBOOK + (
    TABULAR_MAX_CHUNKS_PER_WORKBOOK // LARGE_CHUNK_RATIO
)


class TabularRechunkResult(BaseModel):
    """Outcome of one run. Documents in `failed_document_ids` keep their old
    chunk count, so a finished scan containing them is not a finished
    migration - the next pass starts from the top and finds them again."""

    last_document_id: str | None
    documents_indexed: int
    failed_document_ids: list[str]
    finished: bool


def _tabular_file_name(semantic_id: str, file_type: str | None) -> str:
    """A name the tabular reader can dispatch on. Drive keeps a native Sheet's
    own name, which carries no extension, so the stored type supplies one."""
    if is_tabular_file(semantic_id):
        return semantic_id
    if file_type in SPREADSHEET_MIME_TYPES:
        return f"{semantic_id}.xlsx"
    if file_type in OnyxMimeTypes.CSV_MIME_TYPES:
        return f"{semantic_id}.csv"
    raise ValueError(
        f"{semantic_id!r} is not tabular and {file_type!r} does not say so"
    )


def _rebuild_document(
    db_doc: DbDocument,
    head: DocumentChunkWithoutVectors,
    stage: RawFileCallback,
    file_type: str | None,
) -> Document:
    """Rebuilds the connector Document for one tabular file: only what chunking,
    chunk enrichment and the chunk writer read. The run skips the document
    upsert, so no other row value has to be reproduced faithfully.
    """
    if db_doc.file_id is None:
        raise ValueError(f"{db_doc.id} has no stored file")

    with get_default_file_store().read_file(db_doc.file_id, use_tempfile=True) as raw:
        sections = tabular_file_to_sections(
            file=raw,
            file_name=_tabular_file_name(db_doc.semantic_id, file_type),
            stage=stage,
            link=db_doc.link or "",
        )

    return Document(
        id=db_doc.id,
        source=DocumentSource(head.source_type),
        semantic_identifier=db_doc.semantic_id,
        # None would fall back to semantic_identifier, adding a title vector
        # the document never had.
        title=head.title if head.title is not None else "",
        metadata=(
            convert_metadata_list_of_strings_to_dict(head.metadata_list)
            if head.metadata_list
            else {}
        ),
        sections=sections,
        # post_index writes these two back.
        doc_updated_at=db_doc.doc_updated_at,
        doc_created_at=db_doc.doc_created_at,
        # Chunk enrichment resolves the document's ancestors from this.
        parent_hierarchy_node_id=db_doc.parent_hierarchy_node_id,
        # The chunk writer reads owners off the document, not off the row.
        primary_owners=experts_from_stores_representations(db_doc.primary_owners),
        secondary_owners=experts_from_stores_representations(db_doc.secondary_owners),
    )


def _rechunk_batch(
    targets: list[TabularRechunkTarget],
    connector_id: int,
    credential_id: int,
    tenant_id: str,
    embedder: IndexingEmbedder,
    document_index: OpenSearchDocumentIndex,
    batch_num: int,
) -> tuple[int, list[str]]:
    """Re-chunks one cc-pair's worth of documents. Returns (indexed, failed)."""
    heads = document_index.get_chunk_heads([t.document.id for t in targets])

    # No index attempt here for the standard staging reapers to key on.
    stage, staged_csv_ids = build_tracking_raw_file_callback(
        metadata={"connector_id": str(connector_id), "tenant_id": tenant_id}
    )

    documents: list[Document] = []
    failed: list[str] = []
    try:
        for target in targets:
            db_doc = target.document
            head = heads.get(db_doc.id)
            if head is None:
                # Nothing to preserve and nothing to replace; a crawl owns it.
                logger.warning(
                    "tabular re-chunk: %s has no chunks, skipping", db_doc.id
                )
                failed.append(db_doc.id)
                continue
            try:
                documents.append(
                    _rebuild_document(db_doc, head, stage, file_type=target.file_type)
                )
            except Exception:
                logger.exception("tabular re-chunk: could not rebuild %s", db_doc.id)
                failed.append(db_doc.id)

        if not documents:
            return 0, failed

        metadata = IndexAttemptMetadata(
            connector_id=connector_id,
            credential_id=credential_id,
            request_id=make_randomized_onyx_request_id("TRC"),
            structured_id=f"{tenant_id}:{connector_id}:tabular-rechunk:{batch_num}",
            batch_num=batch_num,
        )
        result = run_indexing_pipeline(
            embedder=embedder,
            document_index=document_index,
            # Both change gates must be off: a tabular document's content_hash
            # never moves, because content_hash() ignores TabularSections.
            ignore_time_skip=True,
            force_update=True,
            # Nothing re-fetched the document, so its row has nothing newer.
            skip_document_row_writes=True,
            tenant_id=tenant_id,
            document_batch=documents,
            request_id=metadata.request_id,
            adapter=DocumentIndexingBatchAdapter(
                connector_id=connector_id,
                credential_id=credential_id,
                tenant_id=tenant_id,
                index_attempt_metadata=metadata,
            ),
        )
    finally:
        delete_files_best_effort(
            staged_csv_ids,
            context=f"tabular-rechunk staging cleanup connector={connector_id}",
        )

    pipeline_failed = {
        failure.failed_document.document_id
        for failure in result.failures
        if failure.failed_document is not None
    }
    return len(documents) - len(pipeline_failed), failed + sorted(pipeline_failed)


def run_tabular_rechunk(
    *,
    tenant_id: str,
    after_doc_id: str | None,
    time_budget_s: float = TABULAR_RECHUNK_TIME_BUDGET_S,
    on_batch: Callable[[], None],
) -> TabularRechunkResult:
    """Re-chunks oversized tabular documents from the cursor until the scan
    reaches the end of the table or the time budget runs out.

    `on_batch` runs after every batch, so the caller can keep a lock lease
    alive: the budget is only checked between pages, and one batch can outlast
    it when the embedding provider throttles.
    """
    start = time.monotonic()
    cursor = after_doc_id
    indexed = 0
    failed: list[str] = []
    batch_num = 0
    finished = False

    with get_session_with_current_tenant() as db_session:
        search_settings = get_current_search_settings(db_session)
        embedder = DefaultIndexingEmbedder.from_db_search_settings(
            search_settings=search_settings, callback=None
        )
        document_index = build_opensearch_document_index(search_settings)
        index_name = search_settings.index_name  # read while attached

    while time.monotonic() - start < time_budget_s:
        with get_session_with_current_tenant() as db_session:
            # An INSTANT swap retires the index this run holds: writing on
            # would lower chunk_count while the new live index keeps the old
            # chunks, stranding it. The cursor is kept for the next tick.
            if get_current_search_settings(db_session).index_name != index_name:
                logger.info("tabular re-chunk: the live index changed, stopping")
                break
            targets = get_oversized_tabular_documents(
                db_session,
                chunk_count_above=TABULAR_CHUNK_CEILING,
                after_doc_id=cursor,
                limit=INDEX_BATCH_SIZE,
            )
        # A short page means no further matches before the end of the table.
        finished = len(targets) < INDEX_BATCH_SIZE

        # The pipeline adapter is per connector + credential.
        grouped: dict[tuple[int, int], list[TabularRechunkTarget]] = defaultdict(list)
        for target in targets:
            grouped[(target.connector_id, target.credential_id)].append(target)

        for (connector_id, credential_id), batch in grouped.items():
            batch_indexed, batch_failed = _rechunk_batch(
                targets=batch,
                connector_id=connector_id,
                credential_id=credential_id,
                tenant_id=tenant_id,
                embedder=embedder,
                document_index=document_index,
                batch_num=batch_num,
            )
            indexed += batch_indexed
            failed.extend(batch_failed)
            batch_num += 1
            on_batch()

        if targets:
            cursor = targets[-1].document.id
        if finished:
            break

    logger.info(
        "tabular re-chunk: %s, indexed=%s failed=%s cursor=%s",
        "scan complete" if finished else "budget spent",
        indexed,
        len(failed),
        cursor,
    )
    return TabularRechunkResult(
        last_document_id=cursor,
        documents_indexed=indexed,
        failed_document_ids=failed,
        finished=finished,
    )
