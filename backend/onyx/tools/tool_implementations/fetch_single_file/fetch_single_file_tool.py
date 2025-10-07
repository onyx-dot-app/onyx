import json
import re
from collections.abc import Generator
from typing import Any
from uuid import UUID

from rapidfuzz import fuzz
from sqlalchemy.orm import Session

from onyx.agents.agent_search.shared_graph_utils.models import QueryExpansionType
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import IndexFilters
from onyx.context.search.models import SearchQuery
from onyx.context.search.preprocessing.access_filters import (
    build_access_filters_for_user,
)
from onyx.context.search.utils import get_query_embedding
from onyx.context.search.utils import remove_stop_words_and_punctuation
from onyx.db.models import User
from onyx.db.search_settings import get_current_search_settings
from onyx.document_index.factory import get_current_primary_default_document_index
from onyx.document_index.vespa.index import VespaIndex
from onyx.federated_connectors.federated_retrieval import (
    get_federated_retrieval_functions,
)
from onyx.llm.interfaces import LLM
from onyx.llm.models import PreviousMessage
from onyx.tools.base_tool import BaseTool
from onyx.tools.models import DocumentResult
from onyx.tools.models import ToolResponse
from onyx.tools.utils import get_full_document_by_id
from onyx.utils.logger import setup_logger

logger = setup_logger()

DESCRIPTION_FIELD = "description"
DOCUMENT_RESULT_ID = "document_result"


def is_document_request(query: str) -> bool:
    """Detect if the user is asking for a specific document"""
    query_lower = query.lower().strip()

    # Document request patterns
    document_patterns = [
        "give me",
        "find the",
        "show me the",
        "get me the",
        "find me",
        "show me",
        "get me",
        "fetch me",
        "retrieve",
        "doc about",
        "document about",
        "design doc",
        "specification",
        "manual",
        "guide",
        "documentation",
        "tell me about",
    ]

    # Check if query contains document request patterns
    for pattern in document_patterns:
        if pattern in query_lower:
            return True

    # Check for specific document types
    document_types = [
        "doc",
        "document",
        "spec",
        "specification",
        "manual",
        "guide",
        "readme",
        "api doc",
        "design doc",
        "requirements",
        "proposal",
    ]

    for doc_type in document_types:
        if doc_type in query_lower:
            return True

    return False


class FetchSingleFileTool(BaseTool):
    _NAME = "fetch_single_file"
    _DESCRIPTION = (
        "Find and retrieve a specific document from the knowledge base by name or title. "
        "ALWAYS use this tool when the user asks for a document using phrases like 'give me', "
        "'find', 'show me', or 'get me' followed by a document name or title. "
        "Examples: 'give me slack bot design doc' → use this tool, "
        "'find the portfolio companies document' → use this tool, "
        "'show me the API documentation' → use this tool. "
        "This tool searches the internal document database and returns the exact document content with URL. "
        "CRITICAL: When returning results, ALWAYS include the source URL in your response. "
        "The URL is provided in the content and metadata. "
        "IMPORTANT: If this tool finds relevant documents, STOP here and provide the results. "
        "Do NOT call additional search tools unless no documents are found. "
        "This tool is comprehensive and should be sufficient for document retrieval requests."
    )

    def __init__(self, tool_id: int, db_session: Session, user_id: UUID | None = None):
        self.tool_id = tool_id
        self.db_session = db_session
        self.user_id = user_id

    _DISPLAY_NAME = "Fetch Single Document"

    @property
    def id(self) -> int:
        return self.tool_id

    @property
    def name(self) -> str:
        return self._NAME

    @property
    def description(self) -> str:
        return self._DESCRIPTION

    @property
    def display_name(self) -> str:
        return self._DISPLAY_NAME

    @classmethod
    def is_available(cls, db_session: Session) -> bool:
        """Always available"""
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
                        DESCRIPTION_FIELD: {
                            "type": "string",
                            "description": (
                                "The exact name or description of the document to find. "
                                "Use the user's exact words when they ask for a specific document. "
                                "Examples: 'slack bot design doc', 'portfolio companies', 'API documentation'"
                            ),
                        },
                    },
                    "required": [DESCRIPTION_FIELD],
                },
            },
        }

    def get_args_for_non_tool_calling_llm(
        self,
        query: str,
        history: list[PreviousMessage],
        llm: LLM,
        force_run: bool = False,
    ) -> dict[str, Any] | None:
        """Extract document description from query for non-tool-calling LLMs"""
        logger.info(
            f"FetchSingleFileTool.get_args_for_non_tool_calling_llm called with query: '{query}'"
        )
        # Use the query as the description to search for
        # This tool should be called when user asks about finding specific documents
        return {DESCRIPTION_FIELD: query}

    def build_tool_message_content(
        self, *args: ToolResponse
    ) -> str | list[str | dict[str, Any]]:
        document_result_response = next(
            response for response in args if response.id == DOCUMENT_RESULT_ID
        )
        document_result = document_result_response.response

        if isinstance(document_result, DocumentResult):
            return json.dumps(
                {
                    "title": document_result.title,
                    "content": document_result.content,
                    "source": document_result.source,
                    "url": document_result.url,
                    "confidence": document_result.confidence,
                    "metadata": document_result.metadata,
                }
            )
        return json.dumps({"error": "No document found"})

    def run(
        self, override_kwargs: None = None, **llm_kwargs: Any
    ) -> Generator[ToolResponse, None, None]:
        description = llm_kwargs.get(DESCRIPTION_FIELD, "")
        if not description:
            raise ValueError("Description is required")

        logger.info(f"FetchSingleFileTool.run called with description: {description}")
        logger.info(f"Searching for document: {description}")

        # Search for documents matching the description
        all_results = []

        # 1. Search internal docs
        internal_results = self._search_internal_docs(description)

        all_results.extend(internal_results)

        # 2. Search federated sources
        federated_results = self._search_federated_sources(description)
        all_results.extend(federated_results)

        # 3. Deduplicate results by document ID (keep highest confidence for each unique document)
        all_results = self._deduplicate_by_document_id(all_results)

        # 4. Handle results - always return the best match
        logger.info(f"Total unique documents found: {len(all_results)}")
        if len(all_results) == 0:
            logger.warning("No documents found - returning empty result")
            # No documents found
            result = DocumentResult(
                title="No documents found",
                content=f"No documents found matching '{description}'",
                source="none",
                url=None,
                metadata={"search_query": description},
                confidence=0,
            )
        else:
            # Sort by confidence score and return the best match
            all_results.sort(key=lambda x: x.confidence, reverse=True)
            best_match = all_results[0]

            logger.info(
                f"Best match: title='{best_match.title}', url='{best_match.url}', confidence={best_match.confidence}"
            )

            # Check if we should show multiple options
            should_show_multiple = self._should_show_multiple_options(
                all_results, best_match
            )

            if should_show_multiple:
                result = self._create_multiple_results_response(
                    all_results, description
                )
            else:
                # Get full document content for the best match using generic method
                document_id = best_match.metadata.get("document_id")

                if document_id:
                    # Fetch user object if user_id is available
                    user = None
                    if self.user_id:
                        user = (
                            self.db_session.query(User)
                            .filter(User.id == self.user_id)
                            .first()
                        )

                    # Use the generic method to get full document content
                    full_doc_result = get_full_document_by_id(
                        document_id=document_id,
                        url=best_match.url or "",
                        source_type=getattr(
                            best_match, "source_type", DocumentSource.WEB
                        ),
                        source_method="full_document_retrieval",
                        db_session=self.db_session,
                        user=user,  # User context for access control
                        use_access_filters=True,  # Apply access filters for search-based access
                    )

                    # Use the full document result with additional metadata
                    content_with_url = (
                        f"Source URL: {best_match.url}\n\n{full_doc_result.content}"
                        if best_match.url
                        else full_doc_result.content
                    )

                    result = DocumentResult(
                        title=full_doc_result.title,
                        content=content_with_url,
                        source=full_doc_result.source,
                        url=full_doc_result.url,
                        metadata={
                            **full_doc_result.metadata,
                            "total_matches": str(len(all_results)),
                            "confidence_explanation": f"Best match out of {len(all_results)} results",
                            "source_url": best_match.url,
                            "instruction": "CRITICAL: Always include the source URL in your response. The URL is: "
                            + (best_match.url or "No URL available"),
                            "full_document_retrieved": "true",
                        },
                        confidence=full_doc_result.confidence,
                    )

                    logger.info(
                        f"Retrieved full document content: {len(full_doc_result.content)} characters"
                    )
                else:
                    # No document_id available, use original result
                    content_with_url = (
                        f"Source URL: {best_match.url}\n\n{best_match.content}"
                        if best_match.url
                        else best_match.content
                    )
                    result = DocumentResult(
                        title=best_match.title,
                        content=content_with_url,
                        source=best_match.source,
                        url=best_match.url,
                        metadata={
                            **best_match.metadata,
                            "total_matches": str(len(all_results)),
                            "confidence_explanation": f"Best match out of {len(all_results)} results",
                            "source_url": best_match.url,
                            "instruction": "CRITICAL: Always include the source URL in your response. The URL is: "
                            + (best_match.url or "No URL available"),
                            "full_document_retrieved": "false",
                        },
                        confidence=best_match.confidence,
                    )

        yield ToolResponse(id=DOCUMENT_RESULT_ID, response=result)

    def final_result(self, *args: ToolResponse) -> dict[str, Any]:
        document_result_response = next(
            arg for arg in args if arg.id == DOCUMENT_RESULT_ID
        )
        document_result = document_result_response.response

        logger.info(
            f"Final result: title='{document_result.title}', url='{document_result.url}', confidence={document_result.confidence}"
        )

        if isinstance(document_result, DocumentResult):
            return {
                "title": document_result.title,
                "content": document_result.content,
                "source": document_result.source,
                "url": document_result.url,
                "confidence": document_result.confidence,
                "metadata": document_result.metadata,
            }

    def _extract_ticket_pattern(self, description: str) -> str | None:
        """Extract ticket pattern from description (e.g., 'DAN-1919', 'dan 1919', 'linear ticket 50')"""
        description_lower = description.lower()

        # Pattern 1: Direct ticket format (DAN-1919, JIRA-123, etc.)
        ticket_match = re.search(r"\b([A-Z]{2,}-\d+)\b", description.upper())
        if ticket_match:
            return ticket_match.group(1)

        # Common mapping for platform/prefix names to ticket prefixes
        platform_mapping = {
            "dan": "DAN",
            "linear": "DAN",
            "jira": "JIRA",
            "gh": "GH",
            "github": "GH",
            "notion": "NOTION",
            "zendesk": "ZENDESK",
            "asana": "ASANA",
        }

        # Pattern 2: Platform prefix + number (dan 1919, jira 123, etc.)
        prefix_pattern = r"\b(dan|jira|gh|github|notion|zendesk|asana)\s+(\d+)\b"
        match = re.search(prefix_pattern, description_lower)
        if match:
            platform = match.group(1)
            number = match.group(2)
            prefix = platform_mapping.get(platform, platform.upper())
            return f"{prefix}-{number}"

        # Pattern 3: Platform + number (linear ticket 50, jira ticket 123, etc.)
        platform_pattern = (
            r"\b(linear|jira|github|notion|zendesk|asana)\s+(?:ticket|issue)?\s*(\d+)\b"
        )
        match = re.search(platform_pattern, description_lower)
        if match:
            platform = match.group(1)
            number = match.group(2)
            prefix = platform_mapping.get(platform, platform.upper())
            return f"{prefix}-{number}"

        return None

    def _extract_search_terms(self, description: str) -> str:
        """Extract search terms for Vespa search, focusing on general search terms"""

        # Extract other ID patterns (non-ticket IDs)
        identifiers = []
        id_patterns = re.findall(r"\b\d{4,}\b", description)  # 4+ digit numbers
        identifiers.extend(id_patterns)

        # Use the existing NLTK-based stop word removal
        words = description.split()
        cleaned_words = remove_stop_words_and_punctuation(words)

        # Additional domain-specific stop words to remove
        domain_stop_words = {
            "ticket",
            "issue",
            "linear",
            "jira",
            "github",
            "document",
            "information",
        }

        # Filter out domain-specific stop words
        filtered_words = [
            word for word in cleaned_words if word.lower() not in domain_stop_words
        ]

        # Combine identifiers and filtered words, prioritizing identifiers
        all_terms = identifiers + filtered_words

        # Remove duplicates while preserving order
        seen = set()
        unique_terms = []
        for term in all_terms:
            if term.lower() not in seen:
                unique_terms.append(term)
                seen.add(term.lower())

        result = " ".join(unique_terms)
        return result if result else description

    def _deduplicate_by_document_id(
        self, results: list[DocumentResult]
    ) -> list[DocumentResult]:
        """Deduplicate results by document ID, keeping the highest confidence for each unique document"""
        document_map = {}

        for result in results:
            doc_id = result.metadata.get("document_id", "unknown")

            # If we haven't seen this document ID, or this result has higher confidence
            if (
                doc_id not in document_map
                or result.confidence > document_map[doc_id].confidence
            ):
                document_map[doc_id] = result

        # Convert back to list and sort by confidence
        unique_results = list(document_map.values())
        unique_results.sort(key=lambda x: x.confidence, reverse=True)

        logger.info(
            f"Deduplicated {len(results)} results to {len(unique_results)} unique documents"
        )
        return unique_results

    def _search_internal_docs(self, description: str) -> list[DocumentResult]:
        """Search internal documents using direct VespaIndex retrieval"""
        logger.info(f"Searching internal docs for: {description}")

        try:
            # Get search settings and document index
            get_current_search_settings(self.db_session)
            document_index = get_current_primary_default_document_index(self.db_session)

            if not isinstance(document_index, VespaIndex):
                logger.warning(
                    "Document index is not VespaIndex, skipping internal search"
                )
                return []

            # Build access filters for the user
            user = User(id=self.user_id) if self.user_id else None
            access_filters = (
                build_access_filters_for_user(user, self.db_session) if user else None
            )

            # Create index filters
            index_filters = IndexFilters(
                access_control_list=access_filters,
                source_filters=None,
                time_cutoff=None,
                tags=None,
            )

            # Extract key terms from description for better search
            search_terms = self._extract_search_terms(description)
            logger.info(
                f"Searching with terms: '{search_terms}' (original: '{description}')"
            )
            logger.info(
                f"Search query: '{search_terms}' - looking for Jira tickets, documents, etc."
            )

            # Generate query embedding for hybrid search
            query_embedding = get_query_embedding(search_terms, self.db_session)

            # Perform hybrid retrieval (semantic + keyword search)
            retrieved_chunks = document_index.hybrid_retrieval(
                query=search_terms,
                query_embedding=query_embedding,
                final_keywords=[search_terms],
                filters=index_filters,
                hybrid_alpha=0.7,  # 70% semantic, 30% keyword
                time_decay_multiplier=1.0,
                num_to_retrieve=20,  # Increase to get more results
                ranking_profile_type=QueryExpansionType.SEMANTIC,
            )

            # Convert to DocumentResult objects with fuzzy confidence scoring
            results = []
            logger.info(
                f"Processing {len(retrieved_chunks)} chunks from internal search"
            )
            for i, chunk in enumerate(retrieved_chunks):
                logger.info(
                    f"Chunk {i+1}: title='{chunk.semantic_identifier}', "
                    f"source='{chunk.source_type}', doc_id='{chunk.document_id}'"
                )

                # Calculate fuzzy confidence score
                fuzzy_confidence = self._calculate_confidence(chunk, description)

                # Use real semantic score from hybrid_retrieval (Vespa relevance score)
                raw_semantic_score = chunk.score if chunk.score is not None else 0
                semantic_score = raw_semantic_score

                # Scale Vespa semantic scores (0-1) to match fuzzy confidence range (0-100)
                if semantic_score <= 1.0:  # Vespa scores are typically 0-1
                    semantic_score = semantic_score * 100  # Scale to 0-100

                # Weighted combination: 70% fuzzy matching, 30% semantic search
                combined_confidence = int(
                    (fuzzy_confidence * 0.7) + (semantic_score * 0.3)
                )

                # Debug logging for score analysis
                logger.debug(
                    f"Score breakdown for '{chunk.semantic_identifier}': "
                    f"fuzzy={fuzzy_confidence:.1f}, raw_semantic={raw_semantic_score:.3f}, "
                    f"scaled_semantic={semantic_score:.1f}, final={combined_confidence}"
                )

                # Get URL from source_links (first available link)
                url = ""
                if chunk.source_links:
                    url = next(iter(chunk.source_links.values()), "")

                # Include chunk content if available, otherwise provide a summary
                content = (
                    chunk.content
                    if chunk.content
                    else f"Document: {chunk.semantic_identifier}"
                )
                if chunk.blurb:
                    content = f"{chunk.blurb}\n\n{content}"

                result = DocumentResult(
                    title=chunk.semantic_identifier,
                    content=content,
                    source="internal",
                    url=url,
                    metadata={
                        "search_query": description,
                        "source_type": (
                            chunk.source_type.value
                            if hasattr(chunk.source_type, "value")
                            else str(chunk.source_type)
                        ),
                        "document_id": chunk.document_id,
                        "chunk_id": str(chunk.chunk_id),
                        "semantic_score": str(semantic_score),
                        "fuzzy_score": str(fuzzy_confidence),
                        "combined_score": str(combined_confidence),
                    },
                    confidence=combined_confidence,
                )
                results.append(result)

            logger.info(f"Found {len(results)} internal documents")
            return results

        except Exception as e:
            logger.warning(f"Failed to search internal docs: {e}")
            return []

    def _search_federated_sources(self, description: str) -> list[DocumentResult]:
        """Search federated sources using get_federated_retrieval_functions"""
        logger.info(f"Searching federated sources for: {description}")

        try:
            # Get federated retrieval functions for all available sources
            federated_functions = get_federated_retrieval_functions(
                db_session=self.db_session,
                user_id=getattr(self, "user_id", None),
                source_types=None,  # Search all available sources
                document_set_names=None,
            )

            logger.info(f"Found {len(federated_functions)} federated sources to search")
            all_results = []
            for federated_info in federated_functions:
                try:
                    # Search this federated source
                    search_query = SearchQuery(query=description)
                    chunks = federated_info.retrieval_function(search_query)

                    # Convert chunks to DocumentResult
                    for chunk in chunks[:3]:  # Top 3 from each source
                        all_results.append(
                            DocumentResult(
                                title=chunk.document.semantic_identifier,
                                content="",  # No content yet
                                source="federated",
                                url=chunk.document.link,
                                metadata={
                                    "search_query": description,
                                    "source_type": federated_info.source.value,
                                    "chunk_id": chunk.chunk_id,
                                },
                                confidence=self._calculate_confidence(
                                    chunk, description
                                ),
                            )
                        )
                except Exception as e:
                    logger.warning(f"Failed to search {federated_info.source}: {e}")

            return all_results

        except Exception as e:
            logger.warning(f"Failed to get federated retrieval functions: {e}")
            return []

    def _calculate_confidence(self, chunk: Any, description: str) -> int:
        """Calculate confidence score using clean fuzzy matching"""
        try:
            # Get chunk content and document info
            content = getattr(chunk, "content", "")
            doc = getattr(chunk, "document", None)
            title = getattr(doc, "semantic_identifier", "") if doc else ""

            if not content and not title:
                return 30

            # Normalize inputs
            normalized_description = description.lower().strip()
            title_lower = title.lower() if title else ""
            content_lower = content.lower() if content else ""

            # Extract meaningful words (remove common stop words)
            stop_words = {
                "the",
                "a",
                "an",
                "and",
                "or",
                "but",
                "in",
                "on",
                "at",
                "to",
                "for",
                "of",
                "with",
                "by",
                "about",
                "find",
                "information",
                "document",
                "file",
                "get",
                "show",
                "tell",
                "me",
                "about",
            }
            desc_words = (
                set(re.findall(r"\b\w+\b", normalized_description)) - stop_words
            )
            logger.debug(
                f"Extracted words from '{normalized_description}': {desc_words}"
            )

            # Calculate confidence using multiple strategies
            scores = []

            # 1. Ticket pattern matching (highest priority for tickets)
            ticket_pattern = self._extract_ticket_pattern(description)
            if ticket_pattern:
                # Check for exact ticket match in title
                if title_lower and ticket_pattern.lower() in title_lower:
                    scores.append(98)  # Higher than regular exact match
                # Check for partial ticket match (just the number)
                ticket_number = ticket_pattern.split("-")[-1]
                if title_lower and ticket_number in title_lower:
                    scores.append(95)  # High confidence for number match

            # 2. Exact substring match in title (high confidence)
            if title_lower and normalized_description in title_lower:
                scores.append(95)

            # 3. Word overlap in title (high confidence)
            if title_lower and desc_words:
                title_words = set(re.findall(r"\b\w+\b", title_lower))
                word_overlap = len(desc_words & title_words)
                if word_overlap > 0:
                    overlap_score = (word_overlap / len(desc_words)) * 85
                    scores.append(overlap_score)

            # 4. Fuzzy matching on title
            if title_lower:
                fuzzy_score = max(
                    [
                        fuzz.ratio(normalized_description, title_lower),
                        fuzz.partial_ratio(normalized_description, title_lower),
                        fuzz.token_sort_ratio(normalized_description, title_lower),
                        fuzz.token_set_ratio(normalized_description, title_lower),
                    ]
                )
                scores.append(fuzzy_score * 0.8)  # Weight down fuzzy matches

            # 5. Word overlap in content (medium confidence)
            if content_lower and desc_words:
                content_words = set(re.findall(r"\b\w+\b", content_lower))
                word_overlap = len(desc_words & content_words)
                if word_overlap > 0:
                    overlap_score = (word_overlap / len(desc_words)) * 60
                    scores.append(overlap_score)

            # 6. Fuzzy matching on content (lowest confidence)
            if content_lower:
                fuzzy_score = max(
                    [
                        fuzz.token_sort_ratio(normalized_description, content_lower),
                        fuzz.token_set_ratio(normalized_description, content_lower),
                        fuzz.partial_ratio(normalized_description, content_lower),
                    ]
                )
                scores.append(fuzzy_score * 0.5)  # Weight down content matches

            # Take the highest score
            final_score = max(scores) if scores else 30

            # Apply bounds
            final_score = max(30, min(int(final_score), 95))

            logger.debug(
                f"Confidence scores: {scores}, final: {final_score} for '{normalized_description}' -> '{title_lower[:50]}...'"
            )
            return final_score

        except Exception as e:
            logger.warning(f"Error calculating confidence: {e}")
            return 30

    def _should_show_multiple_options(
        self, results: list[DocumentResult], best_match: DocumentResult
    ) -> bool:
        """Determine if we should show multiple options to the user"""
        if len(results) <= 1:
            return False

        # Always show multiple options if best match has zero confidence
        if best_match.confidence < 1:
            return True

        # Check if there are other results with similar confidence scores
        # Look for results within 3 points of the best match (more restrictive)
        confidence_threshold = best_match.confidence - 3

        # Count how many results are close to the best match
        close_matches = [r for r in results if r.confidence >= confidence_threshold]

        # If there are 2 or more close matches AND the best match has decent confidence, show multiple options
        # But only if the gap is actually small (within 3 points)
        if len(close_matches) >= 2 and best_match.confidence >= 30:
            # Check if the second best is actually close
            second_best = results[1] if len(results) > 1 else None
            if second_best and (best_match.confidence - second_best.confidence) <= 3:
                logger.info(
                    f"Showing multiple options: best={best_match.confidence}, close_matches={len(close_matches)}"
                )
                return True

        # Also show multiple options if there are many results (5+) and the gap is small AND confidence is low
        if len(results) >= 5 and best_match.confidence < 35:
            second_best = results[1] if len(results) > 1 else None
            if second_best and (best_match.confidence - second_best.confidence) <= 3:
                logger.info(
                    f"Showing multiple options: many results ({len(results)}) with small gap"
                )
                return True

        return False

    def _create_multiple_results_response(
        self, results: list[DocumentResult], description: str
    ) -> DocumentResult:
        """Create response when multiple documents are found"""
        # Sort by confidence score
        results.sort(key=lambda x: x.confidence, reverse=True)

        # Determine why we're showing multiple options
        best_match = results[0]
        second_best = results[1] if len(results) > 1 else None

        if best_match.confidence < 1:
            reason = "zero confidence scores"
        elif second_best and (best_match.confidence - second_best.confidence) <= 10:
            reason = f"similar confidence scores ({best_match.confidence} vs {second_best.confidence})"
        elif len(results) >= 5:
            reason = f"many results ({len(results)}) with small gaps"
        else:
            reason = "multiple close matches"

        # Create a special response indicating multiple results with URLs in content
        top_results_text = "\n".join(
            [
                f"{i+1}. **{result.title}**: {result.url}"
                for i, result in enumerate(results[:5])  # Top 5 results
            ]
        )

        content_with_urls = (
            f"I found {len(results)} documents matching your description. The top results have {reason}, "
            f"so please specify which one you'd like me to fetch:\n\n{top_results_text}"
        )

        return DocumentResult(
            title=f"Multiple documents found for '{description}'",
            content=content_with_urls,
            source="multiple",
            url=None,
            metadata={
                "search_query": description,
                "reason_for_multiple": reason,
                "best_confidence": str(best_match.confidence),
                "second_best_confidence": (
                    str(second_best.confidence) if second_best else "None"
                ),
                "confidence_gap": (
                    str(best_match.confidence - second_best.confidence)
                    if second_best
                    else "None"
                ),
                "found_documents": json.dumps(
                    [
                        {
                            "title": result.title,
                            "url": result.url,
                            "source": result.source,
                            "confidence": result.confidence,
                            "rank": i + 1,
                        }
                        for i, result in enumerate(results[:5])  # Top 5 results
                    ]
                ),
            },
            confidence=0,  # Special case for multiple results
        )
