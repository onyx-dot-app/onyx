"""Jira Service Management connector.

Jira Service Management projects are backed by Jira issues. Reuse the existing
Jira connector implementation so JSM indexing keeps parity with Jira support
(incremental sync, comments, hierarchy, permissions, checkpointing, and
credential handling) while exposing a separate source type in Onyx.
"""

from typing import Any
from typing import TypeVar

from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.jira.connector import JiraConnector
from onyx.connectors.jira.connector import JiraConnectorCheckpoint
from onyx.connectors.models import Document
from onyx.connectors.models import HierarchyNode
from onyx.connectors.models import SlimDocument

_T = TypeVar("_T", Document, SlimDocument)


def _as_jsm_source(document: _T) -> _T:
    """Return a copy of a Jira document tagged as Jira Service Management."""

    return document.model_copy(
        update={"source": DocumentSource.JIRA_SERVICE_MANAGEMENT}
    )


class JiraServiceManagementConnector(JiraConnector):
    """Connector for Jira Service Management projects.

    The configuration mirrors the Jira connector, except the frontend labels the
    base URL as ``jsm_base_url``. Internally, JSM requests are Jira issues, so the
    Jira connector APIs are the canonical and most complete way to index them.
    """

    def __init__(
        self,
        jsm_base_url: str | None = None,
        jira_base_url: str | None = None,
        **kwargs: Any,
    ) -> None:
        base_url = jsm_base_url or jira_base_url
        if base_url is None:
            raise ValueError("jsm_base_url is required")
        super().__init__(jira_base_url=base_url, **kwargs)

    def load_from_checkpoint(
        self,
        start: float,
        end: float,
        checkpoint: JiraConnectorCheckpoint,
    ) -> CheckpointOutput[JiraConnectorCheckpoint]:
        yield from self._with_jsm_source(
            super().load_from_checkpoint(start, end, checkpoint)
        )

    def load_from_checkpoint_with_perm_sync(
        self,
        start: float,
        end: float,
        checkpoint: JiraConnectorCheckpoint,
    ) -> CheckpointOutput[JiraConnectorCheckpoint]:
        yield from self._with_jsm_source(
            super().load_from_checkpoint_with_perm_sync(start, end, checkpoint)
        )

    def retrieve_all_slim_docs_perm_sync(
        self,
        start: float | None = None,
        end: float | None = None,
        callback: Any = None,
    ) -> GenerateSlimDocumentOutput:
        for batch in super().retrieve_all_slim_docs_perm_sync(start, end, callback):
            yield [
                _as_jsm_source(item) if isinstance(item, SlimDocument) else item
                for item in batch
            ]

    @staticmethod
    def _with_jsm_source(
        output: CheckpointOutput[JiraConnectorCheckpoint],
    ) -> CheckpointOutput[JiraConnectorCheckpoint]:
        checkpoint: JiraConnectorCheckpoint | None = None

        try:
            while True:
                item = next(output)
                if isinstance(item, Document | SlimDocument):
                    yield _as_jsm_source(item)
                else:
                    yield item
        except StopIteration as stop:
            checkpoint = stop.value

        if checkpoint is None:
            raise RuntimeError("Jira Service Management connector returned no checkpoint")

        return checkpoint
