"""End-to-end composition test for the reindex port flow (MODEL_ONLY strategy).

Proves the layers COMPOSE with NO PortCopier mocking: check_for_port kickoff ->
run_port_attempt (real PIT scan of PRESENT + real re-embed under the FUTURE model
via the local model server + create-only write to FUTURE) -> the port-aware
swap promotion. Asserts the FUTURE chunks carry the seeded content with a freshly
re-embedded 768-dim vector (different from the seeded placeholder), and that the
swap flips our FUTURE row to PRESENT and the present-like row to PAST.

Uses real Postgres + Redis + OpenSearch + the indexing model server.
Restores the dev DB's real current
SearchSettings row in teardown (this dev DB has a leftover PRESENT row + a stale
FUTURE row, so we never rely on the live current/secondary settings being ours).
"""

from datetime import datetime
from datetime import timedelta
from datetime import timezone
from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.access.models import DocumentAccess
from onyx.background.celery.tasks.port import tasks as port_task
from onyx.background.celery.tasks.port.tasks import run_check_for_port
from onyx.background.celery.tasks.port.tasks import run_port_attempt
from onyx.configs.constants import DocumentSource
from onyx.configs.model_configs import ASYM_PASSAGE_PREFIX
from onyx.configs.model_configs import ASYM_QUERY_PREFIX
from onyx.context.search.models import SavedSearchSettings
from onyx.db import swap_index
from onyx.db.enums import EmbeddingPrecision
from onyx.db.enums import IndexingStatus
from onyx.db.enums import IndexModelStatus
from onyx.db.enums import PortAttemptStatus
from onyx.db.enums import SwitchoverType
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import IndexAttempt
from onyx.db.models import PortAttempt
from onyx.db.models import SearchSettings
from onyx.db.port_attempt import get_port_attempt
from onyx.db.search_settings import create_search_settings
from onyx.db.search_settings import get_current_search_settings
from onyx.document_index.interfaces_new import TenantState
from onyx.document_index.opensearch.client import OpenSearchIndexClient
from onyx.document_index.opensearch.constants import DEFAULT_MAX_CHUNK_SIZE
from onyx.document_index.opensearch.opensearch_document_index import (
    generate_opensearch_filtered_access_control_list,
)
from onyx.document_index.opensearch.schema import DocumentChunk
from onyx.document_index.opensearch.schema import DocumentSchema
from onyx.document_index.opensearch.schema import get_opensearch_doc_chunk_id
from shared_configs.configs import MODEL_SERVER_HOST
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from shared_configs.contextvars import get_current_tenant_id
from tests.external_dependency_unit.indexing_helpers import cleanup_cc_pair
from tests.external_dependency_unit.indexing_helpers import make_cc_pair
from tests.external_dependency_unit.indexing_helpers import seed_cc_pair_documents

# The port re-embeds PRESENT -> FUTURE against the local embedding model server;
# ext-dep shards run with it disabled, so this composition test only runs where
# a real model server is present (local dev / nightly with the server up).
pytestmark = pytest.mark.skipif(
    MODEL_SERVER_HOST == "disabled",
    reason="hits the real embedding model server, which is disabled in this env",
)

_VECTOR_DIM = 768
_CHUNKS_PER_DOC = 2
_NUM_DOCS = 4
# A constant placeholder vector seeded into PRESENT; the port re-embeds, so the
# FUTURE vector must differ from this to prove a real embed happened.
_PLACEHOLDER_VECTOR = [0.123] * _VECTOR_DIM
# Real sentences so the local embedder produces meaningful, non-degenerate vectors.
_CHUNK_SENTENCES = [
    "The migration ports stored chunks from the present index to the future one.",
    "Each chunk is re-embedded under the new model before it is written.",
    "External versioning ensures the newest source write wins on a conflict.",
    "The swap promotes the future settings once every required port succeeds.",
    "Documents reach the future index only through the reindex port flow.",
    "A point-in-time scan reads the present chunks without their vectors.",
    "The embedder runs against the local model server during the port.",
    "Cursor commits make a crashed or stalled port resume rather than restart.",
]


def _make_chunk(
    document_id: str,
    chunk_index: int,
    content: str,
    tenant_state: TenantState,
    last_updated: datetime,
) -> DocumentChunk:
    """Minimal PRESENT chunk seeded for the port to scan + re-embed. content is a
    real sentence; content_vector is the placeholder the port must overwrite."""
    access = DocumentAccess.build(
        user_emails=[],
        user_groups=[],
        external_user_emails=[],
        external_user_group_ids=[],
        is_public=True,
    )
    return DocumentChunk(
        document_id=document_id,
        chunk_index=chunk_index,
        title=None,
        title_vector=None,
        content=content,
        content_vector=list(_PLACEHOLDER_VECTOR),
        source_type=DocumentSource.FILE.value,
        metadata_list=None,
        last_updated=last_updated,
        public=access.is_public,
        access_control_list=generate_opensearch_filtered_access_control_list(access),
        hidden=False,
        global_boost=0,
        semantic_identifier=f"semantic-{document_id}",
        image_file_id=None,
        source_links=None,
        blurb="blurb",
        doc_summary="",
        chunk_context="",
        document_sets=None,
        user_projects=None,
        primary_owners=None,
        secondary_owners=None,
        tenant_id=tenant_state,
    )


def _make_saved_settings(
    *,
    index_name: str,
    use_port_flow: bool,
    switchover_type: SwitchoverType,
) -> SavedSearchSettings:
    """nomic MODEL_ONLY settings (contextual RAG off, provider None -> local
    model server)."""
    return SavedSearchSettings(
        model_name="nomic-ai/nomic-embed-text-v1",
        model_dim=_VECTOR_DIM,
        normalize=True,
        query_prefix=ASYM_QUERY_PREFIX,
        passage_prefix=ASYM_PASSAGE_PREFIX,
        provider_type=None,
        index_name=index_name,
        multipass_indexing=False,
        embedding_precision=EmbeddingPrecision.FLOAT,
        reduced_dimension=None,
        enable_contextual_rag=False,
        contextual_rag_llm_name=None,
        contextual_rag_llm_provider=None,
        switchover_type=switchover_type,
        use_port_flow=use_port_flow,
    )


def _create_os_index(index_name: str) -> OpenSearchIndexClient:
    client = OpenSearchIndexClient(index_name=index_name)
    mappings = DocumentSchema.get_document_schema(
        vector_dimension=_VECTOR_DIM, multitenant=False
    )
    settings = DocumentSchema.get_index_settings_based_on_environment()
    client.create_index(mappings=mappings, settings=settings)
    return client


def test_port_flow_end_to_end(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    tenant_state = TenantState(tenant_id=POSTGRES_DEFAULT_SCHEMA, multitenant=False)
    present_index_name = f"test_e2e_present_{uuid4().hex[:8]}"
    future_index_name = f"test_e2e_future_{uuid4().hex[:8]}"

    # The dev DB's real current row — restore this in teardown.
    original_present_id = get_current_search_settings(db_session).id

    pair: ConnectorCredentialPair | None = None
    present_like_id: int | None = None
    future_id: int | None = None
    present_client: OpenSearchIndexClient | None = None
    future_client: OpenSearchIndexClient | None = None
    promoted = False

    try:
        # --- SETUP: cc_pair + docs ---
        pair = make_cc_pair(db_session)
        doc_ids = seed_cc_pair_documents(
            db_session, pair, _NUM_DOCS, prefix="e2edoc-", unique=True
        )

        # --- SETUP: SearchSettings (present-like PAST + FUTURE) ---
        present_like = create_search_settings(
            _make_saved_settings(
                index_name=present_index_name,
                use_port_flow=False,
                switchover_type=SwitchoverType.REINDEX,
            ),
            db_session,
            status=IndexModelStatus.PAST,
        )
        present_like_id = present_like.id
        future = create_search_settings(
            _make_saved_settings(
                index_name=future_index_name,
                use_port_flow=True,
                switchover_type=SwitchoverType.REINDEX,
            ),
            db_session,
            status=IndexModelStatus.FUTURE,
        )
        future_id = future.id

        # --- SETUP: OpenSearch indices + seed PRESENT chunks ---
        present_client = _create_os_index(present_index_name)
        future_client = _create_os_index(future_index_name)

        seeded_ts = datetime.now(timezone.utc).replace(microsecond=0)
        seeded_content: dict[tuple[str, int], str] = {}
        chunks: list[DocumentChunk] = []
        for d_i, doc_id in enumerate(doc_ids):
            for c_i in range(_CHUNKS_PER_DOC):
                content = _CHUNK_SENTENCES[
                    (d_i * _CHUNKS_PER_DOC + c_i) % len(_CHUNK_SENTENCES)
                ]
                seeded_content[(doc_id, c_i)] = content
                chunks.append(
                    _make_chunk(doc_id, c_i, content, tenant_state, seeded_ts)
                )
        present_client.bulk_index_documents(documents=chunks, tenant_state=tenant_state)
        present_client.refresh_index()

        # --- KICKOFF: check_for_port scoped to our FUTURE + cc_pair ---
        celery_app = MagicMock()
        with (
            patch.object(
                port_task,
                "get_secondary_search_settings",
                lambda db, *_, **__: db.get(SearchSettings, future_id),
            ),
            patch.object(
                port_task,
                "fetch_indexable_standard_connector_credential_pair_ids",
                lambda *_, **__: [pair.id],
            ),
        ):
            result = run_check_for_port(get_current_tenant_id(), celery_app)
        assert result == 1
        attempt_id = celery_app.send_task.call_args.kwargs["kwargs"]["port_attempt_id"]

        # --- PORT: real PortCopier (re-embed via model server) ---
        # get_current_search_settings is patched to our present-like row only
        # (the dev DB's live current row has no real model / index).
        with patch.object(
            port_task,
            "get_current_search_settings",
            lambda db: db.get(SearchSettings, present_like_id),
        ):
            run_port_attempt(attempt_id)

        # --- ASSERT PORT ---
        db_session.expire_all()
        attempt = get_port_attempt(db_session, attempt_id)
        assert attempt is not None
        assert attempt.status == PortAttemptStatus.SUCCESS
        assert attempt.last_processed_doc_id == max(doc_ids)
        assert attempt.docs_ported == _NUM_DOCS

        future_client.refresh_index()
        for doc_id in doc_ids:
            for c_i in range(_CHUNKS_PER_DOC):
                chunk_id = get_opensearch_doc_chunk_id(
                    tenant_state=tenant_state,
                    document_id=doc_id,
                    chunk_index=c_i,
                    max_chunk_size=DEFAULT_MAX_CHUNK_SIZE,
                )
                fetched = future_client.get_document(document_chunk_id=chunk_id)
                assert fetched.content == seeded_content[(doc_id, c_i)]
                assert len(fetched.content_vector) == _VECTOR_DIM
                # The port re-embedded: the vector is NOT the seeded placeholder.
                assert fetched.content_vector != _PLACEHOLDER_VECTOR

        # --- SWAP ---
        port_row = get_port_attempt(db_session, attempt_id)
        assert port_row is not None and port_row.time_completed is not None
        # A real (non-seed) FUTURE index attempt landing after the port.
        index_started = port_row.time_completed + timedelta(seconds=1)
        db_session.add(
            IndexAttempt(
                connector_credential_pair_id=pair.id,
                search_settings_id=future_id,
                from_beginning=False,
                status=IndexingStatus.SUCCESS,
                is_synthetic_seed=False,
                time_started=index_started,
                time_updated=index_started,
            )
        )
        db_session.commit()

        # check_and_perform_index_swap fetches the FUTURE row via
        # get_secondary_search_settings (a stale FUTURE row exists in this dev
        # DB), and get_all_document_indices would touch real Vespa/OpenSearch
        # provisioning -> patch both in the swap_index namespace. The deferred
        # metadata-sync backlog is 0 in this dev DB; if it weren't, the swap
        # criterion would block, so we don't need to patch the count.
        # _required_cc_pairs_for_switchover gates the swap on EVERY indexable
        # cc_pair in the dev DB (via fetch_indexable...), none of which have a
        # port for our FUTURE -> scope the required set to our cc_pair only.
        with (
            patch.object(
                swap_index,
                "get_secondary_search_settings",
                lambda db: db.get(SearchSettings, future_id),
            ),
            patch.object(
                swap_index,
                "fetch_indexable_standard_connector_credential_pair_ids",
                lambda *_, **__: [pair.id],
            ),
            patch.object(swap_index, "get_all_document_indices", return_value=[]),
        ):
            old_settings = swap_index.check_and_perform_index_swap(db_session)

        assert old_settings is not None
        promoted = True

        # --- ASSERT SWAP ---
        db_session.expire_all()
        future_row = db_session.get(SearchSettings, future_id)
        present_like_row = db_session.get(SearchSettings, present_like_id)
        assert future_row is not None and present_like_row is not None
        assert future_row.status == IndexModelStatus.PRESENT
        assert present_like_row.status == IndexModelStatus.PAST
    finally:
        db_session.rollback()
        # Restore the dev DB's swap state FIRST: original current -> PRESENT, our
        # promoted row off PRESENT (so get_current_search_settings is correct
        # again). _perform_index_swap also set original_present_id -> PAST.
        if promoted and original_present_id is not None:
            db_session.query(SearchSettings).filter(
                SearchSettings.id == original_present_id
            ).update(
                {SearchSettings.status: IndexModelStatus.PRESENT},
                synchronize_session="fetch",
            )
            if future_id is not None:
                db_session.query(SearchSettings).filter(
                    SearchSettings.id == future_id
                ).update(
                    {SearchSettings.status: IndexModelStatus.PAST},
                    synchronize_session="fetch",
                )
            db_session.commit()

        # PortAttempt + IndexAttempt before SearchSettings before cc_pair.
        if pair is not None:
            db_session.query(PortAttempt).filter(
                PortAttempt.cc_pair_id == pair.id
            ).delete(synchronize_session="fetch")
            db_session.query(IndexAttempt).filter(
                IndexAttempt.connector_credential_pair_id == pair.id
            ).delete(synchronize_session="fetch")
            db_session.commit()

        for ss_id in (future_id, present_like_id):
            if ss_id is not None:
                db_session.query(SearchSettings).filter(
                    SearchSettings.id == ss_id
                ).delete(synchronize_session="fetch")
        db_session.commit()

        if pair is not None:
            cleanup_cc_pair(db_session, pair)

        for client in (present_client, future_client):
            if client is not None:
                try:
                    client.delete_index()
                except Exception:
                    pass
                finally:
                    client.close()
