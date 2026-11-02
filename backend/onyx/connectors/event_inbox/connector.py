"""The drain: one connector that indexes whatever a source pushed.

Every event-based source shares this connector. It claims rows from
`connector_event_inbox` for its pair and yields the documents they describe,
so a pushed event reaches the index through the ordinary docfetching run
rather than a pipeline of its own.
"""

from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from sqlalchemy.orm import Session

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.event_inbox.credentials import pair_secrets
from onyx.connectors.event_inbox.handlers import get_event_handler
from onyx.connectors.event_inbox.sources import load_event_sources
from onyx.connectors.interfaces import (
    CheckpointedConnector,
    CheckpointOutput,
    SecondsSinceUnixEpoch,
)
from onyx.connectors.models import (
    ConnectorCheckpoint,
    ConnectorFailure,
    DocumentFailure,
)
from onyx.db.connector_credential_pair import get_connector_credential_pair_from_id
from onyx.db.connector_event_inbox import (
    claim_events,
    mark_events_failed,
    settle_events_from_finished_attempts,
    superseded_by_newer_events,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import ConnectorEventInbox
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _superseded(events: list[ConnectorEventInbox]) -> set[int]:
    """Row ids that a later change to the same document replaces.

    Two changes to one document can be claimed together, and
    `upsert_documents` keeps the first entry it sees for a document id. So
    yielding both would save the older event's title, link and file and
    leave nothing to repair them: both rows settle either way.
    """
    by_document: dict[str, list[ConnectorEventInbox]] = defaultdict(list)
    for event in events:
        by_document[event.document_id].append(event)

    kept = {_latest(group).id for group in by_document.values()}
    return {event.id for event in events} - kept


def _latest(group: list[ConnectorEventInbox]) -> ConnectorEventInbox:
    """The change that wins for one document.

    The source's event time decides, but only when every change in the group
    carries one: a missing timestamp does not mean "oldest", it means the
    provider sent none. Mixing the two would let a timestamped change beat a
    later untimestamped one. Rows are claimed in id order, so id is arrival
    order and stands in whenever the times cannot all be compared.
    """
    if all(event.occurred_at is not None for event in group):
        return max(group, key=lambda event: (event.occurred_at, event.id))
    return max(group, key=lambda event: event.id)


def _secrets_for(db_session: Session, cc_pair_id: int) -> Mapping[str, str]:
    """The pair's credential, read once per batch.

    The same values the verifier saw when the delivery arrived: a provider
    that pushes a link rather than a body needs them again to fetch it.
    """
    pair = get_connector_credential_pair_from_id(
        db_session, cc_pair_id, eager_load_credential=True
    )
    if pair is None:
        raise RuntimeError(f"Event pair {cc_pair_id} no longer exists")
    return pair_secrets(pair)


def _settle_failure(event_id: int, message: str) -> None:
    """Record one rejected row in its own short session.

    Not batched until the end of the drain: docfetching abandons this
    generator once enough documents have failed, so a row settled only
    afterwards would stay claimed, be released by a later run, fail again,
    and keep blocking the queue. There is no document to store for a
    rejection, so nothing later can change its outcome.
    """
    with get_session_with_current_tenant() as db_session:
        mark_events_failed(db_session, [(event_id, message)])
        db_session.commit()


class EventInboxCheckpoint(ConnectorCheckpoint):
    """How many rows the run has drained.

    Carries no row ids: the claim is recorded on the rows themselves, so a
    resumed attempt finds its work in the table rather than in the checkpoint.
    """

    drained: int = 0


class EventInboxConnector(CheckpointedConnector[EventInboxCheckpoint]):
    """Yields the documents that this pair's pending events describe.

    Not registered against a `DocumentSource`: the factory selects it by the
    pair's input type, and the per-source meaning of a row comes from the
    handler registry.
    """

    def __init__(self, batch_size: int = INDEX_BATCH_SIZE) -> None:
        # The worker is not the webhook server, so it registers the
        # handlers itself before it reads any row.
        load_event_sources()
        self.batch_size = batch_size
        self._cc_pair_id: int | None = None
        self._index_attempt_id: int | None = None

    def set_event_context(self, cc_pair_id: int, index_attempt_id: int) -> None:
        """Injected by the docfetching entrypoint, which owns both ids.

        The factory builds a connector from stored config alone, and neither
        id is config: they belong to the run.
        """
        self._cc_pair_id = cc_pair_id
        self._index_attempt_id = index_attempt_id

    def load_credentials(
        self,
        credentials: dict[str, Any],  # noqa: ARG002
    ) -> dict[str, Any] | None:
        """The source authenticated when it posted the event; nothing to load."""
        return None

    def build_dummy_checkpoint(self) -> EventInboxCheckpoint:
        return EventInboxCheckpoint(has_more=True)

    def validate_checkpoint_json(self, checkpoint_json: str) -> EventInboxCheckpoint:
        return EventInboxCheckpoint.model_validate_json(checkpoint_json)

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,  # noqa: ARG002
        end: SecondsSinceUnixEpoch,  # noqa: ARG002
        checkpoint: EventInboxCheckpoint,
    ) -> CheckpointOutput[EventInboxCheckpoint]:
        """Drain one batch.

        `start` and `end` are ignored: the queue already holds exactly the
        changes a source reported, and re-reading by time would index
        documents the pair was never told about.
        """
        if self._cc_pair_id is None or self._index_attempt_id is None:
            raise RuntimeError(
                "EventInboxConnector ran without its event context. The "
                "docfetching entrypoint must call set_event_context first."
            )

        drained = checkpoint.drained

        # The session closes before any handler runs. A handler can fetch a
        # body over the network, and the generator suspends at every yield
        # while the runner stores documents, so holding the session across
        # either would keep a pooled connection for the whole batch.
        # `expire_on_commit` is false on these sessions, so the claimed rows
        # keep their values once detached.
        with get_session_with_current_tenant() as db_session:
            settle_events_from_finished_attempts(db_session, self._cc_pair_id)
            events = claim_events(
                db_session,
                cc_pair_id=self._cc_pair_id,
                index_attempt_id=self._index_attempt_id,
                limit=self.batch_size,
            )
            # Commit the claim before yielding: the rows must stay claimed
            # even if this generator is abandoned part way through.
            db_session.commit()

            secrets = _secrets_for(db_session, self._cc_pair_id) if events else {}
            # Within the batch, and against whatever earlier batches and runs
            # already took: id order is arrival order, not event time.
            superseded = _superseded(events) | superseded_by_newer_events(
                db_session, self._cc_pair_id, events
            )

        for event in events:
            # A later change to this document is in the same batch, and
            # the first entry would win. Its row still settles with the
            # attempt: the document is indexed from the newer event.
            if event.id in superseded:
                continue

            handler = get_event_handler(event.source)
            if handler is None:
                message = f"No event handler registered for {event.source.value}"
                _settle_failure(event.id, message)
                yield ConnectorFailure(
                    failed_document=DocumentFailure(document_id=event.document_id),
                    failure_message=message,
                )
                continue

            try:
                document = handler(event, secrets)
            except Exception as e:
                logger.exception(
                    "Event %s for document %s could not be handled",
                    event.id,
                    event.document_id,
                )
                _settle_failure(event.id, str(e))
                yield ConnectorFailure(
                    failed_document=DocumentFailure(document_id=event.document_id),
                    failure_message=str(e),
                    exception=e,
                )
                continue

            # None means nothing to index, such as a delete.
            if document is not None:
                yield document

        drained += len(events)
        return EventInboxCheckpoint(
            has_more=len(events) == self.batch_size,
            drained=drained,
        )
