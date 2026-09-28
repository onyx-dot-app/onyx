from unittest.mock import MagicMock

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.enums import AccessType
from onyx.server.documents import connector as connector_api
from onyx.server.documents.models import (
    ConnectorUpdateRequest,
    ObjectCreationIdResponse,
)
from onyx.server.models import StatusResponse


def test_creation_response_includes_connector_and_cc_pair_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector_id = 17
    credential_id = 23
    cc_pair_id = 29

    monkeypatch.setattr(connector_api, "_validate_connector_allowed", MagicMock())
    monkeypatch.setattr(connector_api, "assert_within_scope", MagicMock())
    monkeypatch.setattr(
        connector_api,
        "create_connector",
        MagicMock(return_value=ObjectCreationIdResponse(id=connector_id)),
    )
    monkeypatch.setattr(
        connector_api,
        "create_credential",
        MagicMock(return_value=MagicMock(id=credential_id)),
    )
    monkeypatch.setattr(connector_api, "validate_ccpair_for_user", MagicMock())
    monkeypatch.setattr(
        connector_api,
        "add_credential_to_connector",
        MagicMock(
            return_value=StatusResponse[int](
                success=True,
                message="Created connector-credential pair",
                data=cc_pair_id,
            )
        ),
    )
    monkeypatch.setattr(connector_api, "maybe_mark_tenant_active", MagicMock())
    monkeypatch.setattr(connector_api.client_app, "send_task", MagicMock())
    monkeypatch.setattr(connector_api, "mt_cloud_telemetry", MagicMock())
    monkeypatch.setattr(
        connector_api, "get_current_tenant_id", MagicMock(return_value="tenant")
    )

    response = connector_api.create_connector_with_mock_credential(
        connector_data=ConnectorUpdateRequest(
            name="test connector",
            source=DocumentSource.FILE,
            input_type=InputType.LOAD_STATE,
            connector_specific_config={},
            access_type=AccessType.PUBLIC,
        ),
        user=MagicMock(),
        db_session=MagicMock(),
    )

    assert response.success is True
    assert response.connector_id == connector_id
    assert response.data == cc_pair_id
