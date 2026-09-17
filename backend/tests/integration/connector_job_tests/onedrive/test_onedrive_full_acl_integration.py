"""End-to-end ACL and mutation coverage for the fixed OneDrive corpus."""

from datetime import datetime, timezone

import pytest

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from tests.integration.common_utils.document_acl import (
    get_all_connector_documents,
    get_documents_by_permission_type,
    get_user_document_access_via_acl,
)
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.vespa import vespa_fixture
from tests.integration.connector_job_tests.onedrive.conftest import (
    JOB_TIMEOUT_SECONDS,
    OneDriveIntegrationEnvironment,
)
from tests.utils.onedrive_fixture import (
    ANONYMOUS_LINK_SKIP_REASON,
    AnonymousLinkOutcome,
    FilePath,
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

INDEXED_BASELINE_PATHS = {
    path
    for path in FilePath
    if path
    not in {
        FilePath.MOVE_DESTINATION,
        FilePath.EXCLUDED,
        FilePath.OVER_SIZE,
        FilePath.UNSUPPORTED,
    }
}


def _connector_document_ids(
    environment: OneDriveIntegrationEnvironment,
) -> set[str]:
    with get_session_with_current_tenant() as db_session:
        return set(
            get_all_connector_documents(environment.onedrive_cc_pair, db_session)
        )


def _accessible_ids(
    environment: OneDriveIntegrationEnvironment,
) -> dict[str, set[str]]:
    document_ids = list(_connector_document_ids(environment))
    users = {
        "owner": environment.owner_user,
        "primary": environment.primary_user,
        "second_owner": environment.second_owner_user,
        "alternate": environment.alternate_user,
        "outsider": environment.outsider_user,
    }
    with get_session_with_current_tenant() as db_session:
        return {
            name: set(
                get_user_document_access_via_acl(
                    test_user=user,
                    document_ids=document_ids,
                    db_session=db_session,
                )
            )
            for name, user in users.items()
        }


def _assert_baseline_acl(environment: OneDriveIntegrationEnvironment) -> None:
    state = environment.state
    document_ids = _connector_document_ids(environment)
    expected_ids = {state.files[path].id for path in INDEXED_BASELINE_PATHS} | {
        state.second_drive_duplicate.id
    }
    assert expected_ids.issubset(document_ids)
    assert state.files[FilePath.EXCLUDED].id not in document_ids
    assert state.files[FilePath.OVER_SIZE].id not in document_ids
    assert state.files[FilePath.UNSUPPORTED].id not in document_ids
    assert state.files[FilePath.IDENTITY].id != state.second_drive_duplicate.id

    access = _accessible_ids(environment)
    public_ids = {state.files[FilePath.ORGANIZATION_LINK].id}
    if state.anonymous_link_outcome is AnonymousLinkOutcome.CREATED:
        public_ids.add(state.files[FilePath.ANONYMOUS_LINK].id)
    with get_session_with_current_tenant() as db_session:
        indexed_public_ids = set(
            get_documents_by_permission_type(list(document_ids), db_session)
        )
    assert indexed_public_ids & expected_ids == public_ids

    primary_ids = {
        state.files[path].id
        for path in (
            FilePath.DIRECT,
            FilePath.INHERITED,
            FilePath.INHERITED_NESTED,
            FilePath.VISIBLE_GROUP,
            FilePath.MOVE,
            FilePath.REMOVE_SHARE,
        )
    } | public_ids
    alternate_ids = {
        state.files[path].id
        for path in (
            FilePath.RESTRICTED,
            FilePath.HIDDEN_GROUP,
            FilePath.RESTORE_INHERITANCE,
        )
    } | public_ids
    owner_ids = {state.files[path].id for path in INDEXED_BASELINE_PATHS}
    second_owner_ids = public_ids | {state.second_drive_duplicate.id}
    second_owner_email = state.second_owner.user_principal_name.lower()
    if second_owner_email == state.owner.user_principal_name.lower():
        owner_ids.add(state.second_drive_duplicate.id)
        second_owner_ids |= owner_ids
    if second_owner_email == state.primary_user.user_principal_name.lower():
        primary_ids.add(state.second_drive_duplicate.id)
        second_owner_ids |= primary_ids
    if second_owner_email == state.alternate_user.user_principal_name.lower():
        alternate_ids.add(state.second_drive_duplicate.id)
        second_owner_ids |= alternate_ids

    assert access["owner"] & expected_ids == owner_ids
    assert access["primary"] & expected_ids == primary_ids
    assert access["second_owner"] & expected_ids == second_owner_ids
    assert access["alternate"] & expected_ids == alternate_ids
    assert access["outsider"] & expected_ids == public_ids


def _assert_multi_source_overlap(
    environment: OneDriveIntegrationEnvironment,
) -> None:
    overlap_id = environment.state.files[FilePath.IDENTITY].id
    with get_session_with_current_tenant() as db_session:
        onedrive_ids = set(
            get_all_connector_documents(environment.onedrive_cc_pair, db_session)
        )
        sharepoint_ids = set(
            get_all_connector_documents(environment.sharepoint_cc_pair, db_session)
        )
    assert overlap_id in onedrive_ids
    assert overlap_id in sharepoint_ids


def _run_mutation_jobs(environment: OneDriveIntegrationEnvironment) -> None:
    started_at = datetime.now(timezone.utc)
    environment.provisioner.mutate()
    environment.provisioner.wait_for_mutations()
    CCPairManager.run_once(
        environment.onedrive_cc_pair,
        from_beginning=False,
        user_performing_action=environment.admin_user,
    )
    CCPairManager.wait_for_indexing_completion(
        cc_pair=environment.onedrive_cc_pair,
        after=started_at,
        user_performing_action=environment.admin_user,
        timeout=JOB_TIMEOUT_SECONDS,
    )
    CCPairManager.sync(
        cc_pair=environment.onedrive_cc_pair,
        user_performing_action=environment.admin_user,
    )
    CCPairManager.wait_for_sync(
        cc_pair=environment.onedrive_cc_pair,
        after=started_at,
        user_performing_action=environment.admin_user,
        timeout=JOB_TIMEOUT_SECONDS,
        number_of_updated_docs=3,
    )


def _assert_mutated_acl(environment: OneDriveIntegrationEnvironment) -> None:
    state = environment.state
    access = _accessible_ids(environment)
    moved_id = state.files[FilePath.MOVE].id
    removed_share_id = state.files[FilePath.REMOVE_SHARE].id
    restored_id = state.files[FilePath.RESTORE_INHERITANCE].id

    assert moved_id in access["alternate"]
    assert moved_id not in access["primary"]
    assert removed_share_id in access["owner"]
    assert removed_share_id not in access["primary"]
    assert restored_id in access["primary"]
    assert restored_id not in access["alternate"]


def _assert_indexed_mutated_acl(
    environment: OneDriveIntegrationEnvironment,
    document_index: vespa_fixture,
) -> None:
    state = environment.state
    expected_acl_by_id = {
        state.files[FilePath.MOVE].id: {
            f"user_email:{state.owner.user_principal_name.lower()}",
            f"user_email:{state.alternate_user.user_principal_name.lower()}",
        },
        state.files[FilePath.REMOVE_SHARE].id: {
            f"user_email:{state.owner.user_principal_name.lower()}",
        },
        state.files[FilePath.RESTORE_INHERITANCE].id: {
            f"user_email:{state.owner.user_principal_name.lower()}",
            f"user_email:{state.primary_user.user_principal_name.lower()}",
        },
    }
    chunks = document_index.get_documents_by_id(
        list(expected_acl_by_id), wanted_doc_count=100
    )["documents"]
    assert chunks
    assert {chunk["fields"]["document_id"] for chunk in chunks} == set(
        expected_acl_by_id
    )
    for chunk in chunks:
        fields = chunk["fields"]
        document_id = fields["document_id"]
        assert set(fields["access_control_list"]) == expected_acl_by_id[document_id]


def _assert_content_mutation(
    environment: OneDriveIntegrationEnvironment,
    document_index: vespa_fixture,
) -> None:
    update_id = environment.state.files[FilePath.UPDATE].id
    chunks = document_index.get_documents_by_id([update_id])["documents"]
    assert chunks
    assert any("(mutated)" in chunk["fields"]["content"] for chunk in chunks)


def _prune_deleted_item(environment: OneDriveIntegrationEnvironment) -> None:
    started_at = datetime.now(timezone.utc)
    CCPairManager.prune(
        environment.onedrive_cc_pair,
        user_performing_action=environment.admin_user,
    )
    CCPairManager.wait_for_prune(
        environment.onedrive_cc_pair,
        after=started_at,
        user_performing_action=environment.admin_user,
        timeout=JOB_TIMEOUT_SECONDS,
    )
    assert environment.state.files[FilePath.DELETE].id not in _connector_document_ids(
        environment
    )


def _delete_onedrive_source_and_assert_sharepoint_overlap(
    environment: OneDriveIntegrationEnvironment,
) -> None:
    overlap_id = environment.state.files[FilePath.IDENTITY].id
    CCPairManager.delete(
        environment.onedrive_cc_pair,
        user_performing_action=environment.admin_user,
    )
    CCPairManager.wait_for_deletion_completion(
        user_performing_action=environment.admin_user,
        cc_pair_id=environment.onedrive_cc_pair.id,
    )
    CCPairManager.verify(
        environment.onedrive_cc_pair,
        user_performing_action=environment.admin_user,
        verify_deleted=True,
    )
    with get_session_with_current_tenant() as db_session:
        sharepoint_ids = set(
            get_all_connector_documents(environment.sharepoint_cc_pair, db_session)
        )
    assert overlap_id in sharepoint_ids


def test_anonymous_link_acl_when_tenant_policy_allows_it(
    onedrive_integration_environment: OneDriveIntegrationEnvironment,
) -> None:
    state = onedrive_integration_environment.state
    if state.anonymous_link_outcome is AnonymousLinkOutcome.REJECTED_BY_TENANT_POLICY:
        pytest.skip(ANONYMOUS_LINK_SKIP_REASON)

    anonymous_id = state.files[FilePath.ANONYMOUS_LINK].id
    with get_session_with_current_tenant() as db_session:
        public_ids = set(
            get_documents_by_permission_type(
                list(_connector_document_ids(onedrive_integration_environment)),
                db_session,
            )
        )
    assert anonymous_id in public_ids
    assert anonymous_id in _accessible_ids(onedrive_integration_environment)["outsider"]


def test_onedrive_full_acl_mutations_and_multi_source_overlap(
    onedrive_integration_environment: OneDriveIntegrationEnvironment,
    vespa_client: vespa_fixture,
) -> None:
    _assert_baseline_acl(onedrive_integration_environment)
    _assert_multi_source_overlap(onedrive_integration_environment)
    _run_mutation_jobs(onedrive_integration_environment)
    _assert_mutated_acl(onedrive_integration_environment)
    _assert_indexed_mutated_acl(onedrive_integration_environment, vespa_client)
    _assert_content_mutation(onedrive_integration_environment, vespa_client)
    _prune_deleted_item(onedrive_integration_environment)
    _delete_onedrive_source_and_assert_sharepoint_overlap(
        onedrive_integration_environment
    )
