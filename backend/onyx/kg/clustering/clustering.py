import time
from collections.abc import Generator
from typing import cast

from rapidfuzz.fuzz import ratio
from redis.lock import Lock as RedisLock
from sqlalchemy import func
from sqlalchemy import text

from onyx.background.celery.tasks.kg_processing.utils import extend_lock
from onyx.configs.constants import CELERY_GENERIC_BEAT_LOCK_TIMEOUT
from onyx.configs.kg_configs import KG_CLUSTERING_RETRIEVE_THRESHOLD
from onyx.configs.kg_configs import KG_CLUSTERING_THRESHOLD
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.entities import KGEntity
from onyx.db.entities import KGEntityExtractionStaging
from onyx.db.entities import merge_entities
from onyx.db.entities import transfer_entity
from onyx.db.kg_config import get_kg_config_settings
from onyx.db.kg_config import validate_kg_settings
from onyx.db.models import Document
from onyx.db.models import KGEntityType
from onyx.db.models import KGRelationshipExtractionStaging
from onyx.db.models import KGRelationshipTypeExtractionStaging
from onyx.db.relationships import transfer_relationship
from onyx.db.relationships import transfer_relationship_type
from onyx.db.relationships import upsert_relationship
from onyx.db.relationships import upsert_relationship_type
from onyx.document_index.vespa.kg_interactions import (
    get_kg_vespa_info_update_requests_for_document,
)
from onyx.document_index.vespa.kg_interactions import update_kg_chunks_vespa_info
from onyx.kg.models import KGGroundingType
from onyx.kg.utils.formatting_utils import make_relationship_id
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA

logger = setup_logger()


def _get_batch_untransferred_grounded_entities(
    batch_size: int,
) -> Generator[list[KGEntityExtractionStaging], None, None]:
    while True:
        with get_session_with_current_tenant() as db_session:
            batch = (
                db_session.query(KGEntityExtractionStaging)
                .join(
                    KGEntityType,
                    KGEntityExtractionStaging.entity_type_id_name
                    == KGEntityType.id_name,
                )
                .filter(
                    KGEntityType.grounding == KGGroundingType.GROUNDED,
                    KGEntityExtractionStaging.transferred_id_name.is_(None),
                )
                .limit(batch_size)
                .all()
            )
            if not batch:
                break
            yield batch


def _get_batch_untransferred_relationship_types(
    batch_size: int,
) -> Generator[list[KGRelationshipTypeExtractionStaging], None, None]:
    while True:
        with get_session_with_current_tenant() as db_session:
            batch = (
                db_session.query(KGRelationshipTypeExtractionStaging)
                .filter(KGRelationshipTypeExtractionStaging.transferred.is_(False))
                .limit(batch_size)
                .all()
            )
            if not batch:
                break
            yield batch


def _get_batch_untransferred_relationships(
    batch_size: int,
) -> Generator[list[KGRelationshipExtractionStaging], None, None]:
    while True:
        with get_session_with_current_tenant() as db_session:
            batch = (
                db_session.query(KGRelationshipExtractionStaging)
                .filter(KGRelationshipExtractionStaging.transferred.is_(False))
                .limit(batch_size)
                .all()
            )
            if not batch:
                break
            yield batch


def _get_batch_entities_with_parent(
    batch_size: int,
) -> Generator[list[KGEntityExtractionStaging], None, None]:
    offset = 0

    while True:
        with get_session_with_current_tenant() as db_session:
            batch = (
                db_session.query(KGEntityExtractionStaging)
                .filter(KGEntityExtractionStaging.parent_key.isnot(None))
                .order_by(KGEntityExtractionStaging.id_name)
                .offset(offset)
                .limit(batch_size)
                .all()
            )
            if not batch:
                break
            # we can't filter out ""s earlier as it will mess up the pagination
            yield [entity for entity in batch if entity.parent_key != ""]
            offset += batch_size


def _get_batch_kg_processed_documents(
    batch_size: int,
) -> Generator[list[Document], None, None]:
    offset = 0

    while True:
        with get_session_with_current_tenant() as db_session:
            batch = (
                db_session.query(Document)
                .join(
                    KGEntityExtractionStaging,
                    Document.id == KGEntityExtractionStaging.document_id,
                )
                .filter(
                    KGEntityExtractionStaging.transferred_id_name.is_not(None),
                )
                .order_by(Document.id)
                .offset(offset)
                .limit(batch_size)
                .all()
            )
            if not batch:
                break
            yield batch
            offset += batch_size


def _cluster_one_grounded_entity(
    entity: KGEntityExtractionStaging,
) -> tuple[KGEntity, bool]:
    """
    Cluster a single grounded entity.
    """
    with get_session_with_current_tenant() as db_session:
        # get entity name and filtering conditions
        if entity.document_id is not None:
            entity_name = cast(
                str,
                db_session.query(Document.semantic_id)
                .filter(Document.id == entity.document_id)
                .scalar(),
            ).lower()
            filtering = [KGEntity.document_id.is_(None)]
        else:
            entity_name = entity.name.lower()
            filtering = []

        # skip those with numbers so we don't cluster version1 and version2, etc.
        similar_entities: list[KGEntity] = []
        if not any(char.isdigit() for char in entity_name):
            # find similar entities, uses GIN index, very efficient
            db_session.execute(
                text(
                    "SET pg_trgm.similarity_threshold = "
                    + str(KG_CLUSTERING_RETRIEVE_THRESHOLD)
                )
            )
            similar_entities = (
                db_session.query(KGEntity)
                .filter(
                    # find entities of the same type with a similar name
                    *filtering,
                    KGEntity.entity_type_id_name == entity.entity_type_id_name,
                    getattr(func, POSTGRES_DEFAULT_SCHEMA).similarity_op(
                        KGEntity.name, entity_name
                    ),
                )
                .all()
            )

    # find best match
    best_score = -1.0
    best_entity = None
    for similar in similar_entities:
        # skip those with numbers so we don't cluster version1 and version2, etc.
        if any(char.isdigit() for char in similar.name):
            continue
        score = ratio(similar.name, entity_name)
        if score >= KG_CLUSTERING_THRESHOLD * 100 and score > best_score:
            best_score = score
            best_entity = similar

    # if there is a match, update the entity, otherwise create a new one
    with get_session_with_current_tenant() as db_session:
        if best_entity:
            logger.debug(f"Merged {entity.name} with {best_entity.name}")
            update_vespa = (
                best_entity.document_id is None and entity.document_id is not None
            )
            transferred_entity = merge_entities(
                db_session=db_session, parent=best_entity, child=entity
            )
        else:
            update_vespa = entity.document_id is not None
            transferred_entity = transfer_entity(db_session=db_session, entity=entity)

        db_session.commit()

    return transferred_entity, update_vespa


def _create_one_parent_child_relationship(entity: KGEntityExtractionStaging) -> None:
    """
    Creates a relationship between the entity and its parent, if it exists.
    Then, updates the entity's parent to the next ancestor.
    """
    with get_session_with_current_tenant() as db_session:
        # find the next ancestor
        parent = (
            db_session.query(KGEntity)
            .filter(KGEntity.entity_key == entity.parent_key)
            .first()
        )

        if parent is not None:
            # create parent child relationship and relationship type
            upsert_relationship_type(
                db_session=db_session,
                source_entity_type=parent.entity_type_id_name,
                relationship_type="has_subcomponent",
                target_entity_type=entity.entity_type_id_name,
            )
            relationship_id_name = make_relationship_id(
                parent.id_name,
                "has_subcomponent",
                cast(str, entity.transferred_id_name),
            )
            upsert_relationship(
                db_session=db_session,
                relationship_id_name=relationship_id_name,
                source_document_id=entity.document_id,
            )

            next_ancestor = parent.parent_key or ""
        else:
            next_ancestor = ""

        # set the staging entity's parent to the next ancestor
        # if there is no parent or next ancestor, set to "" to differentiate from None
        # None will mess up the pagination in _get_batch_entities_with_parent
        db_session.query(KGEntityExtractionStaging).filter(
            KGEntityExtractionStaging.id_name == entity.id_name
        ).update({"parent_key": next_ancestor})
        db_session.commit()


def _transfer_one_relationship(
    relationship: KGRelationshipExtractionStaging,
) -> None:
    with get_session_with_current_tenant() as db_session:
        # get the translations
        staging_entity_id_names = {
            relationship.source_node,
            relationship.target_node,
        }
        entity_translations: dict[str, str] = {
            entity.id_name: entity.transferred_id_name
            for entity in db_session.query(KGEntityExtractionStaging)
            .filter(KGEntityExtractionStaging.id_name.in_(staging_entity_id_names))
            .all()
            if entity.transferred_id_name is not None
        }
        if len(entity_translations) != len(staging_entity_id_names):
            logger.error(
                f"Missing entity translations for {staging_entity_id_names - entity_translations.keys()}"
            )
            return

        # transfer the relationship
        transfer_relationship(
            db_session=db_session,
            relationship=relationship,
            entity_translations=entity_translations,
        )
        db_session.commit()


def kg_clustering(
    tenant_id: str,
    index_name: str,
    lock: RedisLock,
    processing_chunk_batch_size: int = 16,
) -> None:
    """
    Here we will cluster the extractions based on their cluster frameworks.
    Initially, this will only focus on grounded entities with pre-determined
    relationships, so 'clustering' is actually not yet required.
    However, we may need to reconcile entities coming from different sources.

    The primary purpose of this function is to populate the actual KG tables
    from the temp_extraction tables.

    This will change with deep extraction, where grounded-sourceless entities
    can be extracted and then need to be clustered.
    """
    logger.info(f"Starting kg clustering for tenant {tenant_id}")

    kg_config_settings = get_kg_config_settings()
    validate_kg_settings(kg_config_settings)

    last_lock_time = time.monotonic()

    # Cluster and transfer grounded entities sequentially
    start_time = time.monotonic()
    i_batch = 0
    for i_batch, untransferred_grounded_entities in enumerate(
        _get_batch_untransferred_grounded_entities(
            batch_size=processing_chunk_batch_size
        )
    ):
        for entity in untransferred_grounded_entities:
            _cluster_one_grounded_entity(entity)
        last_lock_time = extend_lock(
            lock, CELERY_GENERIC_BEAT_LOCK_TIMEOUT, last_lock_time
        )
        # logger.debug(f"Transferred entities batch {i}")
    # NOTE: we assume every entity is transferred, as we currently only have grounded entities
    time_delta = time.monotonic() - start_time
    logger.info(
        f"Finished transferring {i_batch+1} entity batches in {time_delta:.2f}s"
    )

    # Create parent-child relationships in parallel
    for _ in range(kg_config_settings.KG_MAX_PARENT_RECURSION_DEPTH):
        for root_entities in _get_batch_entities_with_parent(
            batch_size=processing_chunk_batch_size
        ):
            run_functions_tuples_in_parallel(
                [
                    (_create_one_parent_child_relationship, (root_entity,))
                    for root_entity in root_entities
                ]
            )
            last_lock_time = extend_lock(
                lock, CELERY_GENERIC_BEAT_LOCK_TIMEOUT, last_lock_time
            )
    logger.info("Finished creating all parent-child relationships")

    # Transfer the relationship types (no need to do in parallel as there's only a few)
    start_time = time.monotonic()
    i_batch = 0
    for i_batch, relationship_types in enumerate(
        _get_batch_untransferred_relationship_types(
            batch_size=processing_chunk_batch_size
        )
    ):
        with get_session_with_current_tenant() as db_session:
            for relationship_type in relationship_types:
                transfer_relationship_type(db_session, relationship_type)
            db_session.commit()
        last_lock_time = extend_lock(
            lock, CELERY_GENERIC_BEAT_LOCK_TIMEOUT, last_lock_time
        )
        # logger.debug(f"Transferred relationship types batch {i}")
    time_delta = time.monotonic() - start_time
    logger.info(
        f"Finished transferring {i_batch+1} relationship type batches in {time_delta:.2f}s"
    )

    # Transfer the relationships in parallel
    start_time = time.monotonic()
    i_batch = 0
    for i_batch, relationships in enumerate(
        _get_batch_untransferred_relationships(batch_size=processing_chunk_batch_size)
    ):
        run_functions_tuples_in_parallel(
            [
                (_transfer_one_relationship, (relationship,))
                for relationship in relationships
            ]
        )
        last_lock_time = extend_lock(
            lock, CELERY_GENERIC_BEAT_LOCK_TIMEOUT, last_lock_time
        )
        # logger.debug(f"Transferred relationships batch {i}")
    time_delta = time.monotonic() - start_time
    logger.info(
        f"Finished transferring {i_batch+1} relationship batches in {time_delta:.2f}s"
    )

    # Update vespa for each document
    start_time = time.monotonic()
    i_batch = 0
    for i_batch, documents in enumerate(
        _get_batch_kg_processed_documents(batch_size=processing_chunk_batch_size)
    ):
        batch_update_requests = run_functions_tuples_in_parallel(
            [
                (get_kg_vespa_info_update_requests_for_document, (document.id,))
                for document in documents
            ]
        )
        for update_requests, document in zip(batch_update_requests, documents):
            try:
                update_kg_chunks_vespa_info(update_requests, index_name, tenant_id)
            except Exception as e:
                logger.error(f"Error updating vespa for document {document.id}: {e}")
        last_lock_time = extend_lock(
            lock, CELERY_GENERIC_BEAT_LOCK_TIMEOUT, last_lock_time
        )
        # logger.debug(f"Updated vespa for documents batch {i}")
    time_delta = time.monotonic() - start_time
    logger.info(f"Finished updating {i_batch+1} document batches in {time_delta:.2f}s")

    # Delete the transferred objects from the staging tables
    try:
        with get_session_with_current_tenant() as db_session:
            db_session.query(KGRelationshipExtractionStaging).filter(
                KGRelationshipExtractionStaging.transferred.is_(True)
            ).delete(synchronize_session=False)
            db_session.commit()
    except Exception as e:
        logger.error(f"Error deleting relationships: {e}")

    try:
        with get_session_with_current_tenant() as db_session:
            db_session.query(KGRelationshipTypeExtractionStaging).filter(
                KGRelationshipTypeExtractionStaging.transferred.is_(True)
            ).delete(synchronize_session=False)
            db_session.commit()
    except Exception as e:
        logger.error(f"Error deleting relationship types: {e}")

    try:
        with get_session_with_current_tenant() as db_session:
            db_session.query(KGEntityExtractionStaging).filter(
                KGEntityExtractionStaging.transferred_id_name.is_not(None)
            ).delete(synchronize_session=False)
            db_session.commit()
    except Exception as e:
        logger.error(f"Error deleting entities: {e}")
    logger.info("Finished deleting all transferred staging entries")
