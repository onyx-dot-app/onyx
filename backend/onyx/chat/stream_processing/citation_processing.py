import re
from collections.abc import Generator

from onyx.chat.models import CitationInfo
from onyx.chat.models import LlmDoc
from onyx.chat.models import OnyxAnswerPiece
from onyx.chat.models import ResponsePart
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

    # TODO: should reference previous citation processing, rework previous, or completely use new one?
    def multi_process_token(
        self, parsed_object: ResponsePart
    ) -> Generator[ResponsePart, None, None]:
        # if isinstance(parsed_object,OnyxAnswerPiece):
        #     # standard citation processing
        #     yield from self.process_token(parsed_object.answer_piece)

        # elif isinstance(parsed_object, AgentAnswerPiece):
        #     # citation processing for agent answer pieces
        #     for token in self.process_token(parsed_object.answer_piece):
        #         if isinstance(token, CitationInfo):
        #             yield token
        #         else:
        #             yield AgentAnswerPiece(answer_piece=token.answer_piece or '',
        #  answer_type=parsed_object.answer_type, level=parsed_object.level,
        # level_question_nr=parsed_object.level_question_nr)

        # level = getattr(parsed_object, "level", None)
        # level_question_nr = getattr(parsed_object, "level_question_nr", None)

        # if isinstance(parsed_object, (AgentAnswerPiece, OnyxAnswerPiece)):
        #     # logger.debug(f"FA {parsed_object.answer_piece}")
        #     if isinstance(parsed_object, AgentAnswerPiece):
        #         token = parsed_object.answer_piece
        #         level = parsed_object.level
        #         level_question_nr = parsed_object.level_question_nr
        #     else:
        #         yield parsed_object
        #         return
        #         # raise ValueError(
        #         #     f"Invalid parsed object type: {type(parsed_object)}"
        #         # )

        #     if not citation_potential[level][level_question_nr] and token:
        #         if token.startswith(" ["):
        #             citation_potential[level][level_question_nr] = True
        #             current_yield_components[level][level_question_nr] = [token]
        #         else:
        #             yield parsed_object
        #     elif token and citation_potential[level][level_question_nr]:
        #         current_yield_components[level][level_question_nr].append(token)
        #         current_yield_str[level][level_question_nr] = "".join(
        #             current_yield_components[level][level_question_nr]
        #         )

        #         if current_yield_str[level][level_question_nr].strip().startswith(
        #             "[D"
        #         ) or current_yield_str[level][level_question_nr].strip().startswith(
        #             "[Q"
        #         ):
        #             citation_potential[level][level_question_nr] = True

        #         else:
        #             citation_potential[level][level_question_nr] = False
        #             parsed_object = _set_combined_token_value(
        #                 current_yield_str[level][level_question_nr], parsed_object
        #             )
        #             yield parsed_object

        #         if (
        #             len(current_yield_components[level][level_question_nr]) > 15
        #         ):  # ??? 15?
        #             citation_potential[level][level_question_nr] = False
        #             parsed_object = _set_combined_token_value(
        #                 current_yield_str[level][level_question_nr], parsed_object
        #             )
        #             yield parsed_object
        #         elif "]" in current_yield_str[level][level_question_nr]:
        #             section_split = current_yield_str[level][level_question_nr].split(
        #                 "]"
        #             )
        #             section_split[0] + "]"  # dead code?
        #             start_of_next_section = "]".join(section_split[1:])
        #             citation_string = current_yield_str[level][level_question_nr][
        #                 : -len(start_of_next_section)
        #             ]
        #             if "[D" in citation_string:
        #                 cite_open_bracket_marker, cite_close_bracket_marker = (
        #                     "[",
        #                     "]",
        #                 )
        #                 cite_identifyer = "D"

        #                 try:
        #                     cited_document = int(
        #                         citation_string[level][level_question_nr][2:-1]
        #                     )
        #                     if level and level_question_nr:
        #                         link = agent_document_citations[int(level)][
        #                             int(level_question_nr)
        #                         ][cited_document].link
        #                     else:
        #                         link = ""
        #                 except (ValueError, IndexError):
        #                     link = ""
        #             elif "[Q" in citation_string:
        #                 cite_open_bracket_marker, cite_close_bracket_marker = (
        #                     "{",
        #                     "}",
        #                 )
        #                 cite_identifyer = "Q"
        #             else:
        #                 pass

        #             citation_string = citation_string.replace(
        #                 "[" + cite_identifyer,
        #                 cite_open_bracket_marker * 2,
        #             ).replace("]", cite_close_bracket_marker * 2)

        #             if cite_identifyer == "D":
        #                 citation_string += f"({link})"

        #             parsed_object = _set_combined_token_value(
        #                 citation_string, parsed_object
        #             )

        #             yield parsed_object

        #             current_yield_components[level][level_question_nr] = [
        #                 start_of_next_section
        #             ]
        #             if not start_of_next_section.strip().startswith("["):
        #                 citation_potential[level][level_question_nr] = False

        # elif isinstance(parsed_object, ExtendedToolResponse):
        #     if parsed_object.id == "search_response_summary":
        #         level = parsed_object.level
        #         level_question_nr = parsed_object.level_question_nr
        #         for inference_section in parsed_object.response.top_sections:
        #             doc_link = inference_section.center_chunk.source_links[0]
        #             doc_title = inference_section.center_chunk.title
        #             doc_id = inference_section.center_chunk.document_id

        #             if (
        #                 doc_id
        #                 not in agent_question_citations_used_docs[level][
        #                     level_question_nr
        #                 ]
        #             ):
        #                 if level not in agent_document_citations:
        #                     agent_document_citations[level] = {}
        #                 if level_question_nr not in agent_document_citations[level]:
        #                     agent_document_citations[level][level_question_nr] = []

        #                 agent_document_citations[level][level_question_nr].append(
        #                     AgentDocumentCitations(
        #                         document_id=doc_id,
        #                         document_title=doc_title,
        #                         link=doc_link,
        #                     )
        #                 )
        #                 agent_question_citations_used_docs[level][
        #                     level_question_nr
        #                 ].append(doc_id)

        yield parsed_object

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

                if 1 <= numerical_value <= self.max_citation_num:
                    context_llm_doc = self.context_docs[numerical_value - 1]
                    final_citation_num = self.final_order_mapping[
                        context_llm_doc.document_id
                    ]

                    if final_citation_num not in self.citation_order:
                        self.citation_order.append(final_citation_num)

                    citation_order_idx = (
                        self.citation_order.index(final_citation_num) + 1
                    )

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
