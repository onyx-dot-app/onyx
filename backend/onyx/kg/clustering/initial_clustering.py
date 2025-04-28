from collections import defaultdict
from typing import Any
from typing import Dict
from typing import List
from typing import Set

import numpy as np
from sklearn.cluster import SpectralClustering  # type: ignore
from thefuzz import fuzz  # type: ignore

from onyx.db.document import update_document_kg_info
from onyx.db.engine import get_session_with_current_tenant
from onyx.db.entities import add_entity
from onyx.db.entities import delete_entities_by_id_names
from onyx.db.entities import get_entities_by_grounding
from onyx.db.entity_type import get_determined_grounded_entity_types
from onyx.db.entity_type import get_grounded_entity_types_with_null_grounded_source
from onyx.db.relationships import add_relationship
from onyx.db.relationships import add_relationship_type
from onyx.db.relationships import delete_relationship_types_by_id_names
from onyx.db.relationships import delete_relationships_by_id_names
from onyx.db.relationships import get_all_relationship_types
from onyx.db.relationships import get_all_relationships
from onyx.kg.models import KGGroundingType
from onyx.kg.models import KGStage
from onyx.kg.utils.embeddings import encode_string_batch
from onyx.llm.factory import get_default_llms
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
            if entity_type.entity_values:  # Extra safety check
                ge_determined_entity_map[entity_type.id_name] = (
                    entity_type.entity_values
                )

    return ge_determined_entity_map


def _get_grounded_entity_type_no_source() -> dict[str, str]:
    """Build a dictionary mapping entity type id_names to their ge_grounding_signature values.

    Args:
        db_session: SQLAlchemy session

    Returns:
        Dictionary mapping entity type id_names to their ge_grounding_signature values
        for all entity types that have a grounding signature defined
    """
    with get_session_with_current_tenant() as db_session:
        entity_types = get_grounded_entity_types_with_null_grounded_source(db_session)
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
        return {i: [rel["name"]] for (i, rel) in enumerate(relationship_data)}

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

        rel.source_document

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
        reverse_relationship_replacements_count[clustered_id] += rel.occurances or 1

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
    Initially, this will only focus on grounded entities with pre-determined
    relationships, so clustering is actually not yet required.
    The primary purpose of this function is to populate the actual KG tables
    from the temp_extraction tables.

    This will change with deep extraction, where grounded-sourceless entities
    can be extracted and then need to be clustered.
    """

    logger.info(f"Starting kg clustering for tenant {tenant_id}")

    ## Retrieval

    source_documents_w_successful_transfers: Set[str] = set()
    source_documents_w_failed_transfers: Set[str] = set()

    primary_llm, fast_llm = get_default_llms()

    with get_session_with_current_tenant() as db_session:

        relationship_types = get_all_relationship_types(
            db_session, kg_stage=KGStage.EXTRACTED
        )

        relationships = get_all_relationships(db_session, kg_stage=KGStage.EXTRACTED)

        grounded_entities = get_entities_by_grounding(
            db_session, KGStage.EXTRACTED, KGGroundingType.GROUNDED
        )

    ## Clustering

    # TODO: re-implement clustering of ungrounded entities as well as
    # grounded entities that do not have a source document with deep extraction
    # enabled!
    # For now we would just create a trivial entity mapping from the
    # 'unclustered' entities to the 'clustered' entities. So we can simply
    # transfer the entity information from the Staging to the Normalized
    # tables.
    # This will be reimplemented when deep extraction is enabled.

    ## Database operations

    # create the clustered objects - entities

    transferred_entities: list[str] = []
    for grounded_entity in grounded_entities:
        with get_session_with_current_tenant() as db_session:
            added_entity = add_entity(
                db_session,
                KGStage.NORMALIZED,
                entity_type=grounded_entity.entity_type_id_name,
                name=grounded_entity.name,
                occurances=grounded_entity.occurances or 1,
                document_id=grounded_entity.document_id or None,
                attributes=grounded_entity.attributes or None,
            )

            db_session.commit()

            if added_entity:
                transferred_entities.append(added_entity.id_name)

    transferred_relationship_types: list[str] = []
    for relationship_type in relationship_types:
        with get_session_with_current_tenant() as db_session:
            added_relationship_type_id_name = add_relationship_type(
                db_session,
                KGStage.NORMALIZED,
                source_entity_type=relationship_type.source_entity_type_id_name,
                relationship_type=relationship_type.type,
                target_entity_type=relationship_type.target_entity_type_id_name,
                extraction_count=relationship_type.occurances or 1,
            )

            db_session.commit()

            transferred_relationship_types.append(added_relationship_type_id_name)

    transferred_relationships: list[str] = []
    for relationship in relationships:
        with get_session_with_current_tenant() as db_session:
            try:
                added_relationship = add_relationship(
                    db_session,
                    KGStage.NORMALIZED,
                    relationship_id_name=relationship.id_name,
                    source_document_id=relationship.source_document or "",
                    occurances=relationship.occurances or 1,
                )

                if relationship.source_document:
                    source_documents_w_successful_transfers.add(
                        relationship.source_document
                    )

                db_session.commit()

                transferred_relationships.append(added_relationship.id_name)

            except Exception as e:
                if relationship.source_document:
                    source_documents_w_failed_transfers.add(
                        relationship.source_document
                    )
                logger.error(
                    f"Error transferring relationship {relationship.id_name}: {e}"
                )

    # TODO: remove the /relationship types & entities that correspond to relationships
    # source documents that failed to transfer. I.e, do a proper rollback

    # TODO: update Vespa info when clustering/changes are performed

    # delete the added objects from the staging tables

    try:
        with get_session_with_current_tenant() as db_session:
            delete_relationships_by_id_names(
                db_session, transferred_relationships, kg_stage=KGStage.EXTRACTED
            )
            db_session.commit()
    except Exception as e:
        logger.error(f"Error deleting relationships: {e}")

    try:
        with get_session_with_current_tenant() as db_session:
            delete_relationship_types_by_id_names(
                db_session, transferred_relationship_types, kg_stage=KGStage.EXTRACTED
            )
            db_session.commit()
    except Exception as e:
        logger.error(f"Error deleting relationship types: {e}")

    try:
        with get_session_with_current_tenant() as db_session:
            delete_entities_by_id_names(
                db_session, transferred_entities, kg_stage=KGStage.EXTRACTED
            )
            db_session.commit()
    except Exception as e:
        logger.error(f"Error deleting entities: {e}")

    # Update document kg info

    # with get_session_with_current_tenant() as db_session:
    #     all_kg_extracted_documents_info = get_all_kg_extracted_documents_info(
    #         db_session
    #     )

    for document_id in source_documents_w_successful_transfers:

        # Update the document kg info
        with get_session_with_current_tenant() as db_session:
            update_document_kg_info(
                db_session,
                document_id=document_id,
                kg_stage=KGStage.NORMALIZED,
            )
            db_session.commit()
