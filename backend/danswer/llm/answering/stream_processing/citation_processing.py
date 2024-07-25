import re
from collections.abc import Iterator

from danswer.chat.models import AnswerQuestionStreamReturn
from danswer.chat.models import CitationInfo
from danswer.chat.models import DanswerAnswerPiece
from danswer.chat.models import LlmDoc
from danswer.configs.chat_configs import STOP_STREAM_PAT
from danswer.llm.answering.models import StreamProcessor
from danswer.llm.answering.stream_processing.utils import DocumentIdOrderMapping
from danswer.prompts.constants import TRIPLE_BACKTICK
from danswer.utils.logger import setup_logger


logger = setup_logger()


def in_code_block(llm_text: str) -> bool:
    count = llm_text.count(TRIPLE_BACKTICK)
    return count % 2 != 0


def extract_citations_from_stream(
    tokens: Iterator[str],
    context_docs: list[LlmDoc],
    doc_id_to_rank_map: DocumentIdOrderMapping,
    stop_stream: str | None = STOP_STREAM_PAT,
) -> Iterator[DanswerAnswerPiece | CitationInfo]:
    """
    Key aspects:

    1. Stream Processing:
    - Processes tokens one by one, allowing for real-time handling of large texts.

    2. Citation Detection:
    - Uses regex to find citations in the format [number].
    - Example: [1], [2], etc.

    3. Citation Mapping:
    - Maps detected citation numbers to actual document ranks using doc_id_to_rank_map.
    - Example: [1] might become [3] if doc_id_to_rank_map maps it to 3.

    4. Citation Formatting:
    - Replaces citations with properly formatted versions.
    - Adds links if available: [[1]](https://example.com)
    - Handles cases where links are not available: [[1]]()

    5. Duplicate Handling:
    - Skips consecutive citations of the same document to avoid redundancy.

    6. Output Generation:
    - Yields DanswerAnswerPiece objects for regular text.
    - Yields CitationInfo objects for each unique citation encountered.

    7. Context Awareness:
    - Uses context_docs to access document information for citations.

    This function effectively processes a stream of text, identifies and reformats citations,
    and provides both the processed text and citation information as output.
    """
    order_mapping = doc_id_to_rank_map.order_mapping
    llm_out = ""
    max_citation_num = len(context_docs)
    citation_order = []
    curr_segment = ""
    cited_inds = set()
    hold = ""

    raw_out = ""
    current_citations: list[int] = []
    past_cite_count = 0
    for raw_token in tokens:
        raw_out += raw_token
        if stop_stream:
            next_hold = hold + raw_token
            if stop_stream in next_hold:
                break
            if next_hold == stop_stream[: len(next_hold)]:
                hold = next_hold
                continue
            token = next_hold
            hold = ""
        else:
            token = raw_token

        curr_segment += token
        llm_out += token

        citation_pattern = r"\[(\d+)\]"

        citations_found = list(re.finditer(citation_pattern, curr_segment))
        possible_citation_pattern = r"(\[\d*$)"  # [1, [, etc
        possible_citation_found = re.search(possible_citation_pattern, curr_segment)

        # `past_cite_count`: number of characters since past citation
        # 5 to ensure a citation hasn't occured
        if len(citations_found) == 0 and len(llm_out) - past_cite_count > 5:
            current_citations = []

        if citations_found and not in_code_block(llm_out):
            last_citation_end = 0
            length_to_add = 0
            while len(citations_found) > 0:
                citation = citations_found.pop(0)
                numerical_value = int(citation.group(1))

                if 1 <= numerical_value <= max_citation_num:
                    context_llm_doc = context_docs[numerical_value - 1]
                    real_citation_num = order_mapping[context_llm_doc.document_id]

                    if real_citation_num not in citation_order:
                        citation_order.append(real_citation_num)

                    target_citation_num = citation_order.index(real_citation_num) + 1

                    # Skip consecutive citations of the same work
                    if target_citation_num in current_citations:
                        start, end = citation.span()
                        real_start = length_to_add + start
                        diff = end - start
                        curr_segment = (
                            curr_segment[: length_to_add + start]
                            + curr_segment[real_start + diff :]
                        )
                        length_to_add -= diff
                        continue

                    link = context_llm_doc.link

                    # Replace the citation in the current segment
                    start, end = citation.span()
                    curr_segment = (
                        curr_segment[: start + length_to_add]
                        + f"[{target_citation_num}]"
                        + curr_segment[end + length_to_add :]
                    )

                    past_cite_count = len(llm_out)
                    current_citations.append(target_citation_num)

                    if target_citation_num not in cited_inds:
                        cited_inds.add(target_citation_num)
                        yield CitationInfo(
                            citation_num=target_citation_num,
                            document_id=context_llm_doc.document_id,
                        )

                    if link:
                        prev_length = len(curr_segment)
                        curr_segment = (
                            curr_segment[: start + length_to_add]
                            + f"[[{target_citation_num}]]({link})"
                            + curr_segment[end + length_to_add :]
                        )
                        length_to_add += len(curr_segment) - prev_length

                    else:
                        prev_length = len(curr_segment)
                        curr_segment = (
                            curr_segment[: start + length_to_add]
                            + f"[[{target_citation_num}]]()"
                            + curr_segment[end + length_to_add :]
                        )
                        length_to_add += len(curr_segment) - prev_length
                    last_citation_end = end + length_to_add

            if last_citation_end > 0:
                yield DanswerAnswerPiece(answer_piece=curr_segment[:last_citation_end])
                curr_segment = curr_segment[last_citation_end:]
        if possible_citation_found:
            continue
        yield DanswerAnswerPiece(answer_piece=curr_segment)
        curr_segment = ""

    if curr_segment:
        yield DanswerAnswerPiece(answer_piece=curr_segment)


def build_citation_processor(
    context_docs: list[LlmDoc], doc_id_to_rank_map: DocumentIdOrderMapping
) -> StreamProcessor:
    def stream_processor(tokens: Iterator[str]) -> AnswerQuestionStreamReturn:
        yield from extract_citations_from_stream(
            tokens=tokens,
            context_docs=context_docs,
            doc_id_to_rank_map=doc_id_to_rank_map,
        )

    return stream_processor
