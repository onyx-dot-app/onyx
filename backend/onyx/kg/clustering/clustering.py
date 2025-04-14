from collections import defaultdict
from typing import Any
from typing import Dict
from typing import List
from typing import Set

import numpy as np
from langchain.schema import HumanMessage
from sklearn.cluster import SpectralClustering  # type: ignore
from thefuzz import fuzz  # type: ignore

from onyx.db.document import get_all_kg_processed_documents_info
from onyx.db.document import get_kg_processed_document_ids
from onyx.db.document import update_document_kg_info
from onyx.db.engine import get_session_with_current_tenant
from onyx.db.entities import add_entity
from onyx.db.entities import delete_entities_by_id_names
from onyx.db.entities import get_determined_grounded_entity_types
from onyx.db.entities import get_entity_types_with_grounding_signature
from onyx.db.entities import get_ge_entities_by_types
from onyx.db.entities import get_grounded_entities
from onyx.db.entities import get_ungrounded_entities
from onyx.db.relationships import add_relationship
from onyx.db.relationships import add_relationship_type
from onyx.db.relationships import delete_relationship_types_by_id_names
from onyx.db.relationships import delete_relationships_by_id_names
from onyx.db.relationships import get_all_relationship_types
from onyx.db.relationships import get_all_relationships
from onyx.document_index.vespa.index import KGUChunkUpdateRequest
from onyx.document_index.vespa.kg_interactions import update_kg_chunks_vespa_info
from onyx.kg.utils.embeddings import encode_string_batch
from onyx.kg.utils.formatting_utils import format_entity
from onyx.kg.utils.formatting_utils import format_relationship
from onyx.kg.vespa.vespa_interactions import get_document_chunks_for_kg_processing
from onyx.llm.factory import get_default_llms
from onyx.llm.utils import message_to_string
from onyx.utils.logger import setup_logger


logger = setup_logger()


def _create_ge_determined_entity_map() -> Dict[str, List[str]]:
    """Create a mapping of entity type ID names to their grounding determination instructions.

    Returns:
        Dictionary mapping entity type ID names to their list of grounding determination instructions
    """
    ge_determined_entity_map: Dict[str, List[str]] = defaultdict(list)

    with get_session_with_current_tenant() as db_session:
        determined_entities = get_determined_grounded_entity_types(db_session)

        for entity_type in determined_entities:
            if entity_type.ge_determine_instructions:  # Extra safety check
                ge_determined_entity_map[entity_type.id_name] = (
                    entity_type.ge_determine_instructions
                )

    return ge_determined_entity_map


def _get_entity_type_grounding_signatures() -> dict[str, str]:
    """Build a dictionary mapping entity type id_names to their ge_grounding_signature values.

    Args:
        db_session: SQLAlchemy session

    Returns:
        Dictionary mapping entity type id_names to their ge_grounding_signature values
        for all entity types that have a grounding signature defined
    """
    with get_session_with_current_tenant() as db_session:
        entity_types = get_entity_types_with_grounding_signature(db_session)
    return {
        entity_type.id_name: entity_type.ge_grounding_signature
        for entity_type in entity_types
        if entity_type.ge_grounding_signature is not None
    }


def _cluster_relationships(
    relationship_data: List[dict], n_clusters: int = 3, batch_size: int = 12
) -> Dict[int, List[str]]:
    """
    Cluster relationships using their embeddings.

    Args:
        relationship_data: List of dicts with 'name' and 'cluster_count'
        n_clusters: Number of clusters to create
        batch_size: Size of batches for embedding requests

    Returns:
        Dictionary mapping cluster IDs to lists of relationship names
    """

    # TODO: This is TEMP for the pre-defined relationships.
    # if len(relationship_data) < n_clusters:
    if len(relationship_data) < n_clusters:
        logger.warning(
            "Not enough relationships to cluster. Returning each relationship as its own cluster."
        )
        return {
            i: [rel["name"] for rel in relationship_data]
            for i in range(len(relationship_data))
        }

    train_data = []
    rel_names = []

    # Process relationships in batches
    for i in range(0, len(relationship_data), batch_size):
        batch = relationship_data[i : i + batch_size]
        batch_names = [
            rel["name"].replace("_", " ") for rel in batch
        ]  # better for LLM to have spaces between words

        # Get embeddings for the entire batch at once
        batch_embeddings = encode_string_batch(batch_names)

        # Add embeddings and corresponding data
        for rel, embedding in zip(batch, batch_embeddings):
            count = int(rel["cluster_count"]) or 1
            # Add the relationship name 'count' times
            for _ in range(count):
                train_data.append(embedding)
                rel_names.append(rel["name"])

    # Convert to numpy arrays
    X = np.array(train_data)

    # Perform clustering
    # clustering = KMeans(n_clusters=n_clusters, random_state=42)
    clustering = SpectralClustering(n_clusters=n_clusters, random_state=42)
    clusters = clustering.fit_predict(X)

    # Group relationship names by cluster
    cluster_groups: Dict[int, List[str]] = defaultdict(list)
    for rel_name, cluster_id in zip(rel_names, clusters):
        if rel_name not in cluster_groups[cluster_id]:
            cluster_groups[cluster_id].append(rel_name)

    return dict(cluster_groups)


def _cluster_entities(
    entity_data: List[dict], n_clusters: int = 3, batch_size: int = 12
) -> Dict[int, List[str]]:
    """
    Cluster entities using their embeddings.

    Args:
        entity_data: List of dicts with 'name' and 'cluster_count'
        n_clusters: Number of clusters to create
        batch_size: Size of batches for embedding requests

    Returns:
        Dictionary mapping cluster IDs to lists of entity names
    """

    if len(entity_data) < n_clusters:
        logger.warning(
            "Not enough entities to cluster. Returning each entity as its own cluster."
        )
        return {
            i: [ent["name"] for ent in entity_data] for i in range(len(entity_data))
        }

    train_data = []
    entity_names = []

    # Process entities in batches
    for i in range(0, len(entity_data), batch_size):
        batch = entity_data[i : i + batch_size]
        batch_names = [
            ent["name"].replace("_", " ") for ent in batch
        ]  # use spaces between words for LLM

        # Get embeddings for the entire batch at once
        batch_embeddings = encode_string_batch(batch_names)

        # Add embeddings and corresponding data
        for ent, embedding in zip(batch, batch_embeddings):
            count = int(ent["cluster_count"]) or 1

            # Add the entity name 'count' times
            for _ in range(count):
                entity_names.append(ent["name"])
                train_data.append(embedding)

    # Convert to numpy arrays
    X = np.array(train_data)

    # Perform clustering
    # clustering = KMeans(n_clusters=n_clusters, random_state=42)
    clustering = SpectralClustering(n_clusters=n_clusters, random_state=42)
    clusters = clustering.fit_predict(X)

    # Group entity names by cluster
    cluster_groups: Dict[int, List[str]] = defaultdict(list)
    for ent_name, cluster_id in zip(entity_names, clusters):
        if ent_name not in cluster_groups[cluster_id]:
            cluster_groups[cluster_id].append(ent_name)

    return dict(cluster_groups)


def _create_relationship_type_mapping(
    full_clustering_results: Dict[str, Dict[str, Dict[int, Dict[str, Any]]]],
    relationship_mapping: Dict[str, Dict[str, List[dict]]],
) -> tuple[Dict[str, str], Dict[str, int]]:
    """
    Create a mapping between original relationship types and their clustered versions.

    Args:
        full_clustering_results: Clustering results with cluster names
        relationship_mapping: Original relationship types organized by source/target

    Returns:
        Dictionary mapping original relationship type ID to clustered relationship type ID
    """
    relationship_type_replacements: Dict[str, str] = {}
    reverse_relationship_type_replacements_count: Dict[str, int] = defaultdict(int)

    for source_type, target_dict in relationship_mapping.items():
        for target_type, rel_types in target_dict.items():
            # Get clusters for this source/target pair
            clusters = full_clustering_results.get(source_type, {}).get(target_type, {})

            for cluster_id, cluster_info in clusters.items():
                cluster_name = cluster_info["cluster_name"]
                for rel_name in cluster_info["relationships"]:
                    original_id = f"{source_type}__{rel_name.lower()}__{target_type}"
                    clustered_id = (
                        f"{source_type}__{cluster_name.lower()}__{target_type}"
                    )
                    relationship_type_replacements[original_id] = clustered_id
                    reverse_relationship_type_replacements_count[clustered_id] += len(
                        cluster_info["relationships"]
                    )

    return relationship_type_replacements, reverse_relationship_type_replacements_count


def _create_entity_mapping(
    full_entity_clustering_results: Dict[str, Dict[int, Dict[str, Any]]],
    entity_mapping: Dict[str, List[dict]],
) -> tuple[Dict[str, str], Dict[str, int]]:
    """
    Create a mapping between original entities and their clustered versions.

    Args:
        full_entity_clustering_results: Clustering results with cluster names
        entity_mapping: Original entities organized by entity type

    Returns:
        Dictionary mapping original entity ID to clustered entity ID
    """
    entity_replacements: Dict[str, str] = {}
    reverse_entity_replacements_count: Dict[str, int] = defaultdict(int)

    for entity_type, clusters in full_entity_clustering_results.items():
        for cluster_id, cluster_info in clusters.items():
            cluster_name = cluster_info["cluster_name"]
            for entity_name in cluster_info["entities"]:
                # Skip wildcard entities
                if entity_name == "*":
                    continue

                original_id = f"{entity_type}:{entity_name}"
                clustered_id = f"{entity_type}:{cluster_name.title()}"
                entity_replacements[original_id] = clustered_id
                reverse_entity_replacements_count[clustered_id] += len(
                    cluster_info["entities"]
                )
    return entity_replacements, reverse_entity_replacements_count


def _create_relationship_mapping(
    relationship_type_replacements: Dict[str, str],
    reverse_relationship_type_replacements_count: Dict[str, int],
    entity_replacements: Dict[str, str],
    reverse_entity_replacements_count: Dict[str, int],
    relationships: List[
        Any
    ],  # This would be List[KGRelationship] but avoiding the import
) -> tuple[Dict[str, str], Dict[str, int]]:
    """
    Create a mapping between original relationships and their clustered versions,
    taking into account both clustered relationship types and clustered entities.

    Args:
        relationship_type_replacements: Mapping of original to clustered relationship type IDs
        entity_replacements: Mapping of original to clustered entity IDs
        relationships: List of relationships from the database

    Returns:
        Dictionary mapping original relationship ID to clustered relationship ID
    """
    relationship_replacements: Dict[str, str] = {}
    reverse_relationship_replacements_count: Dict[str, int] = defaultdict(int)

    for rel in relationships:
        # Skip if source or target is a wildcard

        # Get the clustered entities (if they exist)
        source_node = entity_replacements.get(rel.source_node, rel.source_node)
        target_node = entity_replacements.get(rel.target_node, rel.target_node)

        # Create the relationship type ID
        source_type = rel.source_node.split(":")[0]
        target_type = rel.target_node.split(":")[0]
        rel_type_id = f"{source_type}__{rel.type.lower()}__{target_type}"

        # Get the clustered relationship type (if it exists)
        clustered_rel_type_id = relationship_type_replacements.get(
            rel_type_id, rel_type_id
        )

        # Extract the relationship name from the clustered type ID
        _, rel_name, _ = clustered_rel_type_id.split("__")

        # Create the original and clustered relationship IDs
        original_id = f"{rel.source_node}__{rel.type.lower()}__{rel.target_node}"
        clustered_id = f"{source_node}__{rel_name}__{target_node}"

        relationship_replacements[original_id] = clustered_id
        reverse_relationship_replacements_count[clustered_id] += rel.cluster_count

    return relationship_replacements, reverse_relationship_replacements_count


def _match_ungrounded_ge_entities(
    ungrounded_ge_entities: Dict[str, List[str]],
    grounded_ge_entities: Dict[str, List[str]],
    fuzzy_match_threshold: int = 80,
) -> Dict[str, Dict[str, str]]:
    """
    Create a mapping for ungrounded entities by matching them to grounded entities
    or previously processed ungrounded entities. First checks for containment relationships,
    then falls back to fuzzy matching if no containment is found.

    Args:
        ungrounded_ge_entities: Dictionary mapping entity types to lists of ungrounded entity names
        grounded_ge_entities: Dictionary mapping entity types to lists of grounded entity names
        fuzzy_match_threshold: Threshold for fuzzy matching (0-100)

    Returns:
        Dictionary mapping entity types to dictionaries of {original_entity: matched_entity}
    """
    entity_match_mapping: Dict[str, Dict[str, str]] = defaultdict(dict)
    processed_entities: Dict[str, Set[str]] = defaultdict(set)

    # For each entity type
    for entity_type, ungrounded_entities_list in ungrounded_ge_entities.items():
        grounded_list = grounded_ge_entities.get(entity_type, [])

        # Process each ungrounded entity
        for ungrounded_entity in ungrounded_entities_list:
            if ungrounded_entity == "*":
                continue
            best_match = None

            # First check if ungrounded entity is contained in or contains any grounded entities
            for grounded_entity in grounded_list:
                if (
                    ungrounded_entity.lower() in grounded_entity.lower()
                    or grounded_entity.lower() in ungrounded_entity.lower()
                ):
                    best_match = grounded_entity
                    break

            # If no containment match with grounded entities, check previously processed ungrounded entities
            if not best_match:
                for processed_entity in processed_entities[entity_type]:
                    if (
                        ungrounded_entity.lower() in processed_entity.lower()
                        or processed_entity.lower() in ungrounded_entity.lower()
                    ):
                        best_match = processed_entity
                        break

            # If still no match, fall back to fuzzy matching
            if not best_match:
                best_score = 0

                # Try fuzzy matching with grounded entities
                for grounded_entity in grounded_list:
                    score = fuzz.ratio(
                        ungrounded_entity.lower(), grounded_entity.lower()
                    )
                    if score > fuzzy_match_threshold and score > best_score:
                        best_match = grounded_entity
                        best_score = score

                # Try fuzzy matching with previously processed ungrounded entities
                if not best_match:
                    for processed_entity in processed_entities[entity_type]:
                        score = fuzz.ratio(
                            ungrounded_entity.lower(), processed_entity.lower()
                        )
                        if score > fuzzy_match_threshold and score > best_score:
                            best_match = processed_entity
                            best_score = score

            # Record the mapping
            if best_match:
                entity_match_mapping[entity_type][ungrounded_entity] = best_match
            else:
                # No match found, this becomes a new unique entity
                entity_match_mapping[entity_type][ungrounded_entity] = ungrounded_entity
                processed_entities[entity_type].add(ungrounded_entity)

    # Log the results
    logger.info("Entity matching results:")
    for entity_type, mappings in entity_match_mapping.items():
        logger.info(f"\nEntity type: {entity_type}")
        for original, matched in mappings.items():
            if original != matched:
                logger.info(f"  Mapped: {original} -> {matched}")
            else:
                logger.info(f"  New unique entity: {original}")

    return entity_match_mapping


def _match_determined_ge_entities(
    determined_ge_entity_map: Dict[str, List[str]],
    determined_ge_entities_by_type: Dict[str, List[str]],
    fuzzy_match_threshold: int = 80,
) -> Dict[str, Dict[str, str]]:
    """
    Create a mapping for determined entities by matching them to grounded entities
    or previously processed ungrounded entities. First checks for containment relationships,
    then falls back to fuzzy matching if no containment is found.

    Args:
        ungrounded_ge_entities: Dictionary mapping entity types to lists of ungrounded entity names
        grounded_ge_entities: Dictionary mapping entity types to lists of grounded entity names
        fuzzy_match_threshold: Threshold for fuzzy matching (0-100)

    Returns:
        Dictionary mapping entity types to dictionaries of {original_entity: matched_entity}
    """
    determined_entity_match_mapping: Dict[str, Dict[str, str]] = defaultdict(dict)

    # For each entity type
    for entity_type, determined_entities_list in determined_ge_entity_map.items():
        ungrounded_list = determined_ge_entities_by_type.get(entity_type, [])

        # Process each ungrounded entity
        for ungrounded_entity in ungrounded_list:
            if ungrounded_entity == "*":
                continue
            best_match = None

            # First check if ungrounded entity is contained in or contains any grounded entities
            for grounded_entity in determined_entities_list:
                if (
                    ungrounded_entity.lower() in grounded_entity.lower()
                    or grounded_entity.lower() in ungrounded_entity.lower()
                ):
                    best_match = grounded_entity
                    break

            # If still no match, fall back to fuzzy matching
            if not best_match:
                best_score = 0

                # Try fuzzy matching with grounded entities
                for grounded_entity in determined_entities_list:
                    score = fuzz.ratio(
                        ungrounded_entity.lower(), grounded_entity.lower()
                    )
                    if score > fuzzy_match_threshold and score > best_score:
                        best_match = grounded_entity
                        best_score = score

            # Record the mapping
            if best_match:
                determined_entity_match_mapping[entity_type][
                    f"{ungrounded_entity}"
                ] = f"{best_match}"
            else:
                # No match found, this becomes a new unique entity
                determined_entity_match_mapping[entity_type][
                    f"{ungrounded_entity}"
                ] = "Other"

    # Log the results
    logger.info("Entity matching results:")
    for entity_type, mappings in determined_entity_match_mapping.items():
        logger.info(f"\nEntity type: {entity_type}")
        for original, matched in mappings.items():
            if original != matched:
                logger.info(f"  Mapped: {original} -> {matched}")
            else:
                logger.info(f"  New unique entity: {original}")

    return determined_entity_match_mapping


def kg_clustering(
    tenant_id: str, index_name: str, processing_chunk_batch_size: int = 8
) -> None:
    """
    Here we will cluster the extractions based on their cluster frameworks.
    """

    logger.info(f"Starting kg clustering for tenant {tenant_id}")

    primary_llm, fast_llm = get_default_llms()

    with get_session_with_current_tenant() as db_session:
        relationship_types = get_all_relationship_types(db_session)
        ungrounded_entities = get_ungrounded_entities(db_session)
        grounded_entities = get_grounded_entities(db_session)

    # cluster 'semi-grounded' entities - TODO: re-think once all grounded entities are actually grounded
    # TODO: make less manual - this is POC only!

    # Define for each grounded type what needs to be in id_name to be considered grounded entity
    # TODO: THIS NEEDS TO BE in DB. FOR POC ONLY!

    ge_grounding_format: Dict[str, str] = _get_entity_type_grounding_signatures()

    grounded_ge_entities: Dict[str, List[str]] = defaultdict(list)
    ungrounded_ge_entities: Dict[str, List[str]] = defaultdict(list)

    # grounded_ge_entity_mapping: Dict[str, List[dict]] = defaultdict(list)
    # ungrounded_ge_entity_mapping: Dict[str, List[dict]] = defaultdict(list)

    for grounded_entity in grounded_entities:
        if grounded_entity.name == "*":
            continue

        if grounded_entity.entity_type_id_name in ge_grounding_format:
            if (
                ge_grounding_format[grounded_entity.entity_type_id_name]
                in grounded_entity.id_name
            ):
                grounded_ge_entities[grounded_entity.entity_type_id_name].append(
                    grounded_entity.name
                )
            else:
                ungrounded_ge_entities[grounded_entity.entity_type_id_name].append(
                    grounded_entity.name
                )
        else:
            grounded_ge_entities[grounded_entity.entity_type_id_name].append(
                grounded_entity.name
            )

    # Create mapping for 'ungrounded' grounded entities
    ge_entity_match_mapping = _match_ungrounded_ge_entities(
        ungrounded_ge_entities, grounded_ge_entities, fuzzy_match_threshold=80
    )

    ge_determined_entity_map: Dict[str, List[str]] = _create_ge_determined_entity_map()

    with get_session_with_current_tenant() as db_session:
        determined_ge_entities = get_ge_entities_by_types(
            db_session, list(ge_determined_entity_map.keys())
        )
        # Organize entities by type
        determined_ge_entities_by_type: Dict[str, List[str]] = defaultdict(list)
        for entity in determined_ge_entities:
            determined_ge_entities_by_type[entity.entity_type_id_name].append(
                entity.name
            )

    # Create mapping for 'determined' grounded entities
    determined_ge_entity_match_mapping = _match_determined_ge_entities(
        ge_determined_entity_map,
        determined_ge_entities_by_type,
        fuzzy_match_threshold=80,
    )

    # Cliuster relationship_types
    relationship_mapping: Dict[str, Dict[str, List[dict]]] = defaultdict(
        lambda: defaultdict(list)
    )

    for rel_type_obj in relationship_types:
        relationship_mapping[rel_type_obj.source_entity_type_id_name][
            rel_type_obj.target_entity_type_id_name
        ].append(
            {"name": rel_type_obj.name, "cluster_count": rel_type_obj.cluster_count}
        )

    # Store clustering results
    clustering_results: Dict[str, Dict[str, Dict[int, List[str]]]] = defaultdict(
        lambda: defaultdict(dict)
    )

    # Perform clustering for each source/target type pair
    for source_type_str, cluster_target_dict in relationship_mapping.items():
        for target_type_str, rel_types in cluster_target_dict.items():
            # Skip if no relationships
            if not rel_types:
                continue

            # Perform clustering
            clusters = _cluster_relationships(rel_types)

            # Store results
            clustering_results[source_type_str][target_type_str] = clusters

            # Log results
            logger.info(
                f"Clustering results for {source_type_str} -> {target_type_str}:"
            )
            for cluster_id, rel_names in clusters.items():
                logger.info(f"Cluster {cluster_id}: {rel_names}")

    # Generate cluster names using fast LLM
    full_clustering_results: Dict[str, Dict[str, Dict[int, Dict[str, Any]]]] = (
        defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))
    )
    for source_type_str, target_cluster_dict in clustering_results.items():
        for target_type_str, clusters in target_cluster_dict.items():
            for cluster_id, rel_names in clusters.items():
                if len(rel_names) == 1:
                    cluster_name = rel_names[0].replace(
                        " ", "_"
                    )  # in table we use '_' between words
                    # Just use the existing relationship name as the cluster name
                    full_clustering_results[source_type_str][target_type_str][
                        cluster_id
                    ] = {
                        "relationships": rel_names,
                        "cluster_name": cluster_name,
                    }

                # Create prompt for the LLM
                else:
                    prompt = f"""Given these relationship names between source type {source_type_str}\
and target type {target_type_str}:

{', '.join(rel_names)}

Generate a single, short (1-3 words) relationship name that best captures the semantic meaning of all these relationships. \
Also make sure that the relationship naturally connects the source type to the target type, as ultimately we will \
use the new term for a relationship <source_type>:<relationship_name>:<target_type>. Also, keep it simple and concise.
Only output the relationship name, nothing else."""

                    try:
                        cluster_name_result = primary_llm.invoke(prompt)
                        cluster_name = message_to_string(cluster_name_result).replace(
                            " ", "_"
                        )  # in table we use '_' between words
                        logger.info(
                            f"Generated cluster name '{cluster_name}' for cluster {cluster_id} "
                            f"between {source_type_str} and {target_type_str}"
                        )

                        # Add the generated name to the clustering results
                        full_clustering_results[source_type_str][target_type_str][
                            cluster_id
                        ] = {
                            "relationships": rel_names,
                            "cluster_name": cluster_name,
                        }
                    except Exception as e:
                        logger.error(
                            f"Failed to generate cluster name for {source_type_str}->{target_type_str} "
                            f"cluster {cluster_id}: {e}"
                        )

                        full_clustering_results[source_type_str][target_type_str][
                            cluster_id
                        ] = {
                            "relationships": rel_names,
                            "cluster_name": f"cluster_{cluster_id}",  # fallback name
                        }

    # Now handle entity clustering
    entity_mapping: Dict[str, List[dict]] = defaultdict(list)

    for ungrounded_entity in ungrounded_entities:
        # do not include the wildcard entity
        if ungrounded_entity.name == "*":
            continue

        entity_mapping[ungrounded_entity.entity_type_id_name].append(
            {
                "name": ungrounded_entity.name,
                "cluster_count": ungrounded_entity.cluster_count or 1,
            }
        )

    # Store entity clustering results
    entity_clustering_results: Dict[str, Dict[int, List[str]]] = defaultdict(dict)

    # Perform clustering for each entity type
    for entity_type, entity_names in entity_mapping.items():
        if not entity_names:
            continue

        # Perform clustering
        clusters = _cluster_entities(entity_names)

        # Store results
        entity_clustering_results[entity_type] = clusters

        # Log results
        logger.info(f"Clustering results for entity type {entity_type}:")
        for cluster_id, ent_names in clusters.items():
            logger.info(f"Cluster {cluster_id}: {ent_names}")

    full_entity_clustering_results: Dict[str, Dict[int, Dict[str, Any]]] = defaultdict(
        dict
    )
    for entity_type, clusters in entity_clustering_results.items():
        for cluster_id, ent_names in clusters.items():
            prompt = f"""Given these entity names of type {entity_type}:

{', '.join(ent_names)}

Generate a single, short (1-3 words) category name that best captures the semantic meaning of all these entities.
Only output the category name, nothing else."""

            msg = [
                HumanMessage(
                    content=prompt,
                )
            ]

            try:
                if len(ent_names) > 1:
                    cluster_name_result = primary_llm.invoke(msg)
                    cluster_name = message_to_string(cluster_name_result).replace(
                        " ", "_"
                    )  # in table we use '_' between words
                else:
                    cluster_name = ent_names[0].replace(
                        " ", "_"
                    )  # in table we use '_' between words; and only one name for the cluster, then keep it
                logger.info(
                    f"Generated cluster name '{cluster_name}' for {entity_type} cluster {cluster_id}"
                )

                # Add the generated name to the clustering results
                full_entity_clustering_results[entity_type][cluster_id] = {
                    "entities": ent_names,
                    "cluster_name": cluster_name,
                }
            except Exception as e:
                logger.error(
                    f"Failed to generate cluster name for {entity_type} "
                    f"cluster {cluster_id}: {e}"
                )

                full_entity_clustering_results[entity_type][cluster_id] = {
                    "entities": ent_names,
                    "cluster_name": f"cluster_{cluster_id}",  # fallback name
                }

    # replace with clustering results in postgres database

    # 1. relationship_types: generate the replacement dict if not available
    (
        relationship_type_replacements,
        reverse_relationship_type_replacements_count,
    ) = _create_relationship_type_mapping(full_clustering_results, relationship_mapping)

    # 2. entity_types: generate the replacement dict if not available

    entity_replacements, reverse_entity_replacements_count = _create_entity_mapping(
        full_entity_clustering_results, entity_mapping
    )

    # add the ungrounded 'grounded' entities
    for entity_type, mappings in ge_entity_match_mapping.items():
        for original, matched in mappings.items():
            entity_replacements[f"{entity_type}:{original}"] = (
                f"{entity_type}:{matched}"
            )
            reverse_entity_replacements_count[f"{entity_type}:{matched}"] += 1

    for entity_type, mappings in determined_ge_entity_match_mapping.items():
        for original, matched in mappings.items():
            entity_replacements[f"{entity_type}:{original}"] = (
                f"{entity_type}:{matched}"
            )
            reverse_entity_replacements_count[f"{entity_type}:{matched}"] += 1

    # add the ungrounded 'grounded' entities

    # 3. relations: generate the replacement dict if not available

    with get_session_with_current_tenant() as db_session:
        relationships = get_all_relationships(db_session)  # Need to add this function

    (
        relationship_replacements,
        reverse_relationship_replacements_count,
    ) = _create_relationship_mapping(
        relationship_type_replacements,
        reverse_relationship_type_replacements_count,
        entity_replacements,
        reverse_entity_replacements_count,
        relationships,
    )

    ## Database operations - DELETE

    # delete the relationships that will be replaced

    try:
        # Get the IDs of relationships to delete (the keys of our replacement dict)
        relationship_ids = list(relationship_replacements.keys())

        # Delete relationships using existing function

        with get_session_with_current_tenant() as db_session:
            deleted_count = delete_relationships_by_id_names(
                db_session, relationship_ids
            )
            db_session.commit()
        logger.info(
            f"Successfully deleted {deleted_count} relationships that will be replaced with clustered versions"
        )
    except Exception as e:
        db_session.rollback()
        logger.error(f"Failed to delete relationships: {e}")
        raise

    # delete the entities that will be replaced

    try:
        # Get the IDs of entities to delete (the keys of our replacement dict)
        entity_ids = list(entity_replacements.keys())

        # Delete entities using existing function
        with get_session_with_current_tenant() as db_session:
            deleted_count = delete_entities_by_id_names(db_session, entity_ids)
            db_session.commit()
        logger.info(
            f"Successfully deleted {deleted_count} entities that will be replaced with clustered versions"
        )
    except Exception as e:
        db_session.rollback()
        logger.error(f"Failed to delete entities: {e}")
        raise

    # delete the relationship types that will be replaced

    try:
        # Get the IDs of relationship types to delete (the keys of our replacement dict)
        relationship_type_ids = list(relationship_type_replacements.keys())

        # Delete relationship types using existing function
        with get_session_with_current_tenant() as db_session:
            deleted_count = delete_relationship_types_by_id_names(
                db_session, relationship_type_ids
            )
            db_session.commit()
        logger.info(
            f"Successfully deleted {deleted_count} relationship types that will be replaced with clustered versions"
        )
    except Exception as e:
        db_session.rollback()
        logger.error(f"Failed to delete relationship types: {e}")
        raise

    ## Database operations - ADD

    # add relationship types

    with get_session_with_current_tenant() as db_session:
        for (
            rel_type_str_5,
            rel_count_8,
        ) in reverse_relationship_type_replacements_count.items():
            assert isinstance(
                rel_type_str_5, str
            ), f"rel_type must be a string, got {type(rel_type_str_5)}"
            assert (
                rel_type_str_5.count("__") == 2
            ), f"Invalid relationship type: {rel_type_str_5}"
            source_type_str, rel_name, target_type_str = rel_type_str_5.split("__")

            add_relationship_type(
                db_session,
                source_entity_type=source_type_str,
                relationship_type=rel_name,
                target_entity_type=target_type_str,
                extraction_count=rel_count_8,
            )

            db_session.commit()

    # add entities

    with get_session_with_current_tenant() as db_session:
        for entity_str, entity_count in reverse_entity_replacements_count.items():
            if len(entity_str.split(":")) == 2:
                entity_type, entity_name = entity_str.split(":")
            else:
                logger.error(f"Invalid entity: {entity_str}")
                continue

            add_entity(
                db_session,
                entity_type=entity_type,
                name=entity_name,
                cluster_count=entity_count,
            )

            db_session.commit()

    # add relationships

    with get_session_with_current_tenant() as db_session:
        for rel, rel_count_8 in reverse_relationship_replacements_count.items():
            add_relationship(
                db_session, relationship_id_name=rel, cluster_count=rel_count_8
            )

            db_session.commit()

    # replace with clustering results in vespa database

    with get_session_with_current_tenant() as db_session:
        kg_processed_document_ids = get_kg_processed_document_ids(db_session)

        for document_id in kg_processed_document_ids:
            formatted_chunk_batches = get_document_chunks_for_kg_processing(
                document_id,
                index_name,
                batch_size=processing_chunk_batch_size,
            )

            new_kg_update_requests = []

            for formatted_chunk_batch in formatted_chunk_batches:
                for formatted_chunk in formatted_chunk_batch:
                    previous_entities = formatted_chunk.entities.keys()
                    previous_relationships = formatted_chunk.relationships.keys()
                    formatted_chunk.terms.keys()

                    replacement_entities: Set[str] = set()
                    replacement_relationships: Set[str] = set()
                    replacement_terms: Set[str] = set()

                    for prev_entity in previous_entities:
                        replacement_entities.add(
                            entity_replacements.get(
                                format_entity(prev_entity),
                                format_entity(prev_entity),
                            )
                        )

                    for previous_relationship in previous_relationships:
                        replacement_relationships.add(
                            relationship_replacements.get(
                                format_relationship(previous_relationship),
                                format_relationship(previous_relationship),
                            )
                        )

                    new_kg_update_requests.append(
                        KGUChunkUpdateRequest(
                            document_id=document_id,
                            chunk_id=formatted_chunk.chunk_id,
                            core_entity="",  # core entities only apply to grounded entities which are not affected by clustering.
                            entities=replacement_entities,
                            relationships=replacement_relationships,
                            terms=replacement_terms,
                        )
                    )

                update_kg_chunks_vespa_info(
                    new_kg_update_requests, index_name, tenant_id
                )

    # Update document kg info

    with get_session_with_current_tenant() as db_session:
        all_kg_processed_documents_info = get_all_kg_processed_documents_info(
            db_session
        )

    for document_id, document_kg_info in all_kg_processed_documents_info:
        original_doc_entities = document_kg_info["entities"]
        original_doc_relationships = document_kg_info["relationships"]
        original_doc_terms = document_kg_info["terms"]

        doc_replacement_entities = [
            entity_replacements.get(
                format_entity(previous_entity),
                format_entity(previous_entity),
            )
            for previous_entity in original_doc_entities
        ]

        doc_replacement_relationships = [
            relationship_replacements.get(
                format_relationship(previous_relationship),
                format_relationship(previous_relationship),
            )
            for previous_relationship in original_doc_relationships
        ]

        doc_replacement_terms = original_doc_terms

        replacement_kg_data = {
            "entities": doc_replacement_entities,
            "relationships": doc_replacement_relationships,
            "terms": doc_replacement_terms,
        }

        # Update the document kg info
        with get_session_with_current_tenant() as db_session:
            update_document_kg_info(
                db_session,
                document_id=document_id,
                kg_processed=True,
                kg_data=replacement_kg_data,
            )
            db_session.commit()
