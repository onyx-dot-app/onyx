import concurrent.futures
import io
import logging
import os
import re
import time
import urllib
import zipfile
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from typing import BinaryIO
from typing import cast
from typing import List

import httpx
import jinja2
import requests
from pydantic import BaseModel
from retry import retry

from onyx.configs.app_configs import BLURB_SIZE
from onyx.configs.chat_configs import NUM_RETURNED_HITS
from onyx.configs.chat_configs import TITLE_CONTENT_RATIO
from onyx.configs.chat_configs import VESPA_SEARCHER_THREADS
from onyx.configs.constants import KV_REINDEX_KEY
from onyx.configs.constants import RETURN_SEPARATOR
from onyx.context.search.enums import QueryType
from onyx.context.search.models import IndexFilters
from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import InferenceChunkUncleaned
from onyx.context.search.models import QueryExpansionType
from onyx.db.enums import EmbeddingPrecision
from onyx.document_index.document_index_utils import get_uuid_from_chunk_info
from onyx.document_index.interfaces import DocumentIndex
from onyx.document_index.interfaces import (
    DocumentInsertionRecord as OldDocumentInsertionRecord,
)
from onyx.document_index.interfaces import EnrichedDocumentIndexingInfo
from onyx.document_index.interfaces import IndexBatchParams
from onyx.document_index.interfaces import MinimalDocumentIndexingInfo
from onyx.document_index.interfaces import UpdateRequest
from onyx.document_index.interfaces import VespaChunkRequest
from onyx.document_index.interfaces import VespaDocumentFields
from onyx.document_index.interfaces import VespaDocumentUserFields
from onyx.document_index.interfaces_new import DocumentSectionRequest
from onyx.document_index.interfaces_new import IndexingMetadata
from onyx.document_index.interfaces_new import MetadataUpdateRequest
from onyx.document_index.vespa.chunk_retrieval import query_vespa
from onyx.document_index.vespa.indexing_utils import BaseHTTPXClientContext
from onyx.document_index.vespa.indexing_utils import check_for_final_chunk_existence
from onyx.document_index.vespa.indexing_utils import GlobalHTTPXClientContext
from onyx.document_index.vespa.indexing_utils import TemporaryHTTPXClientContext
from onyx.document_index.vespa.shared_utils.utils import get_vespa_http_client
from onyx.document_index.vespa.shared_utils.vespa_request_builders import (
    build_vespa_filters,
)
from onyx.document_index.vespa.vespa_document_index import TenantState
from onyx.document_index.vespa.vespa_document_index import VespaDocumentIndex
from onyx.document_index.vespa_constants import BATCH_SIZE
from onyx.document_index.vespa_constants import CONTENT_SUMMARY
from onyx.document_index.vespa_constants import DOCUMENT_ID_ENDPOINT
from onyx.document_index.vespa_constants import NUM_THREADS
from onyx.document_index.vespa_constants import VESPA_APPLICATION_ENDPOINT
from onyx.document_index.vespa_constants import VESPA_TIMEOUT
from onyx.document_index.vespa_constants import YQL_BASE
from onyx.indexing.models import DocMetadataAwareIndexChunk
from onyx.key_value_store.factory import get_shared_kv_store
from onyx.kg.utils.formatting_utils import split_relationship_id
from onyx.utils.batching import batch_generator
from onyx.utils.logger import setup_logger
from onyx.utils.timing import log_function_time
from shared_configs.configs import MULTI_TENANT
from shared_configs.model_server_models import Embedding

logger = setup_logger()

# Set the logging level to WARNING to ignore INFO and DEBUG logs
httpx_logger = logging.getLogger("httpx")
httpx_logger.setLevel(logging.WARNING)


@dataclass
class _VespaUpdateRequest:
    document_id: str
    url: str
    update_request: dict[str, dict]


class KGVespaChunkUpdateRequest(BaseModel):
    document_id: str
    chunk_id: int
    url: str
    update_request: dict[str, dict]


class KGUChunkUpdateRequest(BaseModel):
    """
    Update KG fields for a document
    """

    document_id: str
    chunk_id: int
    core_entity: str
    entities: set[str] | None = None
    relationships: set[str] | None = None
    terms: set[str] | None = None


class KGUDocumentUpdateRequest(BaseModel):
    """
    Update KG fields for a document
    """

    document_id: str
    entities: set[str]
    relationships: set[str]
    terms: set[str]


def generate_kg_update_request(
    kg_update_request: KGUChunkUpdateRequest,
) -> dict[str, dict]:
    kg_update_dict: dict[str, dict] = {}

    if kg_update_request.entities is not None:
        kg_update_dict["kg_entities"] = {"assign": list(kg_update_request.entities)}

    if kg_update_request.relationships is not None:
        kg_update_dict["kg_relationships"] = {"assign": []}
        for relationship in kg_update_request.relationships:
            source, rel_type, target = split_relationship_id(relationship)
            kg_update_dict["kg_relationships"]["assign"].append(
                {
                    "source": source,
                    "rel_type": rel_type,
                    "target": target,
                }
            )

    return kg_update_dict


def in_memory_zip_from_file_bytes(file_contents: dict[str, bytes]) -> BinaryIO:
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
        for filename, content in file_contents.items():
            zipf.writestr(filename, content)
    zip_buffer.seek(0)
    return zip_buffer


def _create_document_xml_lines(doc_names: list[str | None] | list[str]) -> str:
    doc_lines = [
        f'<document type="{doc_name}" mode="index" />'
        for doc_name in doc_names
        if doc_name
    ]
    return "\n".join(doc_lines)


def add_ngrams_to_schema(schema_content: str) -> str:
    # Add the match blocks containing gram and gram-size to title and content fields
    schema_content = re.sub(
        r"(field title type string \{[^}]*indexing: summary \| index \| attribute)",
        r"\1\n            match {\n                gram\n                gram-size: 3\n            }",
        schema_content,
    )
    schema_content = re.sub(
        r"(field content type string \{[^}]*indexing: summary \| index)",
        r"\1\n            match {\n                gram\n                gram-size: 3\n            }",
        schema_content,
    )
    return schema_content


def cleanup_chunks(chunks: list[InferenceChunkUncleaned]) -> list[InferenceChunk]:
    def _remove_title(chunk: InferenceChunkUncleaned) -> str:
        if not chunk.title or not chunk.content:
            return chunk.content

        if chunk.content.startswith(chunk.title):
            return chunk.content[len(chunk.title) :].lstrip()

        # BLURB SIZE is by token instead of char but each token is at least 1 char
        # If this prefix matches the content, it's assumed the title was prepended
        if chunk.content.startswith(chunk.title[:BLURB_SIZE]):
            return (
                chunk.content.split(RETURN_SEPARATOR, 1)[-1]
                if RETURN_SEPARATOR in chunk.content
                else chunk.content
            )

        return chunk.content

    def _remove_metadata_suffix(chunk: InferenceChunkUncleaned) -> str:
        if not chunk.metadata_suffix:
            return chunk.content
        return chunk.content.removesuffix(chunk.metadata_suffix).rstrip(
            RETURN_SEPARATOR
        )

    def _remove_contextual_rag(chunk: InferenceChunkUncleaned) -> str:
        # remove document summary
        if chunk.content.startswith(chunk.doc_summary):
            chunk.content = chunk.content[len(chunk.doc_summary) :].lstrip()
        # remove chunk context
        if chunk.content.endswith(chunk.chunk_context):
            chunk.content = chunk.content[
                : len(chunk.content) - len(chunk.chunk_context)
            ].rstrip()
        return chunk.content

    for chunk in chunks:
        chunk.content = _remove_title(chunk)
        chunk.content = _remove_metadata_suffix(chunk)
        chunk.content = _remove_contextual_rag(chunk)

    return [chunk.to_inference_chunk() for chunk in chunks]


class VespaIndex(DocumentIndex):

    VESPA_SCHEMA_JINJA_FILENAME = "danswer_chunk.sd.jinja"

    def __init__(
        self,
        index_name: str,
        secondary_index_name: str | None,
        large_chunks_enabled: bool,
        secondary_large_chunks_enabled: bool | None,
        multitenant: bool = False,
        httpx_client: httpx.Client | None = None,
    ) -> None:
        self.index_name = index_name
        self.secondary_index_name = secondary_index_name

        self.large_chunks_enabled = large_chunks_enabled
        self.secondary_large_chunks_enabled = secondary_large_chunks_enabled

        self.multitenant = multitenant

        # Temporary until we refactor the entirety of this class.
        self.httpx_client = httpx_client

        self.httpx_client_context: BaseHTTPXClientContext
        if httpx_client:
            self.httpx_client_context = GlobalHTTPXClientContext(httpx_client)
        else:
            self.httpx_client_context = TemporaryHTTPXClientContext(
                get_vespa_http_client
            )

        self.index_to_large_chunks_enabled: dict[str, bool] = {}
        self.index_to_large_chunks_enabled[index_name] = large_chunks_enabled
        if secondary_index_name and secondary_large_chunks_enabled:
            self.index_to_large_chunks_enabled[secondary_index_name] = (
                secondary_large_chunks_enabled
            )

    def ensure_indices_exist(
        self,
        primary_embedding_dim: int,
        primary_embedding_precision: EmbeddingPrecision,
        secondary_index_embedding_dim: int | None,
        secondary_index_embedding_precision: EmbeddingPrecision | None,
    ) -> None:
        if MULTI_TENANT:
            logger.info(
                "Skipping Vespa index setup for multitenant (would wipe all indices)"
            )
            return None

        jinja_env = jinja2.Environment()

        deploy_url = f"{VESPA_APPLICATION_ENDPOINT}/tenant/default/prepareandactivate"
        logger.notice(f"Deploying Vespa application package to {deploy_url}")

        vespa_schema_path = os.path.join(
            os.getcwd(), "onyx", "document_index", "vespa", "app_config"
        )
        schema_jinja_file = os.path.join(
            vespa_schema_path, "schemas", VespaIndex.VESPA_SCHEMA_JINJA_FILENAME
        )
        services_jinja_file = os.path.join(vespa_schema_path, "services.xml.jinja")
        overrides_jinja_file = os.path.join(
            vespa_schema_path, "validation-overrides.xml.jinja"
        )

        with open(services_jinja_file, "r") as services_f:
            schema_names = [self.index_name, self.secondary_index_name]
            doc_lines = _create_document_xml_lines(schema_names)

            services_template_str = services_f.read()
            services_template = jinja_env.from_string(services_template_str)
            services = services_template.render(
                document_elements=doc_lines,
                num_search_threads=str(VESPA_SEARCHER_THREADS),
            )

        kv_store = get_shared_kv_store()

        needs_reindexing = False
        try:
            needs_reindexing = cast(bool, kv_store.load(KV_REINDEX_KEY))
        except Exception:
            logger.debug("Could not load the reindexing flag. Using ngrams")

        # Vespa requires an override to erase data including the indices we're no longer using
        # It also has a 30 day cap from current so we set it to 7 dynamically
        with open(overrides_jinja_file, "r") as overrides_f:
            overrides_template_str = overrides_f.read()
            overrides_template = jinja_env.from_string(overrides_template_str)

            now = datetime.now()
            date_in_7_days = now + timedelta(days=7)
            formatted_date = date_in_7_days.strftime("%Y-%m-%d")
            overrides = overrides_template.render(
                until_date=formatted_date,
            )

        zip_dict = {
            "services.xml": services.encode("utf-8"),
            "validation-overrides.xml": overrides.encode("utf-8"),
        }

        with open(schema_jinja_file, "r") as schema_f:
            template_str = schema_f.read()

        template = jinja_env.from_string(template_str)
        schema = template.render(
            multi_tenant=MULTI_TENANT,
            schema_name=self.index_name,
            dim=primary_embedding_dim,
            embedding_precision=primary_embedding_precision.value,
        )

        schema = add_ngrams_to_schema(schema) if needs_reindexing else schema
        zip_dict[f"schemas/{schema_names[0]}.sd"] = schema.encode("utf-8")

        if self.secondary_index_name:
            if secondary_index_embedding_dim is None:
                raise ValueError("Secondary index embedding dimension is required")
            if secondary_index_embedding_precision is None:
                raise ValueError("Secondary index embedding precision is required")

            upcoming_schema = template.render(
                multi_tenant=MULTI_TENANT,
                schema_name=self.secondary_index_name,
                dim=secondary_index_embedding_dim,
                embedding_precision=secondary_index_embedding_precision.value,
            )

            zip_dict[f"schemas/{schema_names[1]}.sd"] = upcoming_schema.encode("utf-8")

        zip_file = in_memory_zip_from_file_bytes(zip_dict)

        headers = {"Content-Type": "application/zip"}
        response = requests.post(deploy_url, headers=headers, data=zip_file)
        if response.status_code != 200:
            logger.error(
                f"Failed to prepare Vespa Onyx Index. Response: {response.text}"
            )
            raise RuntimeError(
                f"Failed to prepare Vespa Onyx Index. Response: {response.text}"
            )

    @staticmethod
    def register_multitenant_indices(
        indices: list[str],
        embedding_dims: list[int],
        embedding_precisions: list[EmbeddingPrecision],
    ) -> None:
        if not MULTI_TENANT:
            raise ValueError("Multi-tenant is not enabled")

        deploy_url = f"{VESPA_APPLICATION_ENDPOINT}/tenant/default/prepareandactivate"
        logger.info(f"Deploying Vespa application package to {deploy_url}")

        vespa_schema_path = os.path.join(
            os.getcwd(), "onyx", "document_index", "vespa", "app_config"
        )
        schema_jinja_file = os.path.join(
            vespa_schema_path, "schemas", VespaIndex.VESPA_SCHEMA_JINJA_FILENAME
        )
        services_jinja_file = os.path.join(vespa_schema_path, "services.xml.jinja")
        overrides_jinja_file = os.path.join(
            vespa_schema_path, "validation-overrides.xml.jinja"
        )

        jinja_env = jinja2.Environment()

        # Generate schema names from index settings
        with open(services_jinja_file, "r") as services_f:
            schema_names = [index_name for index_name in indices]
            doc_lines = _create_document_xml_lines(schema_names)

            services_template_str = services_f.read()
            services_template = jinja_env.from_string(services_template_str)
            services = services_template.render(
                document_elements=doc_lines,
                num_search_threads=str(VESPA_SEARCHER_THREADS),
            )

        kv_store = get_shared_kv_store()

        needs_reindexing = False
        try:
            needs_reindexing = cast(bool, kv_store.load(KV_REINDEX_KEY))
        except Exception:
            logger.debug("Could not load the reindexing flag. Using ngrams")

        # Vespa requires an override to erase data including the indices we're no longer using
        # It also has a 30 day cap from current so we set it to 7 dynamically
        with open(overrides_jinja_file, "r") as overrides_f:
            overrides_template_str = overrides_f.read()
            overrides_template = jinja_env.from_string(overrides_template_str)

            now = datetime.now()
            date_in_7_days = now + timedelta(days=7)
            formatted_date = date_in_7_days.strftime("%Y-%m-%d")
            overrides = overrides_template.render(
                until_date=formatted_date,
            )

        zip_dict = {
            "services.xml": services.encode("utf-8"),
            "validation-overrides.xml": overrides.encode("utf-8"),
        }

        with open(schema_jinja_file, "r") as schema_f:
            schema_template_str = schema_f.read()

        schema_template = jinja_env.from_string(schema_template_str)

        for i, index_name in enumerate(indices):
            embedding_dim = embedding_dims[i]
            embedding_precision = embedding_precisions[i]
            logger.info(
                f"Creating index: {index_name} with embedding dimension: {embedding_dim}"
            )

            schema = schema_template.render(
                multi_tenant=MULTI_TENANT,
                schema_name=index_name,
                dim=embedding_dim,
                embedding_precision=embedding_precision.value,
            )

            schema = add_ngrams_to_schema(schema) if needs_reindexing else schema
            zip_dict[f"schemas/{index_name}.sd"] = schema.encode("utf-8")

        zip_file = in_memory_zip_from_file_bytes(zip_dict)

        headers = {"Content-Type": "application/zip"}
        response = requests.post(deploy_url, headers=headers, data=zip_file)

        if response.status_code != 200:
            raise RuntimeError(
                f"Failed to prepare Vespa Onyx Indexes. Response: {response.text}"
            )

    def index(
        self,
        chunks: list[DocMetadataAwareIndexChunk],
        index_batch_params: IndexBatchParams,
    ) -> set[OldDocumentInsertionRecord]:
        if len(index_batch_params.doc_id_to_previous_chunk_cnt) != len(
            index_batch_params.doc_id_to_new_chunk_cnt
        ):
            raise ValueError("Bug: Length of doc ID to chunk maps does not match.")
        doc_id_to_chunk_cnt_diff = {
            doc_id: IndexingMetadata.ChunkCounts(
                old_chunk_cnt=index_batch_params.doc_id_to_previous_chunk_cnt[doc_id],
                new_chunk_cnt=index_batch_params.doc_id_to_new_chunk_cnt[doc_id],
            )
            for doc_id in index_batch_params.doc_id_to_previous_chunk_cnt.keys()
        }
        indexing_metadata = IndexingMetadata(
            doc_id_to_chunk_cnt_diff=doc_id_to_chunk_cnt_diff,
        )
        vespa_document_index = VespaDocumentIndex(
            index_name=self.index_name,
            tenant_state=TenantState(
                tenant_id=index_batch_params.tenant_id,
                multitenant=self.multitenant,
            ),
            large_chunks_enabled=self.large_chunks_enabled,
            httpx_client=self.httpx_client,
        )
        # This conversion from list to set only to be converted again to a list
        # upstream is suboptimal and only temporary until we refactor the
        # entirety of this class.
        document_insertion_records = vespa_document_index.index(
            chunks, indexing_metadata
        )
        return set(
            [
                OldDocumentInsertionRecord(
                    document_id=doc_insertion_record.document_id,
                    already_existed=doc_insertion_record.already_existed,
                )
                for doc_insertion_record in document_insertion_records
            ]
        )

    @classmethod
    def _apply_updates_batched(
        cls,
        updates: list[_VespaUpdateRequest],
        httpx_client: httpx.Client,
        batch_size: int = BATCH_SIZE,
    ) -> None:
        """Runs a batch of updates in parallel via the ThreadPoolExecutor."""

        def _update_chunk(
            update: _VespaUpdateRequest, http_client: httpx.Client
        ) -> httpx.Response:
            logger.debug(
                f"Updating with request to {update.url} with body {update.update_request}"
            )
            return http_client.put(
                update.url,
                headers={"Content-Type": "application/json"},
                json=update.update_request,
            )

        # NOTE: using `httpx` here since `requests` doesn't support HTTP2. This is beneficient for
        # indexing / updates / deletes since we have to make a large volume of requests.

        with (
            concurrent.futures.ThreadPoolExecutor(max_workers=NUM_THREADS) as executor,
            httpx_client as http_client,
        ):
            for update_batch in batch_generator(updates, batch_size):
                future_to_document_id = {
                    executor.submit(
                        _update_chunk,
                        update,
                        http_client,
                    ): update.document_id
                    for update in update_batch
                }
                for future in concurrent.futures.as_completed(future_to_document_id):
                    res = future.result()
                    try:
                        res.raise_for_status()
                    except requests.HTTPError as e:
                        failure_msg = f"Failed to update document: {future_to_document_id[future]}"
                        raise requests.HTTPError(failure_msg) from e

    @classmethod
    def _apply_kg_chunk_updates_batched(
        cls,
        updates: list[KGVespaChunkUpdateRequest],
        httpx_client: httpx.Client,
        batch_size: int = BATCH_SIZE,
    ) -> None:
        """Runs a batch of updates in parallel via the ThreadPoolExecutor."""

        @retry(tries=3, delay=1, backoff=2, jitter=(0.0, 1.0))
        def _kg_update_chunk(
            update: KGVespaChunkUpdateRequest, http_client: httpx.Client
        ) -> httpx.Response:
            return http_client.put(
                update.url,
                headers={"Content-Type": "application/json"},
                json=update.update_request,
            )

        # NOTE: using `httpx` here since `requests` doesn't support HTTP2. This is beneficient for
        # indexing / updates / deletes since we have to make a large volume of requests.

        with concurrent.futures.ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
            for update_batch in batch_generator(updates, batch_size):
                future_to_document_id = {
                    executor.submit(
                        _kg_update_chunk,
                        update,
                        httpx_client,
                    ): update.document_id
                    for update in update_batch
                }
                for future in concurrent.futures.as_completed(future_to_document_id):
                    res = future.result()
                    try:
                        res.raise_for_status()
                    except requests.HTTPError as e:
                        failure_msg = (
                            f"Failed to update document {future_to_document_id[future]}\n"
                            f"Response: {res.text}"
                        )
                        raise requests.HTTPError(failure_msg) from e

    def kg_chunk_updates(
        self, kg_update_requests: list[KGUChunkUpdateRequest], tenant_id: str
    ) -> None:

        processed_updates_requests: list[KGVespaChunkUpdateRequest] = []
        update_start = time.monotonic()

        # Build the _VespaUpdateRequest objects

        for kg_update_request in kg_update_requests:
            kg_update_dict: dict[str, dict] = {
                "fields": generate_kg_update_request(kg_update_request)
            }
            if not kg_update_dict["fields"]:
                logger.error("Update request received but nothing to update")
                continue

            doc_chunk_id = get_uuid_from_chunk_info(
                document_id=kg_update_request.document_id,
                chunk_id=kg_update_request.chunk_id,
                tenant_id=tenant_id,
                large_chunk_id=None,
            )

            processed_updates_requests.append(
                KGVespaChunkUpdateRequest(
                    document_id=kg_update_request.document_id,
                    chunk_id=kg_update_request.chunk_id,
                    url=f"{DOCUMENT_ID_ENDPOINT.format(index_name=self.index_name)}/{doc_chunk_id}",
                    update_request=kg_update_dict,
                )
            )

        with self.httpx_client_context as httpx_client:
            self._apply_kg_chunk_updates_batched(
                processed_updates_requests, httpx_client
            )
        logger.debug(
            "Updated %d vespa documents in %.2f seconds",
            len(processed_updates_requests),
            time.monotonic() - update_start,
        )

    def update(self, update_requests: list[UpdateRequest], *, tenant_id: str) -> None:
        raise NotImplementedError

    def update_single(
        self,
        doc_id: str,
        *,
        chunk_count: int | None,
        tenant_id: str,
        fields: VespaDocumentFields | None,
        user_fields: VespaDocumentUserFields | None,
    ) -> None:
        """Note: if the document id does not exist, the update will be a no-op and the
        function will complete with no errors or exceptions.
        Handle other exceptions if you wish to implement retry behavior
        """
        if fields is None and user_fields is None:
            raise ValueError(
                f"Bug: Tried to update document {doc_id} with no updated fields or user fields."
            )
        # TODO(andrei): Very temporary, reinstate this soon.
        # if fields is not None and fields.document_id is not None:
        #     raise ValueError(
        #         "The new vector db interface does not support updating the document ID field."
        #     )

        vespa_document_index = VespaDocumentIndex(
            index_name=self.index_name,
            tenant_state=TenantState(
                tenant_id=tenant_id,
                multitenant=self.multitenant,
            ),
            large_chunks_enabled=self.large_chunks_enabled,
            httpx_client=self.httpx_client,
        )

        project_ids: set[int] | None = None
        if user_fields is not None and user_fields.user_projects is not None:
            project_ids = set(user_fields.user_projects)
        update_request = MetadataUpdateRequest(
            document_ids=[doc_id],
            doc_id_to_chunk_cnt={
                doc_id: chunk_count if chunk_count is not None else -1
            },  # NOTE: -1 represents an unknown chunk count.
            access=fields.access if fields is not None else None,
            document_sets=fields.document_sets if fields is not None else None,
            boost=fields.boost if fields is not None else None,
            hidden=fields.hidden if fields is not None else None,
            project_ids=project_ids,
        )

        vespa_document_index.update([update_request])

    def delete_single(
        self,
        doc_id: str,
        *,
        tenant_id: str,
        chunk_count: int | None,
    ) -> int:
        vespa_document_index = VespaDocumentIndex(
            index_name=self.index_name,
            tenant_state=TenantState(
                tenant_id=tenant_id,
                multitenant=self.multitenant,
            ),
            large_chunks_enabled=self.large_chunks_enabled,
            httpx_client=self.httpx_client,
        )
        return vespa_document_index.delete(document_id=doc_id, chunk_count=chunk_count)

    def id_based_retrieval(
        self,
        chunk_requests: list[VespaChunkRequest],
        filters: IndexFilters,
        batch_retrieval: bool = False,
        get_large_chunks: bool = False,
    ) -> list[InferenceChunk]:
        tenant_id = filters.tenant_id if filters.tenant_id is not None else ""
        vespa_document_index = VespaDocumentIndex(
            index_name=self.index_name,
            tenant_state=TenantState(
                tenant_id=tenant_id,
                multitenant=self.multitenant,
            ),
            large_chunks_enabled=self.large_chunks_enabled,
            httpx_client=self.httpx_client,
        )
        generic_chunk_requests: list[DocumentSectionRequest] = []
        for chunk_request in chunk_requests:
            generic_chunk_requests.append(
                DocumentSectionRequest(
                    document_id=chunk_request.document_id,
                    min_chunk_ind=chunk_request.min_chunk_ind,
                    max_chunk_ind=chunk_request.max_chunk_ind,
                )
            )
        return vespa_document_index.id_based_retrieval(
            chunk_requests=generic_chunk_requests,
            filters=filters,
            batch_retrieval=batch_retrieval,
        )

    @log_function_time(print_only=True, debug_only=True)
    def hybrid_retrieval(
        self,
        query: str,
        query_embedding: Embedding,
        final_keywords: list[str] | None,
        filters: IndexFilters,
        hybrid_alpha: float,
        time_decay_multiplier: float,
        num_to_retrieve: int,
        ranking_profile_type: QueryExpansionType = QueryExpansionType.SEMANTIC,
        offset: int = 0,
        title_content_ratio: float | None = TITLE_CONTENT_RATIO,
    ) -> list[InferenceChunk]:
        tenant_id = filters.tenant_id if filters.tenant_id is not None else ""
        vespa_document_index = VespaDocumentIndex(
            index_name=self.index_name,
            tenant_state=TenantState(
                tenant_id=tenant_id,
                multitenant=self.multitenant,
            ),
            large_chunks_enabled=self.large_chunks_enabled,
            httpx_client=self.httpx_client,
        )
        if not (
            ranking_profile_type == QueryExpansionType.KEYWORD
            or ranking_profile_type == QueryExpansionType.SEMANTIC
        ):
            raise ValueError(
                f"Bug: Received invalid ranking profile type: {ranking_profile_type}"
            )
        query_type = (
            QueryType.KEYWORD
            if ranking_profile_type == QueryExpansionType.KEYWORD
            else QueryType.SEMANTIC
        )
        return vespa_document_index.hybrid_retrieval(
            query,
            query_embedding,
            final_keywords,
            query_type,
            filters,
            num_to_retrieve,
            offset,
        )

    def admin_retrieval(
        self,
        query: str,
        filters: IndexFilters,
        num_to_retrieve: int = NUM_RETURNED_HITS,
        offset: int = 0,
    ) -> list[InferenceChunk]:
        vespa_where_clauses = build_vespa_filters(filters, include_hidden=True)
        yql = (
            YQL_BASE.format(index_name=self.index_name)
            + vespa_where_clauses
            + '({grammar: "weakAnd"}userInput(@query) '
            # `({defaultIndex: "content_summary"}userInput(@query))` section is
            # needed for highlighting while the N-gram highlighting is broken /
            # not working as desired
            + f'or ({{defaultIndex: "{CONTENT_SUMMARY}"}}userInput(@query)))'
        )

        params: dict[str, str | int] = {
            "yql": yql,
            "query": query,
            "hits": num_to_retrieve,
            "offset": 0,
            "ranking.profile": "admin_search",
            "timeout": VESPA_TIMEOUT,
        }

        return cleanup_chunks(query_vespa(params))

    # Retrieves chunk information for a document:
    # - Determines the last indexed chunk
    # - Identifies if the document uses the old or new chunk ID system
    # This data is crucial for Vespa document updates without relying on the visit API.
    @classmethod
    def enrich_basic_chunk_info(
        cls,
        index_name: str,
        http_client: httpx.Client,
        document_id: str,
        previous_chunk_count: int | None = None,
        new_chunk_count: int = 0,
    ) -> EnrichedDocumentIndexingInfo:
        last_indexed_chunk = previous_chunk_count

        # If the document has no `chunk_count` in the database, we know that it
        # has the old chunk ID system and we must check for the final chunk index
        is_old_version = False
        if last_indexed_chunk is None:
            is_old_version = True
            minimal_doc_info = MinimalDocumentIndexingInfo(
                doc_id=document_id, chunk_start_index=new_chunk_count
            )
            last_indexed_chunk = check_for_final_chunk_existence(
                minimal_doc_info=minimal_doc_info,
                start_index=new_chunk_count,
                index_name=index_name,
                http_client=http_client,
            )

        enriched_doc_info = EnrichedDocumentIndexingInfo(
            doc_id=document_id,
            chunk_start_index=new_chunk_count,
            chunk_end_index=last_indexed_chunk,
            old_version=is_old_version,
        )
        return enriched_doc_info

    @classmethod
    def delete_entries_by_tenant_id(
        cls,
        *,
        tenant_id: str,
        index_name: str,
    ) -> int:
        """
        Deletes all entries in the specified index with the given tenant_id.

        Currently unused, but we anticipate this being useful. The entire flow does not
        use the httpx connection pool of an instance.

        Parameters:
            tenant_id (str): The tenant ID whose documents are to be deleted.
            index_name (str): The name of the index from which to delete documents.

        Returns:
            int: The number of documents deleted.
        """
        logger.info(
            f"Deleting entries with tenant_id: {tenant_id} from index: {index_name}"
        )

        # Step 1: Retrieve all document IDs with the given tenant_id
        document_ids = cls._get_all_document_ids_by_tenant_id(tenant_id, index_name)

        if not document_ids:
            logger.info(
                f"No documents found with tenant_id: {tenant_id} in index: {index_name}"
            )
            return 0

        # Step 2: Delete documents in batches
        delete_requests = [
            _VespaDeleteRequest(document_id=doc_id, index_name=index_name)
            for doc_id in document_ids
        ]

        cls._apply_deletes_batched(delete_requests)
        return len(document_ids)

    @classmethod
    def _get_all_document_ids_by_tenant_id(
        cls, tenant_id: str, index_name: str
    ) -> List[str]:
        """
        Retrieves all document IDs with the specified tenant_id, handling pagination.

        Internal helper function for delete_entries_by_tenant_id.

        Parameters:
            tenant_id (str): The tenant ID to search for.
            index_name (str): The name of the index to search in.

        Returns:
            List[str]: A list of document IDs matching the tenant_id.
        """
        offset = 0
        limit = 1000  # Vespa's maximum hits per query
        document_ids = []

        logger.debug(
            f"Starting document ID retrieval for tenant_id: {tenant_id} in index: {index_name}"
        )

        while True:
            # Construct the query to fetch document IDs
            query_params = {
                "yql": f'select id from sources * where tenant_id contains "{tenant_id}";',
                "offset": str(offset),
                "hits": str(limit),
                "timeout": "10s",
                "format": "json",
                "summary": "id",
            }

            url = f"{VESPA_APPLICATION_ENDPOINT}/search/"

            logger.debug(
                f"Querying for document IDs with tenant_id: {tenant_id}, offset: {offset}"
            )

            with get_vespa_http_client() as http_client:
                response = http_client.get(url, params=query_params, timeout=None)
                response.raise_for_status()

                search_result = response.json()
                hits = search_result.get("root", {}).get("children", [])

                if not hits:
                    break

                for hit in hits:
                    doc_id = hit.get("id")
                    if doc_id:
                        document_ids.append(doc_id)

                offset += limit  # Move to the next page

        logger.debug(
            f"Retrieved {len(document_ids)} document IDs for tenant_id: {tenant_id}"
        )
        return document_ids

    @classmethod
    def _apply_deletes_batched(
        cls,
        delete_requests: List["_VespaDeleteRequest"],
        batch_size: int = BATCH_SIZE,
    ) -> None:
        """
        Deletes documents in batches using multiple threads.

        Internal helper function for delete_entries_by_tenant_id.

        This is a class method and does not use the httpx pool of the instance.
        This is OK because we don't use this method often.

        Parameters:
            delete_requests (List[_VespaDeleteRequest]): The list of delete requests.
            batch_size (int): The number of documents to delete in each batch.
        """

        def _delete_document(
            delete_request: "_VespaDeleteRequest", http_client: httpx.Client
        ) -> None:
            logger.debug(f"Deleting document with ID {delete_request.document_id}")
            response = http_client.delete(
                delete_request.url,
                headers={"Content-Type": "application/json"},
                timeout=None,
            )
            response.raise_for_status()

        logger.debug(f"Starting batch deletion for {len(delete_requests)} documents")

        with concurrent.futures.ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
            with get_vespa_http_client() as http_client:
                for batch_start in range(0, len(delete_requests), batch_size):
                    batch = delete_requests[batch_start : batch_start + batch_size]

                    future_to_document_id = {
                        executor.submit(
                            _delete_document,
                            delete_request,
                            http_client,
                        ): delete_request.document_id
                        for delete_request in batch
                    }

                    for future in concurrent.futures.as_completed(
                        future_to_document_id
                    ):
                        doc_id = future_to_document_id[future]
                        try:
                            future.result()
                            logger.debug(f"Successfully deleted document: {doc_id}")
                        except httpx.HTTPError as e:
                            logger.error(f"Failed to delete document {doc_id}: {e}")
                            # Optionally, implement retry logic or error handling here

        logger.info("Batch deletion completed")

    def random_retrieval(
        self,
        filters: IndexFilters,
        num_to_retrieve: int = 10,
    ) -> list[InferenceChunk]:
        """Retrieve random chunks matching the filters using Vespa's random ranking

        This method is currently used for random chunk retrieval in the context of
        assistant starter message creation (passed as sample context for usage by the assistant).
        """
        tenant_id = filters.tenant_id if filters.tenant_id is not None else ""
        vespa_document_index = VespaDocumentIndex(
            index_name=self.index_name,
            tenant_state=TenantState(
                tenant_id=tenant_id,
                multitenant=self.multitenant,
            ),
            large_chunks_enabled=self.large_chunks_enabled,
            httpx_client=self.httpx_client,
        )
        return vespa_document_index.random_retrieval(
            filters=filters,
            num_to_retrieve=num_to_retrieve,
        )


class _VespaDeleteRequest:
    def __init__(self, document_id: str, index_name: str) -> None:
        self.document_id = document_id
        # Encode the document ID to ensure it's safe for use in the URL
        encoded_doc_id = urllib.parse.quote_plus(self.document_id)
        self.url = (
            f"{VESPA_APPLICATION_ENDPOINT}/document/v1/"
            f"{index_name}/{index_name}/docid/{encoded_doc_id}"
        )
