"""Indexes the `adls-perm-fixture` container with permission sync and checks
which fixture files each user can read after the doc and group syncs. The
fixture is read only; the daily permission test lists what each path's ACL
grants."""

import pytest

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from tests.integration.common_utils.document_acl import (
    get_all_connector_documents,
    get_user_document_access_via_acl,
)
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.connector_job_tests.azure_datalake.conftest import (
    ACCOUNT,
    CONTAINER,
    AzureDataLakePermissionEnvironment,
)
from tests.utils.secret_names import TestSecret

pytestmark = [
    pytest.mark.secrets(
        TestSecret.PERM_SYNC_SHAREPOINT_CLIENT_ID,
        TestSecret.PERM_SYNC_SHAREPOINT_DIRECTORY_ID,
        TestSecret.PERM_SYNC_SHAREPOINT_PRIVATE_KEY,
        TestSecret.PERM_SYNC_SHAREPOINT_CERTIFICATE_PASSWORD,
    ),
]

ID_PREFIX = f"azure_datalake:{ACCOUNT}:{CONTAINER}:"
ALL_PATHS = {
    "00-private/private.txt",
    "10-named-user/named-user.txt",
    "20-group-a/group-a.txt",
    "30-cross-group/cross-group.txt",
    "40-mask/masked.txt",
    "50-other/other-readable.txt",
    "55-other-no-traverse/other-blocked.txt",
    "60-other-minus-group/other-minus-group-a.txt",
    "70-no-traverse/no-traverse.txt",
    "80-default-only/default-only.txt",
}
# Through a named-user entry, ACL Group A, Groups A and B, and "other".
ACL_MEMBER_PATHS = {
    "10-named-user/named-user.txt",
    "20-group-a/group-a.txt",
    "30-cross-group/cross-group.txt",
    "50-other/other-readable.txt",
}


def _readable_paths(
    environment: AzureDataLakePermissionEnvironment, user: DATestUser
) -> set[str]:
    with get_session_with_current_tenant() as db_session:
        document_ids = get_all_connector_documents(environment.cc_pair, db_session)
        return {
            document_id.removeprefix(ID_PREFIX)
            for document_id in get_user_document_access_via_acl(
                test_user=user, document_ids=document_ids, db_session=db_session
            )
        }


def test_every_fixture_file_is_indexed(
    azure_datalake_permission_environment: AzureDataLakePermissionEnvironment,
) -> None:
    with get_session_with_current_tenant() as db_session:
        document_ids = get_all_connector_documents(
            azure_datalake_permission_environment.cc_pair, db_session
        )

    assert {document_id.removeprefix(ID_PREFIX) for document_id in document_ids} == (
        ALL_PATHS
    )


def test_each_user_reads_what_the_container_grants(
    azure_datalake_permission_environment: AzureDataLakePermissionEnvironment,
) -> None:
    environment = azure_datalake_permission_environment

    assert _readable_paths(environment, environment.owner_user) == ALL_PATHS
    # The container RBAC role skips the ACLs.
    assert _readable_paths(environment, environment.rbac_reader_user) == ALL_PATHS
    assert _readable_paths(environment, environment.acl_member_user) == (
        ACL_MEMBER_PATHS
    )
    assert _readable_paths(environment, environment.admin_user) == set()
