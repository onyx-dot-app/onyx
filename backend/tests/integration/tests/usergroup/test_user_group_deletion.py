"""
This tests the deletion of a user group with the following foreign key constraints:
- connector_credential_pair
- user
- credential
- llm_provider
- document_set
- token_rate_limit (Not Implemented)
- persona
"""

import os

import pytest

from onyx.server.documents.models import DocumentSource
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.credential import CredentialManager
from tests.integration.common_utils.managers.document_set import DocumentSetManager
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.managers.persona import PersonaManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import DATestCredential
from tests.integration.common_utils.test_models import DATestDocumentSet
from tests.integration.common_utils.test_models import DATestLLMProvider
from tests.integration.common_utils.test_models import DATestPersona
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.common_utils.test_models import DATestUserGroup
from tests.integration.common_utils.vespa import vespa_fixture


@pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="User group tests are enterprise only",
)
def test_user_group_deletion(reset: None, vespa_client: vespa_fixture) -> None:
    # Creating an admin user (first user created is automatically an admin)
    admin_user: DATestUser = UserManager.create(name="admin_user")

    # create connectors
    cc_pair = CCPairManager.create_from_scratch(
        source=DocumentSource.INGESTION_API,
        user_performing_action=admin_user,
    )

    # Create user group with a cc_pair and a user
    user_group: DATestUserGroup = UserGroupManager.create(
        user_ids=[admin_user.id],
        cc_pair_ids=[cc_pair.id],
        user_performing_action=admin_user,
    )
    cc_pair.groups = [user_group.id]

    UserGroupManager.wait_for_sync(
        user_groups_to_check=[user_group], user_performing_action=admin_user
    )
    UserGroupManager.verify(
        user_group=user_group,
        user_performing_action=admin_user,
    )
    CCPairManager.verify(
        cc_pair=cc_pair,
        user_performing_action=admin_user,
    )

    # Create other objects that are related to the user group
    credential: DATestCredential = CredentialManager.create(
        groups=[user_group.id],
        user_performing_action=admin_user,
    )
    document_set: DATestDocumentSet = DocumentSetManager.create(
        cc_pair_ids=[cc_pair.id],
        groups=[user_group.id],
        user_performing_action=admin_user,
    )
    llm_provider: DATestLLMProvider = LLMProviderManager.create(
        groups=[user_group.id],
        user_performing_action=admin_user,
    )
    persona: DATestPersona = PersonaManager.create(
        groups=[user_group.id],
        user_performing_action=admin_user,
    )

    UserGroupManager.wait_for_sync(
        user_groups_to_check=[user_group], user_performing_action=admin_user
    )
    UserGroupManager.verify(
        user_group=user_group,
        user_performing_action=admin_user,
    )

    # Delete the user group
    UserGroupManager.delete(
        user_group=user_group,
        user_performing_action=admin_user,
    )

    UserGroupManager.wait_for_deletion_completion(
        user_groups_to_check=[user_group], user_performing_action=admin_user
    )

    # Set our expected local representations to empty
    credential.groups = []
    document_set.groups = []
    llm_provider.groups = []
    persona.groups = []

    # Verify that the local representations were updated
    CredentialManager.verify(
        credential=credential,
        user_performing_action=admin_user,
    )

    DocumentSetManager.verify(
        document_set=document_set,
        user_performing_action=admin_user,
    )

    LLMProviderManager.verify(
        llm_provider=llm_provider,
        user_performing_action=admin_user,
    )

    PersonaManager.verify(
        persona=persona,
        user_performing_action=admin_user,
    )
