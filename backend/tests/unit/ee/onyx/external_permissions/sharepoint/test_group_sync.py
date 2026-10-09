from typing import Any
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from ee.onyx.external_permissions.sharepoint import group_sync
from onyx.configs.constants import DocumentSource
from onyx.connectors.sharepoint.connector import SharepointConnector

_SITE_URL = "https://contoso.sharepoint.com/sites/engineering"


def _cc_pair(connector_specific_config: dict[str, Any]) -> MagicMock:
    cc_pair = MagicMock()
    cc_pair.connector.source = DocumentSource.SHAREPOINT
    cc_pair.connector.connector_specific_config = connector_specific_config
    cc_pair.credential.credential_json = None
    return cc_pair


def _fake_load_credentials(
    self: SharepointConnector,
    credentials: dict[str, Any],  # noqa: ARG001
) -> None:
    self.msal_app = MagicMock()
    self.sp_tenant_domain = "contoso"


@pytest.mark.parametrize("exhaustive", [True, False])
def test_group_sync_uses_the_connector_config_flag(exhaustive: bool) -> None:
    with (
        patch.object(SharepointConnector, "load_credentials", _fake_load_credentials),
        patch.object(SharepointConnector, "_create_rest_client_context"),
        patch.object(SharepointConnector, "graph_client", new_callable=PropertyMock),
        patch.object(SharepointConnector, "graph_api", new_callable=PropertyMock),
        patch.object(
            group_sync, "get_sharepoint_external_groups", return_value=[]
        ) as get_groups,
    ):
        list(
            group_sync.sharepoint_group_sync(
                "tenant",
                _cc_pair(
                    {"sites": [_SITE_URL], "exhaustive_ad_enumeration": exhaustive}
                ),
            )
        )

    assert get_groups.call_args.args[1] == _SITE_URL
    assert get_groups.call_args.kwargs["enumerate_all_ad_groups"] is exhaustive
