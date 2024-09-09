from danswer.server.documents.models import DocumentSource
from tests.integration.common_utils.constants import NUM_DOCS
from tests.integration.common_utils.managers.api_key import APIKeyManager
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.document import DocumentManager
from tests.integration.common_utils.managers.document_set import DocumentSetManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import TestAPIKey
from tests.integration.common_utils.test_models import TestUser
from tests.integration.common_utils.vespa import TestVespaClient


def test_multiple_document_sets_syncing_same_connnector(
    reset: None, vespa_client: TestVespaClient
) -> None:
    # Creating an admin user (first user created is automatically an admin)
    admin_user: TestUser = UserManager.create(name="admin_user")

    # add api key to user
    api_key: TestAPIKey = APIKeyManager.create(
        user_performing_action=admin_user,
    )

    # create connector
    cc_pair_1 = CCPairManager.create_from_scratch(
        source=DocumentSource.INGESTION_API,
        user_performing_action=admin_user,
    )

    # seed documents
    cc_pair_1 = DocumentManager.seed_and_attach_docs(
        cc_pair=cc_pair_1,
        num_docs=NUM_DOCS,
        api_key=api_key,
    )

    # Create document sets
    doc_set_1 = DocumentSetManager.create(
        cc_pair_ids=[cc_pair_1.id],
        user_performing_action=admin_user,
    )
    doc_set_2 = DocumentSetManager.create(
        cc_pair_ids=[cc_pair_1.id],
        user_performing_action=admin_user,
    )

    DocumentSetManager.wait_for_sync(
        user_performing_action=admin_user,
    )

    DocumentSetManager.verify(
        document_set=doc_set_1,
        user_performing_action=admin_user,
    )
    DocumentSetManager.verify(
        document_set=doc_set_2,
        user_performing_action=admin_user,
    )

    # make sure documents are as expected
    DocumentManager.verify(
        vespa_client=vespa_client,
        cc_pair=cc_pair_1,
        doc_set_names=[doc_set_1.name, doc_set_2.name],
        doc_creating_user=admin_user,
    )
