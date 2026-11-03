"""The drain: the one connector every event source shares. It claims its
pair's rows from `connector_event_inbox` inside an ordinary docfetching run."""

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
    retry_or_fail_events,
    settle_events_from_finished_attempts,
    superseded_by_newer_events,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _secrets_for(db_session: Session, cc_pair_id: int) -> Mapping[str, str]:
    pair = get_connector_credential_pair_from_id(
        db_session, cc_pair_id, eager_load_credential=True
    )
    if pair is None:
        raise RuntimeError(f"Event pair {cc_pair_id} no longer exists")
    return pair_secrets(pair)


def _settle_failure(event_id: int, message: str) -> None:
    """Settle one row at once: docfetching can abandon this generator after
    enough failures, so a row settled at the end might never be."""
    with get_session_with_current_tenant() as db_session:
        retry_or_fail_events(db_session, [(event_id, message)])
        db_session.commit()


class EventInboxCheckpoint(ConnectorCheckpoint):
    """No row ids: the claim is recorded on the rows."""

    drained: int = 0


class EventInboxConnector(CheckpointedConnector[EventInboxCheckpoint]):
    """Selected by the factory for any EVENT pair; a row's source picks its
    handler."""

    def __init__(self, batch_size: int = INDEX_BATCH_SIZE) -> None:
        load_event_sources()
        self.batch_size = batch_size
        self._cc_pair_id: int | None = None
        self._index_attempt_id: int | None = None

    def set_event_context(self, cc_pair_id: int, index_attempt_id: int) -> None:
        """Set by the docfetching entrypoint: both ids belong to the run, not
        to stored config."""
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
        """Drain one batch. Ignores `start` and `end`: the queue holds exactly
        the changes the source reported."""
        if self._cc_pair_id is None or self._index_attempt_id is None:
            raise RuntimeError(
                "EventInboxConnector ran without its event context. The "
                "docfetching entrypoint must call set_event_context first."
            )

        drained = checkpoint.drained

        # Close the session before any handler runs: a handler can fetch over
        # the network, and the generator suspends at every yield.
        with get_session_with_current_tenant() as db_session:
            settle_events_from_finished_attempts(db_session, self._cc_pair_id)
            events, claimed_ids = claim_events(
                db_session,
                cc_pair_id=self._cc_pair_id,
                index_attempt_id=self._index_attempt_id,
                limit=self.batch_size,
            )
            db_session.commit()

            secrets = _secrets_for(db_session, self._cc_pair_id) if events else {}
            superseded = superseded_by_newer_events(
                db_session, self._cc_pair_id, events, claimed_ids
            )

        for event in events:
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

            if document is not None:
                yield document

        drained += len(claimed_ids)
        return EventInboxCheckpoint(
            # A claim can exceed the limit, since it takes whole documents.
            has_more=len(claimed_ids) >= self.batch_size,
            drained=drained,
        )
