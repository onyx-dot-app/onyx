"""Cross-group authorization tests for curator-facing cc-pair / ingestion endpoints.

Regression coverage for the object-level authorization fix: a group-scoped
CURATOR must not be able to read, reindex, or ingest against a
connector-credential pair that belongs to a user group they do not curate.
Each guarded endpoint now calls ``verify_user_has_access_to_cc_pair`` before
touching the resource.

We invoke the FastAPI route functions directly with a constructed ``User`` and
the test ``db_session`` (the pattern used across ``external_dependency_unit``).
The ``POST /onyx-api/ingestion`` (upsert) and ``DELETE /onyx-api/ingestion``
paths share the exact same ``verify_user_has_access_to_cc_pair`` guard proven
denied in ``test_verify_access_boundary`` below, so they are covered by that
assertion without the heavier document/index fixtures.
"""

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.db.connector_credential_pair import verify_user_has_access_to_cc_pair
from onyx.db.enums import AccessType
from onyx.db.models import UserRole
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.documents.cc_pair import (
    get_cc_pair_indexing_errors,
    get_docs_sync_status,
)
from onyx.server.documents.targeted_reindex import (
    DocumentTargetRequest,
    TargetedReindexRequest,
    submit_targeted_reindex,
)
from onyx.server.onyx_api.ingestion import get_docs_by_connector_credential_pair
from tests.external_dependency_unit.conftest import create_test_user
from tests.external_dependency_unit.craft.db_helpers import (
    add_user_to_group,
    make_cc_pair,
    make_group,
)

# Curator group scoping runs through the same EE-versioned paths the sibling
# cc-pair route tests use; applied module-wide so each test doesn't wire it in.
pytestmark = pytest.mark.usefixtures("enable_ee")


class _Scenario:
    """A curator who curates group A, plus private cc-pairs in group A and B.

    The curator has no relationship to group B, so any access to ``cc_pair_b``
    must be denied.
    """

    def __init__(self, db_session: Session) -> None:
        self.admin = create_test_user(db_session, "admin", role=UserRole.ADMIN)
        self.curator = create_test_user(db_session, "curator", role=UserRole.CURATOR)

        self.group_a = make_group(db_session)
        self.group_b = make_group(db_session)
        membership = add_user_to_group(db_session, self.curator, self.group_a)
        membership.is_curator = True
        db_session.flush()

        # Private cc-pairs whose only visibility is the group mapping.
        self.cc_pair_a = make_cc_pair(
            db_session,
            DocumentSource.FILE,
            access_type=AccessType.PRIVATE,
            group=self.group_a,
            user=None,
        )
        self.cc_pair_b = make_cc_pair(
            db_session,
            DocumentSource.FILE,
            access_type=AccessType.PRIVATE,
            group=self.group_b,
            user=None,
        )
        db_session.commit()


def test_verify_access_boundary(db_session: Session) -> None:
    """The shared guard denies the curator on the uncurated group's cc-pair."""
    s = _Scenario(db_session)

    # Curator can read and edit its own group's cc-pair...
    assert verify_user_has_access_to_cc_pair(
        s.cc_pair_a.id, db_session, s.curator, get_editable=False
    )
    assert verify_user_has_access_to_cc_pair(
        s.cc_pair_a.id, db_session, s.curator, get_editable=True
    )
    # ...but not the other group's, for reads or writes.
    assert not verify_user_has_access_to_cc_pair(
        s.cc_pair_b.id, db_session, s.curator, get_editable=False
    )
    assert not verify_user_has_access_to_cc_pair(
        s.cc_pair_b.id, db_session, s.curator, get_editable=True
    )
    # Admin bypasses group scoping entirely.
    assert verify_user_has_access_to_cc_pair(
        s.cc_pair_b.id, db_session, s.admin, get_editable=True
    )


def test_get_docs_sync_status_cross_group_denied(db_session: Session) -> None:
    s = _Scenario(db_session)

    with pytest.raises(OnyxError) as exc:
        get_docs_sync_status(
            cc_pair_id=s.cc_pair_b.id, user=s.curator, db_session=db_session
        )
    assert exc.value.error_code == OnyxErrorCode.NOT_FOUND

    # The curator's own group and the admin are both allowed (empty cc-pairs
    # return an empty list rather than raising).
    assert (
        get_docs_sync_status(
            cc_pair_id=s.cc_pair_a.id, user=s.curator, db_session=db_session
        )
        == []
    )
    assert (
        get_docs_sync_status(
            cc_pair_id=s.cc_pair_b.id, user=s.admin, db_session=db_session
        )
        == []
    )


def test_get_cc_pair_indexing_errors_cross_group_denied(db_session: Session) -> None:
    s = _Scenario(db_session)

    with pytest.raises(OnyxError) as exc:
        get_cc_pair_indexing_errors(
            cc_pair_id=s.cc_pair_b.id,
            include_resolved=False,
            page_num=0,
            page_size=10,
            user=s.curator,
            db_session=db_session,
        )
    assert exc.value.error_code == OnyxErrorCode.NOT_FOUND


def test_ingestion_connector_docs_cross_group_denied(db_session: Session) -> None:
    s = _Scenario(db_session)

    with pytest.raises(OnyxError) as exc:
        get_docs_by_connector_credential_pair(
            cc_pair_id=s.cc_pair_b.id, user=s.curator, db_session=db_session
        )
    assert exc.value.error_code == OnyxErrorCode.NOT_FOUND


def test_targeted_reindex_cross_group_denied(db_session: Session) -> None:
    s = _Scenario(db_session)

    request = TargetedReindexRequest(
        targets=[DocumentTargetRequest(cc_pair_id=s.cc_pair_b.id, document_id="doc-1")]
    )
    with pytest.raises(OnyxError) as exc:
        submit_targeted_reindex(request=request, user=s.curator, db_session=db_session)
    assert exc.value.error_code == OnyxErrorCode.NOT_FOUND
