"""End-to-end Google Drive permission sync against the onyx-test.com Workspace.

The test creates its own shared drive as the Workspace admin, changes file and
drive permissions, runs a permission sync after each change, and checks which
documents each Onyx user can read through the stored ACLs.
"""

import json
import os
from collections.abc import Generator
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pytest
from pydantic import BaseModel, ConfigDict

from onyx.configs.constants import DocumentSource
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY,
    DB_CREDENTIALS_PRIMARY_ADMIN_KEY,
)
from onyx.connectors.models import InputType
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import AccessType
from tests.integration.common_utils.document_acl import (
    get_all_connector_documents,
    get_user_document_access_via_acl,
)
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.connector import ConnectorManager
from tests.integration.common_utils.managers.credential import CredentialManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.reset import reset_all
from tests.integration.common_utils.test_models import DATestCCPair, DATestUser
from tests.integration.connector_job_tests.google.google_drive_api_utils import (
    GoogleDriveManager,
)
from tests.utils.secret_names import TestSecret

pytestmark = [
    pytest.mark.secrets(TestSecret.GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON_STR),
    pytest.mark.skipif(
        os.environ.get("RUN_EE_TESTS", "").lower() != "true",
        reason="Permission tests are enterprise only",
    ),
]

# Real users of the onyx-test.com Workspace that the service account can impersonate.
ADMIN_EMAIL = "admin@onyx-test.com"
TEST_USER_1_EMAIL = "test_user_1@onyx-test.com"
TEST_USER_2_EMAIL = "test_user_2@onyx-test.com"


class DriveSyncEnv(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    # A googleapiclient Resource; GoogleDriveService is only a type alias.
    drive_service: Any
    drive_id: str
    cc_pair: DATestCCPair
    admin_user: DATestUser
    test_user_1: DATestUser
    test_user_2: DATestUser


@pytest.fixture()
def drive_sync_env(
    reset: None,  # noqa: ARG001
    test_secrets: dict[TestSecret, str],
) -> Generator[DriveSyncEnv, None, None]:
    # The first user created is the Onyx admin.
    admin_user = UserManager.create(email=ADMIN_EMAIL)
    test_user_1 = UserManager.create(email=TEST_USER_1_EMAIL)
    test_user_2 = UserManager.create(email=TEST_USER_2_EMAIL)

    service_account_key = test_secrets[TestSecret.GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON_STR]
    drive_service = GoogleDriveManager.create_impersonated_drive_service(
        json.loads(service_account_key), ADMIN_EMAIL
    )
    drive_id = GoogleDriveManager.create_shared_drive(
        drive_service, ADMIN_EMAIL, str(uuid4())
    )
    try:
        credential = CredentialManager.create(
            source=DocumentSource.GOOGLE_DRIVE,
            credential_json={
                DB_CREDENTIALS_PRIMARY_ADMIN_KEY: ADMIN_EMAIL,
                DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY: service_account_key,
            },
            user_performing_action=admin_user,
        )
        connector = ConnectorManager.create(
            name="Google Drive Permission Sync Test",
            input_type=InputType.POLL,
            source=DocumentSource.GOOGLE_DRIVE,
            connector_specific_config={
                "include_shared_drives": False,
                "include_my_drives": False,
                "include_files_shared_with_me": False,
                "shared_drive_urls": f"https://drive.google.com/drive/folders/{drive_id}",
            },
            access_type=AccessType.SYNC,
            user_performing_action=admin_user,
        )
        cc_pair = CCPairManager.create(
            credential_id=credential.id,
            connector_id=connector.id,
            access_type=AccessType.SYNC,
            user_performing_action=admin_user,
        )
        yield DriveSyncEnv(
            drive_service=drive_service,
            drive_id=drive_id,
            cc_pair=cc_pair,
            admin_user=admin_user,
            test_user_1=test_user_1,
            test_user_2=test_user_2,
        )
    finally:
        try:
            GoogleDriveManager.cleanup_drive(drive_service, drive_id)
        finally:
            reset_all()


def _index(env: DriveSyncEnv) -> None:
    """Wait out any run already open (the first starts when the pair is created,
    and may predate the test's changes), then run once and wait for it."""
    CCPairManager.wait_for_indexing_inactive(
        cc_pair=env.cc_pair, user_performing_action=env.admin_user
    )
    before = datetime.now(timezone.utc)
    CCPairManager.run_once(
        env.cc_pair, from_beginning=True, user_performing_action=env.admin_user
    )
    CCPairManager.wait_for_indexing_completion(
        cc_pair=env.cc_pair, after=before, user_performing_action=env.admin_user
    )


def _sync(
    env: DriveSyncEnv, changed_at: datetime, changed_doc_ids: list[str] | None = None
) -> None:
    """Run doc sync and group sync, wait for both, then for the changed docs to
    reach the index.

    `changed_at` is taken before the step's first Drive change. A doc sync
    stamps its start time, so one stamped after `changed_at` saw every change.
    A sync that applies a change before the step ends also stamps the doc after
    `changed_at`. The beat may start a sync right after indexing; the sync
    request then finds it open and starts no other, so waiting for a sync newer
    than the request would wait for the next beat."""
    CCPairManager.sync(cc_pair=env.cc_pair, user_performing_action=env.admin_user)
    CCPairManager.wait_for_sync(
        cc_pair=env.cc_pair,
        after=changed_at,
        user_performing_action=env.admin_user,
        doc_ids=changed_doc_ids,
        should_wait_for_index_sync=bool(changed_doc_ids),
    )


def _onyx_doc_id(env: DriveSyncEnv, file_id: str) -> str:
    with get_session_with_current_tenant() as db_session:
        doc_ids = get_all_connector_documents(env.cc_pair, db_session)
    matches = [doc_id for doc_id in doc_ids if file_id in doc_id]
    assert len(matches) == 1, f"expected one indexed doc for {file_id}: {doc_ids}"
    return matches[0]


def _readable(user: DATestUser, doc_ids: list[str]) -> set[str]:
    with get_session_with_current_tenant() as db_session:
        return set(
            get_user_document_access_via_acl(
                test_user=user, document_ids=doc_ids, db_session=db_session
            )
        )


def test_google_permission_sync(drive_sync_env: DriveSyncEnv) -> None:
    env = drive_sync_env
    drive_service = env.drive_service

    # Baseline: only the drive's members (the admin) can read a new file.
    changed_at = datetime.now(timezone.utc)
    file_1 = GoogleDriveManager.create_empty_doc(drive_service, env.drive_id)
    GoogleDriveManager.append_text_to_doc(
        drive_service, file_1, "The secret number is 12345"
    )
    _index(env)
    doc_1 = _onyx_doc_id(env, file_1)
    _sync(env, changed_at, [doc_1])

    assert _readable(env.admin_user, [doc_1]) == {doc_1}
    assert _readable(env.test_user_1, [doc_1]) == set()
    assert _readable(env.test_user_2, [doc_1]) == set()

    # A file-level grant reaches only that file.
    changed_at = datetime.now(timezone.utc)
    GoogleDriveManager.update_file_permissions(
        drive_service=drive_service, file_id=file_1, email=TEST_USER_1_EMAIL
    )
    file_2 = GoogleDriveManager.create_empty_doc(drive_service, env.drive_id)
    GoogleDriveManager.append_text_to_doc(
        drive_service, file_2, "The secret number is 67890"
    )
    _index(env)
    doc_2 = _onyx_doc_id(env, file_2)
    _sync(env, changed_at, [doc_1, doc_2])
    both = [doc_1, doc_2]

    assert _readable(env.admin_user, both) == {doc_1, doc_2}
    assert _readable(env.test_user_1, both) == {doc_1}
    assert _readable(env.test_user_2, both) == set()

    # Removing the grant removes access.
    changed_at = datetime.now(timezone.utc)
    GoogleDriveManager.remove_file_permissions(
        drive_service=drive_service, file_id=file_1, email=TEST_USER_1_EMAIL
    )
    _sync(env, changed_at, [doc_1])

    assert _readable(env.test_user_1, both) == set()

    # Drive membership is a group: group sync grants every file in the drive.
    GoogleDriveManager.update_file_permissions(
        drive_service=drive_service, file_id=env.drive_id, email=TEST_USER_1_EMAIL
    )
    # A group sync stamps its end time, so the first one stamped after the change
    # may have read the members before it. Group syncs of a pair do not overlap,
    # so any group sync that ends after the first one started after the change.
    _sync(env, datetime.now(timezone.utc))
    _sync(env, datetime.now(timezone.utc))

    assert _readable(env.test_user_1, both) == {doc_1, doc_2}
    assert _readable(env.test_user_2, both) == set()
