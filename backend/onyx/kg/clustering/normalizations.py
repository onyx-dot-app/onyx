import re
from collections import defaultdict
from typing import cast

import numpy as np
from nltk import ngrams  # type: ignore
from rapidfuzz.distance.DamerauLevenshtein import normalized_similarity
from sqlalchemy import desc
from sqlalchemy import Float
from sqlalchemy import func
from sqlalchemy import MetaData
from sqlalchemy import select
from sqlalchemy import String
from sqlalchemy import Table
from sqlalchemy.dialects.postgresql import ARRAY

from onyx.configs.kg_configs import KG_NORMALIZATION_RERANK_LEVENSHTEIN_WEIGHT
from onyx.configs.kg_configs import KG_NORMALIZATION_RERANK_NGRAM_WEIGHTS
from onyx.configs.kg_configs import KG_NORMALIZATION_RERANK_THRESHOLD
from onyx.configs.kg_configs import KG_NORMALIZATION_RETRIEVE_ENTITIES_LIMIT
from onyx.db.engine import get_session_with_current_tenant
from onyx.db.models import KGEntity
from onyx.db.relationships import get_relationships_for_entity_type_pairs
from onyx.kg.models import NormalizedEntities
from onyx.kg.models import NormalizedRelationships
from onyx.kg.models import NormalizedTerms
from onyx.kg.utils.embeddings import encode_string_batch
from onyx.kg.utils.formatting_utils import format_entity_id_for_models
from onyx.kg.utils.formatting_utils import get_entity_type
from onyx.kg.utils.formatting_utils import make_relationship_id
from onyx.kg.utils.formatting_utils import split_entity_id
from onyx.kg.utils.formatting_utils import split_relationship_id
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE

logger = setup_logger()


alphanum_regex = re.compile(r"[^a-z0-9]+")
rem_email_regex = re.compile(r"(?<=\S)@([a-z0-9-]+)\.([a-z]{2,6})$")


def _clean_name(entity_name: str) -> str:
    """
    Clean an entity string by removing non-alphanumeric characters and email addresses.
    If the name after cleaning is empty, return the original name in lowercase.
    """
    cleaned_entity = entity_name.casefold()
    return (
        alphanum_regex.sub("", rem_email_regex.sub("", cleaned_entity))
        or cleaned_entity
    )


def _normalize_one_entity(
    entity: str, allowed_docs_temp_view_name: str | None = None
) -> str | None:
    """
    Matches a single entity to the best matching entity of the same type.
    """
    entity_type, entity_name = split_entity_id(entity)
    if entity_name == "*":
        return entity

    cleaned_entity = _clean_name(entity_name)

    # step 1: find entities containing the entity_name or something similar
    with get_session_with_current_tenant() as db_session:

        # get allowed documents

        metadata = MetaData()
        if allowed_docs_temp_view_name is None:
            raise ValueError("allowed_docs_temp_view_name is not available")
        allowed_docs_temp_view = Table(
            allowed_docs_temp_view_name,
            metadata,
            autoload_with=db_session.get_bind(),
        )

        # generate trigrams of the queried entity Q
        query_trigrams = db_session.query(
            getattr(func, POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)
            .show_trgm(cleaned_entity)
            .cast(ARRAY(String(3)))
            .label("trigrams")
        ).cte("query")

        candidates = cast(
            list[tuple[str, str, float]],
            db_session.query(
                KGEntity.id_name,
                KGEntity.name,
                (
                    # for each entity E, compute score = | Q ∩ E | / min(|Q|, |E|)
                    func.cardinality(
                        func.array(
                            select(func.unnest(KGEntity.name_trigrams))
                            .correlate(KGEntity)
                            .intersect(
                                select(
                                    func.unnest(query_trigrams.c.trigrams)
                                ).correlate(query_trigrams)
                            )
                            .scalar_subquery()
                        )
                    ).cast(Float)
                    / func.least(
                        func.cardinality(query_trigrams.c.trigrams),
                        func.cardinality(KGEntity.name_trigrams),
                    )
                ).label("score"),
            )
            .select_from(KGEntity, query_trigrams)
            .outerjoin(
                allowed_docs_temp_view,
                KGEntity.document_id == allowed_docs_temp_view.c.allowed_doc_id,
            )
            .filter(
                KGEntity.entity_type_id_name == entity_type,
                KGEntity.name_trigrams.overlap(query_trigrams.c.trigrams),
                # Add filter for allowed docs - either document_id is NULL or it's in allowed_docs
                (
                    KGEntity.document_id.is_(None)
                    | allowed_docs_temp_view.c.allowed_doc_id.isnot(None)
                ),
            )
            .order_by(desc("score"))
            .limit(KG_NORMALIZATION_RETRIEVE_ENTITIES_LIMIT)
            .all(),
        )
    if not candidates:
        return None

    # step 2: do a weighted ngram analysis and damerau levenshtein distance to rerank
    n1, n2, n3 = (
        set(ngrams(cleaned_entity, 1)),
        set(ngrams(cleaned_entity, 2)),
        set(ngrams(cleaned_entity, 3)),
    )
    for i, (candidate_id_name, candidate_name, _) in enumerate(candidates):
        cleaned_candidate = _clean_name(candidate_name)
        h_n1, h_n2, h_n3 = (
            set(ngrams(cleaned_candidate, 1)),
            set(ngrams(cleaned_candidate, 2)),
            set(ngrams(cleaned_candidate, 3)),
        )

        # compute ngram overlap, renormalize scores if the names are too short for larger ngrams
        grams_used = min(2, len(cleaned_entity) - 1, len(cleaned_candidate) - 1)
        W_n1, W_n2, W_n3 = KG_NORMALIZATION_RERANK_NGRAM_WEIGHTS
        ngram_score = (
            # compute | Q ∩ E | / min(|Q|, |E|) for unigrams and bigrams (trigrams already computed)
            W_n1 * len(n1 & h_n1) / max(1, min(len(n1), len(h_n1)))
            + W_n2 * len(n2 & h_n2) / max(1, min(len(n2), len(h_n2)))
            + W_n3 * len(n3 & h_n3) / max(1, min(len(n3), len(h_n3)))
        ) / (W_n1, W_n1 + W_n2, 1.0)[grams_used]

        # compute damerau levenshtein distance to fuzzy match against typos
        W_leven = KG_NORMALIZATION_RERANK_LEVENSHTEIN_WEIGHT
        leven_score = normalized_similarity(cleaned_entity, cleaned_candidate)

        # combine scores
        score = (1.0 - W_leven) * ngram_score + W_leven * leven_score
        candidates[i] = (candidate_id_name, candidate_name, score)
    candidates = list(
        sorted(
            filter(lambda x: x[2] > KG_NORMALIZATION_RERANK_THRESHOLD, candidates),
            key=lambda x: x[2],
            reverse=True,
        )
    )
    if not candidates:
        return None

    return candidates[0][0]


def _get_existing_normalized_relationships(
    raw_relationships: list[str],
) -> dict[str, dict[str, list[str]]]:
    """
    Get existing normalized relationships from the database.
    """

    relationship_type_map: dict[str, dict[str, list[str]]] = defaultdict(
        lambda: defaultdict(list)
    )
    relationship_pairs = list(
        {
            (
                get_entity_type(split_relationship_id(relationship)[0]),
                get_entity_type(split_relationship_id(relationship)[2]),
            )
            for relationship in raw_relationships
        }
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
    raw_entities_no_attributes: list[str],
    allowed_docs_temp_view_name: str | None = None,
) -> NormalizedEntities:
    """
    Match each entity against a list of normalized entities using fuzzy matching.
    Returns the best matching normalized entity for each input entity.

    Args:
        raw_entities_no_attributes: list of entity strings to normalize, w/o attributes

    Returns:
        list of normalized entity strings
    """
    normalized_results: list[str] = []
    normalized_map: dict[str, str] = {}

    mapping: list[str | None] = run_functions_tuples_in_parallel(
        [
            (_normalize_one_entity, (entity, allowed_docs_temp_view_name))
            for entity in raw_entities_no_attributes
        ]
    )
    for entity, normalized_entity in zip(raw_entities_no_attributes, mapping):
        if normalized_entity is not None:
            normalized_results.append(normalized_entity)
            normalized_map[format_entity_id_for_models(entity)] = normalized_entity
        else:
            normalized_map[format_entity_id_for_models(entity)] = entity

    return NormalizedEntities(
        entities=normalized_results, entity_normalization_map=normalized_map
    )


def normalize_entities_w_attributes_from_map(
    raw_entities_w_attributes: list[str],
    entity_normalization_map: dict[str, str],
) -> list[str]:
    """
    Normalize entities with attributes using the entity normalization map.
    """

    normalized_entities_w_attributes: list[str] = []

    for raw_entities_w_attribute in raw_entities_w_attributes:
        assert (
            len(raw_entities_w_attribute.split("--")) == 2
        ), f"Invalid entity with attributes: {raw_entities_w_attribute}"
        raw_entity, attributes = raw_entities_w_attribute.split("--")
        formatted_raw_entity = format_entity_id_for_models(raw_entity)
        normalized_entity = entity_normalization_map.get(formatted_raw_entity)
        if normalized_entity is None:
            logger.warning(f"No normalized entity found for {raw_entity}")
            continue
        else:
            normalized_entities_w_attributes.append(
                f"{normalized_entity}--{raw_entities_w_attribute.split('--')[1].strip()}"
            )

    return normalized_entities_w_attributes


def normalize_relationships(
    raw_relationships: list[str], entity_normalization_map: dict[str, str]
) -> NormalizedRelationships:
    """
    Normalize relationships using entity mappings and relationship string matching.

    Args:
        relationships: list of relationships in format "source__relation__target"
        entity_normalization_map: Mapping of raw entities to normalized ones (or None)

    Returns:
        NormalizedRelationships containing normalized relationships and mapping
    """
    # Placeholder for normalized relationship structure
    nor_relationships = _get_existing_normalized_relationships(raw_relationships)

    normalized_rels: list[str] = []
    normalization_map: dict[str, str] = {}

    for raw_rel in raw_relationships:
        # 1. Split and normalize entities
        try:
            source, rel_string, target = split_relationship_id(raw_rel)
        except ValueError:
            raise ValueError(f"Invalid relationship format: {raw_rel}")

        # Check if entities are in normalization map and not None
        norm_source = entity_normalization_map.get(source)
        norm_target = entity_normalization_map.get(target)

        if norm_source is None or norm_target is None:
            logger.warning(f"No normalized entities found for {raw_rel}")
            continue

        # 2. Find candidate normalized relationships
        candidate_rels = []
        norm_source_type = get_entity_type(norm_source)
        norm_target_type = get_entity_type(norm_target)
        if (
            norm_source_type in nor_relationships
            and norm_target_type in nor_relationships[norm_source_type]
        ):
            candidate_rels = [
                split_relationship_id(rel)[1]
                for rel in nor_relationships[norm_source_type][norm_target_type]
            ]

        if not candidate_rels:
            logger.warning(f"No candidate relationships found for {raw_rel}")
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
        norm_rel = make_relationship_id(
            norm_source, candidate_rels[best_match_idx], norm_target
        )
        normalized_rels.append(norm_rel)
        normalization_map[raw_rel] = norm_rel

    return NormalizedRelationships(
        relationships=normalized_rels, relationship_normalization_map=normalization_map
    )


def normalize_terms(raw_terms: list[str]) -> NormalizedTerms:
    """
    Normalize terms using semantic similarity matching.

    Args:
        terms: list of terms to normalize

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

    # normalized_terms: list[str] = []
    # normalization_map: dict[str, str | None] = {}

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
