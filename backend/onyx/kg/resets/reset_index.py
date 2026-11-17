from sqlalchemy.orm import Session

from onyx.db.document import reset_all_document_kg_stages
from onyx.db.entities import (
    delete_all_kg_entities__no_commit,
    delete_all_kg_entities_extraction_staging__no_commit,
)
from onyx.db.entity_type import (
    deactivate_grounded_entity_types__no_commit,
    disable_kg_processing_for_all_connectors__no_commit,
)
from onyx.db.relationships import (
    delete_all_kg_relationship_types__no_commit,
    delete_all_kg_relationship_types_extraction_staging__no_commit,
    delete_all_kg_relationships__no_commit,
    delete_all_kg_relationships_extraction_staging__no_commit,
)


def reset_full_kg_index__commit(db_session: Session) -> None:
    """
    Resets the knowledge graph index.
    """

    delete_all_kg_relationships__no_commit(db_session)
    delete_all_kg_relationship_types__no_commit(db_session)
    delete_all_kg_entities__no_commit(db_session)
    delete_all_kg_relationships_extraction_staging__no_commit(db_session)
    delete_all_kg_entities_extraction_staging__no_commit(db_session)
    delete_all_kg_relationship_types_extraction_staging__no_commit(db_session)
    disable_kg_processing_for_all_connectors__no_commit(db_session)

    # Only reset grounded entity types
    deactivate_grounded_entity_types__no_commit(db_session)

    reset_all_document_kg_stages(db_session)

    db_session.commit()
