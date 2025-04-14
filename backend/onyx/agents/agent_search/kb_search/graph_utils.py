from typing import Set

from onyx.agents.agent_search.kb_search.models import KGExpendedGraphObjects
from onyx.db.engine import get_session_with_current_tenant
from onyx.db.relationships import get_relationships_of_entity
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
                graph[target].add(source)  # Add reverse edge since graph is undirected
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
    entities: list[str], relationships: list[str], max_depth: int = 2
) -> KGExpendedGraphObjects:
    """
    Find the minimal subgraph that connects all input entities, using only general entities
    (<entity_type>:*) as intermediate nodes. The subgraph will include only the relationships
    necessary to connect all input entities through the shortest possible paths.

    Args:
        entities: Initial list of entity IDs
        relationships: Initial list of relationships in format source__relationship__target
        max_depth: Maximum depth to expand the graph (default: 2)

    Returns:
        KGExpendedGraphObjects containing expanded entities and relationships
    """
    # Create copies of input lists to avoid modifying originals
    expanded_entities = entities.copy()
    expanded_relationships = relationships.copy()

    # Keep track of original entities
    original_entities = set(entities)

    # Build initial graph from existing relationships
    graph: dict[str, set[tuple[str, str]]] = {
        entity: set() for entity in expanded_entities
    }
    for rel in relationships:
        try:
            source, rel_name, target = rel.split("__")
            if source in graph and target in graph:
                graph[source].add((target, rel_name))
                graph[target].add((source, rel_name))
        except ValueError:
            continue

    # For each depth level
    counter = 0
    while counter < max_depth:
        # Find all connected components in the current graph
        components = []
        visited = set()

        def dfs(node: str, component: set[str]) -> None:
            visited.add(node)
            component.add(node)
            for neighbor, _ in graph.get(node, set()):
                if neighbor not in visited:
                    dfs(neighbor, component)

        # Find all components
        for entity in expanded_entities:
            if entity not in visited:
                component: Set[str] = set()
                dfs(entity, component)
                components.append(component)

        # If we only have one component, we're done
        if len(components) == 1:
            break

        # Find the shortest path between any two components using general entities
        shortest_path = None
        shortest_path_length = float("inf")

        for comp1 in components:
            for comp2 in components:
                if comp1 == comp2:
                    continue

                # Try to find path between entities in different components
                for entity1 in comp1:
                    if not any(e in original_entities for e in comp1):
                        continue

                    # entity1_type = entity1.split(":")[0]

                    with get_session_with_current_tenant() as db_session:
                        entity1_rels = get_relationships_of_entity(db_session, entity1)

                    for rel1 in entity1_rels:
                        try:
                            source1, rel_name1, target1 = rel1.split("__")
                            if source1 != entity1:
                                continue

                            target1_type = target1.split(":")[0]
                            general_target = f"{target1_type}:*"

                            # Try to find path from general_target to comp2
                            for entity2 in comp2:
                                if not any(e in original_entities for e in comp2):
                                    continue

                                with get_session_with_current_tenant() as db_session:
                                    entity2_rels = get_relationships_of_entity(
                                        db_session, entity2
                                    )

                                for rel2 in entity2_rels:
                                    try:
                                        source2, rel_name2, target2 = rel2.split("__")
                                        if target2 != entity2:
                                            continue

                                        source2_type = source2.split(":")[0]
                                        general_source = f"{source2_type}:*"

                                        if general_target == general_source:
                                            # Found a path of length 2
                                            path = [
                                                (entity1, rel_name1, general_target),
                                                (general_target, rel_name2, entity2),
                                            ]
                                            if len(path) < shortest_path_length:
                                                shortest_path = path
                                                shortest_path_length = len(path)

                                    except ValueError:
                                        continue

                        except ValueError:
                            continue

        # If we found a path, add it to our graph
        if shortest_path:
            for source, rel_name, target in shortest_path:
                # Add general entity if needed
                if ":*" in source and source not in expanded_entities:
                    expanded_entities.append(source)
                if ":*" in target and target not in expanded_entities:
                    expanded_entities.append(target)

                # Add relationship
                rel = f"{source}__{rel_name}__{target}"
                if rel not in expanded_relationships:
                    expanded_relationships.append(rel)

                # Update graph
                if source not in graph:
                    graph[source] = set()
                if target not in graph:
                    graph[target] = set()
                graph[source].add((target, rel_name))
                graph[target].add((source, rel_name))

        counter += 1

    logger.debug(f"Number of expanded entities: {len(expanded_entities)}")
    logger.debug(f"Number of expanded relationships: {len(expanded_relationships)}")

    return KGExpendedGraphObjects(
        entities=expanded_entities, relationships=expanded_relationships
    )
