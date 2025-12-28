import json
from collections import defaultdict
from typing import Dict
from typing import Optional
from uuid import UUID

import numpy as np
from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage
from sqlalchemy.orm import Session

from onyx.agents.agent_search.exploration_2.dr_experimentation_prompts import (
    CS_COMPRESSION_PROMPT_TEMPLATE,
)
from onyx.agents.agent_search.exploration_2.dr_experimentation_prompts import (
    INTERNAL_SEARCH_TOPIC_ANALYSIS_SYSTEM_PROMPT,
)
from onyx.agents.agent_search.exploration_2.dr_experimentation_prompts import (
    NEGATIVE_QUERY_DEPENDENT_CONTEXT_EXTRACTION_SYSTEM_PROMPT,
)
from onyx.agents.agent_search.exploration_2.dr_experimentation_prompts import (
    POSITIVE_QUERY_DEPENDENT_CONTEXT_EXTRACTION_SYSTEM_PROMPT,
)
from onyx.agents.agent_search.exploration_2.dr_experimentation_prompts import (
    QUERY_INDEPENDENT_LEARNING_CONSOLIDATION_PROMPT_TEMPLATE,
)
from onyx.agents.agent_search.exploration_2.dr_experimentation_prompts import (
    RATED_QUERY_ANALYSIS_USER_PROMPT_TEMPLATE,
)
from onyx.agents.agent_search.exploration_2.dr_experimentation_prompts import (
    UNRATED_QUERY_ANALYSIS_USER_PROMPT_TEMPLATE,
)
from onyx.agents.agent_search.exploration_2.dr_experimentation_prompts import (
    UNRATED_QUERY_INDEPENDENT_CONTEXT_EXTRACTION_SYSTEM_PROMPT,
)
from onyx.agents.agent_search.shared_graph_utils.llm import invoke_llm_raw
from onyx.chat.models import MessageType
from onyx.context.search.utils import get_query_embedding
from onyx.db.models import ChatMessage
from onyx.db.models import ChatMessageFeedback
from onyx.db.models import ChatSession
from onyx.db.models import QueryDependentLearning__ChatMessage
from onyx.db.models import QueryDependentLearnings
from onyx.db.models import ResearchAgentIterationSubStep
from onyx.db.models import User
from onyx.llm.factory import get_default_llms
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _strip_markdown_json(content: str) -> str:
    """
    Remove markdown code block formatting from JSON content.
    Handles cases where LLM returns JSON wrapped in ```json or ```python blocks.
    """
    content = content.strip()
    # Remove opening code block markers (```json, ```python, etc.)
    if content.startswith("```"):
        # Find the end of the first line (the language identifier)
        first_newline = content.find("\n")
        if first_newline != -1:
            content = content[first_newline + 1 :]
    # Remove closing code block marker
    if content.endswith("```"):
        content = content[:-3]
    return content.strip()


def _get_user_message_pairs_for_chat_message(
    chat_message_id: int, db_session: Session
) -> tuple[str, str]:
    """
    Traverse from a chat_message_id up through parent_message relationships
    until parent_message is null. Returns all message (id, message_type) tuples
    in the chain, starting from the given chat_message_id and ending at the root.
    """
    message_chain: list[tuple[int, MessageType]] = []

    current_id: int | None = chat_message_id
    min_message_id = 100000000
    initial_user_question: str | None = None

    user_query_components: list[str] = []

    while current_id is not None:
        # Get the current message
        current_message = (
            db_session.query(ChatMessage).filter(ChatMessage.id == current_id).first()
        )

        if not current_message:
            raise ValueError(f"Chat message {current_id} not found")

        if current_id == chat_message_id:
            current_message.chat_session_id

        if current_message is None:
            break

        message_chain.append((current_message.id, current_message.message_type))
        current_id = current_message.parent_message

        if current_message.message_type == MessageType.USER:
            user_query_components.append(current_message.message)
            if current_message.id < min_message_id:
                min_message_id = current_message.id
                initial_user_question = current_message.message

    user_query_string = "\n".join(user_query_components)

    return (initial_user_question or "", user_query_string or "")


def _save_query_dependent_learnings(
    query_dependent_learnings: list[str],
    chat_message_id: int,
    user_id: UUID | None,
    db_session: Session,
) -> None:
    """
    Save query-dependent learnings to the database.

    Creates entries in QueryDependentLearnings table and links them to the chat message
    via the QueryDependentLearning__ChatMessage junction table.

    Args:
        result: The extraction response containing learnings
        chat_message_id: The ID of the chat message to associate with
        user_id: The user who provided the feedback
        db_session: Database session for persistence
        is_positive: Whether this is positive or negative feedback
    """
    if not user_id:
        raise ValueError("user_id is required to save learnings")

    insight_type = "proprietary"

    # Save each learning as a separate entry
    for learning_text in query_dependent_learnings:
        # Create the learning entry
        learning = QueryDependentLearnings(
            user_id=user_id,
            insight_text=learning_text,
            insight_type=insight_type,
        )
        db_session.add(learning)
        db_session.flush()  # Flush to get the learning.id

        # Create the junction table entry to link learning to chat message
        learning_chat_link = QueryDependentLearning__ChatMessage(
            learning_id=learning.id,
            chat_message_id=chat_message_id,
        )
        db_session.add(learning_chat_link)

    # Commit all changes
    db_session.commit()


def _compress_cheet_sheet(cheet_sheet_str: str) -> dict[str, dict[str, str]]:
    """
    Compress the cheat sheet string to a maximum of 2000 characters.
    """
    prompt = CS_COMPRESSION_PROMPT_TEMPLATE.replace(
        "---original_cheatsheet---", cheet_sheet_str
    )
    result = invoke_llm_raw(
        prompt=prompt,
        # schema=QueryIndependentLearningConsolidationResponse,
        llm=get_default_llms()[0],
    )

    if not isinstance(result.content, str):
        raise ValueError("Result content is not a string")

    compressed_cheet_sheet = json.loads(_strip_markdown_json(result.content))

    return compressed_cheet_sheet


def _update_query_independent_learnings(
    query_independent_learnings: Dict[str, str], user_id: UUID, db_session: Session
) -> dict[str, dict[str, str]] | None:
    """
    Update query-independent learnings to the database.
    """

    user_record: User | None = db_session.query(User).filter_by(id=user_id).first()
    if not user_record:
        raise ValueError(
            "User record is required to update query-independent learnings"
        )

    existing_cheatsheet = user_record.cheat_sheet_context if user_record else None

    if existing_cheatsheet is None:
        raise ValueError(
            "Existing cheatsheet is required to update query-independent learnings"
        )

    query_independent_learning_consolidation_prompt = (
        QUERY_INDEPENDENT_LEARNING_CONSOLIDATION_PROMPT_TEMPLATE.replace(
            "---existing_cheatsheet---", str(existing_cheatsheet)
        ).replace("---new_learnings---", str(query_independent_learnings))
    )

    result = invoke_llm_raw(
        prompt=query_independent_learning_consolidation_prompt,
        # schema=QueryIndependentLearningConsolidationResponse,
        llm=get_default_llms()[0],
    )

    if not isinstance(result.content, str):
        raise ValueError("Result content is not a string")

    result_dict = json.loads(_strip_markdown_json(result.content))

    new_cheat_sheet = {
        "user_background": result_dict.get("user_background", {}),
        "company_background": result_dict.get("company_background", {}),
        "answer_preferences": result_dict.get("answer_preferences", {}),
        "internal_search_topics": result_dict.get("internal_search_topics", {}),
    }

    new_cheat_sheet_str = str(new_cheat_sheet)
    num_words_new_cheat_sheet = len(new_cheat_sheet_str.split())
    logger.info(f"Number of words in new cheat sheet: {num_words_new_cheat_sheet}")
    if num_words_new_cheat_sheet > 500:
        new_cheat_sheet = _compress_cheet_sheet(new_cheat_sheet_str)
        logger.info(
            f"Number of words in compressed cheat sheet: {len(str(new_cheat_sheet).split())}"
        )

    user_record.cheat_sheet_context = new_cheat_sheet
    db_session.commit()
    return new_cheat_sheet


def extract_insights_for_chat_message(
    is_positive: Optional[bool],
    feedback_text: Optional[str],
    predefined_feedback: Optional[str],
    chat_message_id: int,
    user_id: UUID,
    db_session: Session,
) -> Optional[dict[str, dict[str, str]]]:
    user_question, combined_user_messages = _get_user_message_pairs_for_chat_message(
        chat_message_id, db_session
    )  # very slow? Can definitely be quantized and truncated

    if is_positive is not None:
        # save embedding to chat message
        query_string_embedding = get_query_embedding(combined_user_messages, db_session)

        db_session.query(ChatMessage).filter(ChatMessage.id == chat_message_id).update(
            {ChatMessage.query_embeddings: query_string_embedding}
        )
        db_session.commit()

    message_result = (
        db_session.query(ChatMessage).filter(ChatMessage.id == chat_message_id).first()
    )
    if message_result:
        message_answer = message_result.message
    else:
        raise ValueError(f"Chat message {chat_message_id} not found")

    message_sub_steps = (
        db_session.query(ResearchAgentIterationSubStep)
        .filter(ResearchAgentIterationSubStep.primary_question_id == chat_message_id)
        .all()
    )

    trace_components: dict[int, dict[int, str]] = defaultdict(lambda: defaultdict(str))
    fact_components: dict[int, dict[int, str]] = defaultdict(lambda: defaultdict(str))

    internal_search_history: list[str] = []

    for message_sub_step in message_sub_steps:

        sub_step_iteration_nr = message_sub_step.iteration_nr
        sub_step_iteration_sub_step_nr = message_sub_step.iteration_sub_step_nr

        sub_step_tool_name = message_sub_step.sub_step_tool_name

        sub_step_instructions = (
            f"\n   - Tool Call Instruction/Question: {message_sub_step.sub_step_instructions}"
            if message_sub_step.sub_step_instructions
            else ""
        )
        sub_step_answer = (
            f"\n   - Tool Call Answer: {message_sub_step.sub_answer}"
            if message_sub_step.sub_answer
            else ""
        )
        sub_step_reasoning = (
            f"\n   - Tool Call Reasoning: {message_sub_step.reasoning}"
            if message_sub_step.reasoning
            else ""
        )
        sub_step_claim_string = (
            ("\n     - " + "\n     - ".join(message_sub_step.claims))
            if message_sub_step.claims
            else ""
        )
        sub_step_claims = (
            f"\n   - Tool Call Claims: {sub_step_claim_string}"
            if sub_step_claim_string
            else ""
        )

        if sub_step_iteration_sub_step_nr == 0:
            tool_name_string = (
                f"\n\nIteration: {sub_step_iteration_nr} - Tool: {sub_step_tool_name}"
            )
        else:
            tool_name_string = ""

        trace_components[sub_step_iteration_nr][sub_step_iteration_sub_step_nr] = (
            tool_name_string
            + sub_step_instructions
            + sub_step_answer
            + sub_step_reasoning
            + sub_step_claims
            + "\n\n"
        )

        fact_components[sub_step_iteration_nr][sub_step_iteration_sub_step_nr] = (
            sub_step_claims + "\n\n"
        )

        sorted_trace_components = sorted(trace_components.items(), key=lambda x: x[0])
        sorted_fact_components = sorted(fact_components.items(), key=lambda x: x[0])

        if sub_step_tool_name == "Internal Search":
            internal_search_history.append(
                f"""Search Question: {message_sub_step.sub_step_instructions}\n--\n \
    Search Answer:\n{message_sub_step.sub_answer}\n--\n\n"""
            )

    full_trace_components = []
    fact_string_components = []

    for iteration_nr, sub_step_components in sorted_trace_components:
        sorted_sub_step_components = sorted(
            sub_step_components.items(), key=lambda x: x[0]
        )
        for sub_step_nr, sub_step_component in sorted_sub_step_components:
            full_trace_components.append(sub_step_component)
    full_trace_string = "\n".join(full_trace_components)

    for iteration_nr, sub_step_components in sorted_fact_components:
        sorted_sub_step_components = sorted(
            sub_step_components.items(), key=lambda x: x[0]
        )
        for sub_step_nr, sub_step_component in sorted_sub_step_components:
            fact_string_components.append(sub_step_component)
    fact_string = "\n".join(fact_string_components)

    full_history_string = f"User Question:\n{user_question}\n\nHistory of \
Tool Calls:\n{full_trace_string}\n\nFinal Answer:\n{message_answer}"
    unrated_history_string = f"User Question:\n{user_question}\n\nHistory of Facts Discovered:\n{fact_string}\n\n"

    feedback_string = ""

    if predefined_feedback or feedback_text:
        feedback_string = f"""###\n
Here is more feedback from the user:\n----\nPredefined feedback options: \n{predefined_feedback}\n---\nExplicit \
feedback text: \n{feedback_text}\n###\n"""

    if is_positive:
        query_analysis_system_prompt = (
            POSITIVE_QUERY_DEPENDENT_CONTEXT_EXTRACTION_SYSTEM_PROMPT
        )
        query_analysis_human_prompt = RATED_QUERY_ANALYSIS_USER_PROMPT_TEMPLATE.replace(
            "---full_history_string---", full_history_string
        )

    elif is_positive is not None and not is_positive:
        # only learn
        query_analysis_system_prompt = (
            NEGATIVE_QUERY_DEPENDENT_CONTEXT_EXTRACTION_SYSTEM_PROMPT
        )
        query_analysis_human_prompt = RATED_QUERY_ANALYSIS_USER_PROMPT_TEMPLATE.replace(
            "---full_history_string---", full_history_string
        ).replace("---feedback_string---", feedback_string)
    elif is_positive is None:
        query_analysis_system_prompt = (
            UNRATED_QUERY_INDEPENDENT_CONTEXT_EXTRACTION_SYSTEM_PROMPT
        )
        query_analysis_human_prompt = (
            UNRATED_QUERY_ANALYSIS_USER_PROMPT_TEMPLATE.replace(
                "---unrated_history_string---", unrated_history_string
            )
        )

    result = invoke_llm_raw(
        prompt=[
            SystemMessage(content=query_analysis_system_prompt),
            HumanMessage(content=query_analysis_human_prompt),
        ],
        # schema=QueryDependentContextExtractionResponse,
        llm=get_default_llms()[0],
    )

    if not isinstance(result.content, str):
        raise ValueError("Result content is not a string")

    result_dict = json.loads(_strip_markdown_json(result.content))

    if not isinstance(result_dict, dict):
        raise ValueError("Result dict is not a dictionary")

    if is_positive is not None and user_id and chat_message_id:
        _save_query_dependent_learnings(
            result_dict.get("query_dependent_learnings", []),
            chat_message_id,
            user_id,
            db_session,
        )

    internal_search_topic_update_string = ""
    if internal_search_history:
        internal_search_history_string = "\n".join(internal_search_history)

        topic_update_result = invoke_llm_raw(
            prompt=[
                SystemMessage(content=INTERNAL_SEARCH_TOPIC_ANALYSIS_SYSTEM_PROMPT),
                HumanMessage(
                    content=f"""History of search questions and answers: \n{internal_search_history_string}"""
                ),
            ],
            # schema=QueryDependentContextExtractionResponse,
            llm=get_default_llms()[0],
        )

        topic_update_result_dict = json.loads(
            _strip_markdown_json(topic_update_result.content)
        )

        if not isinstance(topic_update_result_dict, dict):
            raise ValueError("Result dict is not a dictionary")

        well_represented_topics = topic_update_result_dict.get("covered", [])
        not_well_represented_topics = topic_update_result_dict.get("not_covered", [])

        if well_represented_topics:
            internal_search_topic_update_string += (
                f"""\n\nWell-represented topics: \n{well_represented_topics}"""
            )
        if not_well_represented_topics:
            internal_search_topic_update_string += (
                f"""\n\nNot-well-represented topics: \n{not_well_represented_topics}"""
            )

    if internal_search_topic_update_string:
        if not result_dict.get("query_independent_learnings", {}):
            result_dict["query_independent_learnings"] = {}
        if not result_dict["query_independent_learnings"].get(
            "internal_search_topics", {}
        ):
            result_dict["query_independent_learnings"]["internal_search_topics"] = {}
        result_dict["query_independent_learnings"][
            "internal_search_topics"
        ] = internal_search_topic_update_string

    new_cheat_sheet = None
    if user_id:
        new_cheat_sheet = _update_query_independent_learnings(
            result_dict.get("query_independent_learnings", {}), user_id, db_session
        )

    logger.info(
        f"\n-----\nWords in updated cheat sheet: {len(str(new_cheat_sheet).split())}\n-----\n\n"
    )
    return new_cheat_sheet


def get_top_similar_answered_question(
    question_embedding: list[float],
    desired_polarity: str,
    user_id: UUID | None,
    db_session: Session,
    similarity_threshold: float = 1.0,  # Cosine distance threshold (0=identical, 2=opposite)
) -> tuple[int, float] | None:
    """
    Get the top similar answered question from the database based on vector similarity.

    Args:
        question_embedding: The embedding vector of the question to find similar answers for
        desired_polarity: Filter by learning polarity ('positive', 'negative', or 'proprietary')
        user_id: Filter by user ID to only find learnings from this user
        db_session: Database session
        similarity_threshold: Maximum cosine distance to consider (default 1.0). Lower is more similar.

    Returns:
        Tuple of (message_id, similarity_score) or None if no match found within threshold.
        Similarity score is cosine distance where 0=identical, 2=opposite.
    """
    # Fetch candidate messages from database, then compute cosine distance in Python with numpy
    query = (
        db_session.query(ChatMessage)
        .join(
            ChatSession,
            ChatMessage.chat_session_id == ChatSession.id,
        )
        .join(
            ChatMessageFeedback,
            ChatMessageFeedback.chat_message_id == ChatMessage.id,
        )
        .join(
            QueryDependentLearning__ChatMessage,
            QueryDependentLearning__ChatMessage.chat_message_id == ChatMessage.id,
        )
        .join(
            QueryDependentLearnings,
            QueryDependentLearnings.id
            == QueryDependentLearning__ChatMessage.learning_id,
        )
        .filter(
            ChatMessage.query_embeddings.isnot(None)
        )  # Only messages with embeddings
        .filter(
            ChatMessage.message_type == MessageType.ASSISTANT
        )  # Only assistant responses
        .filter(
            QueryDependentLearnings.insight_type == "proprietary"
        )  # Filter by polarity
        .distinct()  # Remove duplicate ChatMessages from multiple joins
    )

    # Filter by feedback polarity based on desired_polarity parameter
    if desired_polarity == "positive":
        query = query.filter(ChatMessageFeedback.is_positive == True)  # noqa: E712
    elif desired_polarity == "negative":
        query = query.filter(ChatMessageFeedback.is_positive == False)  # noqa: E712
    # For other polarity types, no feedback filter is applied

    # Filter by user_id from ChatSession if provided
    if user_id is not None:
        query = query.filter(ChatSession.user_id == user_id)
    else:
        raise ValueError("User ID is required to get top similar answered question")

    # Fetch all candidate messages
    candidates = query.all()

    if not candidates:
        return None

    # Compute cosine distance in Python using vectorized numpy operations
    # Extract all embeddings and message IDs
    message_ids = []
    embeddings_list = []

    for message in candidates:
        if message.query_embeddings is not None:
            message_ids.append(message.id)
            embeddings_list.append(message.query_embeddings)

    if not embeddings_list:
        return None

    # Convert to numpy arrays for vectorized operations
    query_emb = np.array(question_embedding)  # Shape: (d,)
    stored_embs = np.array(
        embeddings_list
    )  # Shape: (n, d) where n = number of candidates

    # Compute norms
    query_norm = np.linalg.norm(query_emb)
    stored_norms = np.linalg.norm(stored_embs, axis=1)  # Shape: (n,)

    # Compute all dot products at once using matrix multiplication
    dot_products = stored_embs @ query_emb  # Shape: (n,)

    # Compute all cosine similarities at once
    cosine_sims = dot_products / (stored_norms * query_norm)  # Shape: (n,)

    # Compute all cosine distances at once
    cosine_dists = 1 - cosine_sims  # Shape: (n,)

    # Filter by threshold and find the minimum
    valid_mask = cosine_dists <= similarity_threshold

    if not np.any(valid_mask):
        return None

    # Get the index of the minimum distance among valid candidates
    valid_distances = np.where(valid_mask, cosine_dists, np.inf)
    best_idx = np.argmin(valid_distances)

    return (message_ids[best_idx], float(cosine_dists[best_idx]))
