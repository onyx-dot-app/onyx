from abc import ABC, abstractmethod
from collections.abc import Callable, Generator
from datetime import datetime
from typing import Optional, Protocol

from pydantic import BaseModel

from ee.onyx.db.external_perm import ExternalUserGroup  # noqa
from onyx.access.models import (
    DocExternalAccess,  # noqa
    ElementExternalAccess,  # noqa
    NodeExternalAccess,  # noqa
)
from onyx.connectors.models import ConnectorCheckpoint
from onyx.context.search.models import InferenceChunk
from onyx.db.models import ConnectorCredentialPair  # noqa
from onyx.db.utils import DocumentRow, SortOrder
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface  # noqa


class FetchAllDocumentsFunction(Protocol):
    """Protocol for a function that fetches documents for a connector credential pair.

    This protocol defines the interface for functions that retrieve documents
    from the database, typically used in permission synchronization workflows.
    """

    def __call__(
        self,
        sort_order: SortOrder | None,
    ) -> list[DocumentRow]:
        """
        Fetches documents for a connector credential pair.
        """
        ...


class FetchAllDocumentsIdsFunction(Protocol):
    """Protocol for a function that fetches document IDs for a connector credential pair.

    This protocol defines the interface for functions that retrieve document IDs
    from the database, typically used in permission synchronization workflows.
    """

    def __call__(
        self,
    ) -> list[str]:
        """
        Fetches document IDs for a connector credential pair.
        """
        ...


# Defining the input/output types for the sync functions
DocSyncFuncType = Callable[
    [
        ConnectorCredentialPair,
        FetchAllDocumentsFunction,
        FetchAllDocumentsIdsFunction,
        Optional[IndexingHeartbeatInterface],
    ],
    Generator[ElementExternalAccess, None, None],
]


class DocSyncResume(BaseModel):
    checkpoint_json: str
    poll_range_start: datetime | None
    poll_range_end: datetime


class DocSyncCheckpointer(ABC):
    """Carries a resumable doc sync's crawl state across attempts, so an attempt
    stopped by the timeout hands its progress to the next one."""

    @property
    @abstractmethod
    def resume(self) -> DocSyncResume | None:
        """Where an earlier failed attempt stopped, or None to start fresh."""

    @abstractmethod
    def save(
        self,
        checkpoint: ConnectorCheckpoint,
        poll_range_start: datetime | None,
        poll_range_end: datetime,
    ) -> None:
        """Called at a boundary where every element before ``checkpoint`` has
        been yielded and written. May skip writes to bound their frequency."""


# Resumable variant of DocSyncFuncType
CheckpointedDocSyncFuncType = Callable[
    [
        ConnectorCredentialPair,
        FetchAllDocumentsFunction,
        FetchAllDocumentsIdsFunction,
        Optional[IndexingHeartbeatInterface],
        DocSyncCheckpointer,
    ],
    Generator[ElementExternalAccess, None, None],
]

GroupSyncFuncType = Callable[
    [
        str,  # tenant_id
        ConnectorCredentialPair,  # cc_pair
    ],
    Generator[ExternalUserGroup, None, None],
]

# list of chunks to be censored and the user email. returns censored chunks
CensoringFuncType = Callable[[list[InferenceChunk], str], list[InferenceChunk]]
