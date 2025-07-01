from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.db.models import Document
from onyx.utils.logger import setup_logger
from tests.regression.search_quality.models import GroundTruth

logger = setup_logger(__name__)


def find_document(ground_truth: GroundTruth, db_session: Session) -> Document | None:
    """Find a document by its link."""
    # necessary preprocessing of links
    doc_link = ground_truth.doc_link
    if ground_truth.doc_source == DocumentSource.GOOGLE_DRIVE:
        if "/edit" in doc_link:
            doc_link = doc_link.split("/edit", 1)[0]
        elif "/view" in doc_link:
            doc_link = doc_link.split("/view", 1)[0]
    elif ground_truth.doc_source == DocumentSource.FIREFLIES:
        doc_link = doc_link.split("?", 1)[0]

    docs = db_session.query(Document).filter(Document.link.ilike(f"{doc_link}%")).all()
    if len(docs) == 0:
        logger.warning("Could not find ground truth document: %s", doc_link)
        return None
    elif len(docs) > 1:
        logger.warning(
            "Found multiple ground truth documents: %s, using the first one: %s",
            doc_link,
            docs[0].id,
        )
    return docs[0]
