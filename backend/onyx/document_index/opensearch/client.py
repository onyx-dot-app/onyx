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


class OpenSearchClient:
    def __init__(
        self,
        index_name: str,
        host: str = "localhost",
        port: int = 9200,
        auth: tuple[str, str] = ("admin", "D@nswer_1ndex"),
        use_ssl: bool = True,
        verify_certs: bool = False,
        ssl_show_warn: bool = False,
    ):
        self.index_name = index_name
        self.client = OpenSearch(
            hosts=[{"host": host, "port": port}],
            http_auth=auth,
            use_ssl=use_ssl,
            verify_certs=verify_certs,
            ssl_show_warn=ssl_show_warn,
            timeout=30,
            max_retries=3,
            retry_on_timeout=True,
        )

    def create_index(self, mappings: dict, settings: dict | None = None) -> dict:
        body = {}
        if settings:
            body["settings"] = settings
        if mappings:
            body["mappings"] = mappings

        return self.client.indices.create(index=self.index_name, body=body)

    def delete_index(self) -> dict:
        if self.client.indices.exists(index=self.index_name):
            return self.client.indices.delete(index=self.index_name)
        return {"acknowledged": False, "message": "Index does not exist"}

    def index_document(self, doc_id: str, document: DocumentChunk) -> dict:
        return self.client.index(
            index=self.index_name, id=doc_id, body=document.to_dict()
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

    def get_mapping(self) -> dict:
        return self.client.indices.get_mapping(index=self.index_name)

    def update_settings(self, settings: dict) -> dict:
        """Update index settings."""
        return self.client.indices.put_settings(index=self.index_name, body=settings)

    def refresh_index(self) -> dict:
        """Manually refresh the index."""
        return self.client.indices.refresh(index=self.index_name)

    def close(self):
        self.client.close()

    def create_search_pipeline(
        self,
        pipeline_body: dict = NORMALIZATION_PIPELINE,
        pipeline_id: str = SEARCH_PIPELINE_NAME,
    ) -> dict:
        """Create a search pipeline for score normalization and combination."""
        return self.client.search_pipeline.put(id=pipeline_id, body=pipeline_body)

    def delete_search_pipeline(self, pipeline_id: str = SEARCH_PIPELINE_NAME) -> dict:
        """Delete a search pipeline."""
        return self.client.search_pipeline.delete(id=pipeline_id)

    def search(self, body: dict, search_pipeline: str | None) -> dict:
        if search_pipeline:
            return self.client.search(
                index=self.index_name, search_pipeline=search_pipeline, body=body
            )
        else:
            return self.client.search(index=self.index_name, body=body)
