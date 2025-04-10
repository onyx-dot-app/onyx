import os

import pytest

from onyx.server.documents.models import DocumentSource
from tests.integration.common_utils.constants import NUM_DOCS
from tests.integration.common_utils.managers.api_key import APIKeyManager
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.document import DocumentManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import DATestAPIKey
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.common_utils.test_models import DATestUserGroup
from tests.integration.common_utils.vespa import vespa_fixture


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="User group tests are enterprise only",
)
def test_removing_connector(reset: None, vespa_client: vespa_fixture) -> None:
    # Creating an admin user (first user created is automatically an admin)
    admin_user: DATestUser = UserManager.create(name="admin_user")

    # create api key
    api_key: DATestAPIKey = APIKeyManager.create(
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
    cc_pair_1.documents = DocumentManager.seed_dummy_docs(
        cc_pair=cc_pair_1,
        num_docs=NUM_DOCS,
        api_key=api_key,
    )

    cc_pair_2.documents = DocumentManager.seed_dummy_docs(
        cc_pair=cc_pair_2,
        num_docs=NUM_DOCS,
        api_key=api_key,
    )

    # Create user group
    user_group_1: DATestUserGroup = UserGroupManager.create(
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
