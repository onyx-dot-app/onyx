from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from ee.onyx.external_permissions.sharepoint.group_sync import sharepoint_group_sync
from onyx.db.models import ConnectorCredentialPair


def _cc_pair() -> ConnectorCredentialPair:
    credential_json = MagicMock()
    credential_json.get_value.return_value = {}
    return cast(
        ConnectorCredentialPair,
        SimpleNamespace(
            connector=SimpleNamespace(connector_specific_config={}),
            credential=SimpleNamespace(credential_json=credential_json),
        ),
    )


def test_sharepoint_site_group_sync_failure_is_fatal() -> None:
    connector = MagicMock()
    connector.msal_app = object()
    connector.sp_tenant_domain = "contoso"
    connector.sharepoint_domain_suffix = "sharepoint.com"
    connector.site_descriptors = [
        SimpleNamespace(url="https://contoso.sharepoint.com/sites/team")
    ]
    connector.graph_client = object()
    connector.graph_api_base = "https://graph.microsoft.com/v1.0"
    connector._get_graph_access_token.return_value = "token"

    with (
        patch(
            "ee.onyx.external_permissions.sharepoint.group_sync.SharepointConnector",
            return_value=connector,
        ),
        patch(
            "ee.onyx.external_permissions.sharepoint.group_sync.ClientContext"
        ) as mock_client_context,
        patch(
            "ee.onyx.external_permissions.sharepoint.group_sync.get_sharepoint_external_groups",
            side_effect=RuntimeError("site failed"),
        ),
        pytest.raises(RuntimeError, match="site failed"),
    ):
        mock_client_context.return_value.with_access_token.return_value = MagicMock()
        list(
            sharepoint_group_sync(
                "tenant",
                _cc_pair(),
                lambda failure: pytest.fail(
                    f"Unexpected group sync failure callback: {failure}"
                ),
            )
        )
