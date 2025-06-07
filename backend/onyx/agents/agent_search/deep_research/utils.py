from typing import List

from langchain_core.messages import AIMessage
from langchain_core.messages import AnyMessage
from langchain_core.messages import HumanMessage

from onyx.llm.factory import get_default_llms


def collate_messages(messages: List[AnyMessage]) -> str:
    """
    Collate the messages into a single string.
    """
    # check if request has a history and combine the messages into a single string
    if len(messages) == 1:
        research_topic = messages[-1].content
    else:
        research_topic = ""
        for message in messages:
            if isinstance(message, HumanMessage):
                research_topic += f"User: {message.content}\n"
            elif isinstance(message, AIMessage):
                research_topic += f"Assistant: {message.content}\n"
    return research_topic


def get_research_topic(messages: list[AnyMessage]) -> str:
    """
    Get the research topic from the messages.
    """
    _, fast_llm = get_default_llms()
    prompt = """You are a helpful assistant that summarizes the conversation history.
    The conversation history is as follows:
    {messages}

    Please summarize the conversation history in a single research topic.
    """
    collated_messages = collate_messages(messages)
    llm_response = fast_llm.invoke(prompt.format(messages=collated_messages))
    return llm_response.content
