"""Salesforce query-time permission cache isolation coverage."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from unittest.mock import MagicMock, call, patch

import pytest

import ee.onyx.external_permissions.salesforce.utils as sf_utils
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.salesforce.models import SalesforceAuthenticationMethod
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

_CREDENTIAL_UPDATED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def _cc_pair(credential_id: int) -> MagicMock:
    cc_pair = MagicMock()
    cc_pair.credential.id = credential_id
    cc_pair.credential.time_updated = _CREDENTIAL_UPDATED_AT
    return cc_pair


def test_salesforce_permission_caches_are_bounded() -> None:
    assert (
        sf_utils._SALESFORCE_CLIENT_CACHE.maxsize
        == sf_utils._SALESFORCE_CLIENT_CACHE_MAX_SIZE
    )
    assert (
        sf_utils._CACHED_SF_EMAIL_TO_ID_MAP.maxsize
        == sf_utils._SALESFORCE_USER_ID_CACHE_MAX_SIZE
    )


def test_concurrent_client_builds_cache_one_client() -> None:
    sf_utils._SALESFORCE_CLIENT_CACHE.clear()
    barrier = Barrier(2)
    clients = [MagicMock(), MagicMock()]

    def cache_client(client: MagicMock) -> object:
        barrier.wait()
        return sf_utils._cache_salesforce_client(
            ("tenant_a", 11), _CREDENTIAL_UPDATED_AT, client
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(cache_client, clients))

    assert results[0] is results[1]
    assert sum(client.session.close.call_count for client in clients) == 1


def test_email_to_id_cache_is_tenant_isolated() -> None:
    sf_utils._CACHED_SF_EMAIL_TO_ID_MAP.clear()
    email = "shared@example.com"
    client = MagicMock()
    client.sf_instance = "shared.salesforce.com"

    with patch.object(sf_utils, "_query_salesforce_user_id") as mock_query:
        mock_query.return_value = "id_a"
        token = CURRENT_TENANT_ID_CONTEXTVAR.set("tenant_a")
        try:
            assert sf_utils.get_salesforce_user_id_from_email(client, email) == "id_a"
            assert sf_utils.get_salesforce_user_id_from_email(client, email) == "id_a"
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
        assert mock_query.call_count == 1

        mock_query.return_value = "id_b"
        token = CURRENT_TENANT_ID_CONTEXTVAR.set("tenant_b")
        try:
            assert sf_utils.get_salesforce_user_id_from_email(client, email) == "id_b"
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
        assert mock_query.call_count == 2


def test_email_to_id_cache_is_client_isolated_on_same_instance() -> None:
    sf_utils._CACHED_SF_EMAIL_TO_ID_MAP.clear()
    client_a = MagicMock(sf_instance="shared.salesforce.com")
    client_b = MagicMock(sf_instance="shared.salesforce.com")

    with patch.object(
        sf_utils, "_query_salesforce_user_id", side_effect=["id_a", "id_b"]
    ) as mock_query:
        assert (
            sf_utils.get_salesforce_user_id_from_email(client_a, "shared@example.com")
            == "id_a"
        )
        assert (
            sf_utils.get_salesforce_user_id_from_email(client_b, "shared@example.com")
            == "id_b"
        )

    assert mock_query.call_count == 2


def test_salesforce_client_cache_is_tenant_isolated() -> None:
    sf_utils._SALESFORCE_CLIENT_CACHE.clear()
    cc_pair = _cc_pair(11)
    provider_a = object()
    provider_b = object()
    client_a = object()
    client_b = object()

    with (
        patch.object(sf_utils, "get_cc_pairs_for_document", return_value=[cc_pair]),
        patch.object(
            sf_utils,
            "build_db_credentials_provider",
            side_effect=[provider_a, provider_b],
        ) as mock_provider_builder,
        patch.object(
            sf_utils, "build_salesforce_client", side_effect=[client_a, client_b]
        ) as mock_client_builder,
    ):
        db_session = MagicMock()
        token = CURRENT_TENANT_ID_CONTEXTVAR.set("tenant_a")
        try:
            first = sf_utils.get_any_salesforce_client_for_doc_id(db_session, "doc-1")
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)

        token = CURRENT_TENANT_ID_CONTEXTVAR.set("tenant_b")
        try:
            other = sf_utils.get_any_salesforce_client_for_doc_id(db_session, "doc-1")
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)

    assert first is client_a
    assert other is client_b
    assert mock_provider_builder.call_args_list == [
        call(DocumentSource.SALESFORCE, 11),
        call(DocumentSource.SALESFORCE, 11),
    ]
    assert mock_client_builder.call_args_list == [call(provider_a), call(provider_b)]


def test_salesforce_client_cache_is_credential_isolated_within_tenant() -> None:
    sf_utils._SALESFORCE_CLIENT_CACHE.clear()
    cc_pairs = {
        "doc-1": [_cc_pair(11)],
        "doc-2": [_cc_pair(22)],
    }
    provider_a = object()
    provider_b = object()
    client_a = object()
    client_b = object()

    with (
        patch.object(
            sf_utils,
            "get_cc_pairs_for_document",
            side_effect=lambda _session, doc_id: cc_pairs[doc_id],
        ),
        patch.object(
            sf_utils,
            "build_db_credentials_provider",
            side_effect=[provider_a, provider_b],
        ),
        patch.object(
            sf_utils, "build_salesforce_client", side_effect=[client_a, client_b]
        ),
    ):
        token = CURRENT_TENANT_ID_CONTEXTVAR.set("tenant_a")
        try:
            first = sf_utils.get_any_salesforce_client_for_doc_id(MagicMock(), "doc-1")
            second = sf_utils.get_any_salesforce_client_for_doc_id(MagicMock(), "doc-2")
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)

    assert first is client_a
    assert second is client_b


def test_salesforce_client_cache_reuses_same_credential() -> None:
    sf_utils._SALESFORCE_CLIENT_CACHE.clear()
    cc_pair = _cc_pair(11)
    provider = object()
    client = object()

    with (
        patch.object(
            sf_utils, "get_cc_pairs_for_document", return_value=[cc_pair]
        ) as mock_get_cc_pairs,
        patch.object(
            sf_utils, "build_db_credentials_provider", return_value=provider
        ) as mock_provider_builder,
        patch.object(
            sf_utils, "build_salesforce_client", return_value=client
        ) as mock_client_builder,
    ):
        token = CURRENT_TENANT_ID_CONTEXTVAR.set("tenant_a")
        try:
            first = sf_utils.get_any_salesforce_client_for_doc_id(MagicMock(), "doc-1")
            second = sf_utils.get_any_salesforce_client_for_doc_id(MagicMock(), "doc-2")
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)

    assert first is client
    assert second is client
    assert mock_get_cc_pairs.call_count == 2
    mock_provider_builder.assert_called_once_with(DocumentSource.SALESFORCE, 11)
    mock_client_builder.assert_called_once_with(provider)


def test_salesforce_client_cache_rebuilds_updated_credential() -> None:
    sf_utils._SALESFORCE_CLIENT_CACHE.clear()
    cc_pair = _cc_pair(11)
    provider_a = object()
    provider_b = object()
    client_a = object()
    client_b = object()

    with (
        patch.object(sf_utils, "get_cc_pairs_for_document", return_value=[cc_pair]),
        patch.object(
            sf_utils,
            "build_db_credentials_provider",
            side_effect=[provider_a, provider_b],
        ) as mock_provider_builder,
        patch.object(
            sf_utils, "build_salesforce_client", side_effect=[client_a, client_b]
        ) as mock_client_builder,
    ):
        first = sf_utils.get_any_salesforce_client_for_doc_id(MagicMock(), "doc-1")
        unchanged = sf_utils.get_any_salesforce_client_for_doc_id(MagicMock(), "doc-1")
        cc_pair.credential.time_updated += timedelta(seconds=1)
        updated = sf_utils.get_any_salesforce_client_for_doc_id(MagicMock(), "doc-1")

    assert first is client_a
    assert unchanged is client_a
    assert updated is client_b
    assert mock_provider_builder.call_count == 2
    assert mock_client_builder.call_args_list == [call(provider_a), call(provider_b)]
    assert len(sf_utils._SALESFORCE_CLIENT_CACHE) == 1


def test_credential_revision_replacement_clears_cached_user_ids() -> None:
    sf_utils._SALESFORCE_CLIENT_CACHE.clear()
    sf_utils._CACHED_SF_EMAIL_TO_ID_MAP.clear()
    cc_pair = _cc_pair(11)
    client_a = MagicMock(sf_instance="shared.salesforce.com")
    client_b = MagicMock(sf_instance="shared.salesforce.com")
    email = "shared@example.com"

    with (
        patch.object(sf_utils, "get_cc_pairs_for_document", return_value=[cc_pair]),
        patch.object(sf_utils, "build_db_credentials_provider"),
        patch.object(
            sf_utils, "build_salesforce_client", side_effect=[client_a, client_b]
        ),
        patch.object(
            sf_utils, "_query_salesforce_user_id", side_effect=["id_a", "id_b"]
        ),
    ):
        token = CURRENT_TENANT_ID_CONTEXTVAR.set("tenant_a")
        try:
            first = sf_utils.get_any_salesforce_client_for_doc_id(MagicMock(), "doc-1")
            assert sf_utils.get_salesforce_user_id_from_email(first, email) == "id_a"

            cc_pair.credential.time_updated += timedelta(seconds=1)
            updated = sf_utils.get_any_salesforce_client_for_doc_id(
                MagicMock(), "doc-1"
            )
            assert not sf_utils._CACHED_SF_EMAIL_TO_ID_MAP
            assert sf_utils.get_salesforce_user_id_from_email(updated, email) == "id_b"
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)

    [(tenant_id, cached_client_ref, cached_email)] = sf_utils._CACHED_SF_EMAIL_TO_ID_MAP
    assert tenant_id == "tenant_a"
    assert cached_client_ref() is client_b
    assert cached_email == email


def test_oauth_client_uses_db_credentials_provider() -> None:
    sf_utils._SALESFORCE_CLIENT_CACHE.clear()
    cc_pair = _cc_pair(42)
    provider = MagicMock()
    provider.get_credentials.return_value = {
        "authentication_method": SalesforceAuthenticationMethod.OAUTH,
        "sf_access_token": "access-token",
        "sf_refresh_token": "refresh-token",
        "sf_instance_url": "https://example.my.salesforce.com",
        "sf_login_url": "https://example.my.salesforce.com",
    }
    client = MagicMock()

    with (
        patch.object(sf_utils, "get_cc_pairs_for_document", return_value=[cc_pair]),
        patch.object(
            sf_utils, "build_db_credentials_provider", return_value=provider
        ) as mock_provider_builder,
        patch(
            "onyx.connectors.salesforce.auth.OnyxSalesforce", return_value=client
        ) as mock_salesforce,
    ):
        result = sf_utils.get_any_salesforce_client_for_doc_id(MagicMock(), "oauth-doc")

    assert result is client
    mock_provider_builder.assert_called_once_with(DocumentSource.SALESFORCE, 42)
    provider.get_credentials.assert_called_once_with()
    assert mock_salesforce.call_args.kwargs["session_id"] == "access-token"
    assert (
        mock_salesforce.call_args.kwargs["instance_url"]
        == "https://example.my.salesforce.com"
    )
    assert callable(mock_salesforce.call_args.kwargs["refresh_callback"])


def test_salesforce_document_without_cc_pairs_raises_connector_error() -> None:
    sf_utils._SALESFORCE_CLIENT_CACHE.clear()
    with (
        patch.object(sf_utils, "get_cc_pairs_for_document", return_value=[]),
        pytest.raises(
            ConnectorValidationError,
            match="No connector credential pair found for Salesforce document: doc-1",
        ),
    ):
        sf_utils.get_any_salesforce_client_for_doc_id(MagicMock(), "doc-1")
