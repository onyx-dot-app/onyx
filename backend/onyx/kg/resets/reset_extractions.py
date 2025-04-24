from onyx.db.document import reset_extracted_document_kg_stages
from onyx.db.engine import get_session_with_current_tenant
from onyx.db.models import KGEntityExtractionTemp
from onyx.db.models import KGRelationshipExtractionTemp
from onyx.db.models import KGRelationshipTypeExtractionTemp


def reset_extraction_kg_index() -> None:
    """
    Resets the knowledge graph index.
    """
    with get_session_with_current_tenant() as db_session:
        db_session.query(KGRelationshipExtractionTemp).delete()
        db_session.query(KGEntityExtractionTemp).delete()
        db_session.query(KGRelationshipTypeExtractionTemp).delete()
        db_session.commit()

    with get_session_with_current_tenant() as db_session:
        reset_extracted_document_kg_stages(db_session)
        db_session.commit()
