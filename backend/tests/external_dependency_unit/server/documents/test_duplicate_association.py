"""A duplicate association request leaves the live pair's report alone."""

from collections.abc import Generator
from datetime import timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.db.credential_capability import (
    get_capability_report_row,
    mark_capability_report_running,
)
from onyx.db.enums import AccessType, CapabilityCheckTrigger
from onyx.db.models import ConnectorCredentialPair
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.documents import cc_pair as cc_pair_api
from onyx.server.documents.cc_pair import associate_credential_to_connector
from onyx.server.documents.models import ConnectorCredentialPairMetadata
from shared_configs.contextvars import get_current_tenant_id
from tests.external_dependency_unit.conftest import create_test_user
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)


@pytest.fixture
def slack_pair(db_session: Session) -> Generator[ConnectorCredentialPair, None, None]:
    cc_pair = make_cc_pair(db_session, source=DocumentSource.SLACK)
    yield cc_pair
    cleanup_cc_pair(db_session, cc_pair)


@pytest.mark.usefixtures("tenant_context")
def test_duplicate_association_leaves_the_live_report_unchanged(
    db_session: Session,
    slack_pair: ConnectorCredentialPair,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = create_test_user(db_session, "dup-assoc", is_admin=True)
    running = mark_capability_report_running(
        db_session,
        credential_id=slack_pair.credential_id,
        connector_id=slack_pair.connector_id,
        source=DocumentSource.SLACK,
        trigger=CapabilityCheckTrigger.CC_PAIR_VALIDATION,
        active_within=timedelta(0),
    )
    assert running is not None
    run_id = running.run_id
    db_session.commit()
    validate = MagicMock()
    monkeypatch.setattr(cc_pair_api, "validate_ccpair_for_user", validate)

    with pytest.raises(OnyxError) as error:
        associate_credential_to_connector(
            slack_pair.connector_id,
            slack_pair.credential_id,
            ConnectorCredentialPairMetadata(
                name=f"dup-assoc-{uuid4().hex[:8]}", access_type=AccessType.PUBLIC
            ),
            admin,
            db_session,
            get_current_tenant_id(),
        )

    assert error.value.error_code == OnyxErrorCode.CONFLICT
    validate.assert_not_called()
    db_session.expire_all()
    row = get_capability_report_row(
        db_session, slack_pair.credential_id, slack_pair.connector_id
    )
    assert row is not None
    assert row.run_id == run_id
