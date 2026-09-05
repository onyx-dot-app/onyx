"""A user-group update tombstones the old association row and leaves it until
the sync clears it, so the read has to filter on is_current."""

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.enums import AccessType, ConnectorCredentialPairStatus
from onyx.db.models import (
    Connector,
    ConnectorCredentialPair,
    Credential,
    UserGroup,
    UserGroup__ConnectorCredentialPair,
)
from onyx.server.documents.cc_pair import get_cc_pair_full_info
from tests.external_dependency_unit.conftest import create_test_user


def _build_pair(db_session: Session, tag: str) -> ConnectorCredentialPair:
    connector = Connector(
        name=f"conn-{tag}",
        source=DocumentSource.MOCK_CONNECTOR,
        input_type=InputType.POLL,
        connector_specific_config={},
    )
    credential = Credential(
        name=f"cred-{tag}",
        source=DocumentSource.MOCK_CONNECTOR,
        credential_json={},
    )
    db_session.add_all([connector, credential])
    db_session.flush()

    cc_pair = ConnectorCredentialPair(
        name=f"pair-{tag}",
        status=ConnectorCredentialPairStatus.ACTIVE,
        connector_id=connector.id,
        credential_id=credential.id,
        access_type=AccessType.PRIVATE,
    )
    db_session.add(cc_pair)
    db_session.flush()
    return cc_pair


@pytest.mark.usefixtures("tenant_context")
def test_a_pair_reports_only_the_groups_it_is_still_in(
    db_session: Session,
) -> None:
    tag = uuid4().hex[:8]
    admin = create_test_user(db_session, f"ccgroups_{tag}", is_admin=True)
    cc_pair = _build_pair(db_session, tag)

    live_group = UserGroup(name=f"live-{tag}")
    left_group = UserGroup(name=f"left-{tag}")
    db_session.add_all([live_group, left_group])
    db_session.flush()

    db_session.add_all(
        [
            UserGroup__ConnectorCredentialPair(
                user_group_id=live_group.id, cc_pair_id=cc_pair.id, is_current=True
            ),
            # What an in-flight group update leaves behind.
            UserGroup__ConnectorCredentialPair(
                user_group_id=left_group.id, cc_pair_id=cc_pair.id, is_current=False
            ),
        ]
    )
    db_session.commit()

    info = get_cc_pair_full_info(
        cc_pair_id=cc_pair.id, user=admin, db_session=db_session
    )

    assert live_group.id in info.groups
    assert left_group.id not in info.groups, (
        "A tombstoned row is a group the pair has already left"
    )
