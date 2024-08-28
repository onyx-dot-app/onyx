import time

from danswer.server.features.document_set.models import DocumentSetCreationRequest
from tests.integration.common_utils.seed_documents import TestDocumentClient
from tests.integration.common_utils.vespa import TestVespaClient
from tests.integration.tests.document_set.utils import create_document_set
from tests.integration.tests.document_set.utils import fetch_document_sets


def test_multiple_document_sets_syncing_same_connnector(
    reset: None, vespa_client: TestVespaClient
) -> None:
    # Seed documents
    seed_result = TestDocumentClient.seed_documents(num_docs=5)
    cc_pair_id = seed_result.cc_pair_id

    # Create first document set
    doc_set_1_id = create_document_set(
        DocumentSetCreationRequest(
            name="Test Document Set 1",
            description="First test document set",
            cc_pair_ids=[cc_pair_id],
            is_public=True,
            users=[],
            groups=[],
        )
    )

    doc_set_2_id = create_document_set(
        DocumentSetCreationRequest(
            name="Test Document Set 2",
            description="Second test document set",
            cc_pair_ids=[cc_pair_id],
            is_public=True,
            users=[],
            groups=[],
        )
    )

    # wait for syncing to be complete
    max_delay = 45
    start = time.time()
    while True:
        doc_sets = fetch_document_sets()
        doc_set_1 = next(
            (doc_set for doc_set in doc_sets if doc_set.id == doc_set_1_id), None
        )
        doc_set_2 = next(
            (doc_set for doc_set in doc_sets if doc_set.id == doc_set_2_id), None
        )

        if not doc_set_1 or not doc_set_2:
            raise RuntimeError("Document set not found")

        if doc_set_1.is_up_to_date and doc_set_2.is_up_to_date:
            assert [ccp.id for ccp in doc_set_1.cc_pair_descriptors] == [
                ccp.id for ccp in doc_set_2.cc_pair_descriptors
            ]
            break

        if time.time() - start > max_delay:
            raise TimeoutError("Document sets were not synced within the max delay")

        time.sleep(2)

    # get names so we can compare to what is in vespa
    doc_sets = fetch_document_sets()
    doc_set_names = {doc_set.name for doc_set in doc_sets}

    # make sure documents are as expected
    seeded_document_ids = [doc.id for doc in seed_result.documents]

    result = vespa_client.get_documents_by_id([doc.id for doc in seed_result.documents])
    documents = result["documents"]
    assert len(documents) == len(seed_result.documents)
    assert all(doc["fields"]["document_id"] in seeded_document_ids for doc in documents)
    assert all(
        set(doc["fields"]["document_sets"].keys()) == doc_set_names for doc in documents
    )
