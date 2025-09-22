from collections import defaultdict

from sqlalchemy import update
from sqlalchemy.orm import Session

from onyx.db.connector import fetch_unique_document_sources
from onyx.db.document import DocumentSource
from onyx.db.models import Connector
from onyx.db.models import KGEntityType
from onyx.kg.models import KGAttributeEntityOption
from onyx.server.kg.models import EntityType


UNGROUNDED_SOURCE_NAME = "Ungrounded"


def get_entity_types_with_grounded_source_name(
    db_session: Session,
) -> list[KGEntityType]:
    """Get all entity types that have non-null grounded_source_name.

    Args:
        db_session: SQLAlchemy session

    Returns:
        List of KGEntityType objects that have grounded_source_name defined
    """
    return (
        db_session.query(KGEntityType)
        .filter(KGEntityType.grounded_source_name.isnot(None))
        .all()
    )


def get_entity_types(
    db_session: Session,
    active: bool | None = True,
) -> list[KGEntityType]:
    # Query the database for all distinct entity types

    if active is None:
        return db_session.query(KGEntityType).order_by(KGEntityType.id_name).all()

    else:
        return (
            db_session.query(KGEntityType)
            .filter(KGEntityType.active == active)
            .order_by(KGEntityType.id_name)
            .all()
        )


def get_configured_entity_types(db_session: Session) -> dict[str, list[KGEntityType]]:
    # get entity types from configured sources
    configured_connector_sources = {
        source.value.lower()
        for source in fetch_unique_document_sources(db_session=db_session)
    }
    entity_types = (
        db_session.query(KGEntityType)
        .filter(KGEntityType.grounded_source_name.in_(configured_connector_sources))
        .all()
    )
    entity_type_set = {et.id_name for et in entity_types}

    # get implied entity types from those entity types
    for et in entity_types:
        for prop in et.parsed_attributes.metadata_attribute_conversion.values():
            if prop.implication_property is None:
                continue

            implied_et = prop.implication_property.implied_entity_type
            if implied_et == KGAttributeEntityOption.FROM_EMAIL:
                if "ACCOUNT" not in entity_type_set:
                    entity_type_set.add("ACCOUNT")
                if "EMPLOYEE" not in entity_type_set:
                    entity_type_set.add("EMPLOYEE")
            elif isinstance(implied_et, str):
                if implied_et not in entity_type_set:
                    entity_type_set.add(implied_et)

    ets = (
        db_session.query(KGEntityType)
        .filter(KGEntityType.id_name.in_(entity_type_set))
        .all()
    )

    et_map = defaultdict(list)
    for et in ets:
        key = et.grounded_source_name or UNGROUNDED_SOURCE_NAME
        et_map[key].append(et)

    return et_map


def update_entity_types_and_related_connectors__commit(
    db_session: Session, updates: list[EntityType]
) -> None:
    for upd in updates:
        db_session.execute(
            update(KGEntityType)
            .where(KGEntityType.id_name == upd.name)
            .values(
                description=upd.description,
                active=upd.active,
            )
        )
    db_session.flush()

    # Update connector sources

    configured_entity_types = get_configured_entity_types(db_session=db_session)

    active_entity_type_sources = {
        et.grounded_source_name
        for ets in configured_entity_types.values()
        for et in ets
        if et.active
    }

    # Update connectors that should be enabled
    db_session.execute(
        update(Connector)
        .where(
            Connector.source.in_(
                [
                    source
                    for source in DocumentSource
                    if source.value.lower() in active_entity_type_sources
                ]
            )
        )
        .where(~Connector.kg_processing_enabled)
        .values(kg_processing_enabled=True)
    )

    # Update connectors that should be disabled
    db_session.execute(
        update(Connector)
        .where(
            Connector.source.in_(
                [
                    source
                    for source in DocumentSource
                    if source.value.lower() not in active_entity_type_sources
                ]
            )
        )
        .where(Connector.kg_processing_enabled)
        .values(kg_processing_enabled=False)
    )

    db_session.commit()
