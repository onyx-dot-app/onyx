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
from onyx.db.document import fetch_document_ids_by_links
from onyx.db.document import filter_existing_document_ids
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import User
from onyx.document_index.interfaces import DocumentIndex
from onyx.document_index.interfaces import VespaChunkRequest
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import OpenUrlDocuments
from onyx.server.query_and_chat.streaming_models import OpenUrlStart
from onyx.server.query_and_chat.streaming_models import OpenUrlUrls
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.tools.interface import Tool
from onyx.tools.models import OpenURLToolOverrideKwargs
from onyx.tools.models import ToolResponse
from onyx.tools.tool_implementations.open_url.models import WebContentProvider
from onyx.tools.tool_implementations.open_url.url_normalization import (
    _default_url_normalizer,
)
from onyx.tools.tool_implementations.open_url.url_normalization import normalize_url
from onyx.tools.tool_implementations.open_url.utils import (
    filter_web_contents_with_no_title_or_content,
)
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


def _lookup_document_ids_by_link(
    urls: list[str], db_session: Session
) -> list[IndexedDocumentRequest]:
    """Lookup document IDs by matching URLs against the Document.link column.

    This is used as a fallback when document ID resolution fails and URL scraping fails.
    Useful for connectors like Linear.
    """
    variant_to_original: dict[str, str] = {}
    for url in urls:
        if not url:
            continue
        # Generate URL variants (normalized, with/without trailing slash)
        variants = _url_lookup_variants(url)
        variants.add(url)
        # Map each variant back to the original URL
        for variant in variants:
            variant_to_original.setdefault(variant, url)

    if not variant_to_original:
        return []

    # Query database for documents matching any of the URL variants
    link_to_doc_id = fetch_document_ids_by_links(
        db_session, list(variant_to_original.keys())
    )

    requests: list[IndexedDocumentRequest] = []
    for link_value, doc_id in link_to_doc_id.items():
        original_url = variant_to_original.get(link_value)
        if original_url:
            requests.append(
                IndexedDocumentRequest(
                    document_id=doc_id,
                    original_url=original_url,
                )
            )
    return requests


def _dedupe_document_requests(
    requests: list[IndexedDocumentRequest],
) -> list[IndexedDocumentRequest]:
    """Remove duplicate document requests, preserving order."""
    seen: set[str] = set()
    deduped: list[IndexedDocumentRequest] = []
    for request in requests:
        if request.document_id in seen:
            continue
        seen.add(request.document_id)
        deduped.append(request)
    return deduped


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
    existing_document_ids = filter_existing_document_ids(db_session, list(all_variants))

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

        if "url" not in result:
            result["document_identifier"] = document_id

        if chunk.metadata:
            result["metadata"] = json.dumps(chunk.metadata)
        result["content"] = section.combined_content

        results.append(result)

    output = {"results": results}
    return json.dumps(output, indent=2), citation_mapping


class OpenURLTool(Tool[OpenURLToolOverrideKwargs]):
    NAME = "open_url"
    DESCRIPTION = "Open and read the content of one or more URLs."
    DISPLAY_NAME = "Open URL"

    def __init__(
        self,
        tool_id: int,
        emitter: Emitter,
        document_index: DocumentIndex,
        user: User | None,
        content_provider: WebContentProvider | None = None,
    ) -> None:
        """Initialize the OpenURLTool.

        Args:
            tool_id: Unique identifier for this tool instance.
            emitter: Emitter for streaming packets to the client.
            document_index: Index handle for retrieving stored documents.
            user: User context for ACL filtering.
            content_provider: Optional content provider. If not provided,
                will use the default provider from the database or fall back
                to the built-in Onyx web crawler.
        """
        super().__init__(emitter=emitter)
        self._id = tool_id
        self._document_index = document_index
        self._user = user

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
                "description": self.description,
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
                    "required": [URLS_FIELD],
                },
            },
        }

    def emit_start(self, placement: Placement) -> None:
        """Emit start packet to signal tool has started."""
        self.emitter.emit(
            Packet(
                placement=placement,
                obj=OpenUrlStart(),
            )
        )

    def run(
        self,
        placement: Placement,
        override_kwargs: OpenURLToolOverrideKwargs,
        **llm_kwargs: Any,
    ) -> ToolResponse:
        """Execute the open URL tool to fetch content from the specified URLs.

        Args:
            placement: The placement info (turn_index and tab_index) for this tool call.
            override_kwargs: Override arguments including starting citation number
                and existing citation_mapping to reuse citations for already-cited URLs.
            **llm_kwargs: Arguments provided by the LLM, including the 'urls' field.

        Returns:
                ToolResponse containing the fetched content and citation mapping.
        """
        urls = _normalize_string_list(llm_kwargs.get(URLS_FIELD))

        if not urls:
            raise ValueError("OpenURL requires at least one URL to run.")

        self.emitter.emit(
            Packet(
                placement=placement,
                obj=OpenUrlUrls(urls=urls),
            )
        )

        logger.info(f"OpenURL tool called with {len(urls)} URLs")

        with get_session_with_current_tenant() as db_session:
            # Resolve URLs to document IDs for indexed retrieval
            # Handles both raw URLs and already-normalized document IDs
            url_requests, unresolved_urls = _resolve_urls_to_document_ids(
                urls, db_session
            )
            logger.info(
                f"Resolved {len(url_requests)} URLs to indexed document IDs for parallel retrieval"
            )

            all_requests = _dedupe_document_requests(url_requests)
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

            # Last-resort: attempt link-based lookup for URLs that failed both
            # document-ID resolution and crawling.
            failed_web_urls = self._fallback_link_lookup(
                unresolved_urls=unresolved_urls,
                failed_web_urls=failed_web_urls,
                db_session=db_session,
                indexed_result=indexed_result,
                url_to_doc_id=url_to_doc_id,
                filters=filters,
            )

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

        for section in inference_sections:
            chunk = section.center_chunk
            if not chunk.semantic_identifier and chunk.source_links:
                chunk.semantic_identifier = chunk.source_links[0]

        # Convert sections to search docs, preserving source information
        search_docs = convert_inference_sections_to_search_docs(
            inference_sections, is_internet=False
        )

        self.emitter.emit(
            Packet(
                placement=placement,
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

    def _fallback_link_lookup(
        self,
        unresolved_urls: list[str],
        failed_web_urls: list[str],
        db_session: Session,
        indexed_result: IndexedRetrievalResult,
        url_to_doc_id: dict[str, str],
        filters: IndexFilters,
    ) -> list[str]:
        """Attempt link-based lookup for URLs that failed both document-ID resolution and crawling.

        Args:
            unresolved_urls: URLs that couldn't be resolved to document IDs
            failed_web_urls: URLs that failed crawling
            db_session: Database session
            indexed_result: Result object to update with found sections
            url_to_doc_id: Mapping to update with resolved URLs
            filters: Pre-built index filters for document retrieval

        Returns:
            Updated list of failed_web_urls (with resolved URLs removed)
        """
        if not unresolved_urls or not failed_web_urls:
            return failed_web_urls

        failed_set = {url for url in failed_web_urls if url}
        fallback_urls = sorted(set(unresolved_urls).intersection(failed_set))

        if not fallback_urls:
            return failed_web_urls

        logger.info(
            "Attempting link-based lookup for %d URLs that lacked "
            "document IDs and failed crawling",
            len(fallback_urls),
        )
        fallback_requests = _lookup_document_ids_by_link(fallback_urls, db_session)

        if not fallback_requests:
            return failed_web_urls

        deduped_fallback_requests = _dedupe_document_requests(fallback_requests)
        fallback_result = self._retrieve_indexed_documents_with_filters(
            deduped_fallback_requests, filters
        )

        if fallback_result.sections:
            indexed_result.sections.extend(fallback_result.sections)
            for request in deduped_fallback_requests:
                if request.original_url:
                    url_to_doc_id[request.original_url] = request.document_id

        if fallback_result.missing_document_ids:
            indexed_result.missing_document_ids.extend(
                fallback_result.missing_document_ids
            )

        resolved_links = {request.original_url for request in deduped_fallback_requests}
        return [url for url in failed_web_urls if url not in resolved_links]

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
            project_id=None,
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

        raw_web_contents = self._provider.contents(urls)
        # Treat "no title and no content" as a failure for that URL, but don't
        # include the empty entry in downstream prompting/sections.
        failed_urls: list[str] = [
            content.link
            for content in raw_web_contents
            if not content.title.strip() and not content.full_content.strip()
        ]
        web_contents = filter_web_contents_with_no_title_or_content(raw_web_contents)
        sections: list[InferenceSection] = []

        for content in web_contents:
            # Check if content is insufficient (e.g., "Loading..." or too short)
            text_stripped = content.full_content.strip()
            is_insufficient = (
                not text_stripped
                # TODO: Likely a behavior of our scraper, understand why this special pattern occurs
                or text_stripped.lower() == "loading..."
                or len(text_stripped) < 50
            )

            if (
                content.scrape_successful
                and content.full_content
                and not is_insufficient
            ):
                sections.append(inference_section_from_internet_page_scrape(content))
            else:
                # TODO: Slight improvement - if failed URL reasons are passed back to the LLM
                # for example, if it tries to crawl Reddit and fails, it should know (probably) that this error would
                # happen again if it tried to crawl Reddit again.
                failed_urls.append(content.link or "")

        return sections, failed_urls
