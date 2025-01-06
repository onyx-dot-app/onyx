import requests

from onyx.document_index.vespa_constants import DOCUMENT_ID_ENDPOINT


class vespa_fixture:
    def __init__(self, index_name: str):
        self.index_name = index_name
        self.vespa_document_url = DOCUMENT_ID_ENDPOINT.format(index_name=index_name)

    def get_documents_by_id(
        self, document_ids: list[str], wanted_doc_count: int = 1_000
    ) -> dict:
        selection = " or ".join(
            f"{self.index_name}.document_id=='{document_id}'"
            for document_id in document_ids
        )
        params = {
            "selection": selection,
            "wantedDocumentCount": wanted_doc_count,
        }
        response = requests.get(
            self.vespa_document_url,
            params=params,  # type: ignore
        )
        response.raise_for_status()
        return response.json()
