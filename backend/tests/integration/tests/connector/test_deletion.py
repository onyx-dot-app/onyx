import time

from danswer.db.enums import ConnectorCredentialPairStatus
from danswer.server.features.document_set.models import DocumentSetCreationRequest
from tests.integration.common_utils.connectors import ConnectorClient
from tests.integration.common_utils.constants import MAX_DELAY
from tests.integration.common_utils.document_sets import DocumentSetClient
from tests.integration.common_utils.seed_documents import TestDocumentClient
from tests.integration.common_utils.user_groups import UserGroupClient
from tests.integration.common_utils.user_groups import UserGroupCreate
from tests.integration.common_utils.vespa import TestVespaClient


def test_connector_deletion(reset: None, vespa_client: TestVespaClient) -> None:
    # create connectors
    c1_details = ConnectorClient.create_connector(name_prefix="tc1")
    c2_details = ConnectorClient.create_connector(name_prefix="tc2")
    c1_seed_res = TestDocumentClient.seed_documents(
        num_docs=5, cc_pair_id=c1_details.cc_pair_id
    )
    c2_seed_res = TestDocumentClient.seed_documents(
        num_docs=5, cc_pair_id=c2_details.cc_pair_id
    )

    # create document sets
    doc_set_1_id = DocumentSetClient.create_document_set(
        DocumentSetCreationRequest(
            name="Test Document Set 1",
            description="Intially connector to be deleted, should be empty after test",
            cc_pair_ids=[c1_details.cc_pair_id],
            is_public=True,
            users=[],
            groups=[],
        )
    )

    doc_set_2_id = DocumentSetClient.create_document_set(
        DocumentSetCreationRequest(
            name="Test Document Set 2",
            description="Intially both connectors, should contain undeleted connector after test",
            cc_pair_ids=[c1_details.cc_pair_id, c2_details.cc_pair_id],
            is_public=True,
            users=[],
            groups=[],
        )
    )

    # wait for document sets to be synced
    start = time.time()
    while True:
        doc_sets = DocumentSetClient.fetch_document_sets()
        doc_set_1 = next(
            (doc_set for doc_set in doc_sets if doc_set.id == doc_set_1_id), None
        )
        doc_set_2 = next(
            (doc_set for doc_set in doc_sets if doc_set.id == doc_set_2_id), None
        )

        if not doc_set_1 or not doc_set_2:
            raise RuntimeError("Document set not found")

        if doc_set_1.is_up_to_date and doc_set_2.is_up_to_date:
            break

        if time.time() - start > MAX_DELAY:
            raise TimeoutError("Document sets were not synced within the max delay")

        time.sleep(2)

    print("Document sets created and synced")

    # if so, create ACLs
    user_group_1 = UserGroupClient.create_user_group(
        UserGroupCreate(
            name="Test User Group 1", user_ids=[], cc_pair_ids=[c1_details.cc_pair_id]
        )
    )
    user_group_2 = UserGroupClient.create_user_group(
        UserGroupCreate(
            name="Test User Group 2",
            user_ids=[],
            cc_pair_ids=[c1_details.cc_pair_id, c2_details.cc_pair_id],
        )
    )

    # wait for user groups to be available
    start = time.time()
    while True:
        user_groups = {ug.id: ug for ug in UserGroupClient.fetch_user_groups()}

        if not (
            user_group_1 in user_groups.keys() and user_group_2 in user_groups.keys()
        ):
            raise RuntimeError("User groups not found")

        if (
            user_groups[user_group_1].is_up_to_date
            and user_groups[user_group_2].is_up_to_date
        ):
            break

        if time.time() - start > MAX_DELAY:
            raise TimeoutError("User groups were not synced within the max delay")

        time.sleep(2)

    print("User groups created and synced")

    # delete connector 1
    ConnectorClient.update_connector_status(
        cc_pair_id=c1_details.cc_pair_id, status=ConnectorCredentialPairStatus.PAUSED
    )
    ConnectorClient.delete_connector(
        connector_id=c1_details.connector_id, credential_id=c1_details.credential_id
    )

    start = time.time()
    while True:
        connectors = ConnectorClient.get_connectors()

        if c1_details.connector_id not in [c["id"] for c in connectors]:
            break

        if time.time() - start > MAX_DELAY:
            raise TimeoutError("Connector 1 was not deleted within the max delay")

        time.sleep(2)

    print("Connector 1 deleted")

    # validate vespa documents
    c1_vespa_docs = vespa_client.get_documents_by_id(
        [doc.id for doc in c1_seed_res.documents]
    )["documents"]
    c2_vespa_docs = vespa_client.get_documents_by_id(
        [doc.id for doc in c2_seed_res.documents]
    )["documents"]

    assert len(c1_vespa_docs) == 0
    assert len(c2_vespa_docs) == 5

    for doc in c2_vespa_docs:
        assert doc["fields"]["access_control_list"] == {
            "PUBLIC": 1,
            "group:Test User Group 2": 1,
        }
        assert doc["fields"]["document_sets"] == {"Test Document Set 2": 1}

    # check that only connector 1 is deleted
    # TODO: check for the CC pair rather than the connector once the refactor is done
    all_connectors = ConnectorClient.get_connectors()
    assert len(all_connectors) == 1
    assert all_connectors[0]["id"] == c2_details.connector_id

    # validate document sets
    all_doc_sets = DocumentSetClient.fetch_document_sets()
    assert len(all_doc_sets) == 2

    doc_set_1_found = False
    doc_set_2_found = False
    for doc_set in all_doc_sets:
        if doc_set.id == doc_set_1_id:
            doc_set_1_found = True
            assert doc_set.cc_pair_descriptors == []

        if doc_set.id == doc_set_2_id:
            doc_set_2_found = True
            assert len(doc_set.cc_pair_descriptors) == 1
            assert doc_set.cc_pair_descriptors[0].id == c2_details.cc_pair_id

    assert doc_set_1_found
    assert doc_set_2_found

    # validate user groups
    all_user_groups = UserGroupClient.fetch_user_groups()
    assert len(all_user_groups) == 2

    user_group_1_found = False
    user_group_2_found = False
    for user_group in all_user_groups:
        if user_group.id == user_group_1:
            user_group_1_found = True
            assert user_group.cc_pairs == []
        if user_group.id == user_group_2:
            user_group_2_found = True
            assert len(user_group.cc_pairs) == 1
            assert user_group.cc_pairs[0].id == c2_details.cc_pair_id

    assert user_group_1_found
    assert user_group_2_found
