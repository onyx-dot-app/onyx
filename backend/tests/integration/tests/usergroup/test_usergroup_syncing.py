from danswer.server.documents.models import DocumentSource
from tests.integration.common_utils.constants import NUM_DOCS
from tests.integration.common_utils.managers.api_key import APIKeyManager
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.document import DocumentManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import TestAPIKey
from tests.integration.common_utils.test_models import TestUser
from tests.integration.common_utils.test_models import TestUserGroup
from tests.integration.common_utils.vespa import TestVespaClient


def test_removing_connector(reset: None, vespa_client: TestVespaClient) -> None:
    # Creating an admin user (first user created is automatically an admin)
    admin_user: TestUser = UserManager.create(name="admin_user")

    # add api key to user
    api_key: TestAPIKey = APIKeyManager.create(
        user_performing_action=admin_user,
    )

    # create connectors
    cc_pair_1 = CCPairManager.create_from_scratch(
        source=DocumentSource.INGESTION_API,
        user_performing_action=admin_user,
    )
    cc_pair_2 = CCPairManager.create_from_scratch(
        source=DocumentSource.INGESTION_API,
        user_performing_action=admin_user,
    )

    # seed documents
    cc_pair_1 = DocumentManager.seed_and_attach_docs(
        cc_pair=cc_pair_1,
        num_docs=NUM_DOCS,
        api_key=api_key,
    )

    cc_pair_2 = DocumentManager.seed_and_attach_docs(
        cc_pair=cc_pair_2,
        num_docs=NUM_DOCS,
        api_key=api_key,
    )

    # Create user group
    user_group_1: TestUserGroup = UserGroupManager.create(
        cc_pair_ids=[cc_pair_1.id, cc_pair_2.id],
        user_performing_action=admin_user,
    )

    UserGroupManager.wait_for_sync(
        user_groups_to_check=[user_group_1], user_performing_action=admin_user
    )

    UserGroupManager.verify(
        user_group=user_group_1,
        user_performing_action=admin_user,
    )

    # make sure cc_pair_1 docs are user_group_1 only
    DocumentManager.verify(
        vespa_client=vespa_client,
        cc_pair=cc_pair_1,
        group_names=[user_group_1.name],
        doc_creating_user=admin_user,
    )

    # make sure cc_pair_2 docs are user_group_1 only
    DocumentManager.verify(
        vespa_client=vespa_client,
        cc_pair=cc_pair_2,
        group_names=[user_group_1.name],
        doc_creating_user=admin_user,
    )

    # remove cc_pair_2 from document set
    user_group_1.cc_pair_ids = [cc_pair_1.id]
    UserGroupManager.edit(
        user_group_1,
        user_performing_action=admin_user,
    )

    UserGroupManager.wait_for_sync(
        user_performing_action=admin_user,
    )

    # make sure cc_pair_1 docs are user_group_1 only
    DocumentManager.verify(
        vespa_client=vespa_client,
        cc_pair=cc_pair_1,
        group_names=[user_group_1.name],
        doc_creating_user=admin_user,
    )

    # make sure cc_pair_2 docs have no user group
    DocumentManager.verify(
        vespa_client=vespa_client,
        cc_pair=cc_pair_2,
        group_names=[],
        doc_creating_user=admin_user,
    )
