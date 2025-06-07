from onyx.db.document import reset_all_document_kg_stages
from onyx.db.engine import get_session_with_current_tenant
from onyx.db.models import KGEntity
from onyx.db.models import KGEntityExtractionStaging
from onyx.db.models import KGRelationship
from onyx.db.models import KGRelationshipExtractionStaging
from onyx.db.models import KGRelationshipType
from onyx.db.models import KGRelationshipTypeExtractionStaging


def reset_full_kg_index() -> None:
    """
    Resets the knowledge graph index.
    """
    with get_session_with_current_tenant() as db_session:
        db_session.query(KGRelationship).delete()
        db_session.query(KGRelationshipType).delete()
        db_session.query(KGEntity).delete()
        db_session.query(KGRelationshipExtractionStaging).delete()
        db_session.query(KGEntityExtractionStaging).delete()
        db_session.query(KGRelationshipTypeExtractionStaging).delete()
        db_session.commit()

    with get_session_with_current_tenant() as db_session:
        reset_all_document_kg_stages(db_session)
        db_session.commit()
