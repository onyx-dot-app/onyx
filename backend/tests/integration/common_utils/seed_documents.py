import uuid

import requests
from pydantic import BaseModel

from danswer.configs.constants import DocumentSource
from tests.integration.common_utils.connectors import ConnectorClient
from tests.integration.common_utils.constants import API_SERVER_URL


class SimpleTestDocument(BaseModel):
    id: str
    content: str


class SeedDocumentResponse(BaseModel):
    cc_pair_id: int
    documents: list[SimpleTestDocument]


class TestDocumentClient:
    @staticmethod
    def seed_documents(
        num_docs: int = 5, cc_pair_id: int | None = None
    ) -> SeedDocumentResponse:
        if not cc_pair_id:
            connector_details = ConnectorClient.create_connector()
            cc_pair_id = connector_details.cc_pair_id

        # Create and ingest some documents
        documents: list[dict] = []
        for _ in range(num_docs):
            document_id = f"test-doc-{uuid.uuid4()}"
            document = {
                "document": {
                    "id": document_id,
                    "sections": [
                        {
                            "text": f"This is test document {document_id}",
                            "link": f"{document_id}",
                        }
                    ],
                    "source": DocumentSource.NOT_APPLICABLE,
                    # just for testing metadata
                    "metadata": {"document_id": document_id},
                    "semantic_identifier": f"Test Document {document_id}",
                    "from_ingestion_api": True,
                },
                "cc_pair_id": cc_pair_id,
            }
            documents.append(document)
            response = requests.post(
                f"{API_SERVER_URL}/danswer-api/ingestion",
                json=document,
            )
            response.raise_for_status()

        print("Seeding completed successfully.")
        return SeedDocumentResponse(
            cc_pair_id=cc_pair_id,
            documents=[
                SimpleTestDocument(
                    id=document["document"]["id"],
                    content=document["document"]["sections"][0]["text"],
                )
                for document in documents
            ],
        )


if __name__ == "__main__":
    seed_documents_resp = TestDocumentClient.seed_documents()
