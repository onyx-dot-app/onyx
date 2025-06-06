import re
from time import sleep

from langgraph.types import StreamWriter

from onyx.agents.agent_search.kb_search.models import KGEntityDocInfo
from onyx.agents.agent_search.kb_search.models import KGExpandedGraphObjects
from onyx.agents.agent_search.kb_search.states import SubQuestionAnswerResults
from onyx.agents.agent_search.kb_search.step_definitions import STEP_DESCRIPTIONS
from onyx.agents.agent_search.shared_graph_utils.models import AgentChunkRetrievalStats
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.chat.models import AgentAnswerPiece
from onyx.chat.models import LlmDoc
from onyx.chat.models import StreamStopInfo
from onyx.chat.models import StreamStopReason
from onyx.chat.models import StreamType
from onyx.chat.models import SubQueryPiece
from onyx.chat.models import SubQuestionPiece
from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import InferenceSection
from onyx.db.document import get_kg_doc_info_for_entity_name
from onyx.db.engine import get_session_with_current_tenant
from onyx.db.entities import get_document_id_for_entity
from onyx.db.entity_type import get_entity_types
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _check_entities_disconnected(
    current_entities: list[str], current_relationships: list[str]
) -> bool:
    """
    Check if all entities in current_entities are disconnected via the given relationships.
    Relationships are in the format: source_entity__relationship_name__target_entity

    Args:
        current_entities: List of entity IDs to check connectivity for
        current_relationships: List of relationships in format source__relationship__target

    Returns:
        bool: True if all entities are disconnected, False otherwise
    """
    if not current_entities:
        return True

    # Create a graph representation using adjacency list
    graph: dict[str, set[str]] = {entity: set() for entity in current_entities}

    # Build the graph from relationships
    for relationship in current_relationships:
        try:
            source, _, target = relationship.split("__")
            if source in graph and target in graph:
                graph[source].add(target)
                # Add reverse edge to capture that we do also have a relationship in the other direction,
                # albeit not quite the same one.
                graph[target].add(source)
        except ValueError:
            raise ValueError(f"Invalid relationship format: {relationship}")

    # Use BFS to check if all entities are connected
    visited: set[str] = set()
    start_entity = current_entities[0]

    def _bfs(start: str) -> None:
        queue = [start]
        visited.add(start)
        while queue:
            current = queue.pop(0)
            for neighbor in graph[current]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)

    # Start BFS from the first entity
    _bfs(start_entity)

    logger.debug(f"Number of visited entities: {len(visited)}")

    # Check if all current_entities are in visited
    return not all(entity in visited for entity in current_entities)


def create_minimal_connected_query_graph(
    entities: list[str], relationships: list[str], max_depth: int = 1
) -> KGExpandedGraphObjects:
    """
    TODO: Implement this. For now we'll trust the SQL generation to do the right thing.
    Return the original entities and relationships.
    """
    return KGExpandedGraphObjects(entities=entities, relationships=relationships)


# def rename_entities_in_answer(answer: str) -> str:
#     """
#     Rename entities in the answer to be more readable by replacing entity references
#     with their semantic_id and link. This is case-insensitive and handles spaces between
#     entity type and ID. Trailing quotes are removed from entity names.
#     """
#     # Create a mapping of entity IDs to new names
#     entity_mapping = {}


#     with get_session_with_current_tenant() as db_session:
#         # Get all entity types
#         entity_types = get_entity_types(db_session)

#         # For each entity type, find all entities in the answer
#         for entity_type in entity_types:
#             # Find all occurrences of <entity_type>:<entity_name> in the answer (case-insensitive)
#             # Pattern now handles spaces after the colon
#             pattern = f"{entity_type.id_name}:\\s*([^\\s,;.]+)"
#             matches = re.finditer(pattern, answer, re.IGNORECASE)

#             for match in matches:
#                 # Get the full match including any spaces
#                 full_match = match.group(0)
#                 # Get just the entity ID part (without spaces) and remove trailing quotes
#                 entity_name = match.group(1).rstrip("\"'")
#                 entity_id = f"{entity_type.id_name}:{entity_name}"

#                 if entity_id.lower() in entity_mapping:
#                     continue

#                 # Get the document for this entity
#                 entity = (
#                     db_session.query(KGEntity)
#                     .filter(
#                         KGEntity.id_name.ilike(
#                             entity_id
#                         )  # Case-insensitive comparison
#                     )
#                     .first()
#                 )

#                 if entity and entity.document_id:
#                     # Get the document's semantic_id and link
#                     document = (
#                         db_session.query(Document)
#                         .filter(Document.id == entity.document_id)
#                         .first()
#                     )

#                     if document:
#                         # Create the replacement text with semantic_id and link
#                         replacement = f"{document.semantic_id}"
#                         if document.link:
#                             replacement = f"[{replacement}]({document.link})"
#                         entity_mapping[entity_id.lower()] = replacement
#                         # Also map the full match (with spaces) to the same replacement
#                         entity_mapping[full_match.lower()] = replacement

#     # Replace all entity references in the answer (case-insensitive)
#     for entity_id, replacement in entity_mapping.items():
#         # Use regex for case-insensitive replacement
#         answer = re.sub(re.escape(entity_id), replacement, answer, flags=re.IGNORECASE)

#     return answer


def stream_write_step_description(
    writer: StreamWriter, step_nr: int, level: int = 0
) -> None:

    write_custom_event(
        "decomp_qs",
        SubQuestionPiece(
            sub_question=STEP_DESCRIPTIONS[step_nr].description,
            level=level,
            level_question_num=step_nr,
        ),
        writer,
    )

    # Give the frontend a brief moment to catch up
    sleep(0.2)


def stream_write_step_activities(
    writer: StreamWriter, step_nr: int, level: int = 0
) -> None:
    for activity_nr, activity in enumerate(STEP_DESCRIPTIONS[step_nr].activities):
        write_custom_event(
            "subqueries",
            SubQueryPiece(
                sub_query=activity,
                level=level,
                level_question_num=step_nr,
                query_id=activity_nr + 1,
            ),
            writer,
        )


def stream_write_step_activity_explicit(
    writer: StreamWriter, step_nr: int, query_id: int, activity: str, level: int = 0
) -> None:
    for activity in STEP_DESCRIPTIONS[step_nr].activities:
        write_custom_event(
            "subqueries",
            SubQueryPiece(
                sub_query=activity,
                level=level,
                level_question_num=step_nr,
                query_id=query_id,
            ),
            writer,
        )


def stream_write_step_answer_explicit(
    writer: StreamWriter, step_nr: int, answer: str, level: int = 0
) -> None:
    write_custom_event(
        "sub_answers",
        AgentAnswerPiece(
            answer_piece=answer,
            level=level,
            level_question_num=step_nr,
            answer_type="agent_sub_answer",
        ),
        writer,
    )


def stream_write_step_structure(writer: StreamWriter, level: int = 0) -> None:
    for step_nr, step_detail in STEP_DESCRIPTIONS.items():

        write_custom_event(
            "decomp_qs",
            SubQuestionPiece(
                sub_question=step_detail.description,
                level=level,
                level_question_num=step_nr,
            ),
            writer,
        )

    for step_nr in STEP_DESCRIPTIONS.keys():

        write_custom_event(
            "stream_finished",
            StreamStopInfo(
                stop_reason=StreamStopReason.FINISHED,
                stream_type=StreamType.SUB_QUESTIONS,
                level=level,
                level_question_num=step_nr,
            ),
            writer,
        )

    stop_event = StreamStopInfo(
        stop_reason=StreamStopReason.FINISHED,
        stream_type=StreamType.SUB_QUESTIONS,
        level=0,
    )

    write_custom_event("stream_finished", stop_event, writer)


def stream_close_step_answer(
    writer: StreamWriter, step_nr: int, level: int = 0
) -> None:
    stop_event = StreamStopInfo(
        stop_reason=StreamStopReason.FINISHED,
        stream_type=StreamType.SUB_ANSWER,
        level=level,
        level_question_num=step_nr,
    )
    write_custom_event("stream_finished", stop_event, writer)


def stream_write_close_steps(writer: StreamWriter, level: int = 0) -> None:
    stop_event = StreamStopInfo(
        stop_reason=StreamStopReason.FINISHED,
        stream_type=StreamType.SUB_QUESTIONS,
        level=level,
    )

    write_custom_event("stream_finished", stop_event, writer)


def stream_write_close_main_answer(writer: StreamWriter, level: int = 0) -> None:
    stop_event = StreamStopInfo(
        stop_reason=StreamStopReason.FINISHED,
        stream_type=StreamType.MAIN_ANSWER,
        level=level,
        level_question_num=0,
    )
    write_custom_event("stream_finished", stop_event, writer)


def stream_write_main_answer_token(
    writer: StreamWriter, token: str, level: int = 0, level_question_num: int = 0
) -> None:
    write_custom_event(
        "initial_agent_answer",
        AgentAnswerPiece(
            answer_piece=token,  # No need to add space as tokenizer handles this
            level=level,
            level_question_num=level_question_num,
            answer_type="agent_level_answer",
        ),
        writer,
    )


def get_doc_information_for_entity(entity_id_name: str) -> KGEntityDocInfo:
    """
    Get document information for an entity, including its semantic name and document details.
    """
    if "::" not in entity_id_name:
        return KGEntityDocInfo(
            doc_id=None,
            doc_semantic_id=None,
            doc_link=None,
            semantic_entity_name=entity_id_name,
            semantic_linked_entity_name=entity_id_name,
        )

    entity_type, entity_name = map(str.strip, entity_id_name.split("::", 1))

    with get_session_with_current_tenant() as db_session:
        entity_document_id = get_document_id_for_entity(db_session, entity_id_name)
        if entity_document_id:
            return get_kg_doc_info_for_entity_name(
                db_session, entity_document_id, entity_type
            )
        else:
            return KGEntityDocInfo(
                doc_id=None,
                doc_semantic_id=None,
                doc_link=None,
                semantic_entity_name=entity_id_name,
                semantic_linked_entity_name=entity_id_name,
            )


def rename_entities_in_answer(answer: str) -> str:
    """
    Process entity references in the answer string by:
    1. Extracting all strings matching <str>:<str> or <str>: <str> patterns
    2. Looking up these references in the entity table
    3. Replacing valid references with their corresponding values

    Args:
        answer: The input string containing potential entity references

    Returns:
        str: The processed string with entity references replaced
    """
    # Extract all entity references using regex
    # Pattern matches both <str>:<str> and <str>: <str> formats
    pattern = r"([^:\s]+):\s*([^\s,;.]+)"
    matches = re.finditer(pattern, answer)

    # get active entity types
    with get_session_with_current_tenant() as db_session:
        active_entity_types = [
            x.id_name for x in get_entity_types(db_session, active=True)
        ]

    # Collect extracted references
    entity_refs = [match.group(0).strip("::") for match in matches]

    # Create dictionary for processed references
    processed_refs = {}

    for entity_ref in entity_refs:
        entity_ref_split = entity_ref.split("::")
        if len(entity_ref_split) != 2:
            logger.warning(
                f"Invalid entity reference - number of colons is not 2 but {len(entity_ref_split)}"
            )
            continue
        entity_type, entity_name = entity_ref.split("::")
        entity_type = entity_type.upper().strip()
        if entity_type not in active_entity_types:
            continue
        entity_name = entity_name.capitalize().strip()
        potential_entity_id_name = f"{entity_type}::{entity_name}"

        replacement_candidate = get_doc_information_for_entity(potential_entity_id_name)

        if replacement_candidate.doc_id:
            processed_refs[entity_ref] = (
                replacement_candidate.semantic_linked_entity_name
            )
        else:
            continue

    # Replace all references in the answer
    for ref, replacement in processed_refs.items():
        answer = answer.replace(ref, replacement)

    return answer


def build_document_context(
    document: InferenceSection | LlmDoc, document_number: int
) -> str:
    """
    Build a context string for a document.
    """

    metadata_list: list[str] = []
    document_content: str | None = None
    info_source: InferenceChunk | LlmDoc | None = None
    info_content: str | None = None

    if isinstance(document, InferenceSection):
        info_source = document.center_chunk
        info_content = document.combined_content
    elif isinstance(document, LlmDoc):
        info_source = document
        info_content = document.content

    for key, value in info_source.metadata.items():
        metadata_list.append(f"   - {key}: {value}")

    if metadata_list:
        metadata_str = "- Document Metadata:\n" + "\n".join(metadata_list)
    else:
        metadata_str = ""

    # Construct document header with number and semantic identifier
    doc_header = f"Document {str(document_number)}: {info_source.semantic_identifier}"

    # Combine all parts with proper spacing
    document_content = f"{doc_header}\n\n{metadata_str}\n\n{info_content}"

    return document_content


def get_near_empty_step_results(
    step_number: int,
    step_answer: str,
    verified_reranked_documents: list[InferenceSection] = [],
) -> SubQuestionAnswerResults:
    """
    Get near-empty step results from a list of step results.
    """
    return SubQuestionAnswerResults(
        question=STEP_DESCRIPTIONS[step_number].description,
        question_id="0_" + str(step_number),
        answer=step_answer,
        verified_high_quality=True,
        sub_query_retrieval_results=[],
        verified_reranked_documents=verified_reranked_documents,
        context_documents=[],
        cited_documents=[],
        sub_question_retrieval_stats=AgentChunkRetrievalStats(
            verified_count=None,
            verified_avg_scores=None,
            rejected_count=None,
            rejected_avg_scores=None,
            verified_doc_chunk_ids=[],
            dismissed_doc_chunk_ids=[],
        ),
    )
