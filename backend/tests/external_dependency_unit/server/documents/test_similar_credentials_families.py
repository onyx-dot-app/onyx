"""The similar-credentials listing returns family credentials across a family's
sources, in the requested source's keys, with usage hints limited to the pairs
the caller can manage."""

from collections.abc import Generator
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira.config import JiraCredentialBinding
from onyx.connectors.models import InputType
from onyx.db.credentials import (
    backend_update_credential_json,
    create_credential,
    update_credential,
)
from onyx.db.enums import AccessType, ConnectorCredentialPairStatus
from onyx.db.models import (
    Connector,
    ConnectorCredentialPair,
    Credential,
    User,
)
from onyx.server.documents.credential import get_cc_source_full_info
from onyx.server.documents.models import CredentialBase
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user

_SITE = "https://acme.atlassian.net"


class _Setup:
    def __init__(
        self,
        owner: User,
        admin: User,
        family_credential: Credential,
        legacy_credential: Credential,
        owned_pair: ConnectorCredentialPair,
        public_pair: ConnectorCredentialPair,
    ) -> None:
        self.owner = owner
        self.admin = admin
        self.family_credential = family_credential
        self.legacy_credential = legacy_credential
        self.owned_pair = owned_pair
        self.public_pair = public_pair


def _make_pair(
    db_session: Session,
    credential: Credential,
    source: DocumentSource,
    config: dict[str, object],
    access_type: AccessType,
    creator: User,
) -> ConnectorCredentialPair:
    connector = Connector(
        name=f"test-connector-{uuid4().hex[:8]}",
        source=source,
        input_type=InputType.POLL,
        connector_specific_config=config,
    )
    db_session.add(connector)
    db_session.flush()
    pair = ConnectorCredentialPair(
        connector_id=connector.id,
        credential_id=credential.id,
        name=f"test-cc-pair-{uuid4().hex[:8]}",
        status=ConnectorCredentialPairStatus.ACTIVE,
        access_type=access_type,
        auto_sync_options=None,
        creator_id=creator.id,
    )
    db_session.add(pair)
    db_session.commit()
    return pair


@pytest.fixture
def setup(
    db_session: Session,
) -> Generator[_Setup, None, None]:
    owner = create_test_user(db_session, "family_owner")
    admin = create_test_user(db_session, "family_admin", is_admin=True)
    family_credential = create_credential(
        CredentialBase(
            credential_json={
                "confluence_username": "user@example.com",
                "confluence_access_token": "secret-token",
            },
            admin_public=True,
            source=DocumentSource.CONFLUENCE,
        ),
        owner,
        db_session,
    )
    # Written before Confluence joined the family: stays in its source's keys.
    legacy_credential = Credential(
        source=DocumentSource.CONFLUENCE,
        credential_json={
            "confluence_username": "old@example.com",
            "confluence_access_token": "old-token",
        },
        user_id=owner.id,
        admin_public=True,
    )
    db_session.add(legacy_credential)
    db_session.commit()
    owned_pair = _make_pair(
        db_session,
        family_credential,
        DocumentSource.JIRA,
        {"jira_base_url": _SITE},
        AccessType.PRIVATE,
        owner,
    )
    public_pair = _make_pair(
        db_session,
        family_credential,
        DocumentSource.CONFLUENCE,
        {"wiki_base": _SITE, "is_cloud": True},
        AccessType.PUBLIC,
        admin,
    )
    yield _Setup(
        owner, admin, family_credential, legacy_credential, owned_pair, public_pair
    )

    pairs = [owned_pair, public_pair]
    connector_ids = [pair.connector_id for pair in pairs]
    db_session.execute(
        delete(ConnectorCredentialPair).where(
            ConnectorCredentialPair.id.in_([pair.id for pair in pairs])
        )
    )
    db_session.execute(delete(Connector).where(Connector.id.in_(connector_ids)))
    db_session.execute(
        delete(Credential).where(
            Credential.id.in_([family_credential.id, legacy_credential.id])
        )
    )
    delete_test_user(db_session, owner, admin)
    db_session.commit()


@pytest.mark.usefixtures("tenant_context")
def test_family_credential_is_listed_for_other_family_sources(
    db_session: Session, setup: _Setup
) -> None:
    # Under test.
    jira_listing = get_cc_source_full_info(
        source_type=DocumentSource.JIRA, user=setup.owner, db_session=db_session
    )
    confluence_listing = get_cc_source_full_info(
        source_type=DocumentSource.CONFLUENCE, user=setup.owner, db_session=db_session
    )

    # Postcondition.
    assert [snapshot.id for snapshot in jira_listing] == [setup.family_credential.id]
    assert set(jira_listing[0].credential_json) == {"jira_user_email", "jira_api_token"}
    assert {snapshot.id for snapshot in confluence_listing} == {
        setup.family_credential.id,
        setup.legacy_credential.id,
    }


@pytest.mark.usefixtures("tenant_context")
def test_usage_hints_only_show_manageable_pairs(
    db_session: Session, setup: _Setup
) -> None:
    # Under test.
    owner_listing = get_cc_source_full_info(
        source_type=DocumentSource.JIRA, user=setup.owner, db_session=db_session
    )
    admin_listing = get_cc_source_full_info(
        source_type=DocumentSource.JIRA, user=setup.admin, db_session=db_session
    )

    # Postcondition.
    owner_usages = owner_listing[0].usages
    assert [usage.cc_pair_id for usage in owner_usages] == [setup.owned_pair.id]
    assert owner_usages[0].credential_binding == JiraCredentialBinding(
        jira_base_url=_SITE
    )
    admin_usages = next(
        snapshot
        for snapshot in admin_listing
        if snapshot.id == setup.family_credential.id
    ).usages
    assert {usage.cc_pair_id for usage in admin_usages} == {
        setup.owned_pair.id,
        setup.public_pair.id,
    }


@pytest.mark.usefixtures("tenant_context")
def test_refresh_write_back_keeps_the_family_shape(
    db_session: Session, setup: _Setup
) -> None:
    # Under test: a Jira connector writes back refreshed material.
    backend_update_credential_json(
        setup.family_credential,
        DocumentSource.JIRA,
        {"jira_user_email": "user@example.com", "jira_api_token": "rotated-token"},
        db_session,
    )

    # Postcondition.
    db_session.refresh(setup.family_credential)
    assert setup.family_credential.credential_json is not None
    stored = setup.family_credential.credential_json.get_value(apply_mask=False)
    assert stored == {
        "email": "user@example.com",
        "token": "rotated-token",
        "oauth": None,
        "credential_family": "atlassian",
    }


@pytest.mark.usefixtures("tenant_context")
def test_family_credential_update_from_another_source_is_rejected(
    db_session: Session, setup: _Setup
) -> None:
    # Under test / postcondition.
    with pytest.raises(ValueError, match="update it as confluence"):
        update_credential(
            setup.family_credential.id,
            CredentialBase(
                credential_json={"jira_api_token": "new-token"},
                admin_public=True,
                source=DocumentSource.JIRA,
            ),
            setup.owner,
            db_session,
        )
