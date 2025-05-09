from onyx.db.document import update_document_kg_stages
from onyx.db.engine import get_session_with_current_tenant
from onyx.db.models import KGEntityExtractionStaging
from onyx.db.models import KGRelationshipExtractionStaging
from onyx.db.models import KGRelationshipTypeExtractionStaging
from onyx.kg.models import KGStage


def reset_extraction_kg_index() -> None:
    """
    Resets the knowledge graph index.
    """
    with get_session_with_current_tenant() as db_session:
        db_session.query(KGRelationshipExtractionStaging).delete()
        db_session.query(KGEntityExtractionStaging).delete()
        db_session.query(KGRelationshipTypeExtractionStaging).delete()
        db_session.commit()

    with get_session_with_current_tenant() as db_session:
        update_document_kg_stages(db_session, KGStage.EXTRACTED, KGStage.NOT_STARTED)
        db_session.commit()
