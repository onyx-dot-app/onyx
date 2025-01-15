from langchain.schema import AIMessage
from langchain.schema import HumanMessage
from langchain.schema import SystemMessage
from langchain_core.messages.tool import ToolMessage

from onyx.agent_search.shared_graph_utils.prompts import BASE_RAG_PROMPT_v2
from onyx.context.search.models import InferenceSection


def build_sub_question_answer_prompt(
    question: str,
    original_question: str,
    docs: list[InferenceSection],
    persona_specification: str,
) -> list[SystemMessage | HumanMessage | AIMessage | ToolMessage]:
    system_message = SystemMessage(
        content=persona_specification,
    )

    docs_format_list = [
        f"""Document Number: [D{doc_nr + 1}]\n
                             Content: {doc.combined_content}\n\n"""
        for doc_nr, doc in enumerate(docs)
    ]

    docs_str = "\n\n".join(docs_format_list)

    human_message = HumanMessage(
        content=BASE_RAG_PROMPT_v2.format(
            question=question, original_question=original_question, context=docs_str
        )
    )

    return [system_message, human_message]
