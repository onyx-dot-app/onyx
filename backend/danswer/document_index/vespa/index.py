import concurrent.futures
import io
import os
import re
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from typing import BinaryIO
from typing import cast

import httpx
import requests

from danswer.configs.chat_configs import DOC_TIME_DECAY
from danswer.configs.chat_configs import NUM_RETURNED_HITS
from danswer.configs.chat_configs import TITLE_CONTENT_RATIO
from danswer.configs.constants import KV_REINDEX_KEY
from danswer.document_index.interfaces import DocumentIndex
from danswer.document_index.interfaces import DocumentInsertionRecord
from danswer.document_index.interfaces import UpdateRequest
from danswer.document_index.interfaces import VespaChunkRequest
from danswer.document_index.vespa.chunk_retrieval import batch_search_api_retrieval
from danswer.document_index.vespa.chunk_retrieval import (
    get_all_vespa_ids_for_document_id,
)
from danswer.document_index.vespa.chunk_retrieval import (
    parallel_visit_api_retrieval,
)
from danswer.document_index.vespa.chunk_retrieval import query_vespa
from danswer.document_index.vespa.deletion import delete_vespa_docs
from danswer.document_index.vespa.indexing_utils import batch_index_vespa_chunks
from danswer.document_index.vespa.indexing_utils import clean_chunk_id_copy
from danswer.document_index.vespa.indexing_utils import (
    get_existing_documents_from_chunks,
)
from danswer.document_index.vespa.shared_utils.utils import (
    replace_invalid_doc_id_characters,
)
from danswer.document_index.vespa.shared_utils.vespa_request_builders import (
    build_vespa_filters,
)
from danswer.document_index.vespa_constants import ACCESS_CONTROL_LIST
from danswer.document_index.vespa_constants import BATCH_SIZE
from danswer.document_index.vespa_constants import BOOST
from danswer.document_index.vespa_constants import CONTENT_SUMMARY
from danswer.document_index.vespa_constants import DANSWER_CHUNK_REPLACEMENT_PAT
from danswer.document_index.vespa_constants import DATE_REPLACEMENT
from danswer.document_index.vespa_constants import DOCUMENT_ID_ENDPOINT
from danswer.document_index.vespa_constants import DOCUMENT_REPLACEMENT_PAT
from danswer.document_index.vespa_constants import DOCUMENT_SETS
from danswer.document_index.vespa_constants import HIDDEN
from danswer.document_index.vespa_constants import NUM_THREADS
from danswer.document_index.vespa_constants import VESPA_APPLICATION_ENDPOINT
from danswer.document_index.vespa_constants import VESPA_DIM_REPLACEMENT_PAT
from danswer.document_index.vespa_constants import VESPA_TIMEOUT
from danswer.document_index.vespa_constants import YQL_BASE
from danswer.dynamic_configs.factory import get_dynamic_config_store
from danswer.indexing.models import DocMetadataAwareIndexChunk
from danswer.search.models import IndexFilters
from danswer.search.models import InferenceChunkUncleaned
from danswer.utils.batching import batch_generator
from danswer.utils.logger import setup_logger
from shared_configs.model_server_models import Embedding

logger = setup_logger()


@dataclass
class _VespaUpdateRequest:
    document_id: str
    url: str
    update_request: dict[str, dict]


def in_memory_zip_from_file_bytes(file_contents: dict[str, bytes]) -> BinaryIO:
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
        for filename, content in file_contents.items():
            zipf.writestr(filename, content)
    zip_buffer.seek(0)
    return zip_buffer


def _create_document_xml_lines(doc_names: list[str | None]) -> str:
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


class VespaIndex(DocumentIndex):
    def __init__(self, index_name: str, secondary_index_name: str | None) -> None:
        self.index_name = index_name
        self.secondary_index_name = secondary_index_name

    def ensure_indices_exist(
        self,
        index_embedding_dim: int,
        secondary_index_embedding_dim: int | None,
    ) -> None:
        deploy_url = f"{VESPA_APPLICATION_ENDPOINT}/tenant/default/prepareandactivate"
        logger.debug(f"Sending Vespa zip to {deploy_url}")

        vespa_schema_path = os.path.join(
            os.getcwd(), "danswer", "document_index", "vespa", "app_config"
        )
        schema_file = os.path.join(vespa_schema_path, "schemas", "danswer_chunk.sd")
        services_file = os.path.join(vespa_schema_path, "services.xml")
        overrides_file = os.path.join(vespa_schema_path, "validation-overrides.xml")

        with open(services_file, "r") as services_f:
            services_template = services_f.read()

        schema_names = [self.index_name, self.secondary_index_name]

        doc_lines = _create_document_xml_lines(schema_names)
        services = services_template.replace(DOCUMENT_REPLACEMENT_PAT, doc_lines)
        kv_store = get_dynamic_config_store()

        needs_reindexing = False
        try:
            needs_reindexing = cast(bool, kv_store.load(KV_REINDEX_KEY))
        except Exception:
            logger.debug("Could not load the reindexing flag. Using ngrams")

        with open(overrides_file, "r") as overrides_f:
            overrides_template = overrides_f.read()

        # Vespa requires an override to erase data including the indices we're no longer using
        # It also has a 30 day cap from current so we set it to 7 dynamically
        now = datetime.now()
        date_in_7_days = now + timedelta(days=7)
        formatted_date = date_in_7_days.strftime("%Y-%m-%d")

        overrides = overrides_template.replace(DATE_REPLACEMENT, formatted_date)

        zip_dict = {
            "services.xml": services.encode("utf-8"),
            "validation-overrides.xml": overrides.encode("utf-8"),
        }

        with open(schema_file, "r") as schema_f:
            schema_template = schema_f.read()
        schema = schema_template.replace(
            DANSWER_CHUNK_REPLACEMENT_PAT, self.index_name
        ).replace(VESPA_DIM_REPLACEMENT_PAT, str(index_embedding_dim))
        schema = add_ngrams_to_schema(schema) if needs_reindexing else schema
        zip_dict[f"schemas/{schema_names[0]}.sd"] = schema.encode("utf-8")

        if self.secondary_index_name:
            upcoming_schema = schema_template.replace(
                DANSWER_CHUNK_REPLACEMENT_PAT, self.secondary_index_name
            ).replace(VESPA_DIM_REPLACEMENT_PAT, str(secondary_index_embedding_dim))
            zip_dict[f"schemas/{schema_names[1]}.sd"] = upcoming_schema.encode("utf-8")

        zip_file = in_memory_zip_from_file_bytes(zip_dict)

        headers = {"Content-Type": "application/zip"}
        response = requests.post(deploy_url, headers=headers, data=zip_file)
        if response.status_code != 200:
            raise RuntimeError(
                f"Failed to prepare Vespa Danswer Index. Response: {response.text}"
            )

    def index(
        self,
        chunks: list[DocMetadataAwareIndexChunk],
    ) -> set[DocumentInsertionRecord]:
        """Receive a list of chunks from a batch of documents and index the chunks into Vespa along
        with updating the associated permissions. Assumes that a document will not be split into
        multiple chunk batches calling this function multiple times, otherwise only the last set of
        chunks will be kept"""
        # IMPORTANT: This must be done one index at a time, do not use secondary index here
        cleaned_chunks = [clean_chunk_id_copy(chunk) for chunk in chunks]

        existing_docs: set[str] = set()

        # NOTE: using `httpx` here since `requests` doesn't support HTTP2. This is beneficial for
        # indexing / updates / deletes since we have to make a large volume of requests.
        with (
            concurrent.futures.ThreadPoolExecutor(max_workers=NUM_THREADS) as executor,
            httpx.Client(http2=True) as http_client,
        ):
            # Check for existing documents, existing documents need to have all of their chunks deleted
            # prior to indexing as the document size (num chunks) may have shrunk
            first_chunks = [chunk for chunk in cleaned_chunks if chunk.chunk_id == 0]
            for chunk_batch in batch_generator(first_chunks, BATCH_SIZE):
                existing_docs.update(
                    get_existing_documents_from_chunks(
                        chunks=chunk_batch,
                        index_name=self.index_name,
                        http_client=http_client,
                        executor=executor,
                    )
                )

            for doc_id_batch in batch_generator(existing_docs, BATCH_SIZE):
                delete_vespa_docs(
                    document_ids=doc_id_batch,
                    index_name=self.index_name,
                    http_client=http_client,
                    executor=executor,
                )

            for chunk_batch in batch_generator(cleaned_chunks, BATCH_SIZE):
                batch_index_vespa_chunks(
                    chunks=chunk_batch,
                    index_name=self.index_name,
                    http_client=http_client,
                    executor=executor,
                )

        all_doc_ids = {chunk.source_document.id for chunk in cleaned_chunks}

        return {
            DocumentInsertionRecord(
                document_id=doc_id,
                already_existed=doc_id in existing_docs,
            )
            for doc_id in all_doc_ids
        }

    @staticmethod
    def _apply_updates_batched(
        updates: list[_VespaUpdateRequest],
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
            httpx.Client(http2=True) as http_client,
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

    def update(self, update_requests: list[UpdateRequest]) -> None:
        logger.info(f"Updating {len(update_requests)} documents in Vespa")

        # Handle Vespa character limitations
        # Mutating update_requests but it's not used later anyway
        for update_request in update_requests:
            update_request.document_ids = [
                replace_invalid_doc_id_characters(doc_id)
                for doc_id in update_request.document_ids
            ]

        update_start = time.monotonic()

        processed_updates_requests: list[_VespaUpdateRequest] = []
        all_doc_chunk_ids: dict[str, list[str]] = {}

        # Fetch all chunks for each document ahead of time
        index_names = [self.index_name]
        if self.secondary_index_name:
            index_names.append(self.secondary_index_name)

        chunk_id_start_time = time.monotonic()
        with concurrent.futures.ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
            future_to_doc_chunk_ids = {
                executor.submit(
                    get_all_vespa_ids_for_document_id,
                    document_id=document_id,
                    index_name=index_name,
                    filters=None,
                    get_large_chunks=True,
                ): (document_id, index_name)
                for index_name in index_names
                for update_request in update_requests
                for document_id in update_request.document_ids
            }
            for future in concurrent.futures.as_completed(future_to_doc_chunk_ids):
                document_id, index_name = future_to_doc_chunk_ids[future]
                try:
                    doc_chunk_ids = future.result()
                    if document_id not in all_doc_chunk_ids:
                        all_doc_chunk_ids[document_id] = []
                    all_doc_chunk_ids[document_id].extend(doc_chunk_ids)
                except Exception as e:
                    logger.error(
                        f"Error retrieving chunk IDs for document {document_id} in index {index_name}: {e}"
                    )
        logger.debug(
            f"Took {time.monotonic() - chunk_id_start_time:.2f} seconds to fetch all Vespa chunk IDs"
        )

        # Build the _VespaUpdateRequest objects
        for update_request in update_requests:
            update_dict: dict[str, dict] = {"fields": {}}
            if update_request.boost is not None:
                update_dict["fields"][BOOST] = {"assign": update_request.boost}
            if update_request.document_sets is not None:
                update_dict["fields"][DOCUMENT_SETS] = {
                    "assign": {
                        document_set: 1 for document_set in update_request.document_sets
                    }
                }
            if update_request.access is not None:
                update_dict["fields"][ACCESS_CONTROL_LIST] = {
                    "assign": {
                        acl_entry: 1 for acl_entry in update_request.access.to_acl()
                    }
                }
            if update_request.hidden is not None:
                update_dict["fields"][HIDDEN] = {"assign": update_request.hidden}

            if not update_dict["fields"]:
                logger.error("Update request received but nothing to update")
                continue

            for document_id in update_request.document_ids:
                for doc_chunk_id in all_doc_chunk_ids[document_id]:
                    processed_updates_requests.append(
                        _VespaUpdateRequest(
                            document_id=document_id,
                            url=f"{DOCUMENT_ID_ENDPOINT.format(index_name=self.index_name)}/{doc_chunk_id}",
                            update_request=update_dict,
                        )
                    )

        self._apply_updates_batched(processed_updates_requests)
        logger.debug(
            "Finished updating Vespa documents in %.2f seconds",
            time.monotonic() - update_start,
        )

    def delete(self, doc_ids: list[str]) -> None:
        logger.info(f"Deleting {len(doc_ids)} documents from Vespa")

        doc_ids = [replace_invalid_doc_id_characters(doc_id) for doc_id in doc_ids]

        # NOTE: using `httpx` here since `requests` doesn't support HTTP2. This is beneficial for
        # indexing / updates / deletes since we have to make a large volume of requests.
        with httpx.Client(http2=True) as http_client:
            index_names = [self.index_name]
            if self.secondary_index_name:
                index_names.append(self.secondary_index_name)

            for index_name in index_names:
                delete_vespa_docs(
                    document_ids=doc_ids, index_name=index_name, http_client=http_client
                )

    def id_based_retrieval(
        self,
        chunk_requests: list[VespaChunkRequest],
        filters: IndexFilters,
        batch_retrieval: bool = False,
        get_large_chunks: bool = False,
    ) -> list[InferenceChunkUncleaned]:
        if batch_retrieval:
            return batch_search_api_retrieval(
                index_name=self.index_name,
                chunk_requests=chunk_requests,
                filters=filters,
                get_large_chunks=get_large_chunks,
            )
        return parallel_visit_api_retrieval(
            index_name=self.index_name,
            chunk_requests=chunk_requests,
            filters=filters,
            get_large_chunks=get_large_chunks,
        )

    def hybrid_retrieval(
        self,
        query: str,
        query_embedding: Embedding,
        final_keywords: list[str] | None,
        filters: IndexFilters,
        hybrid_alpha: float,
        time_decay_multiplier: float,
        num_to_retrieve: int,
        offset: int = 0,
        title_content_ratio: float | None = TITLE_CONTENT_RATIO,
    ) -> list[InferenceChunkUncleaned]:
        vespa_where_clauses = build_vespa_filters(filters)
        # Needs to be at least as much as the value set in Vespa schema config
        target_hits = max(10 * num_to_retrieve, 1000)
        yql = (
            YQL_BASE.format(index_name=self.index_name)
            + vespa_where_clauses
            + f"(({{targetHits: {target_hits}}}nearestNeighbor(embeddings, query_embedding)) "
            + f"or ({{targetHits: {target_hits}}}nearestNeighbor(title_embedding, query_embedding)) "
            + 'or ({grammar: "weakAnd"}userInput(@query)) '
            + f'or ({{defaultIndex: "{CONTENT_SUMMARY}"}}userInput(@query)))'
        )

        final_query = " ".join(final_keywords) if final_keywords else query

        logger.debug(f"Query YQL: {yql}")

        params: dict[str, str | int | float] = {
            "yql": yql,
            "query": final_query,
            "input.query(query_embedding)": str(query_embedding),
            "input.query(decay_factor)": str(DOC_TIME_DECAY * time_decay_multiplier),
            "input.query(alpha)": hybrid_alpha,
            "input.query(title_content_ratio)": title_content_ratio
            if title_content_ratio is not None
            else TITLE_CONTENT_RATIO,
            "hits": num_to_retrieve,
            "offset": offset,
            "ranking.profile": f"hybrid_search{len(query_embedding)}",
            "timeout": VESPA_TIMEOUT,
        }

        return query_vespa(params)

    def admin_retrieval(
        self,
        query: str,
        filters: IndexFilters,
        num_to_retrieve: int = NUM_RETURNED_HITS,
        offset: int = 0,
    ) -> list[InferenceChunkUncleaned]:
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

        return query_vespa(params)
