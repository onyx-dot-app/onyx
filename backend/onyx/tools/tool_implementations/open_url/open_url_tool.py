import json
import threading
from collections import defaultdict
from collections.abc import Callable, Mapping
from typing import Any, NamedTuple

from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing_extensions import override

from onyx.access.access import censor_chunks_for_user
from onyx.agents.tools import ToolInvocation, ToolProgress
from onyx.configs.app_configs import DISABLE_VECTOR_DB
from onyx.context.search.models import (
    IndexFilters,
    InferenceSection,
    SearchDocsResponse,
)
from onyx.context.search.preprocessing.access_filters import (
    build_access_filters_for_user,
)
from onyx.context.search.utils import (
    convert_inference_sections_to_search_docs,
    inference_section_from_chunks,
)
from onyx.db.document import fetch_document_ids_by_links, filter_existing_document_ids
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import User
from onyx.document_index.interfaces import DocumentIndex, DocumentSectionRequest
from onyx.llm.model_capabilities import ToolFamily
from onyx.llm.models import ToolDefinition, ToolResult
from onyx.prompts.tool_prompts import OPEN_URLS_GUIDANCE
from onyx.tools.constants import OPEN_URL_TOOL_NAME, WEB_FETCH_TOOL_NAME
from onyx.tools.interface import (
    CITATIONS_PER_TOOL_CALL,
    Tool,
    parse_tool_arguments,
    tool_definition_from_arguments,
)
from onyx.tools.models import (
    CodeModeExposure,
    CodeModeResultSpec,
    SearchResult,
    SearchResults,
    ToolContext,
)
from onyx.tools.ordering import ToolRank
from onyx.tools.tool_implementations.open_url.models import (
    FailedFetch,
    OpenURLArguments,
    WebContentProvider,
)
from onyx.tools.tool_implementations.open_url.url_normalization import (
    _default_url_normalizer,
    normalize_url_candidates,
)
from onyx.tools.tool_implementations.utils import SEARCH_RESULTS_CODE_MODE_RESULT
from onyx.tools.tool_implementations.web_search.providers import (
    get_default_content_provider,
)
from onyx.tools.tool_implementations.web_search.utils import (
    MAX_CHARS_PER_URL,
    TRUNCATED_CONTENT_PREFIX,
    TRUNCATED_CONTENT_SUFFIX,
    inference_section_from_internet_page_scrape,
    truncate_search_result_content,
)
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel
from onyx.utils.url import normalize_url as normalize_web_content_url
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

# 2 minute timeout for parallel URL fetching to prevent indefinite hangs
OPEN_URL_TIMEOUT_SECONDS = 2 * 60

# Sometimes the LLM will ask for a lot of URLs, so we need to limit the total number of characters
# otherwise this alone will completely flood the context and degrade experience.
# Note that if a lot of the URLs contain very little content, this results in no truncation.
MAX_CHARS_ACROSS_URLS = 10 * MAX_CHARS_PER_URL
# The full value of a call (ToolResult.full_value): this many characters of
# whole pages, plus the excerpts of later pages. A fetched page is cut to it
# too, since no call keeps more of one page.
OPEN_URL_MAX_CHARS = 2_000_000
# The same for a call from a code mode program: 200,000 characters of whole
# pages, plus the excerpts of later pages. The program holds its results in
# its 128 MB of memory: ten calls of CJK pages, about 3 bytes for each
# character, still let the program pause to wait for a tool.
OPEN_URL_PROGRAM_MAX_CHARS = 200_000

# Minimum content length to include a document (avoid tiny snippets)
# This is for truncation purposes, if a document is small (unless it goes into truncation flow),
# it still gets included normally.
MIN_CONTENT_CHARS = 200

# LLM-facing reason used when the chat disabled web access (Web Search off) and
# a URL couldn't be served from indexed documents.
WEB_FETCH_DISABLED_REASON = (
    "not fetched: web access is disabled for this conversation and this URL's "
    "content is not in the connected knowledge sources"
)


class IndexedDocumentRequest(BaseModel):
    document_id: str
    original_url: str | None = None


class IndexedRetrievalResult(BaseModel):
    sections: list[InferenceSection]
    missing_document_ids: list[str]


def _format_failed_url(failure: FailedFetch) -> str:
    """Format one failed URL for the LLM-facing failure message.

    With a reason: "https://x.com (blocked by a Cloudflare bot challenge ...)"
    Without:        "https://x.com"
    """
    if failure.failure_reason:
        return f"{failure.url} ({failure.failure_reason})"
    return failure.url


def _build_failure_message(
    *,
    missing_document_ids: list[str],
    failed_web_fetches: list[FailedFetch],
) -> str:
    """Construct the human-/LLM-readable failure message.

    Includes per-URL `failure_reason` strings so the LLM knows e.g. that a
    URL is bot-protected and shouldn't be re-tried verbatim.
    """
    parts: list[str] = []
    if missing_document_ids:
        parts.append("documents " + ", ".join(sorted(set(missing_document_ids))))

    cleaned_failures = [f for f in failed_web_fetches if f.url]
    if cleaned_failures:
        # Dedup by URL, prefer the first FailedFetch we see for each (which
        # already has the most-informative reason from `_mark_failed`).
        deduped: dict[str, FailedFetch] = {}
        for f in cleaned_failures:
            deduped.setdefault(f.url, f)
        ordered = sorted(deduped.values(), key=lambda f: f.url)
        parts.append("URLs " + ", ".join(_format_failed_url(f) for f in ordered))

    if not parts:
        return "Failed to fetch content from the requested resources."
    return "Failed to fetch content from " + " and ".join(parts)


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
    # Ordered by connector-defined candidate priority. Every indexed variant is
    # requested; the caller uses the first one that is readable.
    normalized_map: dict[str, list[str]] = {}

    for url in urls:
        # A single URL may map to several candidate document IDs; match whichever is indexed.
        candidates = normalize_url_candidates(url)

        if candidates:
            variants: list[str] = []
            for candidate in candidates:
                if candidate.startswith(("http://", "https://")):
                    candidate_variants = list(_url_lookup_variants(candidate)) or [
                        candidate
                    ]
                else:
                    # Non-URL canonical id (e.g. a Notion UUID); use it directly.
                    candidate_variants = [candidate]
                variants.extend(v for v in candidate_variants if v not in variants)
            normalized_map[url] = variants
        else:
            # No normalizer found - could be a non-URL document ID (e.g., FILE_CONNECTOR__...)
            if url and not url.startswith(("http://", "https://")):
                # Likely a document ID, use it directly
                normalized_map[url] = [url]
            else:
                # Try generic normalization as fallback
                fallback_variants = list(_url_lookup_variants(url))
                if fallback_variants:
                    normalized_map[url] = fallback_variants
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
        matched_doc_ids = [
            variant for variant in variants if variant in existing_document_ids
        ]
        if matched_doc_ids:
            matches.extend(
                IndexedDocumentRequest(document_id=doc_id, original_url=url)
                for doc_id in matched_doc_ids
            )
        else:
            unresolved.append(url)

    return matches, unresolved


def _pick_readable_document_ids(
    requests: list[IndexedDocumentRequest], readable_ids: set[str]
) -> dict[str, str]:
    """Map each original URL to its first candidate id the caller can read.

    Falls back to the URL's first candidate when none is readable.
    """
    picked: dict[str, str] = {}
    for request in requests:
        url = request.original_url
        if url is None:
            continue
        if url not in picked or (
            picked[url] not in readable_ids and request.document_id in readable_ids
        ):
            picked[url] = request.document_id
    return picked


def _estimate_result_chars(result: SearchResult) -> int:
    """Estimate character count from the document fields of a result."""
    return sum(
        len(str(value)) for value in result.model_dump(exclude_none=True).values()
    )


def _sections_to_search_results(
    sections: list[InferenceSection],
    existing_citation_mapping: dict[str, int],
    citation_start: int,
    max_document_chars: int = MAX_CHARS_ACROSS_URLS,
) -> tuple[SearchResults, dict[int, str]]:
    """Convert InferenceSections to the model's results, reusing existing citations where available.

    Args:
        sections: List of InferenceSection objects to convert.
        existing_citation_mapping: Mapping of document_id -> citation_num for
            documents that have already been cited.
        citation_start: Starting citation number for new citations.
        max_document_chars: Maximum total characters from document fields.
            Content is cut to fit within this budget, with
            TRUNCATED_CONTENT_SUFFIX; the documents after it are left out.

    Returns:
        Tuple of (the results, citation_mapping dict).
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

    # Second pass: build results, respecting max_document_chars budget
    results: list[SearchResult] = []
    total_chars = 0

    for section in sections:
        chunk = section.center_chunk
        # Built without content first to calculate the metadata overhead
        result = SearchResult(
            document=document_id_to_citation_id[chunk.document_id],
            title=chunk.semantic_identifier,
            updated_at=chunk.updated_at.isoformat() if chunk.updated_at else None,
            url=next(iter((chunk.source_links or {}).values()), None) or None,
            content="",
            metadata=json.dumps(chunk.metadata, ensure_ascii=False)
            if chunk.metadata
            else None,
        )

        # Calculate remaining budget for content
        remaining_budget = (
            max_document_chars - total_chars - _estimate_result_chars(result)
        )

        # Check if we have enough budget for meaningful content
        if remaining_budget < MIN_CONTENT_CHARS:
            # Not enough room for meaningful content, stop adding documents
            break

        # Truncate content if it exceeds remaining budget
        result.content = truncate_search_result_content(
            section.combined_content, remaining_budget
        )
        total_chars += _estimate_result_chars(result)
        results.append(result)

    return SearchResults(results=results), citation_mapping


MAX_URLS_PER_CALL = 10


class OpenedPage(NamedTuple):
    """A page that the call opened: its section, whose content is the
    model's excerpt, and its whole text."""

    section: InferenceSection
    text: str


class OpenURLShape(NamedTuple):
    """How one tool family names the URL reading tool; its arguments are the
    same in every shape."""

    name: str


OPEN_URL_SHAPES: Mapping[ToolFamily, OpenURLShape] = {
    ToolFamily.OPENAI: OpenURLShape(OPEN_URL_TOOL_NAME),
    # The name Claude models are trained on.
    ToolFamily.CLAUDE: OpenURLShape(WEB_FETCH_TOOL_NAME),
}
# The tool's names across the shapes and saved chats.
OPEN_URL_TOOL_NAMES = frozenset(shape.name for shape in OPEN_URL_SHAPES.values())


def _report_opened(
    invocation: ToolInvocation,
    sections: list[InferenceSection],
    opened_urls: list[str] | None = None,
) -> None:
    """Shows opened pages in the call's display, as soon as they open.
    `opened_urls` are the requested URLs these pages answer, so the display
    marks exactly those as opened."""
    if not sections:
        return
    for section in sections:
        chunk = section.center_chunk
        if not chunk.semantic_identifier and chunk.source_links:
            chunk.semantic_identifier = chunk.source_links[0]
    invocation.update(
        ToolProgress(
            details=SearchDocsResponse(
                search_docs=convert_inference_sections_to_search_docs(
                    sections, is_internet=False
                ),
                citation_mapping={},
                opened_urls=opened_urls or [],
            )
        )
    )


class OpenURLTool(Tool):
    rank = ToolRank.OPEN_URL
    merge_list_argument = "urls"
    merge_list_limit = MAX_URLS_PER_CALL

    SUMMARY = "Open and read the content of one or more URLs."
    SUMMARY_NO_WEB_FETCH = (
        "Open and read the content of one or more URLs. Web access is "
        "disabled for this conversation, so only URLs whose content already "
        "exists in the connected knowledge sources can be read — nothing is "
        "fetched from the live internet."
    )
    DESCRIPTION = f"{SUMMARY} {OPEN_URLS_GUIDANCE}"
    DESCRIPTION_NO_WEB_FETCH = f"{SUMMARY_NO_WEB_FETCH} {OPEN_URLS_GUIDANCE}"
    DISPLAY_NAME = "Open URL"

    def __init__(
        self,
        tool_id: int,
        document_index: DocumentIndex,
        user: User,
        content_provider: WebContentProvider | None = None,
        web_fetch_disabled: bool = False,
        *,
        shape: OpenURLShape,
    ) -> None:
        """Initialize the OpenURLTool.

        Args:
            shape: The model's tool family's shape (OPEN_URL_SHAPES), which
                names the tool. The tool row keeps the name open_url.
            tool_id: Unique identifier for this tool instance.
            document_index: Index handle for retrieving stored documents.
            user: User context for ACL filtering, anonymous users only see public docs.
            content_provider: Optional content provider. If not provided,
                will use the default provider from the database or fall back
                to the built-in Onyx web crawler.
            web_fetch_disabled: When True (e.g. the user turned Web Search off
                for the chat), URLs are only served from indexed documents —
                the live-crawl path is never used.
        """
        self._id = tool_id
        self.shape = shape
        self._document_index = document_index
        self._user = user
        self._web_fetch_disabled = web_fetch_disabled

        self._provider: WebContentProvider | None
        if content_provider is not None:
            self._provider = content_provider
        elif web_fetch_disabled:
            # Indexed-only mode never crawls, so no provider is needed.
            self._provider = None
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
    def code_mode_exposure(self) -> CodeModeExposure:
        return CodeModeExposure.IMMEDIATE

    @property
    def name(self) -> str:
        return self.shape.name

    @property
    def description(self) -> str:
        if self._web_fetch_disabled:
            return self.DESCRIPTION_NO_WEB_FETCH
        return self.DESCRIPTION

    @property
    def summary(self) -> str:
        if self._web_fetch_disabled:
            return self.SUMMARY_NO_WEB_FETCH
        return self.SUMMARY

    @property
    def display_name(self) -> str:
        return self.DISPLAY_NAME

    @property
    def code_mode_result(self) -> CodeModeResultSpec:
        return SEARCH_RESULTS_CODE_MODE_RESULT

    @override
    @classmethod
    def is_available(cls, db_session: Session) -> bool:  # noqa: ARG003
        """Always available via the web content provider / built-in crawler.

        Full deployments also try indexed retrieval (+ link-based fallback).
        Lite (DISABLE_VECTOR_DB) is crawl-only.
        """
        return True

    def tool_definition(self) -> ToolDefinition:
        return tool_definition_from_arguments(
            self.name, self.description, OpenURLArguments, strict=True
        )

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:
        urls = parse_tool_arguments(OpenURLArguments, invocation.arguments).urls

        if len(urls) > MAX_URLS_PER_CALL:
            logger.warning(
                "OpenURL tool received %s URLs, but the max is %s.",
                len(urls),
                MAX_URLS_PER_CALL,
            )
            urls = urls[:MAX_URLS_PER_CALL]

        with get_session_with_current_tenant() as db_session:
            url_to_doc_id: dict[str, str] = {}
            timeout_occurred = [False]
            # Each requested URL by its normalized form, as crawled pages
            # name it.
            requested_by_normalized: dict[str, list[str]] = {}
            for url in urls:
                requested_by_normalized.setdefault(
                    normalize_web_content_url(url), []
                ).append(url)
            # Every page the crawl fetched, as it arrives. A timeout returns
            # these, so the pages the display showed are also in the result.
            fetched_pages: list[OpenedPage] = []
            # Once the result takes its snapshot, a worker that timed out
            # may neither add nor show a page.
            pages_lock = threading.Lock()
            pages_closed = [False]

            def _on_crawled(url: str, page: OpenedPage, report: bool) -> None:
                with pages_lock:
                    if pages_closed[0]:
                        return
                    fetched_pages.append(page)
                    if report:
                        _report_opened(
                            invocation,
                            [page.section],
                            requested_by_normalized.get(
                                normalize_web_content_url(url), []
                            ),
                        )

            def _close_pages() -> list[OpenedPage]:
                """The pages fetched so far; later ones are dropped."""
                with pages_lock:
                    pages_closed[0] = True
                    return list(fetched_pages)

            def _timeout_handler(
                index: int,  # noqa: ARG001
                func: Any,  # noqa: ARG001
                args: tuple[Any, ...],  # noqa: ARG001
            ) -> None:
                timeout_occurred[0] = True
                return None

            if DISABLE_VECTOR_DB:
                if self._web_fetch_disabled:
                    # No index to serve from and crawling is off — nothing to do.
                    # (construct_tools normally drops the tool in this config;
                    # this is a defensive fallback.)
                    return ToolResult(content=WEB_FETCH_DISABLED_REASON, is_error=True)
                # Crawl-only: no indexed retrieval / link-based fallback without a vector DB.
                crawled_result = run_functions_tuples_in_parallel(
                    [
                        (
                            self._fetch_web_content,
                            (
                                urls,
                                context.url_snippet_map,
                                lambda url, page: _on_crawled(url, page, True),
                            ),
                        )
                    ],
                    allow_failures=True,
                    timeout=OPEN_URL_TIMEOUT_SECONDS,
                    timeout_callback=_timeout_handler,
                )[0]
                indexed_result = IndexedRetrievalResult(
                    sections=[], missing_document_ids=[]
                )
                fetched_so_far = _close_pages()
                crawled_pages, failed_web_fetches = crawled_result or (
                    fetched_so_far,
                    [],
                )

                if (
                    timeout_occurred[0]
                    and not indexed_result.sections
                    and not crawled_pages
                ):
                    return ToolResult(content="The call timed out", is_error=True)
            else:
                url_requests, unresolved_urls = _resolve_urls_to_document_ids(
                    urls, db_session
                )

                all_requests = _dedupe_document_requests(url_requests)

                for request in url_requests:
                    if request.original_url:
                        url_to_doc_id.setdefault(
                            request.original_url, request.document_id
                        )

                # Build filters before parallel execution (session-safe)
                filters = self._build_index_filters(db_session)

                def _retrieve_indexed_with_filters(
                    requests: list[IndexedDocumentRequest],
                ) -> IndexedRetrievalResult:
                    result = self._retrieve_indexed_documents_with_filters(
                        requests, filters
                    )
                    # The merge below prefers an indexed page with content.
                    opened_sections = [
                        section
                        for section in result.sections
                        if section.combined_content
                    ]
                    opened_ids = {
                        section.center_chunk.document_id for section in opened_sections
                    }
                    with pages_lock:
                        if not pages_closed[0]:
                            _report_opened(
                                invocation,
                                opened_sections,
                                [
                                    url
                                    for url, document_id in url_to_doc_id.items()
                                    if document_id in opened_ids
                                ],
                            )
                    return result

                # An indexed copy of a URL wins over its crawl, so a crawled
                # page shows at once only when its URL has no indexed copy.
                indexed_urls = {normalize_web_content_url(url) for url in url_to_doc_id}

                def _report_crawled(url: str, page: OpenedPage) -> None:
                    _on_crawled(
                        url, page, normalize_web_content_url(url) not in indexed_urls
                    )

                if self._web_fetch_disabled:
                    # Indexed-only: never crawl. Unresolved URLs are seeded as
                    # failed (with the disabled reason) so the link-based
                    # fallback below still gets a chance to serve them from the
                    # index; whatever it can't rescue is reported as
                    # unavailable rather than silently fetched from the web.
                    indexed_result = run_functions_tuples_in_parallel(
                        [(_retrieve_indexed_with_filters, (all_requests,))],
                        allow_failures=True,
                        timeout=OPEN_URL_TIMEOUT_SECONDS,
                        timeout_callback=_timeout_handler,
                    )[0]
                    crawled_result = (
                        [],
                        [
                            FailedFetch(
                                url=url, failure_reason=WEB_FETCH_DISABLED_REASON
                            )
                            for url in unresolved_urls
                        ],
                    )
                else:
                    # Indexed + crawl in parallel; allow_failures keeps partial results.
                    indexed_result, crawled_result = run_functions_tuples_in_parallel(
                        [
                            (_retrieve_indexed_with_filters, (all_requests,)),
                            (
                                self._fetch_web_content,
                                (urls, context.url_snippet_map, _report_crawled),
                            ),
                        ],
                        allow_failures=True,
                        timeout=OPEN_URL_TIMEOUT_SECONDS,
                        timeout_callback=_timeout_handler,
                    )

                indexed_result = indexed_result or IndexedRetrievalResult(
                    sections=[], missing_document_ids=[]
                )
                fetched_so_far = _close_pages()
                crawled_pages, failed_web_fetches = crawled_result or (
                    fetched_so_far,
                    [],
                )

                readable_ids = {
                    s.center_chunk.document_id for s in indexed_result.sections
                }
                picked_ids = _pick_readable_document_ids(url_requests, readable_ids)
                url_to_doc_id.update(picked_ids)
                # Drop alternates that were only fallback candidates for a readable URL.
                unused_alternates = {
                    r.document_id
                    for r in url_requests
                    if r.original_url in picked_ids
                    and picked_ids[r.original_url] in readable_ids
                    and r.document_id != picked_ids[r.original_url]
                } - set(picked_ids.values())
                if unused_alternates:
                    indexed_result.missing_document_ids = [
                        doc_id
                        for doc_id in indexed_result.missing_document_ids
                        if doc_id not in unused_alternates
                    ]

                # Before link-based fallback (retries index retrieval with no timeout).
                if (
                    timeout_occurred[0]
                    and not indexed_result.sections
                    and not crawled_pages
                ):
                    return ToolResult(content="The call timed out", is_error=True)

                # Last-resort: link-based lookup when doc-ID resolve + crawl both fail.
                failed_web_fetches = self._fallback_link_lookup(
                    unresolved_urls=unresolved_urls,
                    failed_web_fetches=failed_web_fetches,
                    db_session=db_session,
                    indexed_result=indexed_result,
                    url_to_doc_id=url_to_doc_id,
                    filters=filters,
                )

            # Prefer indexed when available, else crawled
            opened = self._merge_indexed_and_crawled_results(
                indexed_result.sections,
                crawled_pages,
                url_to_doc_id,
                urls,
                failed_web_fetches,
            )
        inference_sections = [page.section for page in opened]

        if not inference_sections:
            failure_msg = _build_failure_message(
                missing_document_ids=indexed_result.missing_document_ids,
                failed_web_fetches=failed_web_fetches,
            )
            logger.warning("OpenURL tool failed: %s", failure_msg)
            return ToolResult(content=failure_msg, is_error=True)

        # All the pages, also those that opened before the end. The display
        # shows each page once. Pages reported only now (a crawl that stood
        # in for an empty indexed copy, a link fallback) name the requested
        # URLs they answer, by document ID or by link.
        opened_ids = {
            section.center_chunk.document_id for section in inference_sections
        }
        opened_links = {
            normalize_web_content_url(link)
            for section in inference_sections
            for link in (section.center_chunk.source_links or {}).values()
        }
        _report_opened(
            invocation,
            inference_sections,
            [
                url
                for url in urls
                if url_to_doc_id.get(url) in opened_ids
                or normalize_web_content_url(url) in opened_links
            ],
        )
        search_docs = convert_inference_sections_to_search_docs(
            inference_sections, is_internet=False
        )

        # Note that with this call, some contents may be truncated or dropped so what the LLM sees may not be the entire set
        # That said, it is still the best experience to show all the docs that were fetched, even if the LLM on rare
        # occasions only actually sees a subset.
        existing_citation_mapping = {
            url: number for number, url in context.citation_mapping.items()
        }
        citation_start = (
            context.next_citation_num + CITATIONS_PER_TOOL_CALL * invocation.call_index
        )
        excerpts, citation_mapping = _sections_to_search_results(
            sections=inference_sections,
            existing_citation_mapping=existing_citation_mapping,
            citation_start=citation_start,
        )
        # The full value: each page whole, within the call's limit. A page
        # keeps its whole text when that text holds all that the model saw of
        # it: the excerpt as the call's budget cut it, without its markers.
        # Otherwise (the limit can cut a page before its snippet) it keeps its
        # excerpt, as does a page past the limit, so the full value holds all
        # that the model sees. A page past the excerpts' budget, which the
        # model did not see, goes in whole. Both lists follow the sections'
        # order, so a page pairs with its excerpt by position, also when two
        # pages share a citation number.
        pages, _ = _sections_to_search_results(
            sections=[
                page.section.model_copy(update={"combined_content": page.text})
                for page in opened
            ],
            existing_citation_mapping=existing_citation_mapping,
            citation_start=citation_start,
            max_document_chars=OPEN_URL_PROGRAM_MAX_CHARS
            if context.program_call
            else OPEN_URL_MAX_CHARS,
        )
        full_pages: list[SearchResult] = []
        for page, excerpt in zip(pages.results, excerpts.results, strict=False):
            seen = excerpt.content.removeprefix(TRUNCATED_CONTENT_PREFIX).removesuffix(
                TRUNCATED_CONTENT_SUFFIX
            )
            # The budget cut can split the excerpt's own closing marker.
            seen = next(
                (
                    seen[:-length]
                    for length in range(len(TRUNCATED_CONTENT_SUFFIX) - 1, 0, -1)
                    if seen.endswith(TRUNCATED_CONTENT_SUFFIX[:length])
                ),
                seen,
            )
            full_pages.append(page if seen in page.content else excerpt)
        full_pages += (
            pages.results[len(excerpts.results) :]
            or excerpts.results[len(pages.results) :]
        )

        return ToolResult(
            details=SearchDocsResponse(
                search_docs=search_docs,
                citation_mapping=citation_mapping,
            ),
            content=excerpts.model_dump_json(),
            # Set only when some page holds more than the model sees of it.
            full_value=None
            if full_pages == excerpts.results
            else SearchResults(results=full_pages),
        )

    def _fallback_link_lookup(
        self,
        unresolved_urls: list[str],
        failed_web_fetches: list[FailedFetch],
        db_session: Session,
        indexed_result: IndexedRetrievalResult,
        url_to_doc_id: dict[str, str],
        filters: IndexFilters,
    ) -> list[FailedFetch]:
        """Attempt link-based lookup for URLs that failed both document-ID resolution and crawling.

        Args:
            unresolved_urls: URLs that couldn't be resolved to document IDs
            failed_web_fetches: URLs that failed crawling, with per-URL reasons
            db_session: Database session
            indexed_result: Result object to update with found sections
            url_to_doc_id: Mapping to update with resolved URLs
            filters: Pre-built index filters for document retrieval

        Returns:
            Updated list of failed fetches (with resolved URLs removed)
        """
        if not unresolved_urls or not failed_web_fetches:
            return failed_web_fetches

        failed_set = {f.url for f in failed_web_fetches if f.url}
        fallback_urls = sorted(set(unresolved_urls).intersection(failed_set))

        if not fallback_urls:
            return failed_web_fetches

        fallback_requests = _lookup_document_ids_by_link(fallback_urls, db_session)

        if not fallback_requests:
            return failed_web_fetches

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
        return [f for f in failed_web_fetches if f.url not in resolved_links]

    def _retrieve_indexed_documents_with_filters(
        self,
        all_requests: list[IndexedDocumentRequest],
        filters: IndexFilters,
    ) -> IndexedRetrievalResult:
        """Retrieve indexed documents using pre-built filters (for parallel execution)."""
        if not all_requests:
            return IndexedRetrievalResult(sections=[], missing_document_ids=[])

        document_ids = [req.document_id for req in all_requests]
        chunk_requests = [
            DocumentSectionRequest(document_id=request.document_id)
            for request in all_requests
        ]

        try:
            chunks = censor_chunks_for_user(
                self._document_index.id_based_retrieval(
                    chunk_requests=chunk_requests,
                    filters=filters,
                    batch_retrieval=True,
                ),
                self._user,
            )
        except Exception as exc:
            logger.warning(
                "Indexed retrieval failed for document IDs %s: %s",
                document_ids,
                exc,
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
                missing.append(request.document_id)
                continue
            doc_chunks.sort(key=lambda chunk: chunk.chunk_id)
            section = inference_section_from_chunks(
                center_chunk=doc_chunks[0],
                chunks=doc_chunks,
            )
            if section:
                sections.append(section)
            else:
                missing.append(request.document_id)

        return IndexedRetrievalResult(sections=sections, missing_document_ids=missing)

    def _build_index_filters(self, db_session: Session) -> IndexFilters:
        user_access_filters = build_access_filters_for_user(self._user, db_session)
        return IndexFilters(
            source_type=None,
            document_set=None,
            tags=None,
            access_control_list=user_access_filters.access_control_list,
            cc_pair_access=user_access_filters.cc_pair_access,
            tenant_id=get_current_tenant_id() if MULTI_TENANT else None,
            project_id_filter=None,
        )

    def _merge_indexed_and_crawled_results(
        self,
        indexed_sections: list[InferenceSection],
        crawled_pages: list[OpenedPage],
        url_to_doc_id: dict[str, str],
        all_urls: list[str],
        failed_web_fetches: list[FailedFetch],  # noqa: ARG002
    ) -> list[OpenedPage]:
        """Merge indexed and crawled results, preferring indexed when available.

        For each URL:
        - If indexed result exists and has content, use it (better/cleaner representation)
        - Otherwise, use crawled result if available
        - If both fail, the URL will be in failed_web_fetches for error reporting
        """
        # Map indexed sections by document_id
        indexed_by_doc_id: dict[str, InferenceSection] = {}
        for section in indexed_sections:
            indexed_by_doc_id[section.center_chunk.document_id] = section

        # Map crawled pages by URL (from source_links)
        crawled_by_url: dict[str, OpenedPage] = {}
        for page in crawled_pages:
            # Extract URL from source_links (crawled sections store URL here)
            if page.section.center_chunk.source_links:
                url = next(iter(page.section.center_chunk.source_links.values()))
                if url:
                    crawled_by_url[url] = page

        # An indexed section's content is the document's whole text.
        merged_sections: list[OpenedPage] = []
        used_doc_ids: set[str] = set()

        # Process URLs: prefer indexed, fallback to crawled
        for url in all_urls:
            doc_id = url_to_doc_id.get(url)
            indexed_section = indexed_by_doc_id.get(doc_id) if doc_id else None
            # WebContent.link is normalized (query/fragment stripped). Match on the
            # same normalized form to avoid dropping successful crawl results.
            crawled_page = crawled_by_url.get(normalize_web_content_url(url))

            if indexed_section and indexed_section.combined_content:
                # Prefer indexed
                merged_sections.append(
                    OpenedPage(indexed_section, indexed_section.combined_content)
                )
                if doc_id:
                    used_doc_ids.add(doc_id)
            elif crawled_page and crawled_page.section.combined_content:
                # Fallback to crawled if indexed unavailable or empty
                # (e.g., auth issues, document not indexed, etc.)
                merged_sections.append(crawled_page)

        # Add any indexed sections that weren't matched to URLs
        for doc_id, section in indexed_by_doc_id.items():
            # Skip if this doc_id was already used for a URL
            if doc_id not in used_doc_ids:
                merged_sections.append(OpenedPage(section, section.combined_content))

        return merged_sections

    def _fetch_web_content(
        self,
        urls: list[str],
        url_snippet_map: dict[str, str],
        on_page: Callable[[str, OpenedPage], None] | None = None,
    ) -> tuple[list[OpenedPage], list[FailedFetch]]:
        """The fetched pages, each with an excerpt around its snippet and its
        whole text cut to OPEN_URL_MAX_CHARS, and the failed fetches.
        on_page gets each page and its normalized URL as soon as it is
        fetched."""
        if not urls:
            return [], []

        if self._provider is None:
            # Only possible in web-fetch-disabled mode, which never routes here.
            return (
                [],
                [
                    FailedFetch(url=url, failure_reason=WEB_FETCH_DISABLED_REASON)
                    for url in urls
                ],
            )

        # Track per-URL failure reasons (preferred) but de-dupe by URL since the
        # same URL can show up in both the "empty" and "scrape unsuccessful"
        # branches below.
        failed_by_url: dict[str, FailedFetch] = {}

        def _mark_failed(url: str, reason: str | None) -> None:
            existing = failed_by_url.get(url)
            # Prefer a non-None reason if we have one, otherwise keep the
            # earlier entry (which itself may already have a reason).
            if existing is None or (reason and not existing.failure_reason):
                failed_by_url[url] = FailedFetch(url=url, failure_reason=reason)

        pages: list[OpenedPage] = []

        for content in self._provider.iter_contents(urls):
            # Treat "no title and no content" as a failure for that URL, but
            # don't include the empty entry in downstream prompting/sections.
            if not content.title.strip() and not content.full_content.strip():
                _mark_failed(content.link, content.failure_reason)
                continue

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
                page = OpenedPage(
                    inference_section_from_internet_page_scrape(
                        content, url_snippet_map.get(content.link, "")
                    ),
                    truncate_search_result_content(
                        content.full_content, OPEN_URL_MAX_CHARS
                    ),
                )
                pages.append(page)
                if on_page is not None:
                    on_page(content.link, page)
            else:
                _mark_failed(content.link or "", content.failure_reason)

        return pages, list(failed_by_url.values())
