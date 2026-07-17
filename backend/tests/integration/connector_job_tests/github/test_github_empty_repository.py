from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import AccessType
from onyx.db.enums import IndexingStatus
from tests.integration.common_utils.document_acl import get_all_connector_documents
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.index_attempt import IndexAttemptManager
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.test_models import DATestUser

EMPTY_GITHUB_REPOSITORY_OWNER = "onyx-dot-app"
EMPTY_GITHUB_REPOSITORY_NAME = "github-connector-empty-repo-test"


def test_github_empty_repository_file_sync_completes(
    github_access_token: str,
    new_admin_user: DATestUser,
) -> None:
    """An empty GitHub repository must complete file indexing without errors.

    The dedicated repository must remain uninitialized: no README, license,
    .gitignore, or other initial commit.
    """
    LLMProviderManager.create(user_performing_action=new_admin_user)
    cc_pair = CCPairManager.create_from_scratch(
        name="github-empty-repository",
        source=DocumentSource.GITHUB,
        input_type=InputType.POLL,
        connector_specific_config={
            "repo_owner": EMPTY_GITHUB_REPOSITORY_OWNER,
            "repositories": EMPTY_GITHUB_REPOSITORY_NAME,
            "include_prs": False,
            "include_issues": False,
            "include_files": True,
        },
        credential_json={"github_access_token": github_access_token},
        access_type=AccessType.PUBLIC,
        user_performing_action=new_admin_user,
    )

    index_attempt = IndexAttemptManager.wait_for_index_attempt_start(
        cc_pair_id=cc_pair.id,
        user_performing_action=new_admin_user,
    )
    IndexAttemptManager.wait_for_index_attempt_completion(
        index_attempt_id=index_attempt.id,
        cc_pair_id=cc_pair.id,
        user_performing_action=new_admin_user,
        timeout=900,
    )
    completed_attempt = IndexAttemptManager.get_index_attempt_by_id(
        index_attempt_id=index_attempt.id,
        cc_pair_id=cc_pair.id,
        user_performing_action=new_admin_user,
    )

    assert completed_attempt.status == IndexingStatus.SUCCESS
    assert completed_attempt.error_count == 0
    assert completed_attempt.new_docs_indexed == 0
    assert completed_attempt.total_docs_indexed == 0

    with get_session_with_current_tenant() as db_session:
        assert get_all_connector_documents(cc_pair, db_session) == []
