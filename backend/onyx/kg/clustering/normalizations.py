import re
from collections import defaultdict
from typing import Dict
from typing import List
from typing import Optional

import numpy as np
from nltk import ngrams  # type: ignore
from rapidfuzz.distance.DamerauLevenshtein import normalized_similarity
from sqlalchemy import desc
from sqlalchemy import Float
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy import String
from sqlalchemy.dialects.postgresql import ARRAY

from onyx.db.engine import get_session_with_current_tenant
from onyx.db.models import KGEntity
from onyx.db.relationships import get_relationships_for_entity_type_pairs
from onyx.kg.models import NormalizedEntities
from onyx.kg.models import NormalizedRelationships
from onyx.kg.models import NormalizedTerms
from onyx.kg.utils.embeddings import encode_string_batch


alphanum_regex = re.compile(r"[^a-z0-9]+")
rem_email_regex = re.compile(r"(?<=\S)@([a-z0-9-]+)\.([a-z]{2,6})$")


def _split_entity_type_v_name(entity: str) -> tuple[str, str]:
    """
    Split an entity string into type and name.
    """

    entity_split = entity.split("::")
    if len(entity_split) < 2:
        raise ValueError(f"Invalid entity: {entity}")

    entity_type = entity_split[0]
    entity_name = "::".join(entity_split[1:])

    return entity_type, entity_name


def _clean_entity_name(entity_name: str) -> str:
    """
    Clean an entity name by removing email addresses and other non-alphanumeric characters.
    """
    cleaned_name = entity_name.casefold()
    return alphanum_regex.sub("", rem_email_regex.sub("", cleaned_name)) or cleaned_name


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
                    relationship.split("__")[0].split("::")[0],
                    relationship.split("__")[2].split("::")[0],
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


def normalize_entities(
    raw_entities_no_attributes: List[str],
) -> NormalizedEntities:
    """
    Match each entity against a list of normalized entities using fuzzy matching.
    Returns the best matching normalized entity for each input entity.

    Args:
        raw_entities_no_attributes: List of entity strings to normalize, w/o attributes

    Returns:
        List of normalized entity strings
    """
    normalized_results: list[str] = []
    normalized_map: dict[str, str] = {}

    with get_session_with_current_tenant() as db_session:
        # TODO make parallel
        for entity in raw_entities_no_attributes:
            entity_type, entity_name = _split_entity_type_v_name(entity)
            cleaned_entity_name = _clean_entity_name(entity_name)
            if entity_name == "*":
                normalized_results.append(entity)
                normalized_map[entity] = entity
                continue

            # step 1: find entities containing the entity_name or something similar
            query_trigrams = db_session.query(
                func.show_trgm(cleaned_entity_name)
                .cast(ARRAY(String(3)))
                .label("trigrams")
            ).cte("query")

            candidates = (
                db_session.query(
                    KGEntity.id_name,
                    KGEntity.semantic_id,
                    (
                        func.cardinality(
                            func.array(
                                select(func.unnest(KGEntity.semantic_id_trigrams))
                                .correlate(KGEntity)
                                .intersect(
                                    select(
                                        func.unnest(query_trigrams.c.trigrams)
                                    ).correlate(query_trigrams)
                                )
                            )
                        ).cast(Float)
                        / func.least(
                            func.cardinality(query_trigrams.c.trigrams),
                            func.cardinality(KGEntity.semantic_id_trigrams),
                        )
                    ).label("score"),
                )
                .select_from(KGEntity, query_trigrams)
                .filter(
                    KGEntity.entity_type_id_name == entity_type,
                    KGEntity.semantic_id_trigrams.overlap(query_trigrams.c.trigrams),
                )
                .order_by(desc("score"))
                .limit(100)
                .all()
            )

            if (
                not candidates or candidates[0][2] < 0.2
            ):  # skip if all candidates are bad
                normalized_map[entity] = entity
                continue

            # TODO: retrieval needs to return the semantic id too, and rerank should compare on that
            # step 2: do a weighted ngram analysis and damerau levenshtein distance to rerank
            n1, n2, n3 = (
                set(ngrams(cleaned_entity_name, 1)),
                set(ngrams(cleaned_entity_name, 2)),
                set(ngrams(cleaned_entity_name, 3)),
            )
            for i, (id_name, semantic_id, _) in enumerate(candidates):
                h_n1, h_n2, h_n3 = (
                    set(ngrams(semantic_id, 1)),
                    set(ngrams(semantic_id, 2)),
                    set(ngrams(semantic_id, 3)),
                )
                i1, i2, i3 = (len(n1 & h_n1), len(n2 & h_n2), len(n3 & h_n3))
                grams_used = min(2, len(cleaned_entity_name) - 1, len(semantic_id) - 1)
                ngram_score = (
                    0.2500 * i1 / max(1, len(n1) + len(h_n1) - i1)
                    + 0.25 * i2 / max(1, len(n2) + len(h_n2) - i2)
                    + 0.50 * i3 / max(1, min(len(n3), len(h_n3)))
                ) / (0.25, 0.5, 1.0)[grams_used]
                leven_score = normalized_similarity(cleaned_entity_name, semantic_id)
                score = 0.75 * ngram_score + 0.25 * leven_score
                candidates[i] = (id_name, semantic_id, score)
            candidates = list(
                sorted(
                    filter(lambda x: x[2] > 0.3, candidates),
                    key=lambda x: x[2],
                    reverse=True,
                )
            )
            if not candidates:
                normalized_map[entity] = entity
                continue

            normalized_results.append(candidates[0][0])
            normalized_map[entity] = candidates[0][0]

    return NormalizedEntities(
        entities=normalized_results, entity_normalization_map=normalized_map
    )


def normalize_entities_w_attributes_from_map(
    raw_entities_w_attributes: List[str],
    entity_normalization_map: Dict[str, Optional[str]],
) -> List[str]:
    """
    Normalize entities with attributes using the entity normalization map.
    """

    normalized_entities_w_attributes: List[str] = []

    for raw_entities_w_attribute in raw_entities_w_attributes:
        assert (
            len(raw_entities_w_attribute.split("--")) == 2
        ), f"Invalid entity with attributes: {raw_entities_w_attribute}"
        raw_entity, attributes = raw_entities_w_attribute.split("--")
        normalized_entity = entity_normalization_map.get(raw_entity.strip())
        if normalized_entity is None:
            continue
        else:
            normalized_entities_w_attributes.append(
                f"{normalized_entity}--{raw_entities_w_attribute.split('--')[1].strip()}"
            )

    return normalized_entities_w_attributes


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
        norm_source_type = norm_source.split("::")[0]
        norm_target_type = norm_target.split("::")[0]
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
