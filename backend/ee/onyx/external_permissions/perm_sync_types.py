from collections.abc import Callable
from collections.abc import Generator
from typing import Optional
from typing import Protocol
from typing import TYPE_CHECKING

# Avoid circular imports
if TYPE_CHECKING:
    from ee.onyx.db.external_perm import ExternalUserGroup  # noqa
    from onyx.access.models import DocExternalAccess  # noqa
    from onyx.db.models import ConnectorCredentialPair  # noqa
    from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface  # noqa


class FetchAllDocumentsFunction(Protocol):
    """Protocol for a function that fetches all document IDs for a connector credential pair."""

    def __call__(self) -> list[str]:
        """
        Returns a list of document IDs for a connector credential pair.

        This is typically used to determine which documents should no longer be
        accessible during the document sync process.
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
        str,
        "ConnectorCredentialPair",
    ],
    list["ExternalUserGroup"],
]
