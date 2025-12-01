"""
Dynamic Citation Processor for LLM Responses

This module provides a citation processor that can:
- Accept citation number to SearchDoc mappings dynamically
- Process token streams from LLMs to extract citations
- Remove citation markers from output text
- Emit CitationInfo objects for detected citations
- Maintain a list of cited documents in order of first citation
"""

import re
from collections.abc import Generator

from onyx.configs.chat_configs import STOP_STREAM_PAT
from onyx.context.search.models import SearchDoc
from onyx.prompts.constants import TRIPLE_BACKTICK
from onyx.server.query_and_chat.streaming_models import CitationInfo
from onyx.utils.logger import setup_logger

logger = setup_logger()


# ============================================================================
# Utility functions (copied for self-containment)
# ============================================================================


def in_code_block(llm_text: str) -> bool:
    """Check if we're currently inside a code block by counting triple backticks."""
    count = llm_text.count(TRIPLE_BACKTICK)
    return count % 2 != 0


# ============================================================================
# Main Citation Processor with Dynamic Mapping
# ============================================================================


class DynamicCitationProcessor:
    """
    A citation processor that accepts dynamic citation mappings.

    This processor is designed for multi-turn conversations where the citation
    number to document mapping is provided externally. It processes streaming
    tokens from an LLM, detects citations (e.g., [1], [2,3], [[4]]), and:

    1. Removes citation markers from the output text
    2. Emits CitationInfo objects for tracking
    3. Maintains the order in which documents were first cited

    Features:
    - Accepts citation number → SearchDoc mapping via update_citation_mapping()
    - Processes tokens from LLM and removes citation markers
    - Holds back tokens that might be partial citations
    - Maintains list of cited SearchDocs in order of first citation

    Example:
        processor = DynamicCitationProcessor()

        # Set up citation mapping
        processor.update_citation_mapping({1: search_doc1, 2: search_doc2})

        # Process tokens from LLM
        for token in llm_stream:
            for result in processor.process_token(token):
                if isinstance(result, str):
                    print(result)  # Display text (citations removed)
                elif isinstance(result, CitationInfo):
                    handle_citation(result)  # Track citation

        # Update mapping with more documents
        processor.update_citation_mapping({3: search_doc3, 4: search_doc4})

        # Continue processing...

        # Get cited documents at the end
        cited_docs = processor.get_cited_documents()
    """

    def __init__(
        self,
        stop_stream: str | None = STOP_STREAM_PAT,
    ):
        """
        Initialize the citation processor.

        Args:
            stop_stream: Optional stop token to halt processing early
        """
        # Citation mapping from citation number to SearchDoc
        self.citation_to_doc: dict[int, SearchDoc] = {}

        # Token processing state
        self.llm_out = ""  # entire output so far
        self.curr_segment = ""  # tokens held for citation processing
        self.hold = ""  # tokens held for stop token processing
        self.stop_stream = stop_stream

        # Citation tracking
        self.cited_documents_in_order: list[SearchDoc] = (
            []
        )  # SearchDocs in citation order
        self.cited_document_ids: set[str] = set()  # all cited document_ids
        self.recent_cited_documents: set[str] = (
            set()
        )  # recently cited (for deduplication)
        self.non_citation_count = 0

        # Citation patterns
        # Matches potential incomplete citations: '[', '[[', '[1', '[[1', '[1,', '[1, ', etc.
        # Also matches unicode bracket variants: 【, ［
        self.possible_citation_pattern = re.compile(r"([\[【［]+(?:\d+,? ?)*$)")

        # Matches complete citations:
        # group 1: '[[1]]', [[2]], etc. (also matches 【【1】】, ［［1］］, 【1】, ［1］)
        # group 2: '[1]', '[1, 2]', '[1,2,16]', etc. (also matches unicode variants)
        self.citation_pattern = re.compile(
            r"([\[【［]{2}\d+[\]】］]{2})|([\[【［]\d+(?:, ?\d+)*[\]】］])"
        )

    def update_citation_mapping(self, citation_mapping: dict[int, SearchDoc]) -> None:
        """
        Update the citation number to SearchDoc mapping.

        This can be called multiple times to add or update mappings. New mappings
        will be merged with existing ones.

        Args:
            citation_mapping: Dictionary mapping citation numbers (1, 2, 3, ...) to SearchDoc objects
        """
        # Filter out duplicate keys and only add non-duplicates
        # Reason for this is that OpenURL may have the same citation number as a Web Search result
        # For those, we should just keep the web search citation and snippet etc.
        duplicate_keys = set(citation_mapping.keys()) & set(self.citation_to_doc.keys())
        non_duplicate_mapping = {
            k: v for k, v in citation_mapping.items() if k not in duplicate_keys
        }
        self.citation_to_doc.update(non_duplicate_mapping)

    def process_token(
        self, token: str | None
    ) -> Generator[str | CitationInfo, None, None]:
        """
        Process a token from the LLM stream.

        This method:
        1. Accumulates tokens until a complete citation or non-citation is found
        2. Holds back potential partial citations (e.g., "[", "[1")
        3. Yields text chunks when they're safe to display (with citations REMOVED)
        4. Yields CitationInfo when citations are detected
        5. Handles code blocks (avoids processing citations inside code)
        6. Handles stop tokens

        Args:
            token: The next token from the LLM stream, or None to signal end of stream

        Yields:
            - str: Text chunks to display (citations removed)
            - CitationInfo: Citation metadata when a citation is detected
        """
        # None -> end of stream, flush remaining segment
        if token is None:
            if self.curr_segment:
                yield self.curr_segment
            return

        # Handle stop stream token
        if self.stop_stream:
            next_hold = self.hold + token
            if self.stop_stream in next_hold:
                return
            if next_hold == self.stop_stream[: len(next_hold)]:
                self.hold = next_hold
                return
            token = next_hold
            self.hold = ""

        self.curr_segment += token
        self.llm_out += token

        # Handle code blocks without language tags
        # If we see ``` followed by \n, add "plaintext" language specifier
        if "`" in self.curr_segment:
            if self.curr_segment.endswith("`"):
                pass
            elif "```" in self.curr_segment:
                parts = self.curr_segment.split("```")
                if len(parts) > 1 and len(parts[1]) > 0:
                    piece_that_comes_after = parts[1][0]
                    if piece_that_comes_after == "\n" and in_code_block(self.llm_out):
                        self.curr_segment = self.curr_segment.replace(
                            "```", "```plaintext"
                        )

        # Look for citations in current segment
        citation_matches = list(self.citation_pattern.finditer(self.curr_segment))
        possible_citation_found = bool(
            re.search(self.possible_citation_pattern, self.curr_segment)
        )

        result = ""
        if citation_matches and not in_code_block(self.llm_out):
            match_idx = 0
            for match in citation_matches:
                match_span = match.span()

                # Get text before/between citations
                intermatch_str = self.curr_segment[match_idx : match_span[0]]
                self.non_citation_count += len(intermatch_str)
                match_idx = match_span[1]

                # Check if there is already a space before this citation
                if intermatch_str:
                    has_leading_space = intermatch_str[-1].isspace()
                else:
                    # No text between citations (consecutive citations)
                    # If match_idx > 0, we've already processed a citation, so don't add space
                    if match_idx > 0:
                        # Consecutive citations - don't add space between them
                        has_leading_space = True
                    else:
                        # Citation at start of segment - check if previous output has space
                        segment_start_idx = len(self.llm_out) - len(self.curr_segment)
                        if segment_start_idx > 0:
                            has_leading_space = self.llm_out[
                                segment_start_idx - 1
                            ].isspace()
                        else:
                            has_leading_space = False

                # Reset recent citations if no citations found for a while
                if self.non_citation_count > 5:
                    self.recent_cited_documents.clear()

                # Yield text before citation FIRST (preserve order)
                if intermatch_str:
                    yield intermatch_str

                # Process the citation (returns formatted citation text and CitationInfo objects)
                citation_text, citation_info_list = self._process_citation(
                    match, has_leading_space
                )
                # Yield CitationInfo objects BEFORE the citation text
                # This allows the frontend to receive citation metadata before the token
                # that contains [[n]](link), enabling immediate rendering
                for citation in citation_info_list:
                    yield citation
                # Then yield the formatted citation text
                if citation_text:
                    yield citation_text
                self.non_citation_count = 0

            # Leftover text could be part of next citation
            self.curr_segment = self.curr_segment[match_idx:]
            self.non_citation_count = len(self.curr_segment)

        # Hold onto the current segment if potential citations found, otherwise stream it
        if not possible_citation_found:
            result += self.curr_segment
            self.non_citation_count += len(self.curr_segment)
            self.curr_segment = ""

        if result:
            yield result

    def _process_citation(
        self, match: re.Match, has_leading_space: bool
    ) -> tuple[str, list[CitationInfo]]:
        """
        Process a single citation match and return formatted citation text and citation info objects.

        The match string can look like '[1]', '[1, 13, 6]', '[[4]]', '【1】', etc.

        This method:
        1. Extracts citation numbers from the match
        2. Looks up the corresponding SearchDoc from the mapping
        3. Skips duplicate citations if they were recently cited
        4. Creates formatted citation text like [n](link) for each citation
        5. Creates CitationInfo objects for new citations

        Args:
            match: Regex match object containing the citation
            has_leading_space: Whether the text before the citation has a leading space
        Returns:
            Tuple of (formatted_citation_text, list[CitationInfo])
            - formatted_citation_text: Markdown-formatted citation text like [1](link) [2](link)
            - citation_info_list: List of CitationInfo objects
        """
        citation_str: str = match.group()  # e.g., '[1]', '[1, 2, 3]', '[[1]]', '【1】'
        formatted = (
            match.lastindex == 1
        )  # True means already in form '[[1]]' or '【【1】】'

        citation_info_list: list[CitationInfo] = []
        formatted_citation_parts: list[str] = []

        # Extract citation numbers - regex ensures matched brackets, so we can simply slice
        citation_content = citation_str[2:-2] if formatted else citation_str[1:-1]

        for num_str in citation_content.split(","):
            num_str = num_str.strip()
            if not num_str:
                continue

            try:
                num = int(num_str)
            except ValueError:
                # Invalid citation, skip it
                logger.warning(f"Invalid citation number format: {num_str}")
                continue

            # Check if we have a mapping for this citation number
            if num not in self.citation_to_doc:
                logger.warning(
                    f"Citation number {num} not found in mapping. "
                    f"Available: {list(self.citation_to_doc.keys())}"
                )
                continue

            # Get the SearchDoc
            search_doc = self.citation_to_doc[num]
            doc_id = search_doc.document_id
            link = search_doc.link or ""

            # Always format the citation text as [[n]](link)
            formatted_citation_parts.append(f"[[{num}]]({link})")

            # Skip creating CitationInfo for citations of the same work if cited recently (deduplication)
            if doc_id in self.recent_cited_documents:
                continue
            self.recent_cited_documents.add(doc_id)

            # Track cited documents and create CitationInfo only for new citations
            if doc_id not in self.cited_document_ids:
                self.cited_document_ids.add(doc_id)
                self.cited_documents_in_order.append(search_doc)
                citation_info_list.append(
                    CitationInfo(
                        citation_number=num,
                        document_id=doc_id,
                    )
                )

        # Join all citation parts with spaces
        formatted_citation_text = " ".join(formatted_citation_parts)

        # Apply leading space only if the text didn't already have one
        if formatted_citation_text and not has_leading_space:
            formatted_citation_text = " " + formatted_citation_text

        return formatted_citation_text, citation_info_list

    def get_cited_documents(self) -> list[SearchDoc]:
        """
        Get the list of cited SearchDoc objects in the order they were first cited.

        Returns:
            List of SearchDoc objects
        """
        return self.cited_documents_in_order

    def get_cited_document_ids(self) -> list[str]:
        """
        Get the list of cited document IDs in the order they were first cited.

        Returns:
            List of document IDs (strings)
        """
        return [doc.document_id for doc in self.cited_documents_in_order]

    @property
    def num_cited_documents(self) -> int:
        """Get the number of documents that have been cited."""
        return len(self.cited_document_ids)

    def reset_recent_citations(self) -> None:
        """
        Reset the recent citations tracker.

        This can be called to allow previously cited documents to be cited again
        without being filtered out by the deduplication logic.
        """
        self.recent_cited_documents.clear()

    def get_next_citation_number(self) -> int:
        """
        Get the next available citation number.

        This method returns the next citation number that should be used for new documents.
        If no citations exist yet, it returns 1. Otherwise, it returns max + 1.

        Returns:
            The next available citation number (1-indexed)
        """
        if not self.citation_to_doc:
            return 1
        return max(self.citation_to_doc.keys()) + 1
