"""Regression coverage for tenant isolation of the Salesforce permission-censoring
caches: the per-tenant Salesforce client and the email->user_id map must never let
one tenant's org, credentials, or resolved user id serve another tenant's access check."""

from unittest.mock import MagicMock
from unittest.mock import patch

import ee.onyx.external_permissions.salesforce.utils as sf_utils
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR


def test_email_to_id_cache_is_tenant_isolated() -> None:
    sf_utils._CACHED_SF_EMAIL_TO_ID_MAP.clear()
    email = "shared@example.com"
    client = MagicMock()

    with patch.object(sf_utils, "_query_salesforce_user_id") as mock_query:
        mock_query.return_value = "id_a"
        token = CURRENT_TENANT_ID_CONTEXTVAR.set("tenant_a")
        try:
            assert sf_utils.get_salesforce_user_id_from_email(client, email) == "id_a"
            # second call for the same tenant is served from cache (no extra query)
            assert sf_utils.get_salesforce_user_id_from_email(client, email) == "id_a"
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
        assert mock_query.call_count == 1

        # same email under a different tenant must not see tenant_a's cached id
        mock_query.return_value = "id_b"
        token = CURRENT_TENANT_ID_CONTEXTVAR.set("tenant_b")
        try:
            assert sf_utils.get_salesforce_user_id_from_email(client, email) == "id_b"
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
        assert mock_query.call_count == 2


def test_salesforce_client_cache_is_tenant_isolated() -> None:
    sf_utils._TENANT_SALESFORCE_CLIENT.clear()
    doc_id = "doc-1"

    cc_pair = MagicMock()
    cc_pair.credential.credential_json.get_value.return_value = {
        "sf_username": "u",
        "sf_password": "p",
        "sf_security_token": "t",
    }
    client_a = object()
    client_b = object()

    with (
        patch.object(sf_utils, "get_cc_pairs_for_document", return_value=[cc_pair]),
        patch.object(
            sf_utils, "Salesforce", side_effect=[client_a, client_b]
        ) as mock_salesforce,
    ):
        db_session = MagicMock()

        token = CURRENT_TENANT_ID_CONTEXTVAR.set("tenant_a")
        try:
            first = sf_utils.get_any_salesforce_client_for_doc_id(db_session, doc_id)
            # repeat call reuses the same client for the tenant
            second = sf_utils.get_any_salesforce_client_for_doc_id(db_session, doc_id)
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
        assert first is client_a
        assert second is client_a

        token = CURRENT_TENANT_ID_CONTEXTVAR.set("tenant_b")
        try:
            other = sf_utils.get_any_salesforce_client_for_doc_id(db_session, doc_id)
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
        # tenant_b gets its own client, never tenant_a's
        assert other is client_b
        # one client built per tenant, not per call
        assert mock_salesforce.call_count == 2
