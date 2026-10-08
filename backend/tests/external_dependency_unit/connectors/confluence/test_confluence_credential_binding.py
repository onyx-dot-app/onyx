"""``validate_ccpair_for_user`` rejects a Confluence config whose site is not the
one the OAuth credential was authorized for, before the connector is built."""

from collections.abc import Generator
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors import factory
from onyx.connectors.capability_checks import creation
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.factory import (
    validate_ccpair_for_user,
    validate_connector_credential_bindings,
)
from onyx.connectors.interfaces import BaseConnector
from onyx.db.credentials import backend_update_credential_json
from onyx.db.enums import AccessType
from onyx.db.models import ConnectorCredentialPair
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)

_AUTHORIZED_SITE = "https://acme.atlassian.net"


@pytest.fixture
def instantiate_connector(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    mock = MagicMock(return_value=MagicMock(spec=BaseConnector))
    monkeypatch.setattr(factory, "instantiate_connector", mock)
    monkeypatch.setattr(factory, "INTEGRATION_TESTS_MODE", False)
    # Confluence has named checks, so validation runs them after the binding
    # gate. These tests cover only the gate; the checks would reach the site.
    monkeypatch.setattr(
        creation, "validate_pairing_with_named_checks", MagicMock(return_value=True)
    )
    return mock


@pytest.fixture
def confluence_oauth_cc_pair(
    db_session: Session,
) -> Generator[ConnectorCredentialPair, None, None]:
    cc_pair = make_cc_pair(db_session, source=DocumentSource.CONFLUENCE)
    backend_update_credential_json(
        cc_pair.credential,
        DocumentSource.CONFLUENCE,
        {
            "confluence_access_token": "fake-access-token",
            "confluence_refresh_token": "fake-refresh-token",
            "wiki_base": _AUTHORIZED_SITE,
        },
        db_session,
    )
    yield cc_pair
    cleanup_cc_pair(db_session, cc_pair)


def _set_wiki_base(
    db_session: Session, cc_pair: ConnectorCredentialPair, wiki_base: str
) -> None:
    cc_pair.connector.connector_specific_config = {
        "wiki_base": wiki_base,
        "is_cloud": True,
    }
    db_session.commit()


@pytest.mark.usefixtures("tenant_context")
def test_other_site_is_rejected_before_the_connector_is_built(
    db_session: Session,
    confluence_oauth_cc_pair: ConnectorCredentialPair,
    instantiate_connector: MagicMock,
) -> None:
    # Precondition.
    _set_wiki_base(db_session, confluence_oauth_cc_pair, "https://other.atlassian.net")

    # Under test.
    with pytest.raises(ConnectorValidationError, match="authorized for"):
        validate_ccpair_for_user(
            confluence_oauth_cc_pair.connector_id,
            confluence_oauth_cc_pair.credential_id,
            AccessType.PUBLIC,
            db_session,
        )

    # Postcondition.
    instantiate_connector.assert_not_called()


@pytest.mark.usefixtures("tenant_context")
def test_authorized_site_is_accepted(
    db_session: Session,
    confluence_oauth_cc_pair: ConnectorCredentialPair,
    instantiate_connector: MagicMock,
) -> None:
    # Precondition: same host, different path and case.
    _set_wiki_base(
        db_session, confluence_oauth_cc_pair, "https://ACME.atlassian.net/wiki/"
    )

    # Under test.
    result = validate_ccpair_for_user(
        confluence_oauth_cc_pair.connector_id,
        confluence_oauth_cc_pair.credential_id,
        AccessType.PUBLIC,
        db_session,
    )

    # Postcondition.
    assert result is True
    instantiate_connector.assert_called_once()


@pytest.mark.usefixtures("tenant_context")
def test_http_downgrade_of_the_authorized_site_is_rejected(
    db_session: Session,
    confluence_oauth_cc_pair: ConnectorCredentialPair,
    instantiate_connector: MagicMock,
) -> None:
    # Precondition.
    _set_wiki_base(db_session, confluence_oauth_cc_pair, "http://acme.atlassian.net")

    # Under test.
    with pytest.raises(ConnectorValidationError, match="authorized for"):
        validate_ccpair_for_user(
            confluence_oauth_cc_pair.connector_id,
            confluence_oauth_cc_pair.credential_id,
            AccessType.PUBLIC,
            db_session,
        )

    # Postcondition.
    instantiate_connector.assert_not_called()


@pytest.mark.usefixtures("tenant_context")
def test_config_edit_is_checked_against_paired_credentials(
    db_session: Session,
    confluence_oauth_cc_pair: ConnectorCredentialPair,
) -> None:
    # Under test / postcondition: the edit an admin would PATCH.
    with pytest.raises(ConnectorValidationError, match="authorized for"):
        validate_connector_credential_bindings(
            confluence_oauth_cc_pair.connector_id,
            DocumentSource.CONFLUENCE,
            {"wiki_base": "https://other.atlassian.net", "is_cloud": True},
            db_session,
        )
    with pytest.raises(ConnectorValidationError, match="invalid"):
        validate_connector_credential_bindings(
            confluence_oauth_cc_pair.connector_id,
            DocumentSource.CONFLUENCE,
            {"wiki_base": _AUTHORIZED_SITE, "is_cloud": "not-a-bool"},
            db_session,
        )
    validate_connector_credential_bindings(
        confluence_oauth_cc_pair.connector_id,
        DocumentSource.CONFLUENCE,
        {"wiki_base": _AUTHORIZED_SITE, "is_cloud": True},
        db_session,
    )
