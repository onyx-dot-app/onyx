import re
from collections.abc import Generator

from onyx.chat.models import CitationInfo
from onyx.chat.models import LlmDoc
from onyx.chat.models import OnyxAnswerPiece
from onyx.chat.stream_processing.utils import DocumentIdOrderMapping
from onyx.configs.chat_configs import STOP_STREAM_PAT
from onyx.prompts.constants import TRIPLE_BACKTICK
from onyx.utils.logger import setup_logger

logger = setup_logger()


def in_code_block(llm_text: str) -> bool:
    count = llm_text.count(TRIPLE_BACKTICK)
    return count % 2 != 0


class CitationProcessor:
    def __init__(
        self,
        context_docs: list[LlmDoc],
        final_doc_id_to_rank_map: DocumentIdOrderMapping,
        display_doc_id_to_rank_map: DocumentIdOrderMapping,
        stop_stream: str | None = STOP_STREAM_PAT,
    ):
        self.context_docs = context_docs
        self.final_doc_id_to_rank_map = final_doc_id_to_rank_map
        self.display_doc_id_to_rank_map = display_doc_id_to_rank_map
        self.stop_stream = stop_stream
        self.final_order_mapping = final_doc_id_to_rank_map.order_mapping
        self.display_order_mapping = display_doc_id_to_rank_map.order_mapping
        self.llm_out = ""
        self.max_citation_num = len(context_docs)
        self.citation_order: list[int] = []  # order of citations in the LLM output
        self.curr_segment = ""
        self.cited_inds: set[int] = set()
        self.hold = ""
        self.current_citations: list[int] = []
        self.past_cite_count = 0

    def process_token(
        self, token: str | None
    ) -> Generator[OnyxAnswerPiece | CitationInfo, None, None]:
        # None -> end of stream
        if token is None:
            yield OnyxAnswerPiece(answer_piece=self.curr_segment)
            return

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
        if "`" in self.curr_segment:
            if self.curr_segment.endswith("`"):
                pass
            elif "```" in self.curr_segment:
                piece_that_comes_after = self.curr_segment.split("```")[1][0]
                if piece_that_comes_after == "\n" and in_code_block(self.llm_out):
                    self.curr_segment = self.curr_segment.replace("```", "```plaintext")

        citation_pattern = r"\[(\d+)\]|\[\[(\d+)\]\]"  # [1], [[1]], etc.
        citations_found = list(re.finditer(citation_pattern, self.curr_segment))
        possible_citation_pattern = r"(\[+\d*$)"  # [1, [, [[, [[2, etc.
        possible_citation_found = re.search(
            possible_citation_pattern, self.curr_segment
        )

        if len(citations_found) == 0 and len(self.llm_out) - self.past_cite_count > 5:
            self.current_citations = []

        result = ""
        if citations_found and not in_code_block(self.llm_out):
            last_citation_end = 0
            length_to_add = 0
            while len(citations_found) > 0:
                citation = citations_found.pop(0)
                numerical_value = int(
                    next(group for group in citation.groups() if group is not None)
                )

                if not (1 <= numerical_value <= self.max_citation_num):
                    continue

                context_llm_doc = self.context_docs[numerical_value - 1]
                final_citation_num = self.final_order_mapping[
                    context_llm_doc.document_id
                ]

                if final_citation_num not in self.citation_order:
                    self.citation_order.append(final_citation_num)

                citation_order_idx = self.citation_order.index(final_citation_num) + 1

                # get the value that was displayed to user, should always
                # be in the display_doc_order_dict. But check anyways
                if context_llm_doc.document_id in self.display_order_mapping:
                    displayed_citation_num = self.display_order_mapping[
                        context_llm_doc.document_id
                    ]
                else:
                    displayed_citation_num = final_citation_num
                    logger.warning(
                        f"Doc {context_llm_doc.document_id} not in display_doc_order_dict. Used LLM citation number instead."
                    )

                # Skip consecutive citations of the same work
                if final_citation_num in self.current_citations:
                    start, end = citation.span()
                    real_start = length_to_add + start
                    diff = end - start
                    self.curr_segment = (
                        self.curr_segment[: length_to_add + start]
                        + self.curr_segment[real_start + diff :]
                    )
                    length_to_add -= diff
                    continue

                # Handle edge case where LLM outputs citation itself
                if self.curr_segment.startswith("[["):
                    match = re.match(r"\[\[(\d+)\]\]", self.curr_segment)
                    if match:
                        try:
                            doc_id = int(match.group(1))
                            context_llm_doc = self.context_docs[doc_id - 1]
                            yield CitationInfo(
                                # citation_num is now the number post initial ranking, i.e. as displayed to user
                                citation_num=displayed_citation_num,
                                document_id=context_llm_doc.document_id,
                            )
                        except Exception as e:
                            logger.warning(
                                f"Manual LLM citation didn't properly cite documents {e}"
                            )
                    else:
                        logger.warning(
                            "Manual LLM citation wasn't able to close brackets"
                        )
                    continue

                link = context_llm_doc.link

                self.past_cite_count = len(self.llm_out)
                self.current_citations.append(final_citation_num)

                if citation_order_idx not in self.cited_inds:
                    self.cited_inds.add(citation_order_idx)
                    yield CitationInfo(
                        # citation number is now the one that was displayed to user
                        citation_num=displayed_citation_num,
                        document_id=context_llm_doc.document_id,
                    )

                start, end = citation.span()
                if link:
                    prev_length = len(self.curr_segment)
                    self.curr_segment = (
                        self.curr_segment[: start + length_to_add]
                        + f"[[{displayed_citation_num}]]({link})"  # use the value that was displayed to user
                        + self.curr_segment[end + length_to_add :]
                    )
                    length_to_add += len(self.curr_segment) - prev_length
                else:
                    prev_length = len(self.curr_segment)
                    self.curr_segment = (
                        self.curr_segment[: start + length_to_add]
                        + f"[[{displayed_citation_num}]]()"  # use the value that was displayed to user
                        + self.curr_segment[end + length_to_add :]
                    )
                    length_to_add += len(self.curr_segment) - prev_length

                last_citation_end = end + length_to_add

            if last_citation_end > 0:
                result += self.curr_segment[:last_citation_end]
                self.curr_segment = self.curr_segment[last_citation_end:]

        if not possible_citation_found:
            result += self.curr_segment
            self.curr_segment = ""

        if result:
            yield OnyxAnswerPiece(answer_piece=result)
