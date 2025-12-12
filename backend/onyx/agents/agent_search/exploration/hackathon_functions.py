from uuid import UUID

from sqlalchemy.orm import Session

from onyx.db.hackathon_subscriptions import get_subscription_registration


def process_notifications(db_session: Session, user_id: UUID) -> None:

    subscription_registration = get_subscription_registration(db_session, user_id)
    if not subscription_registration:
        return

    doc_extraction_contexts = subscription_registration.doc_extraction_contexts
    subscription_registration.search_questions

    for (
        doc_extraction_context_key,
        doc_extraction_context_value,
    ) in doc_extraction_contexts.items():
        # Get all document IDs for this connector credential pair
        # document_ids = get_document_ids_by_cc_pair_name(
        #    db_session, doc_extraction_context_key
        # )
        pass

        # TODO: Process these documents with the extraction context
