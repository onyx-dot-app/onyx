from typing import Any

from opensearchpy import OpenSearch

from onyx.document_index.opensearch.constants import CONTENT_KEYWORD_WEIGHT
from onyx.document_index.opensearch.constants import CONTENT_PHRASE_WEIGHT
from onyx.document_index.opensearch.constants import CONTENT_VECTOR_WEIGHT
from onyx.document_index.opensearch.constants import TITLE_KEYWORD_WEIGHT
from onyx.document_index.opensearch.constants import TITLE_VECTOR_WEIGHT
from onyx.document_index.opensearch.schema import DocumentChunk


SEARCH_PIPELINE_NAME = "normalization_pipeline"
NORMALIZATION_PIPELINE = {
    "description": "Normalization for keyword and vector scores",
    "phase_results_processors": [
        {
            "normalization-processor": {
                "normalization": {"technique": "min_max"},
                "combination": {
                    "technique": "arithmetic_mean",
                    "parameters": {
                        "weights": [
                            TITLE_VECTOR_WEIGHT,
                            CONTENT_VECTOR_WEIGHT,
                            TITLE_KEYWORD_WEIGHT,
                            CONTENT_KEYWORD_WEIGHT,
                            CONTENT_PHRASE_WEIGHT,
                        ]
                    },
                },
            }
        }
    ],
}

NORMALIZATION_PIPELINE_ZSCORE_NAME = "normalization_pipeline_zscore"
NORMALIZATION_PIPELINE_ZSCORE = {
    "description": "Normalization for keyword and vector scores",
    "phase_results_processors": [
        {
            "normalization-processor": {
                "normalization": {"technique": "z_score"},
                "combination": {
                    "technique": "arithmetic_mean",
                    "parameters": {
                        "weights": [
                            TITLE_VECTOR_WEIGHT,
                            CONTENT_VECTOR_WEIGHT,
                            TITLE_KEYWORD_WEIGHT,
                            CONTENT_KEYWORD_WEIGHT,
                            CONTENT_PHRASE_WEIGHT,
                        ]
                    },
                },
            }
        }
    ],
}


OPENSEARCH_CLIENT_TIMEOUT_S = 30
OPENSEARCH_CLIENT_MAX_RETRIES = 3


class OpenSearchClient:
    """
    TODO(andrei): What?
    """

    def __init__(
        self,
        index_name: str,
        host: str = "localhost",
        port: int = 9200,
        auth: tuple[str, str] = ("admin", "D@nswer_1ndex"),
        use_ssl: bool = True,
        verify_certs: bool = False,
    ):
        self._index_name = index_name
        self._client = OpenSearch(
            hosts=[{"host": host, "port": port}],
            http_auth=auth,
            use_ssl=use_ssl,
            verify_certs=verify_certs,
            ssl_show_warn=False,
            timeout=OPENSEARCH_CLIENT_TIMEOUT_S,
            max_retries=OPENSEARCH_CLIENT_MAX_RETRIES,
            retry_on_timeout=True,
        )

    def create_index(
        self, mappings: dict[str, Any], settings: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """
        TODO(andrei): Figure out what the return type is, OpenSearch's
        documentation is so bad.
        """
        body = {}
        if settings:
            body["settings"] = settings
        if mappings:
            body["mappings"] = mappings

        return self._client.indices.create(index=self._index_name, body=body)

    def delete_index(self) -> dict[str, Any]:
        """
        TODO(andrei): Figure out what the return type is, OpenSearch's
        documentation is so bad.
        """
        if self._client.indices.exists(index=self._index_name):
            return self._client.indices.delete(index=self._index_name)
        return {"acknowledged": False, "message": "Index does not exist"}

    def index_document(self, doc_id: str, document: DocumentChunk) -> dict[str, Any]:
        """
        TODO(andrei): Figure out what the return type is, OpenSearch's
        documentation is so bad.
        """
        return self._client.index(
            index=self._index_name, id=doc_id, body=document.to_dict()
        )

    # def bulk_index(self, documents: list[dict]) -> dict:
    #     """
    #     Bulk index documents using opensearchpy helpers for better performance.
    #     """
    #     # Convert to format expected by bulk helper
    #     actions = []
    #     for doc in documents:
    #         action = {
    #             "_index": self.index_name,
    #             "_id": doc.get("_id"),
    #             "_source": doc.get("_source", doc)
    #         }
    #         actions.append(action)

    #     # Use helpers.bulk for optimized bulk indexing
    #     # refresh=False: Don't wait for refresh after each bulk
    #     # request_timeout: Longer timeout for large batches
    #     success, failed = bulk_helper(
    #         self.client,
    #         actions,
    #         refresh=False,
    #         request_timeout=60,
    #         raise_on_error=False
    #     )

    #     return {"success": success, "failed": failed}

    def get_mapping(self) -> dict[str, Any]:
        return self._client.indices.get_mapping(index=self._index_name)

    def update_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        """Update index settings."""
        return self._client.indices.put_settings(index=self._index_name, body=settings)

    def refresh_index(self) -> dict[str, Any]:
        """Manually refresh the index."""
        return self._client.indices.refresh(index=self._index_name)

    def close(self) -> None:
        self._client.close()

    def create_search_pipeline(
        self,
        pipeline_body: dict[str, Any] = NORMALIZATION_PIPELINE,
        pipeline_id: str = SEARCH_PIPELINE_NAME,
    ) -> dict[str, Any]:
        """Create a search pipeline for score normalization and combination."""
        return self._client.search_pipeline.put(id=pipeline_id, body=pipeline_body)

    def delete_search_pipeline(
        self, pipeline_id: str = SEARCH_PIPELINE_NAME
    ) -> dict[str, Any]:
        """Delete a search pipeline."""
        return self._client.search_pipeline.delete(id=pipeline_id)

    def search(
        self, body: dict[str, Any], search_pipeline: str | None = None
    ) -> dict[str, Any]:
        if search_pipeline:
            return self._client.search(
                index=self._index_name, search_pipeline=search_pipeline, body=body
            )
        else:
            return self._client.search(index=self._index_name, body=body)
