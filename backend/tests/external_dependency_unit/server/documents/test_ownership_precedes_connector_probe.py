"""Both credential-attach routes probe the connector by building it from the
submitted credential. Ownership has to be settled first: otherwise a
MANAGE_CONNECTORS holder can aim someone else's credential at a host of their
choosing and read the outcome. Not an integration test: the check runs before the
probe, so the ordering is only observable with the probe mocked.
"""

from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.enums import AccessType
from onyx.db.models import Connector, Credential, User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.documents.cc_pair import associate_credential_to_connector
from onyx.server.documents.credential import swap_credentials_for_connector
from onyx.server.documents.models import (
    ConnectorCredentialPairMetadata,
    CredentialSwapRequest,
)
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.conftest import create_test_user


def _seed_foreign_credential(
    db_session: Session, owner: User
) -> tuple[Connector, Credential]:
    """A connector with no cc_pairs, plus a credential only ``owner`` may read.
    admin_public defaults to True, so it must be turned off for the credential to
    stay foreign to another admin."""
    suffix = uuid4().hex[:8]
    connector = Connector(
        name=f"probe-connector-{suffix}",
        source=DocumentSource.MOCK_CONNECTOR,
        input_type=InputType.LOAD_STATE,
        connector_specific_config={},
        refresh_freq=None,
        prune_freq=None,
        indexing_start=None,
    )
    credential = Credential(
        source=DocumentSource.MOCK_CONNECTOR,
        credential_json={},
        user_id=owner.id,
        admin_public=False,
    )
    db_session.add_all([connector, credential])
    db_session.commit()
    return connector, credential


def test_associate_checks_credential_ownership_before_probing(
    db_session: Session,
) -> None:
    caller = create_test_user(db_session, "associate_probe_caller", is_admin=True)
    owner = create_test_user(db_session, "associate_probe_owner", is_admin=True)
    connector, credential = _seed_foreign_credential(db_session, owner)

    with patch("onyx.server.documents.cc_pair.validate_ccpair_for_user") as probe:
        with pytest.raises(OnyxError) as exc_info:
            associate_credential_to_connector(
                connector_id=connector.id,
                credential_id=credential.id,
                metadata=ConnectorCredentialPairMetadata(
                    name=f"pair-{uuid4().hex[:8]}",
                    access_type=AccessType.PUBLIC,
                ),
                user=caller,
                db_session=db_session,
                tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
            )

    assert exc_info.value.error_code is OnyxErrorCode.CREDENTIAL_NOT_FOUND
    probe.assert_not_called()


def test_swap_checks_credential_ownership_before_probing(db_session: Session) -> None:
    caller = create_test_user(db_session, "swap_probe_caller", is_admin=True)
    owner = create_test_user(db_session, "swap_probe_owner", is_admin=True)
    connector, credential = _seed_foreign_credential(db_session, owner)

    with patch("onyx.server.documents.credential.validate_ccpair_for_user") as probe:
        with pytest.raises(OnyxError) as exc_info:
            swap_credentials_for_connector(
                credential_swap_req=CredentialSwapRequest(
                    new_credential_id=credential.id,
                    connector_id=connector.id,
                    access_type=AccessType.PUBLIC,
                ),
                user=caller,
                db_session=db_session,
            )

    assert exc_info.value.error_code is OnyxErrorCode.CREDENTIAL_NOT_FOUND
    probe.assert_not_called()
