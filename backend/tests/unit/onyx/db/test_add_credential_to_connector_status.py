"""An ingestion-API pair never gets an index attempt, so the attempt lifecycle
never moves it out of SCHEDULED. It must start ACTIVE instead."""

from functools import partial
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from onyx.configs.constants import DocumentSource
from onyx.db.connector_credential_pair import add_credential_to_connector
from onyx.db.enums import AccessType, ConnectorCredentialPairStatus
from onyx.db.models import ConnectorCredentialPair

_MODULE = "onyx.db.connector_credential_pair"


def _created_pair_status(
    mock_db_session: MagicMock,
    source: DocumentSource,
    initial_status: ConnectorCredentialPairStatus | None,
) -> ConnectorCredentialPairStatus:
    mock_db_session.query.return_value.filter.return_value.one_or_none.return_value = (
        None
    )
    create = partial(
        add_credential_to_connector,
        db_session=mock_db_session,
        user=MagicMock(id=uuid4()),
        connector_id=1,
        credential_id=1,
        cc_pair_name="pair",
        access_type=AccessType.PUBLIC,
        manage_access={},
    )
    with (
        patch(
            f"{_MODULE}.fetch_connector_by_id", return_value=MagicMock(source=source)
        ),
        patch(f"{_MODULE}.fetch_credential_by_id_for_user", return_value=MagicMock()),
        patch(f"{_MODULE}.ensure_personal_has_reader"),
        patch(f"{_MODULE}._relate_groups_to_cc_pair__no_commit"),
    ):
        if initial_status is None:
            create()
        else:
            create(initial_status=initial_status)

    (pair,) = [
        call.args[0]
        for call in mock_db_session.add.call_args_list
        if isinstance(call.args[0], ConnectorCredentialPair)
    ]
    return pair.status


def test_ingestion_api_pair_starts_active(mock_db_session: MagicMock) -> None:
    status = _created_pair_status(
        mock_db_session, DocumentSource.INGESTION_API, initial_status=None
    )
    assert status == ConnectorCredentialPairStatus.ACTIVE


def test_ingestion_api_pair_keeps_an_explicit_paused_status(
    mock_db_session: MagicMock,
) -> None:
    status = _created_pair_status(
        mock_db_session,
        DocumentSource.INGESTION_API,
        initial_status=ConnectorCredentialPairStatus.PAUSED,
    )
    assert status == ConnectorCredentialPairStatus.PAUSED


@pytest.mark.parametrize("source", [DocumentSource.WEB, DocumentSource.GOOGLE_DRIVE])
def test_indexed_pair_still_starts_scheduled(
    mock_db_session: MagicMock, source: DocumentSource
) -> None:
    status = _created_pair_status(mock_db_session, source, initial_status=None)
    assert status == ConnectorCredentialPairStatus.SCHEDULED
