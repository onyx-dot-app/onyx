from collections import defaultdict
from typing import Dict
from typing import List
from typing import Optional

import numpy as np
from thefuzz import process  # type: ignore

from onyx.db.engine import get_session_with_current_tenant
from onyx.db.entities import get_entities_for_types
from onyx.db.relationships import get_relationships_for_entity_type_pairs
from onyx.kg.models import NormalizedEntities
from onyx.kg.models import NormalizedRelationships
from onyx.kg.models import NormalizedTerms
from onyx.kg.utils.embeddings import encode_string_batch


def _get_existing_normalized_entities(raw_entities: List[str]) -> List[str]:
    """
    Get existing normalized entities from the database.
    """

    entity_types = list(set([entity.split(":")[0] for entity in raw_entities]))

    with get_session_with_current_tenant() as db_session:
        entities = get_entities_for_types(db_session, entity_types)

    return [entity.id_name for entity in entities]


def _get_existing_normalized_relationships(
    raw_relationships: List[str],
) -> Dict[str, Dict[str, List[str]]]:
    """
    Get existing normalized relationships from the database.
    """

    relationship_type_map: Dict[str, Dict[str, List[str]]] = defaultdict(
        lambda: defaultdict(list)
    )
    relationship_pairs = list(
        set(
            [
                (
                    relationship.split("__")[0].split(":")[0],
                    relationship.split("__")[2].split(":")[0],
                )
                for relationship in raw_relationships
            ]
        )
    )

    with get_session_with_current_tenant() as db_session:
        relationships = get_relationships_for_entity_type_pairs(
            db_session, relationship_pairs
        )

    for relationship in relationships:
        relationship_type_map[relationship.source_entity_type_id_name][
            relationship.target_entity_type_id_name
        ].append(relationship.id_name)

    return relationship_type_map


def normalize_entities(raw_entities: List[str]) -> NormalizedEntities:
    """
    Match each entity against a list of normalized entities using fuzzy matching.
    Returns the best matching normalized entity for each input entity.

    Args:
        entities: List of entity strings to normalize

    Returns:
        List of normalized entity strings
    """
    # Assume this is your predefined list of normalized entities
    norm_entities = _get_existing_normalized_entities(raw_entities)

    normalized_results: List[str] = []
    normalized_map: Dict[str, str | None] = {}
    threshold = 80  # Adjust threshold as needed

    for entity in raw_entities:
        if "*" in entity:
            normalized_results.append(entity)
            normalized_map[entity] = entity
            continue

        # Find the best match and its score from norm_entities
        best_match, score = process.extractOne(entity, norm_entities)

        if score >= threshold:
            normalized_results.append(best_match)
            normalized_map[entity] = best_match
        else:
            # If no good match found, keep original
            normalized_map[entity] = None

    return NormalizedEntities(
        entities=normalized_results, entity_normalization_map=normalized_map
    )


def normalize_relationships(
    raw_relationships: List[str], entity_normalization_map: Dict[str, Optional[str]]
) -> NormalizedRelationships:
    """
    Normalize relationships using entity mappings and relationship string matching.

    Args:
        relationships: List of relationships in format "source__relation__target"
        entity_normalization_map: Mapping of raw entities to normalized ones (or None)

    Returns:
        NormalizedRelationships containing normalized relationships and mapping
    """
    # Placeholder for normalized relationship structure
    nor_relationships = _get_existing_normalized_relationships(raw_relationships)

    normalized_rels: List[str] = []
    normalization_map: Dict[str, str | None] = {}

    for raw_rel in raw_relationships:
        # 1. Split and normalize entities
        try:
            source, rel_string, target = raw_rel.split("__")
        except ValueError:
            raise ValueError(f"Invalid relationship format: {raw_rel}")

        # Check if entities are in normalization map and not None
        norm_source = entity_normalization_map.get(source)
        norm_target = entity_normalization_map.get(target)

        if norm_source is None or norm_target is None:
            normalization_map[raw_rel] = None
            continue

        # 2. Find candidate normalized relationships
        candidate_rels = []
        norm_source_type = norm_source.split(":")[0]
        norm_target_type = norm_target.split(":")[0]
        if (
            norm_source_type in nor_relationships
            and norm_target_type in nor_relationships[norm_source_type]
        ):
            candidate_rels = [
                rel.split("__")[1]
                for rel in nor_relationships[norm_source_type][norm_target_type]
            ]

        if not candidate_rels:
            normalization_map[raw_rel] = None
            continue

        # 3. Encode and find best match
        strings_to_encode = [rel_string] + candidate_rels
        vectors = encode_string_batch(strings_to_encode)

        # Get raw relation vector and candidate vectors
        raw_vector = vectors[0]
        candidate_vectors = vectors[1:]

        # Calculate dot products
        dot_products = np.dot(candidate_vectors, raw_vector)
        best_match_idx = np.argmax(dot_products)

        # Create normalized relationship
        norm_rel = f"{norm_source}__{candidate_rels[best_match_idx]}__{norm_target}"
        normalized_rels.append(norm_rel)
        normalization_map[raw_rel] = norm_rel

    return NormalizedRelationships(
        relationships=normalized_rels, relationship_normalization_map=normalization_map
    )


def normalize_terms(raw_terms: List[str]) -> NormalizedTerms:
    """
    Normalize terms using semantic similarity matching.

    Args:
        terms: List of terms to normalize

    Returns:
        NormalizedTerms containing normalized terms and mapping
    """
    # # Placeholder for normalized terms - this would typically come from a predefined list
    # normalized_term_list = [
    #     "algorithm",
    #     "database",
    #     "software",
    #     "programming",
    #     # ... other normalized terms ...
    # ]

    # normalized_terms: List[str] = []
    # normalization_map: Dict[str, str | None] = {}

    # if not raw_terms:
    #     return NormalizedTerms(terms=[], term_normalization_map={})

    # # Encode all terms at once for efficiency
    # strings_to_encode = raw_terms + normalized_term_list
    # vectors = encode_string_batch(strings_to_encode)

    # # Split vectors into query terms and candidate terms
    # query_vectors = vectors[:len(raw_terms)]
    # candidate_vectors = vectors[len(raw_terms):]

    # # Calculate similarity for each term
    # for i, term in enumerate(raw_terms):
    #     # Calculate dot products with all candidates
    #     similarities = np.dot(candidate_vectors, query_vectors[i])
    #     best_match_idx = np.argmax(similarities)
    #     best_match_score = similarities[best_match_idx]

    #     # Use a threshold to determine if the match is good enough
    #     if best_match_score > 0.7:  # Adjust threshold as needed
    #         normalized_term = normalized_term_list[best_match_idx]
    #         normalized_terms.append(normalized_term)
    #         normalization_map[term] = normalized_term
    #     else:
    #         # If no good match found, keep original
    #         normalization_map[term] = None

    # return NormalizedTerms(
    #     terms=normalized_terms,
    #     term_normalization_map=normalization_map
    # )

    return NormalizedTerms(
        terms=raw_terms, term_normalization_map={term: term for term in raw_terms}
    )
