"""Tests for the per-cc-pair sync-attempt history endpoints.

Covers:

* The new ``get_relevant_external_group_sync_attempts_for_cc_pair`` helper
  in ``onyx.db.permission_sync_attempt`` — including the source-wide query
  used for cc-pair-agnostic sources (Confluence, Jira).
* The migrated ``GET /admin/cc-pair/{id}/permission-sync-attempts`` route,
  now wrapped in ``CCPairSyncAttemptsResponse`` and raising ``OnyxError``.
* The new ``GET /admin/cc-pair/{id}/external-group-sync-attempts`` route.

We invoke the FastAPI route functions directly with a constructed admin
``User`` and the test ``db_session`` rather than going through TestClient —
matching the pattern used elsewhere in ``external_dependency_unit``. The
``applicable`` logic depends on EE-only ``sync_params`` helpers, so any
test that needs ``applicable=True`` uses the ``enable_ee`` fixture from
the root ``backend/tests/conftest.py``.
"""

from datetime import datetime
from datetime import timezone

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.enums import AccessType
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.enums import PermissionSyncStatus
from onyx.db.models import Connector
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Credential
from onyx.db.models import User
from onyx.db.models import UserRole
from onyx.db.permission_sync_attempt import create_doc_permission_sync_attempt
from onyx.db.permission_sync_attempt import create_external_group_sync_attempt
from onyx.db.permission_sync_attempt import (
    get_relevant_external_group_sync_attempts_for_cc_pair,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.documents.cc_pair import get_cc_pair_external_group_sync_attempts
from onyx.server.documents.cc_pair import get_cc_pair_permission_sync_attempts
from tests.external_dependency_unit.conftest import create_test_user

# Every applicable=True path here depends on the EE-only ``sync_params``
# helpers (``source_requires_doc_sync`` etc.); the no-op fallback would
# otherwise short-circuit those paths to ``applicable=False``. Applied
# module-wide so individual tests don't need to wire the fixture in.
pytestmark = pytest.mark.usefixtures("enable_ee")

# --------------------------------------------------------------------------- #
# Setup helpers
# --------------------------------------------------------------------------- #


def _create_cc_pair(
    db_session: Session,
    source: DocumentSource = DocumentSource.GOOGLE_DRIVE,
) -> ConnectorCredentialPair:
    """Create a fully wired ``ConnectorCredentialPair`` for the given source.

    Mirrors ``_create_test_connector_credential_pair`` in the sibling test
    files but kept local so changes here don't ripple into those tests.
    """
    user = create_test_user(db_session, "fixture_user")

    connector = Connector(
        name=f"Test {source.value} Connector",
        source=source,
        input_type=InputType.LOAD_STATE,
        connector_specific_config={},
        refresh_freq=None,
        prune_freq=None,
        indexing_start=datetime.now(timezone.utc),
    )
    db_session.add(connector)
    db_session.flush()

    credential = Credential(
        credential_json={},
        user_id=user.id,
        admin_public=True,
    )
    db_session.add(credential)
    db_session.flush()
    db_session.expire(credential)

    cc_pair = ConnectorCredentialPair(
        connector_id=connector.id,
        credential_id=credential.id,
        name=f"Test CC Pair {source.value}",
        status=ConnectorCredentialPairStatus.ACTIVE,
        access_type=AccessType.SYNC,
    )
    db_session.add(cc_pair)
    db_session.commit()
    return cc_pair


def _admin_user(db_session: Session) -> User:
    return create_test_user(db_session, "admin", role=UserRole.ADMIN)


# --------------------------------------------------------------------------- #
# Helper: get_relevant_external_group_sync_attempts_for_cc_pair
# --------------------------------------------------------------------------- #


class TestGetRelevantExternalGroupSyncAttemptsForCcPair:
    def test_filters_by_cc_pair_when_source_is_not_agnostic(
        self,
        db_session: Session,
    ) -> None:
        """Google Drive's group sync is per-cc-pair; sibling cc-pair attempts
        with the same source must NOT bleed into the result."""
        cc_pair = _create_cc_pair(db_session, DocumentSource.GOOGLE_DRIVE)
        sibling_cc_pair = _create_cc_pair(db_session, DocumentSource.GOOGLE_DRIVE)

        own_attempt_id = create_external_group_sync_attempt(cc_pair.id, db_session)
        sibling_attempt_id = create_external_group_sync_attempt(
            sibling_cc_pair.id, db_session
        )

        result = get_relevant_external_group_sync_attempts_for_cc_pair(
            cc_pair_id=cc_pair.id,
            source=DocumentSource.GOOGLE_DRIVE,
            limit=50,
            db_session=db_session,
        )
        result_ids = {attempt.id for attempt in result}
        assert own_attempt_id in result_ids
        assert sibling_attempt_id not in result_ids

    def test_widens_to_source_when_agnostic(
        self,
        db_session: Session,
    ) -> None:
        """Confluence's group sync is source-wide; sibling cc-pair attempts
        sharing the source should be included even though they are recorded
        against a different cc-pair."""
        cc_pair = _create_cc_pair(db_session, DocumentSource.CONFLUENCE)
        sibling_cc_pair = _create_cc_pair(db_session, DocumentSource.CONFLUENCE)
        unrelated_cc_pair = _create_cc_pair(db_session, DocumentSource.GOOGLE_DRIVE)

        own_attempt_id = create_external_group_sync_attempt(cc_pair.id, db_session)
        sibling_attempt_id = create_external_group_sync_attempt(
            sibling_cc_pair.id, db_session
        )
        unrelated_attempt_id = create_external_group_sync_attempt(
            unrelated_cc_pair.id, db_session
        )

        result = get_relevant_external_group_sync_attempts_for_cc_pair(
            cc_pair_id=cc_pair.id,
            source=DocumentSource.CONFLUENCE,
            limit=100,
            db_session=db_session,
        )
        result_ids = {attempt.id for attempt in result}
        assert own_attempt_id in result_ids
        assert sibling_attempt_id in result_ids
        assert unrelated_attempt_id not in result_ids

    def test_orders_most_recent_first_and_respects_limit(
        self,
        db_session: Session,
    ) -> None:
        cc_pair = _create_cc_pair(db_session, DocumentSource.GOOGLE_DRIVE)

        attempt_ids = [
            create_external_group_sync_attempt(cc_pair.id, db_session) for _ in range(5)
        ]

        result = get_relevant_external_group_sync_attempts_for_cc_pair(
            cc_pair_id=cc_pair.id,
            source=DocumentSource.GOOGLE_DRIVE,
            limit=3,
            db_session=db_session,
        )

        assert len(result) == 3
        # Created sequentially -> most recent first means the last 3 attempt
        # ids in creation order, listed in reverse.
        assert [attempt.id for attempt in result] == list(reversed(attempt_ids[-3:]))


# --------------------------------------------------------------------------- #
# Route: GET /admin/cc-pair/{id}/permission-sync-attempts
# --------------------------------------------------------------------------- #


class TestGetCcPairPermissionSyncAttemptsRoute:
    def test_raises_not_found_for_unknown_cc_pair(self, db_session: Session) -> None:
        admin = _admin_user(db_session)

        with pytest.raises(OnyxError) as exc_info:
            get_cc_pair_permission_sync_attempts(
                cc_pair_id=999_999,
                page_num=0,
                page_size=10,
                user=admin,
                db_session=db_session,
            )

        assert exc_info.value.error_code == OnyxErrorCode.NOT_FOUND

    def test_applicable_false_when_source_does_not_require_doc_sync(
        self,
        db_session: Session,
    ) -> None:
        """Salesforce has no doc-sync config — only chunk censoring — so the
        endpoint must short-circuit with ``applicable=False`` even if the
        cc-pair somehow has rows in the table."""
        admin = _admin_user(db_session)
        cc_pair = _create_cc_pair(db_session, DocumentSource.SALESFORCE)

        response = get_cc_pair_permission_sync_attempts(
            cc_pair_id=cc_pair.id,
            page_num=0,
            page_size=10,
            user=admin,
            db_session=db_session,
        )

        assert response.applicable is False
        assert response.items == []
        assert response.total_items == 0

    def test_returns_attempts_when_applicable(
        self,
        db_session: Session,
    ) -> None:
        admin = _admin_user(db_session)
        cc_pair = _create_cc_pair(db_session, DocumentSource.GOOGLE_DRIVE)

        attempt_ids = [
            create_doc_permission_sync_attempt(cc_pair.id, db_session) for _ in range(3)
        ]

        response = get_cc_pair_permission_sync_attempts(
            cc_pair_id=cc_pair.id,
            page_num=0,
            page_size=10,
            user=admin,
            db_session=db_session,
        )

        assert response.applicable is True
        assert response.total_items == 3
        returned_ids = [item.id for item in response.items]
        assert set(returned_ids) == set(attempt_ids)
        # Snapshot fields populated and statuses default to NOT_STARTED.
        for item in response.items:
            assert item.status == PermissionSyncStatus.NOT_STARTED
            assert item.total_docs_synced == 0
            assert item.docs_with_permission_errors == 0
            assert item.time_finished is None

    def test_pagination_slices_correctly(
        self,
        db_session: Session,
    ) -> None:
        admin = _admin_user(db_session)
        cc_pair = _create_cc_pair(db_session, DocumentSource.GOOGLE_DRIVE)

        attempt_ids = [
            create_doc_permission_sync_attempt(cc_pair.id, db_session) for _ in range(5)
        ]

        first_page = get_cc_pair_permission_sync_attempts(
            cc_pair_id=cc_pair.id,
            page_num=0,
            page_size=2,
            user=admin,
            db_session=db_session,
        )
        second_page = get_cc_pair_permission_sync_attempts(
            cc_pair_id=cc_pair.id,
            page_num=1,
            page_size=2,
            user=admin,
            db_session=db_session,
        )
        third_page = get_cc_pair_permission_sync_attempts(
            cc_pair_id=cc_pair.id,
            page_num=2,
            page_size=2,
            user=admin,
            db_session=db_session,
        )

        assert first_page.applicable is True
        assert second_page.applicable is True
        assert third_page.applicable is True
        assert first_page.total_items == 5
        assert len(first_page.items) == 2
        assert len(second_page.items) == 2
        assert len(third_page.items) == 1

        all_returned = (
            [item.id for item in first_page.items]
            + [item.id for item in second_page.items]
            + [item.id for item in third_page.items]
        )
        assert set(all_returned) == set(attempt_ids)


# --------------------------------------------------------------------------- #
# Route: GET /admin/cc-pair/{id}/external-group-sync-attempts
# --------------------------------------------------------------------------- #


class TestGetCcPairExternalGroupSyncAttemptsRoute:
    def test_raises_not_found_for_unknown_cc_pair(self, db_session: Session) -> None:
        admin = _admin_user(db_session)

        with pytest.raises(OnyxError) as exc_info:
            get_cc_pair_external_group_sync_attempts(
                cc_pair_id=999_999,
                page_num=0,
                page_size=10,
                user=admin,
                db_session=db_session,
            )

        assert exc_info.value.error_code == OnyxErrorCode.NOT_FOUND

    def test_applicable_false_when_source_has_no_group_sync(
        self,
        db_session: Session,
    ) -> None:
        """Slack has doc sync but no separate group sync, so the group-sync
        endpoint must report ``applicable=False`` for it."""
        admin = _admin_user(db_session)
        cc_pair = _create_cc_pair(db_session, DocumentSource.SLACK)

        response = get_cc_pair_external_group_sync_attempts(
            cc_pair_id=cc_pair.id,
            page_num=0,
            page_size=10,
            user=admin,
            db_session=db_session,
        )

        assert response.applicable is False
        assert response.items == []
        assert response.total_items == 0

    def test_returns_only_own_attempts_for_non_agnostic_source(
        self,
        db_session: Session,
    ) -> None:
        admin = _admin_user(db_session)
        cc_pair = _create_cc_pair(db_session, DocumentSource.GOOGLE_DRIVE)
        sibling_cc_pair = _create_cc_pair(db_session, DocumentSource.GOOGLE_DRIVE)

        own_attempt_id = create_external_group_sync_attempt(cc_pair.id, db_session)
        sibling_attempt_id = create_external_group_sync_attempt(
            sibling_cc_pair.id, db_session
        )

        response = get_cc_pair_external_group_sync_attempts(
            cc_pair_id=cc_pair.id,
            page_num=0,
            page_size=50,
            user=admin,
            db_session=db_session,
        )

        assert response.applicable is True
        returned_ids = {item.id for item in response.items}
        assert own_attempt_id in returned_ids
        assert sibling_attempt_id not in returned_ids

    def test_includes_sibling_attempts_for_agnostic_source(
        self,
        db_session: Session,
    ) -> None:
        """For Confluence (cc-pair-agnostic), an attempt logged against a
        sibling cc-pair sharing the source must be visible from this cc-pair's
        perspective."""
        admin = _admin_user(db_session)
        cc_pair = _create_cc_pair(db_session, DocumentSource.CONFLUENCE)
        sibling_cc_pair = _create_cc_pair(db_session, DocumentSource.CONFLUENCE)

        own_attempt_id = create_external_group_sync_attempt(cc_pair.id, db_session)
        sibling_attempt_id = create_external_group_sync_attempt(
            sibling_cc_pair.id, db_session
        )

        response = get_cc_pair_external_group_sync_attempts(
            cc_pair_id=cc_pair.id,
            page_num=0,
            page_size=100,
            user=admin,
            db_session=db_session,
        )

        assert response.applicable is True
        returned_ids = {item.id for item in response.items}
        assert own_attempt_id in returned_ids
        assert sibling_attempt_id in returned_ids
