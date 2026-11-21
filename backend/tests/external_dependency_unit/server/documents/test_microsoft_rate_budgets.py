"""The admin listing of the Microsoft connectors on one app registration,
with the RU per minute that each one sets."""

from collections.abc import Generator
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.credentials import create_credential
from onyx.db.enums import AccessType, ConnectorCredentialPairStatus
from onyx.db.models import Connector, ConnectorCredentialPair, Credential, User
from onyx.error_handling.exceptions import OnyxError
from onyx.server.documents.credential import list_microsoft_rate_budgets
from onyx.server.documents.models import CredentialBase
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user

_SECRET = "s3cret-value-that-must-not-leak"


class _Setup:
    def __init__(self, admin: User, directory_id: str, client_id: str) -> None:
        self.admin = admin
        self.directory_id = directory_id
        self.client_id = client_id
        self.credential_ids: list[int] = []
        self.connector_ids: list[int] = []


def _credential(
    db_session: Session,
    setup: _Setup,
    source: DocumentSource,
    prefix: str,
    client_id: str | None = None,
) -> Credential:
    credential = create_credential(
        CredentialBase(
            credential_json={
                f"{prefix}_client_id": client_id or setup.client_id,
                # Microsoft ids compare in any letter case.
                f"{prefix}_directory_id": setup.directory_id.upper(),
                f"{prefix}_client_secret": _SECRET,
            },
            admin_public=True,
            source=source,
            name=f"test-credential-{uuid4().hex[:8]}",
        ),
        setup.admin,
        db_session,
    )
    setup.credential_ids.append(credential.id)
    return credential


def _pair(
    db_session: Session,
    setup: _Setup,
    credential: Credential,
    source: DocumentSource,
    ru_per_minute: int | None,
) -> Connector:
    connector = Connector(
        name=f"test-connector-{uuid4().hex[:8]}",
        source=source,
        input_type=InputType.POLL,
        connector_specific_config=(
            {} if ru_per_minute is None else {"ru_per_minute": ru_per_minute}
        ),
    )
    db_session.add(connector)
    db_session.flush()
    db_session.add(
        ConnectorCredentialPair(
            connector_id=connector.id,
            credential_id=credential.id,
            name=f"pair of {connector.name}",
            status=ConnectorCredentialPairStatus.ACTIVE,
            access_type=AccessType.PUBLIC,
            auto_sync_options=None,
            creator_id=setup.admin.id,
        )
    )
    db_session.commit()
    setup.connector_ids.append(connector.id)
    return connector


@pytest.fixture
def setup(db_session: Session) -> Generator[_Setup, None, None]:
    admin = create_test_user(db_session, "ru_budget_admin", is_admin=True)
    state = _Setup(admin, str(uuid4()), str(uuid4()))
    yield state
    db_session.rollback()
    db_session.execute(
        delete(ConnectorCredentialPair).where(
            ConnectorCredentialPair.connector_id.in_(state.connector_ids)
        )
    )
    db_session.execute(delete(Connector).where(Connector.id.in_(state.connector_ids)))
    db_session.execute(
        delete(Credential).where(Credential.id.in_(state.credential_ids))
    )
    db_session.commit()
    delete_test_user(db_session, admin)


def test_the_listing_has_the_connectors_of_the_app_on_every_credential(
    db_session: Session, setup: _Setup
) -> None:
    # Two credential rows of two sources hold the same app registration.
    sharepoint_credential = _credential(
        db_session, setup, DocumentSource.SHAREPOINT, "sp"
    )
    teams_credential = _credential(db_session, setup, DocumentSource.TEAMS, "teams")
    other_app_credential = _credential(
        db_session, setup, DocumentSource.SHAREPOINT, "sp", client_id=str(uuid4())
    )
    edited = _pair(
        db_session, setup, sharepoint_credential, DocumentSource.SHAREPOINT, 900
    )
    sibling = _pair(
        db_session, setup, sharepoint_credential, DocumentSource.SHAREPOINT, 500
    )
    teams = _pair(db_session, setup, teams_credential, DocumentSource.TEAMS, 250)
    learned = _pair(db_session, setup, teams_credential, DocumentSource.TEAMS, None)
    _pair(db_session, setup, other_app_credential, DocumentSource.SHAREPOINT, 4000)

    budgets = list_microsoft_rate_budgets(
        sharepoint_credential.id,
        exclude_connector_id=edited.id,
        _=setup.admin,
        db_session=db_session,
    )

    assert {
        entry.connector_id: (entry.source, entry.ru_per_minute)
        for entry in budgets.connectors
    } == {
        sibling.id: (DocumentSource.SHAREPOINT, 500),
        teams.id: (DocumentSource.TEAMS, 250),
        learned.id: (DocumentSource.TEAMS, None),
    }
    assert budgets.total_ru_per_minute == 750
    # The answer holds names and numbers, and no credential field.
    dumped = budgets.model_dump_json()
    assert _SECRET not in dumped
    assert setup.client_id not in dumped and setup.directory_id not in dumped
    assert set(budgets.connectors[0].model_dump()) == {
        "connector_id",
        "name",
        "source",
        "ru_per_minute",
    }

    # With no connector left out, the edited one is in the sum.
    everything = list_microsoft_rate_budgets(
        teams_credential.id,
        exclude_connector_id=None,
        _=setup.admin,
        db_session=db_session,
    )
    assert everything.total_ru_per_minute == 1650

    # A connector on another app sees none of these.
    other = list_microsoft_rate_budgets(
        other_app_credential.id,
        exclude_connector_id=None,
        _=setup.admin,
        db_session=db_session,
    )
    assert [entry.ru_per_minute for entry in other.connectors] == [4000]


def test_a_credential_with_no_app_registration_has_no_listing(
    db_session: Session, setup: _Setup
) -> None:
    slack = create_credential(
        CredentialBase(
            credential_json={"slack_bot_token": "fake"},
            admin_public=True,
            source=DocumentSource.SLACK,
            name=f"test-credential-{uuid4().hex[:8]}",
        ),
        setup.admin,
        db_session,
    )
    setup.credential_ids.append(slack.id)

    budgets = list_microsoft_rate_budgets(
        slack.id, exclude_connector_id=None, _=setup.admin, db_session=db_session
    )
    assert (budgets.connectors, budgets.total_ru_per_minute) == ([], 0)

    with pytest.raises(OnyxError):
        list_microsoft_rate_budgets(
            -1, exclude_connector_id=None, _=setup.admin, db_session=db_session
        )
