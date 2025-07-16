from collections.abc import Callable
from collections.abc import Generator
from typing import Any
from typing import Optional
from typing import Protocol
from typing import TYPE_CHECKING

from onyx.context.search.models import InferenceChunk
from onyx.db.models import DocumentColumns
from onyx.db.utils import DocumentFilter
from onyx.db.utils import SortOrder

# Avoid circular imports
if TYPE_CHECKING:
    from ee.onyx.db.external_perm import ExternalUserGroup  # noqa
    from onyx.access.models import DocExternalAccess  # noqa
    from onyx.db.models import ConnectorCredentialPair  # noqa
    from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface  # noqa


class FetchAllDocumentsFunction(Protocol):
    """Protocol for a function that fetches documents for a connector credential pair.

    This protocol defines the interface for functions that retrieve documents
    from the database, typically used in permission synchronization workflows.
    """

    def __call__(
        self,
        columns: list[DocumentColumns] | None = None,
        document_filter: DocumentFilter | None = None,
        limit: int | None = None,
        sort_order: SortOrder | None = None,
    ) -> list[dict[DocumentColumns, Any]]:
        """
        Fetches documents for a connector credential pair with optional filtering.

        Args:
            columns: List of column attributes to select.
                    If None, implementation should default to all columns.
            document_filter: Optional document filter for filtering documents.
                         If None, no additional filtering is applied.
            limit: Optional limit on the number of documents to return.
                  If None, all matching documents are returned.
            sort_order: Optional sort order for results (ASC or DESC). If None, no ordering is applied for better performance.

        Returns:
            List of dicts matching the specified criteria.
        """
        ...


# Defining the input/output types for the sync functions
DocSyncFuncType = Callable[
    [
        "ConnectorCredentialPair",
        FetchAllDocumentsFunction,
        Optional["IndexingHeartbeatInterface"],
    ],
    Generator["DocExternalAccess", None, None],
]

GroupSyncFuncType = Callable[
    [
        str,  # tenant_id
        "ConnectorCredentialPair",  # cc_pair
    ],
    Generator["ExternalUserGroup", None, None],
]

# list of chunks to be censored and the user email. returns censored chunks
CensoringFuncType = Callable[[list[InferenceChunk], str], list[InferenceChunk]]
