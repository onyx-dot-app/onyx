from collections.abc import Generator

from onyx.access.models import DocExternalAccess
from onyx.access.models import ExternalAccess
from onyx.connectors.models import SlimDocument
from onyx.utils.logger import setup_logger

logger = setup_logger()


def make_missing_docs_inaccessible(
    fetched_slim_docs: list[SlimDocument],
    existing_doc_ids: list[str],
) -> Generator[DocExternalAccess]:
    """
    Given the fetched `SlimDocument`s and the existing doc-ids, the existing doc-ids whose ids were *not* fetched will be marked
    inaccessible.

    Each one of the fetched `SlimDocument`'s `DocExternalAccess` will be yielded.
    """

    fetched_ids = {doc.id for doc in fetched_slim_docs}
    existing_ids = set(existing_doc_ids)

    missing_ids = existing_ids - fetched_ids

    if not missing_ids:
        return

    logger.warning(
        f"Found {len(missing_ids)=} documents that are in the DB but not present in fetch. Making them inaccessible."
    )

    for missing_id in missing_ids:
        logger.warning(f"Removing access for {missing_id=}")
        yield DocExternalAccess(
            doc_id=missing_id,
            # `ExternalAccess.empty()` sets all permissions to empty, thus effectively making this document private.
            external_access=ExternalAccess.empty(),
        )
