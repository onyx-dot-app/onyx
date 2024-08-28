from typing import cast

import requests

from danswer.server.features.document_set.models import DocumentSet
from danswer.server.features.document_set.models import DocumentSetCreationRequest
from tests.integration.common_utils.constants import API_SERVER_URL


def create_document_set(doc_set_creation_request: DocumentSetCreationRequest) -> int:
    response = requests.post(
        f"{API_SERVER_URL}/manage/admin/document-set",
        json=doc_set_creation_request.dict(),
    )
    response.raise_for_status()
    return cast(int, response.json())


def fetch_document_sets() -> list[DocumentSet]:
    response = requests.get(f"{API_SERVER_URL}/manage/admin/document-set")
    response.raise_for_status()

    document_sets = [
        DocumentSet.parse_obj(doc_set_data) for doc_set_data in response.json()
    ]
    return document_sets
