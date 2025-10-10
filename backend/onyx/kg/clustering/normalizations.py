import re
from collections import defaultdict
from typing import cast

import numpy as np
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
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import KGEntity
from onyx.db.relationships import get_relationships_for_entity_type_pairs
from onyx.kg.models import NormalizedEntities
from onyx.kg.models import NormalizedRelationships
from onyx.kg.utils.embeddings import encode_string_batch
from onyx.kg.utils.formatting_utils import format_entity_id_for_models
from onyx.kg.utils.formatting_utils import get_attributes
from onyx.kg.utils.formatting_utils import get_entity_type
from onyx.kg.utils.formatting_utils import make_entity_w_attributes
from onyx.kg.utils.formatting_utils import make_relationship_id
from onyx.kg.utils.formatting_utils import split_entity_id
from onyx.kg.utils.formatting_utils import split_relationship_id
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA

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
    entity: str,
    attributes: dict[str, str],
    allowed_docs_temp_view_name: str | None = None,
) -> str | None:
    from nltk import ngrams  # type: ignore

    """
    Matches a single entity to the best matching entity of the same type.
    """
    entity_type, entity_name = split_entity_id(entity)
    if entity_name == "*":
        return entity

    cleaned_entity = _clean_name(entity_name)

    # narrow filter to subtype if requested
    type_filters = [KGEntity.entity_type_id_name == entity_type]
    if "subtype" in attributes:
        type_filters.append(
            KGEntity.attributes.op("@>")({"subtype": attributes["subtype"]})
        )

    # step 1: find entities containing the entity_name or something similar
    with get_session_with_current_tenant() as db_session:

        # get allowed documents
        metadata = MetaData()
        if allowed_docs_temp_view_name is None:
            raise ValueError("allowed_docs_temp_view_name is not available")

        effective_schema_allowed_docs_temp_view_name = (
            allowed_docs_temp_view_name.split(".")[-1]
        )

        allowed_docs_temp_view = Table(
            effective_schema_allowed_docs_temp_view_name,
            metadata,
            autoload_with=db_session.get_bind(),
        )

        # generate trigrams of the queried entity Q
        query_trigrams = db_session.query(
            getattr(func, POSTGRES_DEFAULT_SCHEMA)
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
                *type_filters,
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
    raw_entities: list[str],
    raw_entities_w_attributes: list[str],
    allowed_docs_temp_view_name: str | None = None,
) -> NormalizedEntities:
    """
    Match each entity against a list of normalized entities using fuzzy matching.
    Returns the best matching normalized entity for each input entity.

    Args:
        raw_entities: list of entity strings to normalize, w/o attributes
        raw_entities_w_attributes: list of entity strings to normalize, w/ attributes

    Returns:
        list of normalized entity strings
    """
    normalized_entities: list[str] = []
    normalized_entities_w_attributes: list[str] = []
    normalized_map: dict[str, str] = {}

    entity_attributes = [
        get_attributes(attr_entity) for attr_entity in raw_entities_w_attributes
    ]

    mapping: list[str | None] = run_functions_tuples_in_parallel(
        [
            (_normalize_one_entity, (entity, attributes, allowed_docs_temp_view_name))
            for entity, attributes in zip(raw_entities, entity_attributes)
        ]
    )
    for entity, attributes, normalized_entity in zip(
        raw_entities, entity_attributes, mapping
    ):

        if normalized_entity is not None:
            normalized_entities.append(normalized_entity)
            normalized_entities_w_attributes.append(
                make_entity_w_attributes(normalized_entity, attributes)
            )
            normalized_map[entity] = format_entity_id_for_models(normalized_entity)
        else:
            logger.warning(f"No normalized entity found for {entity}")
            normalized_map[entity] = format_entity_id_for_models(entity)

    return NormalizedEntities(
        entities=normalized_entities,
        entities_w_attributes=normalized_entities_w_attributes,
        entity_normalization_map=normalized_map,
    )


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
        norm_source_type = get_entity_type(format_entity_id_for_models(norm_source))
        norm_target_type = get_entity_type(format_entity_id_for_models(norm_target))
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
