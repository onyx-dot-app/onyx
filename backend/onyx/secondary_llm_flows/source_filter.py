import json
import random

from sqlalchemy.orm import Session

from onyx.configs.chat_configs import ENABLE_CONNECTOR_CLASSIFIER
from onyx.configs.constants import DocumentSource
from onyx.db.connector import fetch_unique_document_sources
from onyx.db.engine.sql_engine import get_sqlalchemy_engine
from onyx.llm.interfaces import LLM
from onyx.llm.utils import dict_based_prompt_to_langchain_prompt
from onyx.llm.utils import message_to_string
from onyx.natural_language_processing.search_nlp_models import (
    ConnectorClassificationModel,
)
from onyx.prompts.constants import SOURCES_KEY
from onyx.prompts.filter_extration import FILE_SOURCE_WARNING
from onyx.prompts.filter_extration import SOURCE_FILTER_PROMPT
from onyx.prompts.filter_extration import WEB_SOURCE_WARNING
from onyx.utils.logger import setup_logger
from onyx.utils.text_processing import extract_embedded_json

logger = setup_logger()


def strings_to_document_sources(source_strs: list[str]) -> list[DocumentSource]:
    sources = []
    for s in source_strs:
        try:
            sources.append(DocumentSource(s))
        except ValueError:
            logger.warning(f"Failed to translate {s} to a DocumentSource")
    return sources


def _sample_document_sources(
    valid_sources: list[DocumentSource],
    num_sample: int,
    allow_less: bool = True,
) -> list[DocumentSource]:
    if len(valid_sources) < num_sample:
        if not allow_less:
            raise RuntimeError("Not enough sample Document Sources")
        return random.sample(valid_sources, len(valid_sources))
    else:
        return random.sample(valid_sources, num_sample)


def _sample_documents_using_custom_connector_classifier(
    query: str,
    valid_sources: list[DocumentSource],
) -> list[DocumentSource] | None:
    query_joined = "".join(ch for ch in query.lower() if ch.isalnum())
    available_connectors = list(
        filter(
            lambda conn: conn.lower() in query_joined,
            [item.value for item in valid_sources],
        )
    )

    if not available_connectors:
        return None

    connectors = ConnectorClassificationModel().predict(query, available_connectors)

    return strings_to_document_sources(connectors) if connectors else None


def extract_source_filter(
    query: str, llm: LLM, db_session: Session
) -> list[DocumentSource] | None:
    """Returns a list of valid sources for search or None if no specific sources were detected"""

    valid_sources = fetch_unique_document_sources(db_session)
    if not valid_sources:
        return None

    if ENABLE_CONNECTOR_CLASSIFIER:
        return _sample_documents_using_custom_connector_classifier(query, valid_sources)

    def _get_source_filter_messages(
        query: str,
        valid_sources: list[DocumentSource],
        # Seems the LLM performs similarly without examples
        show_samples: bool = False,
    ) -> list[dict[str, str]]:
        sample_json = {
            SOURCES_KEY: [
                s.value
                for s in _sample_document_sources(
                    valid_sources=valid_sources, num_sample=2
                )
            ]
        }

        web_warning = WEB_SOURCE_WARNING if DocumentSource.WEB in valid_sources else ""
        file_warning = (
            FILE_SOURCE_WARNING if DocumentSource.FILE in valid_sources else ""
        )

        msg_1_sources = _sample_document_sources(
            valid_sources=valid_sources, num_sample=2
        )
        msg_1_source_str = " and ".join([s.capitalize() for s in msg_1_sources])

        msg_2_sources = _sample_document_sources(
            valid_sources=valid_sources, num_sample=2
        )

        msg_2_real_source = msg_2_sources[0]
        msg_2_fake_source_str = (
            msg_2_sources[1].value.capitalize()
            if len(msg_2_sources) > 1
            else "Confluence"
        )

        messages = [
            {
                "role": "system",
                "content": SOURCE_FILTER_PROMPT.format(
                    valid_sources=[s.value for s in valid_sources],
                    web_source_warning=web_warning,
                    file_source_warning=file_warning,
                    sample_response=json.dumps(sample_json),
                ),
            },
            {
                "role": "user",
                "content": f"What documents in {msg_1_source_str} cover engineer onboarding",
            },
            {
                "role": "assistant",
                "content": json.dumps({SOURCES_KEY: msg_1_sources}),
            },
            {"role": "user", "content": "What's the latest on project Corgies?"},
            {
                "role": "assistant",
                "content": json.dumps({SOURCES_KEY: None}),
            },
            {
                "role": "user",
                "content": f"What information from {msg_2_real_source.value.capitalize()} "
                f"mentions {msg_2_fake_source_str}?",
            },
            {
                "role": "assistant",
                "content": json.dumps({SOURCES_KEY: [msg_2_real_source]}),
            },
            {
                "role": "user",
                "content": "What page from Onyx contains debugging instruction on segfault",
            },
            {
                "role": "assistant",
                "content": json.dumps({SOURCES_KEY: None}),
            },
            {"role": "user", "content": query},
        ]

        if show_samples:
            return messages

        # Only system prompt and latest user query
        return [messages[0], messages[-1]]

    def _extract_source_filters_from_llm_out(
        model_out: str,
    ) -> list[DocumentSource] | None:
        try:
            sources_dict = extract_embedded_json(model_out)
            sources_list = sources_dict.get(SOURCES_KEY)
            if not sources_list:
                return None

            return strings_to_document_sources(sources_list)
        except ValueError:
            logger.warning("LLM failed to provide a valid Source Filter output")
            return None

    messages = _get_source_filter_messages(query=query, valid_sources=valid_sources)
    filled_llm_prompt = dict_based_prompt_to_langchain_prompt(messages)
    model_output = message_to_string(llm.invoke(filled_llm_prompt))
    logger.debug(model_output)

    return _extract_source_filters_from_llm_out(model_output)


if __name__ == "__main__":
    from onyx.llm.factory import get_default_llms, get_main_llm_from_tuple

    # Just for testing purposes
    with Session(get_sqlalchemy_engine()) as db_session:
        while True:
            user_input = input("Query to Extract Sources: ")
            sources = extract_source_filter(
                user_input, get_main_llm_from_tuple(get_default_llms()), db_session
            )
            print(sources)
