import re

from onyx.agents.agent_search.kb_search.models import KGEntityDocInfo
from onyx.agents.agent_search.kb_search.models import KGExpandedGraphObjects
from onyx.agents.agent_search.kb_search.states import SubQuestionAnswerResults
from onyx.agents.agent_search.kb_search.step_definitions import (
    KG_SEARCH_STEP_DESCRIPTIONS,
)
from onyx.agents.agent_search.shared_graph_utils.models import AgentChunkRetrievalStats
from onyx.chat.models import LlmDoc
from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import InferenceSection
from onyx.db.document import get_kg_doc_info_for_entity_name
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.entities import get_document_id_for_entity
from onyx.db.entities import get_entity_name
from onyx.db.entity_type import get_entity_types
from onyx.kg.utils.formatting_utils import make_entity_id
from onyx.kg.utils.formatting_utils import split_relationship_id
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
            source, _, target = split_relationship_id(relationship)
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
            entity_actual_name = get_entity_name(db_session, entity_id_name)

            return KGEntityDocInfo(
                doc_id=None,
                doc_semantic_id=None,
                doc_link=None,
                semantic_entity_name=f"{entity_type} {entity_actual_name or entity_id_name}",
                semantic_linked_entity_name=f"{entity_type} {entity_actual_name or entity_id_name}",
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
    logger.debug(f"Input answer: {answer}")

    # Clean up any spaces around ::
    answer = re.sub(r"::\s+", "::", answer)

    # Pattern to match entity_type::entity_name, with optional quotes
    pattern = r"(?:')?([a-zA-Z0-9-]+)::([a-zA-Z0-9]+)(?:')?"

    matches = list(re.finditer(pattern, answer))
    logger.debug(f"Found {len(matches)} matches")

    # get active entity types
    with get_session_with_current_tenant() as db_session:
        active_entity_types = [
            x.id_name for x in get_entity_types(db_session, active=True)
        ]
        logger.debug(f"Active entity types: {active_entity_types}")

    # Create dictionary for processed references
    processed_refs = {}

    for match in matches:
        entity_type = match.group(1).upper().strip()
        entity_name = match.group(2).strip()
        potential_entity_id_name = make_entity_id(entity_type, entity_name)

        if entity_type not in active_entity_types:
            continue

        replacement_candidate = get_doc_information_for_entity(potential_entity_id_name)

        if replacement_candidate.doc_id:
            # Store both the original match and the entity_id_name for replacement
            processed_refs[match.group(0)] = (
                replacement_candidate.semantic_linked_entity_name
            )
        else:
            processed_refs[match.group(0)] = replacement_candidate.semantic_entity_name

    # Replace all references in the answer
    for ref, replacement in processed_refs.items():
        answer = answer.replace(ref, replacement)
        logger.debug(f"Replaced {ref} with {replacement}")

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
        question=KG_SEARCH_STEP_DESCRIPTIONS[step_number].description,
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
