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
        self.context_docs = context_docs  # list of docs in the order the LLM sees
        self.final_order_mapping = final_doc_id_to_rank_map.order_mapping
        self.display_order_mapping = display_doc_id_to_rank_map.order_mapping
        self.max_citation_num = len(context_docs)
        self.stop_stream = stop_stream

        self.llm_out = ""  # entire output so far
        self.curr_segment = ""  # tokens held for citation processing
        self.hold = ""  # tokens held for stop token processing

        self.recent_cited_documents: set[str] = set()  # docs recently cited
        self.cited_documents: set[str] = set()  # docs cited in the entire stream
        self.non_citation_count = 0

        # '[', '[[', '[1', '[[1', '[1,', '[1, ', '[1,2', '[1, 2,', etc.
        self.possible_citation_pattern = re.compile(r"(\[+(?:\d+,? ?)*$)")

        # group 1: '[[1]]', [[2]], etc.
        # group 2: '[1]', '[1, 2]', '[1,2,16]', etc.
        self.citation_pattern = re.compile(r"(\[\[\d+\]\])|(\[\d+(?:, ?\d+)*\])")

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

        citation_matches = list(self.citation_pattern.finditer(self.curr_segment))
        possible_citation_found = bool(
            re.search(self.possible_citation_pattern, self.curr_segment)
        )

        result = ""
        if citation_matches and not in_code_block(self.llm_out):
            match_idx = 0
            for match in citation_matches:
                match_span = match.span()

                # add stuff before/between the matches
                intermatch_str = self.curr_segment[match_idx : match_span[0]]
                self.non_citation_count += len(intermatch_str)
                match_idx = match_span[1]
                result += intermatch_str

                # reset recent citations if no citations found for a while
                if self.non_citation_count > 5:
                    self.recent_cited_documents.clear()

                # process the citation string and emit citation info
                res, citation_info = self.process_citation(match)
                result += res
                for citation in citation_info:
                    yield citation
                self.non_citation_count = 0

            # leftover could be part of next citation
            self.curr_segment = self.curr_segment[match_idx:]
            self.non_citation_count = len(self.curr_segment)

        # hold onto the current segment if potential citations found, otherwise stream
        if not possible_citation_found:
            result += self.curr_segment
            self.non_citation_count += len(self.curr_segment)
            self.curr_segment = ""

        if result:
            yield OnyxAnswerPiece(answer_piece=result)

    def process_citation(self, match: re.Match) -> tuple[str, list[CitationInfo]]:
        """
        Process a single citation match and return the citation string and the
        citation info. The match string can look like '[1]', '[1, 13, 6], '[[4]]', etc.
        """
        citation_str: str = match.group()  # e.g., '[1]', '[1, 2, 3]', '[[1]]', etc.
        formatted = match.lastindex == 1  # True means already in the form '[[1]]'

        final_processed_str = ""
        final_citation_info: list[CitationInfo] = []

        # process the citation_str
        citation_content = citation_str[2:-2] if formatted else citation_str[1:-1]
        for num in (int(num) for num in citation_content.split(",")):
            # keep invalid citations as is
            if not (1 <= num <= self.max_citation_num):
                final_processed_str += f"[[{num}]]" if formatted else f"[{num}]"
                continue

            # translate the citation number of the LLM to what the user sees
            # should always be in the display_doc_order_dict. But check anyways
            context_llm_doc = self.context_docs[num - 1]
            llm_docid = context_llm_doc.document_id
            if llm_docid not in self.display_order_mapping:
                logger.warning(
                    f"Doc {llm_docid} not in display_doc_order_dict. "
                    "Used LLM citation number instead."
                )
            displayed_citation_num = self.display_order_mapping.get(
                llm_docid, self.final_order_mapping[llm_docid]
            )

            # skip citations of the same work if cited recently
            if llm_docid in self.recent_cited_documents:
                continue
            self.recent_cited_documents.add(llm_docid)

            # format the citation string
            if formatted:
                final_processed_str += citation_str
            else:
                link = context_llm_doc.link or ""
                final_processed_str += f"[[{displayed_citation_num}]]({link})"

            # create the citation info
            if llm_docid not in self.cited_documents:
                self.cited_documents.add(llm_docid)
                final_citation_info.append(
                    CitationInfo(
                        citation_num=displayed_citation_num,
                        document_id=llm_docid,
                    )
                )

        return final_processed_str, final_citation_info
