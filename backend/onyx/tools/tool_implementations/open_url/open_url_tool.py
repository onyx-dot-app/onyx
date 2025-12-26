import json
from collections import defaultdict
from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing_extensions import override

from onyx.chat.emitter import Emitter
from onyx.context.search.models import IndexFilters
from onyx.context.search.models import InferenceSection
from onyx.context.search.models import SearchDocsResponse
from onyx.context.search.preprocessing.access_filters import (
    build_access_filters_for_user,
)
from onyx.context.search.utils import convert_inference_sections_to_search_docs
from onyx.context.search.utils import inference_section_from_chunks
from onyx.db.document import filter_existing_document_ids
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import User
from onyx.document_index.interfaces import DocumentIndex
from onyx.document_index.interfaces import VespaChunkRequest
from onyx.server.query_and_chat.streaming_models import OpenUrlDocuments
from onyx.server.query_and_chat.streaming_models import OpenUrlStart
from onyx.server.query_and_chat.streaming_models import OpenUrlUrls
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.tools.models import OpenURLToolOverrideKwargs
from onyx.tools.models import ToolResponse
from onyx.tools.tool import Tool
from onyx.tools.tool_implementations.open_url.models import WebContentProvider
from onyx.tools.tool_implementations.open_url.url_normalization import (
    _default_url_normalizer,
)
from onyx.tools.tool_implementations.open_url.url_normalization import normalize_url
from onyx.tools.tool_implementations.web_search.providers import (
    get_default_content_provider,
)
from onyx.tools.tool_implementations.web_search.utils import (
    inference_section_from_internet_page_scrape,
)
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

URLS_FIELD = "urls"


class IndexedDocumentRequest(BaseModel):
    document_id: str
    original_url: str | None = None


class IndexedRetrievalResult(BaseModel):
    sections: list[InferenceSection]
    missing_document_ids: list[str]


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _normalize_string_list(value: str | list[str] | None) -> list[str]:
    """Normalize a value that may be a string, list of strings, or None into a cleaned list.

    Returns a deduplicated list of non-empty stripped strings.
    """
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    return _dedupe_preserve_order(
        [stripped for item in value if (stripped := str(item).strip())]
    )


def _url_lookup_variants(url: str) -> set[str]:
    """Generate URL variants (with/without trailing slash) for database lookup.

    This is used after normalize_url() to create variants for fuzzy matching
    in the database, since URLs may be stored with or without trailing slashes.
    """
    # Use default normalizer to strip query/fragment, then create variants
    normalized = _default_url_normalizer(url)
    if not normalized:
        return set()
    variants = {normalized}
    if normalized.endswith("/"):
        variants.add(normalized.rstrip("/"))
    else:
        variants.add(f"{normalized}/")
    return {variant for variant in variants if variant}


def _convert_sections_to_llm_string_with_citations(
    sections: list[InferenceSection],
    existing_citation_mapping: dict[str, int],
    citation_start: int,
) -> tuple[str, dict[int, str]]:
    """Convert InferenceSections to LLM string, reusing existing citations where available.

    Args:
        sections: List of InferenceSection objects to convert.
        existing_citation_mapping: Mapping of document_id -> citation_num for
            documents that have already been cited.
        citation_start: Starting citation number for new citations.

    Returns:
        Tuple of (JSON string for LLM, citation_mapping dict).
        The citation_mapping maps citation_id -> document_id.
    """
    # Build document_id to citation_id mapping, reusing existing citations
    document_id_to_citation_id: dict[str, int] = {}
    citation_mapping: dict[int, str] = {}
    next_citation_id = citation_start

    # First pass: assign citation_ids, reusing existing ones where available
    for section in sections:
        document_id = section.center_chunk.document_id
        if document_id in document_id_to_citation_id:
            # Already assigned in this batch
            continue

        if document_id in existing_citation_mapping:
            # Reuse existing citation number
            citation_id = existing_citation_mapping[document_id]
            document_id_to_citation_id[document_id] = citation_id
            citation_mapping[citation_id] = document_id
        else:
            # Assign new citation number
            document_id_to_citation_id[document_id] = next_citation_id
            citation_mapping[next_citation_id] = document_id
            next_citation_id += 1

    # Second pass: build results
    results = []
    for section in sections:
        chunk = section.center_chunk
        document_id = chunk.document_id
        citation_id = document_id_to_citation_id[document_id]

        # Format updated_at as ISO string if available
        updated_at_str = None
        if chunk.updated_at:
            updated_at_str = chunk.updated_at.isoformat()

        result: dict[str, Any] = {
            "document": citation_id,
            "title": chunk.semantic_identifier,
        }
        if updated_at_str is not None:
            result["updated_at"] = updated_at_str
        result["source_type"] = chunk.source_type.value
        if chunk.source_links:
            link = next(iter(chunk.source_links.values()), None)
            if link:
                result["url"] = link
        result["document_identifier"] = document_id
        if chunk.metadata:
            result["metadata"] = json.dumps(chunk.metadata)
        result["content"] = section.combined_content

        results.append(result)

    output = {"results": results}
    return json.dumps(output, indent=2), citation_mapping


class OpenURLTool(Tool[OpenURLToolOverrideKwargs]):
    NAME = "open_url"
    DESCRIPTION = (
        "Open and read the full content of URLs or document identifiers. "
        "Use this tool when: (1) Search results mention a document but don't include its full content, "
        "(2) You need to read a specific document that was referenced but not fully retrieved, "
        "(3) Search returned incomplete or truncated content for a document. "
        "This tool retrieves the complete document content, either from indexed storage or by crawling the URL."
    )
    DISPLAY_NAME = "Open URL"

    def __init__(
        self,
        tool_id: int,
        emitter: Emitter,
        db_session: Session,
        document_index: DocumentIndex,
        user: User | None,
        project_id: int | None = None,
        content_provider: WebContentProvider | None = None,
    ) -> None:
        """Initialize the OpenURLTool.

        Args:
            tool_id: Unique identifier for this tool instance.
            emitter: Emitter for streaming packets to the client.
            db_session: Session for database lookups / ACL checks.
            document_index: Index handle for retrieving stored documents.
            user: User context for ACL filtering.
            project_id: Optional project scope for filters.
            content_provider: Optional content provider. If not provided,
                will use the default provider from the database or fall back
                to the built-in Onyx web crawler.
        """
        super().__init__(emitter=emitter)
        self._id = tool_id
        self._document_index = document_index
        self._user = user
        self._project_id = project_id

        if content_provider is not None:
            self._provider = content_provider
        else:
            provider = get_default_content_provider()
            if provider is None:
                raise RuntimeError(
                    "No web content provider available. "
                    "Please configure a content provider or ensure the "
                    "built-in Onyx web crawler can be initialized."
                )
            self._provider = provider

    @property
    def id(self) -> int:
        return self._id

    @property
    def name(self) -> str:
        return self.NAME

    @property
    def description(self) -> str:
        return self.DESCRIPTION

    @property
    def display_name(self) -> str:
        return self.DISPLAY_NAME

    @override
    @classmethod
    def is_available(cls, db_session: Session) -> bool:
        """OpenURLTool is always available since it falls back to built-in crawler."""
        # The tool can use either a configured provider or the built-in crawler,
        # so it's always available
        return True

    def tool_definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": (
                    "Open and read the full content of URLs or document identifiers. "
                    "IMPORTANT: Use this tool when search results reference documents but don't include their full content, "
                    "or when you need complete information from a specific document. "
                    "This tool retrieves complete document content, either from indexed storage or by crawling the URL. "
                    "Returns the full text content of the pages."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        URLS_FIELD: {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "List of URLs or document identifiers to open and read. "
                                "Can be a single URL/identifier or multiple. "
                                "Accepts: (1) Raw URLs (e.g., 'https://docs.google.com/document/d/123/edit'), "
                                "(2) Normalized document IDs from search results "
                                "(e.g., 'https://docs.google.com/document/d/123'), "
                                "or (3) Non-URL document identifiers for file connectors "
                                "(e.g., 'FILE_CONNECTOR__abc-123'). "
                                "Use the 'document_identifier' field from search results when 'url' is not available. "
                                "You can extract URLs or document_identifier values from search results "
                                "to read those documents in full."
                            ),
                        },
                    },
                    "required": [],
                },
            },
        }

    def emit_start(self, turn_index: int) -> None:
        """Emit start packet to signal tool has started."""
        self.emitter.emit(
            Packet(
                turn_index=turn_index,
                obj=OpenUrlStart(),
            )
        )

    def run(
        self,
        turn_index: int,
        override_kwargs: OpenURLToolOverrideKwargs,
        **llm_kwargs: Any,
    ) -> ToolResponse:
        """Execute the OpenURL tool using document identifiers when possible."""
        urls = _normalize_string_list(llm_kwargs.get(URLS_FIELD))

        if not urls:
            raise ValueError("OpenURL requires at least one URL to run.")

        self.emitter.emit(
            Packet(
                turn_index=turn_index,
                obj=OpenUrlUrls(urls=urls),
            )
        )

        logger.info(f"OpenURL tool called with {len(urls)} URLs")

        with get_session_with_current_tenant() as db_session:
            # Resolve URLs to document IDs for indexed retrieval
            # Handles both raw URLs and already-normalized document IDs
            url_requests, _ = OpenURLTool._resolve_urls_to_document_ids(
                urls, db_session
            )
            logger.info(
                f"Resolved {len(url_requests)} URLs to indexed document IDs for parallel retrieval"
            )

            all_requests = OpenURLTool._dedupe_document_requests(url_requests)
            logger.info(f"Total unique document requests: {len(all_requests)}")

            # Create mapping from URL to document_id for result merging
            url_to_doc_id: dict[str, str] = {}
            for request in url_requests:
                if request.original_url:
                    url_to_doc_id[request.original_url] = request.document_id

            # Build filters before parallel execution (session-safe)
            filters = self._build_index_filters(db_session)

            # Create wrapper function for parallel execution
            # Filters are already built, so we just need to pass them
            def _retrieve_indexed_with_filters(
                requests: list[IndexedDocumentRequest],
            ) -> IndexedRetrievalResult:
                """Wrapper for parallel execution with pre-built filters."""
                return self._retrieve_indexed_documents_with_filters(requests, filters)

            # Run indexed retrieval and crawling in parallel for all URLs
            # This allows us to compare results and pick the best representation
            indexed_result, crawled_result = run_functions_tuples_in_parallel(
                [
                    (_retrieve_indexed_with_filters, (all_requests,)),
                    (self._fetch_web_content, (urls,)),
                ],
                allow_failures=True,
            )

            indexed_result = indexed_result or IndexedRetrievalResult(
                sections=[], missing_document_ids=[]
            )
            crawled_sections, failed_web_urls = crawled_result or ([], [])

            # Merge results: prefer indexed when available, fallback to crawled
            inference_sections = self._merge_indexed_and_crawled_results(
                indexed_result.sections,
                crawled_sections,
                url_to_doc_id,
                urls,
                failed_web_urls,
            )

        if not inference_sections:
            failure_descriptions = []
            if indexed_result.missing_document_ids:
                failure_descriptions.append(
                    "documents "
                    + ", ".join(sorted(set(indexed_result.missing_document_ids)))
                )
            if failed_web_urls:
                cleaned_failures = sorted({url for url in failed_web_urls if url})
                if cleaned_failures:
                    failure_descriptions.append("URLs " + ", ".join(cleaned_failures))
            failure_msg = (
                "Failed to fetch content from " + " and ".join(failure_descriptions)
                if failure_descriptions
                else "Failed to fetch content from the requested resources."
            )
            return ToolResponse(rich_response=None, llm_facing_response=failure_msg)

        # Convert sections to search docs, preserving source information
        search_docs = convert_inference_sections_to_search_docs(
            inference_sections, is_internet=False
        )

        self.emitter.emit(
            Packet(
                turn_index=turn_index,
                obj=OpenUrlDocuments(documents=search_docs),
            )
        )

        docs_str, citation_mapping = _convert_sections_to_llm_string_with_citations(
            sections=inference_sections,
            existing_citation_mapping=override_kwargs.citation_mapping,
            citation_start=override_kwargs.starting_citation_num,
        )

        return ToolResponse(
            rich_response=SearchDocsResponse(
                search_docs=search_docs,
                citation_mapping=citation_mapping,
            ),
            llm_facing_response=docs_str,
        )

    @staticmethod
    def _dedupe_document_requests(
        requests: list[IndexedDocumentRequest],
    ) -> list[IndexedDocumentRequest]:
        seen: set[str] = set()
        deduped: list[IndexedDocumentRequest] = []
        for request in requests:
            if request.document_id in seen:
                continue
            seen.add(request.document_id)
            deduped.append(request)
        return deduped

    @staticmethod
    def _resolve_urls_to_document_ids(
        urls: list[str], db_session: Session
    ) -> tuple[list[IndexedDocumentRequest], list[str]]:
        """Resolve URLs to document IDs using connector-owned normalization.

        Uses the url_normalization module which delegates to each connector's
        own normalization function to ensure URLs match the canonical Document.id
        format used during ingestion.
        """
        matches: list[IndexedDocumentRequest] = []
        unresolved: list[str] = []
        normalized_map: dict[str, set[str]] = {}

        for url in urls:
            # Use connector-owned normalization (reuses connector's own logic)
            normalized = normalize_url(url)

            if normalized:
                # Get URL variants (with/without trailing slash) for database lookup
                variants = _url_lookup_variants(normalized)
                if variants:
                    normalized_map[url] = variants
                else:
                    unresolved.append(url)
            else:
                # No normalizer found - could be a non-URL document ID (e.g., FILE_CONNECTOR__...)
                if url and not url.startswith(("http://", "https://")):
                    # Likely a document ID, use it directly
                    normalized_map[url] = {url}
                else:
                    # Try generic normalization as fallback
                    variants = _url_lookup_variants(url)
                    if variants:
                        normalized_map[url] = variants
                    else:
                        unresolved.append(url)

        if not normalized_map:
            return matches, unresolved

        # Query database with all normalized variants
        all_variants = {
            variant for variants in normalized_map.values() for variant in variants
        }
        existing_document_ids = filter_existing_document_ids(
            db_session, list(all_variants)
        )

        # Match URLs to documents
        for url, variants in normalized_map.items():
            matched_doc_id = next(
                (variant for variant in variants if variant in existing_document_ids),
                None,
            )
            if matched_doc_id:
                matches.append(
                    IndexedDocumentRequest(
                        document_id=matched_doc_id,
                        original_url=url,
                    )
                )
            else:
                unresolved.append(url)

        return matches, unresolved

    def _retrieve_indexed_documents_with_filters(
        self,
        all_requests: list[IndexedDocumentRequest],
        filters: IndexFilters,
    ) -> IndexedRetrievalResult:
        """Retrieve indexed documents using pre-built filters (for parallel execution)."""
        if not all_requests:
            return IndexedRetrievalResult(sections=[], missing_document_ids=[])

        document_ids = [req.document_id for req in all_requests]
        logger.info(
            f"Retrieving {len(all_requests)} indexed documents from Vespa. "
            f"Document IDs: {document_ids}"
        )
        chunk_requests = [
            VespaChunkRequest(document_id=request.document_id)
            for request in all_requests
        ]

        try:
            chunks = self._document_index.id_based_retrieval(
                chunk_requests=chunk_requests,
                filters=filters,
                batch_retrieval=True,
            )
            logger.info(
                f"Retrieved {len(chunks)} chunks from Vespa for {len(all_requests)} document requests"
            )
        except Exception as exc:
            logger.warning(
                f"Indexed retrieval failed for document IDs {document_ids}: {exc}",
                exc_info=True,
            )
            return IndexedRetrievalResult(
                sections=[],
                missing_document_ids=[req.document_id for req in all_requests],
            )

        chunk_map: dict[str, list] = defaultdict(list)
        for chunk in chunks:
            chunk_map[chunk.document_id].append(chunk)

        sections: list[InferenceSection] = []
        missing: list[str] = []

        for request in all_requests:
            doc_chunks = chunk_map.get(request.document_id)
            if not doc_chunks:
                logger.warning(
                    f"No chunks found in Vespa for document_id: {request.document_id} "
                    f"(original_url: {request.original_url})"
                )
                missing.append(request.document_id)
                continue
            logger.info(
                f"Found {len(doc_chunks)} chunks for document_id: {request.document_id} "
                f"(original_url: {request.original_url})"
            )
            doc_chunks.sort(key=lambda chunk: chunk.chunk_id)
            section = inference_section_from_chunks(
                center_chunk=doc_chunks[0],
                chunks=doc_chunks,
            )
            if section:
                sections.append(section)
            else:
                logger.warning(
                    f"Failed to create InferenceSection from chunks for document_id: {request.document_id}"
                )
                missing.append(request.document_id)

        logger.info(
            f"Retrieved {len(sections)} documents successfully, {len(missing)} missing. "
            f"Missing document IDs: {missing}"
        )
        return IndexedRetrievalResult(sections=sections, missing_document_ids=missing)

    def _build_index_filters(self, db_session: Session) -> IndexFilters:
        access_control_list = build_access_filters_for_user(self._user, db_session)
        return IndexFilters(
            source_type=None,
            document_set=None,
            time_cutoff=None,
            tags=None,
            access_control_list=access_control_list,
            tenant_id=get_current_tenant_id() if MULTI_TENANT else None,
            user_file_ids=None,
            project_id=self._project_id,
        )

    def _merge_indexed_and_crawled_results(
        self,
        indexed_sections: list[InferenceSection],
        crawled_sections: list[InferenceSection],
        url_to_doc_id: dict[str, str],
        all_urls: list[str],
        failed_web_urls: list[str],
    ) -> list[InferenceSection]:
        """Merge indexed and crawled results, preferring indexed when available.

        For each URL:
        - If indexed result exists and has content, use it (better/cleaner representation)
        - Otherwise, use crawled result if available
        - If both fail, the URL will be in failed_web_urls for error reporting
        """
        # Map indexed sections by document_id
        indexed_by_doc_id: dict[str, InferenceSection] = {}
        for section in indexed_sections:
            indexed_by_doc_id[section.center_chunk.document_id] = section

        # Map crawled sections by URL (from source_links)
        crawled_by_url: dict[str, InferenceSection] = {}
        for section in crawled_sections:
            # Extract URL from source_links (crawled sections store URL here)
            if section.center_chunk.source_links:
                url = next(iter(section.center_chunk.source_links.values()))
                if url:
                    crawled_by_url[url] = section

        merged_sections: list[InferenceSection] = []
        used_doc_ids: set[str] = set()

        # Process URLs: prefer indexed, fallback to crawled
        for url in all_urls:
            doc_id = url_to_doc_id.get(url)
            indexed_section = indexed_by_doc_id.get(doc_id) if doc_id else None
            crawled_section = crawled_by_url.get(url)

            if indexed_section and indexed_section.combined_content:
                # Prefer indexed
                merged_sections.append(indexed_section)
                if doc_id:
                    used_doc_ids.add(doc_id)
                logger.debug(f"Using indexed content for URL: {url} (doc_id: {doc_id})")
            elif crawled_section and crawled_section.combined_content:
                # Fallback to crawled if indexed unavailable or empty
                # (e.g., auth issues, document not indexed, etc.)
                merged_sections.append(crawled_section)
                logger.debug(f"Using crawled content for URL: {url}")

        # Add any indexed sections that weren't matched to URLs
        for doc_id, section in indexed_by_doc_id.items():
            # Skip if this doc_id was already used for a URL
            if doc_id not in used_doc_ids:
                merged_sections.append(section)

        logger.info(
            f"Merged results: {len(merged_sections)} total sections "
            f"({len([s for s in merged_sections if s.center_chunk.document_id in indexed_by_doc_id])} indexed, "
            f"{len([s for s in merged_sections if s.center_chunk.document_id not in indexed_by_doc_id])} crawled)"
        )

        return merged_sections

    def _fetch_web_content(
        self, urls: list[str]
    ) -> tuple[list[InferenceSection], list[str]]:
        if not urls:
            return [], []

        web_contents = self._provider.contents(urls)
        sections: list[InferenceSection] = []
        failed_urls: list[str] = []

        for content in web_contents:
            if content.scrape_successful and content.full_content:
                sections.append(inference_section_from_internet_page_scrape(content))
            else:
                failed_urls.append(content.link or "")

        return sections, failed_urls
