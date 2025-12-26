from typing import cast

from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter
from sqlalchemy.orm import Session

from onyx.agents.agent_search.exploration_2.states import FinalUpdate
from onyx.agents.agent_search.exploration_2.states import MainState
from onyx.agents.agent_search.exploration_2.states import OrchestrationUpdate
from onyx.agents.agent_search.exploration_2.supporting_functions import (
    get_top_similar_answered_question,
)
from onyx.agents.agent_search.models import GraphConfig
from onyx.context.search.utils import get_query_embedding
from onyx.db.models import ChatMessage
from onyx.db.models import QueryDependentLearning__ChatMessage
from onyx.db.models import QueryDependentLearnings
from onyx.db.users import User
from onyx.utils.logger import setup_logger


logger = setup_logger()


def get_query_dependent_context(
    db_session: Session, user: User, original_question: str
) -> str:
    question_embedding = get_query_embedding(original_question, db_session)

    positive_result = get_top_similar_answered_question(
        question_embedding=question_embedding,
        desired_polarity="positive",
        user_id=user.id if user else None,
        db_session=db_session,
        similarity_threshold=0.8,  # Adjust threshold as needed (0=identical, 2=opposite)
    )

    negative_result = get_top_similar_answered_question(
        question_embedding=question_embedding,
        desired_polarity="negative",
        user_id=user.id if user else None,
        db_session=db_session,
        similarity_threshold=0.8,  # Adjust threshold as needed (0=identical, 2=opposite)
    )

    positive_learnings = []
    negative_learnings = []
    positive_similarity_score = None
    negative_similarity_score = None

    if positive_result:
        top_similar_positively_answered_chat_message_id, positive_similarity_score = (
            positive_result
        )
        positively_reviewed_question = (
            db_session.query(ChatMessage)
            .filter(ChatMessage.id == top_similar_positively_answered_chat_message_id)
            .first()
            .message
        )
        logger.debug(
            f"Found positive learning with similarity score: {positive_similarity_score} \
for question: {positively_reviewed_question}."
        )
        positive_learnings = (
            db_session.query(QueryDependentLearnings)
            .join(
                QueryDependentLearning__ChatMessage,
                QueryDependentLearning__ChatMessage.learning_id
                == QueryDependentLearnings.id,
            )
            .filter(
                QueryDependentLearning__ChatMessage.chat_message_id
                == top_similar_positively_answered_chat_message_id
            )
            .filter(QueryDependentLearnings.insight_type == "proprietary")
            .all()
        )

        positive_learning_string = "\n".join(
            [learning.insight_text for learning in positive_learnings]
        )

    if negative_result:
        top_similar_negatively_answered_chat_message_id, negative_similarity_score = (
            negative_result
        )
        negatively_reviewed_question = (
            db_session.query(ChatMessage)
            .filter(ChatMessage.id == top_similar_negatively_answered_chat_message_id)
            .first()
            .message
        )
        logger.debug(
            f"Found negative learning with similarity score: {negative_similarity_score} \
    for question: {negatively_reviewed_question}"
        )
        negative_learnings = (
            db_session.query(QueryDependentLearnings)
            .join(
                QueryDependentLearning__ChatMessage,
                QueryDependentLearning__ChatMessage.learning_id
                == QueryDependentLearnings.id,
            )
            .filter(
                QueryDependentLearning__ChatMessage.chat_message_id
                == top_similar_negatively_answered_chat_message_id
            )
            .filter(QueryDependentLearnings.insight_type == "proprietary")
            .all()
        )

        negative_learning_string = "\n".join(
            [learning.insight_text for learning in negative_learnings]
        )

    dynamic_learnings_string = ""
    if positive_learning_string or negative_learning_string:

        dynamic_learnings_string += "###\nHere are learnings from similar questions that may inform the answer process:\n\n"
        if positive_learning_string:
            dynamic_learnings_string += f"""\n\nHere are learnings from a similar question where the user \
liked the answer:\n{positive_learning_string}\n\n"""

        if negative_learning_string:
            dynamic_learnings_string += f"""\n\nHere are learnings from a similar question where the user disliked \
the answer:\n{negative_learning_string}\n\n"""
        dynamic_learnings_string += "###\n"
    else:
        dynamic_learnings_string = ""

    return dynamic_learnings_string


def query_dependent_context_explorer(
    state: MainState, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> FinalUpdate | OrchestrationUpdate:
    """
    LangGraph node to identify suitable context from memory
    """

    # TODO: generate final answer using all the previous steps
    # (right now, answers from each step are concatenated onto each other)
    # Also, add missing fields once usage in UI is clear.

    graph_config = cast(GraphConfig, config["metadata"]["config"])
    base_question = state.original_question
    db_session = graph_config.persistence.db_session
    user = (
        graph_config.tooling.search_tool.user
        if graph_config.tooling.search_tool
        else None
    )

    if not base_question:
        raise ValueError("Question is required for closer")

    new_messages: list[SystemMessage | HumanMessage | AIMessage] = []

    user_question = state.original_question

    dynamic_learnings_string = get_query_dependent_context(
        db_session, user, user_question
    )

    new_messages.append(HumanMessage(content=dynamic_learnings_string))

    return OrchestrationUpdate(
        message_history_for_continuation=new_messages,
        traces=[
            f"The Query-Dependent-Context Tool was used and resulted in the following learnings: {dynamic_learnings_string}"
        ],
    )
