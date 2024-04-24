import math
import re
from collections.abc import Callable
from collections.abc import Generator
from collections.abc import Iterator
from json import JSONDecodeError
from typing import Optional

import regex

from danswer.chat.models import AnswerQuestionStreamReturn
from danswer.chat.models import DanswerAnswer
from danswer.chat.models import DanswerAnswerPiece
from danswer.chat.models import DanswerQuote
from danswer.chat.models import DanswerQuotes
from danswer.chat.models import LlmDoc
from danswer.configs.chat_configs import QUOTE_ALLOWED_ERROR_PERCENT
from danswer.prompts.constants import ANSWER_PAT
from danswer.prompts.constants import QUOTE_PAT
from danswer.prompts.constants import UNCERTAINTY_PAT
from danswer.search.models import InferenceChunk
from danswer.utils.logger import setup_logger
from danswer.utils.text_processing import clean_model_quote
from danswer.utils.text_processing import clean_up_code_blocks
from danswer.utils.text_processing import extract_embedded_json
from danswer.utils.text_processing import shared_precompare_cleanup


logger = setup_logger()


def _extract_answer_quotes_freeform(
    answer_raw: str,
) -> tuple[Optional[str], Optional[list[str]]]:
    """Splits the model output into an Answer and 0 or more Quote sections.
    Splits by the Quote pattern, if not exist then assume it's all answer and no quotes
    """
    # If no answer section, don't care about the quote
    if answer_raw.lower().strip().startswith(QUOTE_PAT.lower()):
        return None, None

    # Sometimes model regenerates the Answer: pattern despite it being provided in the prompt
    if answer_raw.lower().startswith(ANSWER_PAT.lower()):
        answer_raw = answer_raw[len(ANSWER_PAT) :]

    # Accept quote sections starting with the lower case version
    answer_raw = answer_raw.replace(
        f"\n{QUOTE_PAT}".lower(), f"\n{QUOTE_PAT}"
    )  # Just in case model unreliable

    sections = re.split(rf"(?<=\n){QUOTE_PAT}", answer_raw)
    sections_clean = [
        str(section).strip() for section in sections if str(section).strip()
    ]
    if not sections_clean:
        return None, None

    answer = str(sections_clean[0])
    if len(sections) == 1:
        return answer, None
    return answer, sections_clean[1:]


def _extract_answer_quotes_json(
    answer_dict: dict[str, str | list[str]]
) -> tuple[Optional[str], Optional[list[str]]]:
    answer_dict = {k.lower(): v for k, v in answer_dict.items()}
    answer = str(answer_dict.get("answer"))
    quotes = answer_dict.get("quotes") or answer_dict.get("quote")
    if isinstance(quotes, str):
        quotes = [quotes]
    return answer, quotes


def _extract_answer_json(raw_model_output: str) -> dict:
    try:
        answer_json = extract_embedded_json(raw_model_output)
    except (ValueError, JSONDecodeError):
        # LLMs get confused when handling the list in the json. Sometimes it doesn't attend
        # enough to the previous { token so it just ends the list of quotes and stops there
        # here, we add logic to try to fix this LLM error.
        answer_json = extract_embedded_json(raw_model_output + "}")

    if "answer" not in answer_json:
        raise ValueError("Model did not output an answer as expected.")

    return answer_json


def match_quotes_to_docs(
    quotes: list[str],
    docs: list[LlmDoc] | list[InferenceChunk],
    max_error_percent: float = QUOTE_ALLOWED_ERROR_PERCENT,
    fuzzy_search: bool = False,
    prefix_only_length: int = 100,
) -> DanswerQuotes:
    danswer_quotes: list[DanswerQuote] = []
    for quote in quotes:
        max_edits = math.ceil(float(len(quote)) * max_error_percent)

        for doc in docs:
            if not doc.source_links:
                continue

            quote_clean = shared_precompare_cleanup(
                clean_model_quote(quote, trim_length=prefix_only_length)
            )
            chunk_clean = shared_precompare_cleanup(doc.content)

            # Finding the offset of the quote in the plain text
            if fuzzy_search:
                re_search_str = (
                    r"(" + re.escape(quote_clean) + r"){e<=" + str(max_edits) + r"}"
                )
                found = regex.search(re_search_str, chunk_clean)
                if not found:
                    continue
                offset = found.span()[0]
            else:
                if quote_clean not in chunk_clean:
                    continue
                offset = chunk_clean.index(quote_clean)

            # Extracting the link from the offset
            curr_link = None
            for link_offset, link in doc.source_links.items():
                # Should always find one because offset is at least 0 and there
                # must be a 0 link_offset
                if int(link_offset) <= offset:
                    curr_link = link
                else:
                    break

            danswer_quotes.append(
                DanswerQuote(
                    quote=quote,
                    document_id=doc.document_id,
                    link=curr_link,
                    source_type=doc.source_type,
                    semantic_identifier=doc.semantic_identifier,
                    blurb=doc.blurb,
                )
            )
            break

    return DanswerQuotes(quotes=danswer_quotes)


def separate_answer_quotes(
    answer_raw: str, is_json_prompt: bool = False
) -> tuple[Optional[str], Optional[list[str]]]:
    """Takes in a raw model output and pulls out the answer and the quotes sections."""
    if is_json_prompt:
        model_raw_json = _extract_answer_json(answer_raw)
        return _extract_answer_quotes_json(model_raw_json)

    return _extract_answer_quotes_freeform(clean_up_code_blocks(answer_raw))


def process_answer(
    answer_raw: str,
    docs: list[LlmDoc],
    is_json_prompt: bool = True,
) -> tuple[DanswerAnswer, DanswerQuotes]:
    """Used (1) in the non-streaming case to process the model output
    into an Answer and Quotes AND (2) after the complete streaming response
    has been received to process the model output into an Answer and Quotes."""
    answer, quote_strings = separate_answer_quotes(answer_raw, is_json_prompt)
    if answer == UNCERTAINTY_PAT or not answer:
        if answer == UNCERTAINTY_PAT:
            logger.debug("Answer matched UNCERTAINTY_PAT")
        else:
            logger.debug("No answer extracted from raw output")
        return DanswerAnswer(answer=None), DanswerQuotes(quotes=[])

    logger.info(f"Answer: {answer}")
    if not quote_strings:
        logger.debug("No quotes extracted from raw output")
        return DanswerAnswer(answer=answer), DanswerQuotes(quotes=[])
    logger.info(f"All quotes (including unmatched): {quote_strings}")
    quotes = match_quotes_to_docs(quote_strings, docs)
    logger.debug(f"Final quotes: {quotes}")

    return DanswerAnswer(answer=answer), quotes


def _stream_json_answer_end(answer_so_far: str, next_token: str) -> bool:
    next_token = next_token.replace('\\"', "")
    # If the previous character is an escape token, don't consider the first character of next_token
    # This does not work if it's an escaped escape sign before the " but this is rare, not worth handling
    if answer_so_far and answer_so_far[-1] == "\\":
        next_token = next_token[1:]
    if '"' in next_token:
        return True
    return False


def _extract_quotes_from_completed_token_stream(
    model_output: str, context_docs: list[LlmDoc], is_json_prompt: bool = True
) -> DanswerQuotes:
    answer, quotes = process_answer(model_output, context_docs, is_json_prompt)
    if answer:
        logger.info(answer)
    elif model_output:
        logger.warning("Answer extraction from model output failed.")

    return quotes


def process_model_tokens(
    tokens: Iterator[str],
    context_docs: list[LlmDoc],
    is_json_prompt: bool = True,
) -> Generator[DanswerAnswerPiece | DanswerQuotes, None, None]:
    """Used in the streaming case to process the model output
    into an Answer and Quotes

    Yields Answer tokens back out in a dict for streaming to frontend
    When Answer section ends, yields dict with answer_finished key
    Collects all the tokens at the end to form the complete model output"""
    quote_pat = f"\n{QUOTE_PAT}"
    # Sometimes worse model outputs new line instead of :
    quote_loose = f"\n{quote_pat[:-1]}\n"
    # Sometime model outputs two newlines before quote section
    quote_pat_full = f"\n{quote_pat}"
    model_output: str = ""
    found_answer_start = False if is_json_prompt else True
    found_answer_end = False
    hold_quote = ""
    for token in tokens:
        model_previous = model_output
        model_output += token

        if not found_answer_start and '{"answer":"' in re.sub(r"\s", "", model_output):
            # Note, if the token that completes the pattern has additional text, for example if the token is "?
            # Then the chars after " will not be streamed, but this is ok as it prevents streaming the ? in the
            # event that the model outputs the UNCERTAINTY_PAT
            found_answer_start = True

            # Prevent heavy cases of hallucinations where model is not even providing a json until later
            if is_json_prompt and len(model_output) > 40:
                logger.warning("LLM did not produce json as prompted")
                found_answer_end = True

            continue

        if found_answer_start and not found_answer_end:
            if is_json_prompt and _stream_json_answer_end(model_previous, token):
                found_answer_end = True
                yield DanswerAnswerPiece(answer_piece=None)
                continue
            elif not is_json_prompt:
                if quote_pat in hold_quote + token or quote_loose in hold_quote + token:
                    found_answer_end = True
                    yield DanswerAnswerPiece(answer_piece=None)
                    continue
                if hold_quote + token in quote_pat_full:
                    hold_quote += token
                    continue
            yield DanswerAnswerPiece(answer_piece=hold_quote + token)
            hold_quote = ""

    logger.debug(f"Raw Model QnA Output: {model_output}")

    yield _extract_quotes_from_completed_token_stream(
        model_output=model_output,
        context_docs=context_docs,
        is_json_prompt=is_json_prompt,
    )


def build_quotes_processor(
    context_docs: list[LlmDoc], is_json_prompt: bool
) -> Callable[[Iterator[str]], AnswerQuestionStreamReturn]:
    def stream_processor(tokens: Iterator[str]) -> AnswerQuestionStreamReturn:
        yield from process_model_tokens(
            tokens=tokens,
            context_docs=context_docs,
            is_json_prompt=is_json_prompt,
        )

    return stream_processor
