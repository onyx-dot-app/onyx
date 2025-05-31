from onyx.db.document import update_document_kg_stages
from onyx.db.engine import get_session_with_current_tenant
from onyx.db.models import KGEntity
from onyx.db.models import KGRelationship
from onyx.db.models import KGRelationshipType
from onyx.kg.models import KGStage


def reset_normalization_kg_index() -> None:
    """
    Resets the knowledge graph index.
    """

    with get_session_with_current_tenant() as db_session:
        db_session.query(KGRelationship).delete()
        db_session.query(KGEntity).delete()
        db_session.query(KGRelationshipType).delete()
        db_session.commit()

    with get_session_with_current_tenant() as db_session:
        update_document_kg_stages(db_session, KGStage.NORMALIZED, KGStage.EXTRACTED)
        db_session.commit()
