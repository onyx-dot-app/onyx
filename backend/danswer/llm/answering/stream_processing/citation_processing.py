import re
from collections.abc import Iterator

from danswer.chat.models import AnswerQuestionStreamReturn
from danswer.chat.models import CitationInfo
from danswer.chat.models import DanswerAnswerPiece
from danswer.chat.models import LlmDoc
from danswer.configs.chat_configs import STOP_STREAM_PAT
from danswer.llm.answering.models import StreamProcessor
from danswer.llm.answering.stream_processing.utils import map_document_id_order
from danswer.prompts.constants import TRIPLE_BACKTICK
from danswer.utils.logger import setup_logger


logger = setup_logger()


def in_code_block(llm_text: str) -> bool:
    count = llm_text.count(TRIPLE_BACKTICK)
    return count % 2 != 0


def extract_citations_from_stream(
    tokens: Iterator[str],
    context_docs: list[LlmDoc],
    doc_id_to_rank_map: dict[str, int],
    stop_stream: str | None = STOP_STREAM_PAT,
) -> Iterator[DanswerAnswerPiece | CitationInfo]:
    llm_out = ""
    max_citation_num = len(context_docs)
    curr_segment = ""
    prepend_bracket = False
    cited_inds = set()
    hold = ""
    for raw_token in tokens:
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

        # Special case of [1][ where ][ is a single token
        # This is where the model attempts to do consecutive citations like [1][2]
        if prepend_bracket:
            curr_segment += "[" + curr_segment
            prepend_bracket = False

        curr_segment += token
        llm_out += token

        possible_citation_pattern = r"(\[\d*$)"  # [1, [, etc
        possible_citation_found = re.search(possible_citation_pattern, curr_segment)

        citation_pattern = r"\[(\d+)\]"  # [1], [2] etc
        citation_found = re.search(citation_pattern, curr_segment)

        if citation_found and not in_code_block(llm_out):
            numerical_value = int(citation_found.group(1))
            if 1 <= numerical_value <= max_citation_num:
                context_llm_doc = context_docs[
                    numerical_value - 1
                ]  # remove 1 index offset

                link = context_llm_doc.link
                target_citation_num = doc_id_to_rank_map[context_llm_doc.document_id]

                # Use the citation number for the document's rank in
                # the search (or selected docs) results
                curr_segment = re.sub(
                    rf"\[{numerical_value}\]", f"[{target_citation_num}]", curr_segment
                )

                if target_citation_num not in cited_inds:
                    cited_inds.add(target_citation_num)
                    yield CitationInfo(
                        citation_num=target_citation_num,
                        document_id=context_llm_doc.document_id,
                    )

                if link:
                    curr_segment = re.sub(r"\[", "[[", curr_segment, count=1)
                    curr_segment = re.sub("]", f"]]({link})", curr_segment, count=1)

                # In case there's another open bracket like [1][, don't want to match this
            possible_citation_found = None

        # if we see "[", but haven't seen the right side, hold back - this may be a
        # citation that needs to be replaced with a link
        if possible_citation_found:
            continue

        # Special case with back to back citations [1][2]
        if curr_segment and curr_segment[-1] == "[":
            curr_segment = curr_segment[:-1]
            prepend_bracket = True

        yield DanswerAnswerPiece(answer_piece=curr_segment)
        curr_segment = ""

    if curr_segment:
        if prepend_bracket:
            yield DanswerAnswerPiece(answer_piece="[" + curr_segment)
        else:
            yield DanswerAnswerPiece(answer_piece=curr_segment)


def build_citation_processor(
    context_docs: list[LlmDoc], search_order_docs: list[LlmDoc]
) -> StreamProcessor:
    def stream_processor(tokens: Iterator[str]) -> AnswerQuestionStreamReturn:
        yield from extract_citations_from_stream(
            tokens=tokens,
            context_docs=context_docs,
            doc_id_to_rank_map=map_document_id_order(search_order_docs),
        )

    return stream_processor
