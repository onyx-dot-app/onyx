from enum import StrEnum
from typing import Any

from opensearchpy import OpenSearch

from onyx.configs.app_configs import OPENSEARCH_ADMIN_PASSWORD
from onyx.configs.app_configs import OPENSEARCH_ADMIN_USERNAME
from onyx.configs.app_configs import OPENSEARCH_HOST
from onyx.configs.app_configs import OPENSEARCH_REST_API_PORT
from onyx.document_index.opensearch.schema import DocumentChunk
from onyx.utils.logger import setup_logger


logger = setup_logger(__name__)


class OpenSearchIndexingResult(StrEnum):
    CREATED = "created"
    DELETED = "deleted"
    NOOP = "noop"
    NOT_FOUND = "not_found"
    UPDATED = "updated"


class OpenSearchClient:
    """Client for interacting with OpenSearch.

    OpenSearch's Python module has pretty bad typing support so this client
    attempts to protect the rest of the codebase from this. As a consequence,
    most methods here return the minimum data needed for the rest of Onyx, and
    tend to rely on Exceptions to handle errors.
    """

    def __init__(
        self,
        index_name: str,
        host: str = OPENSEARCH_HOST,
        port: int = OPENSEARCH_REST_API_PORT,
        auth: tuple[str, str] = (OPENSEARCH_ADMIN_USERNAME, OPENSEARCH_ADMIN_PASSWORD),
        use_ssl: bool = True,
        verify_certs: bool = False,
        ssl_show_warn: bool = False,
    ):
        self._index_name = index_name
        self._client = OpenSearch(
            hosts=[{"host": host, "port": port}],
            http_auth=auth,
            use_ssl=use_ssl,
            verify_certs=verify_certs,
            ssl_show_warn=ssl_show_warn,
        )

    def create_index(self, mappings: dict[str, Any], settings: dict[str, Any]) -> None:
        """Creates the index.

        See the OpenSearch documentation for more information on mappings and
        settings.

        Args:
            mappings: The mappings for the index to create.
            settings: The settings for the index to create.

        Raises:
            Exception: There was an error creating the index.
        """
        body: dict[str, Any] = {
            "mappings": mappings,
            "settings": settings,
        }
        response = self._client.indices.create(index=self._index_name, body=body)
        if not response.get("acknowledged", False):
            raise RuntimeError(f"Failed to create index {self._index_name}.")
        response_index = response.get("index", "")
        if response_index != self._index_name:
            raise RuntimeError(
                f"OpenSearch responded with index name {response_index} when creating index {self._index_name}."
            )

    def delete_index(self) -> bool:
        """Deletes the index.

        Raises:
            Exception: There was an error deleting the index.

        Returns:
            True if the index was deleted, False if it did not exist.
        """
        if self._client.indices.exists(index=self._index_name):
            response = self._client.indices.delete(index=self._index_name)
            if not response.get("acknowledged", False):
                raise RuntimeError(f"Failed to delete index {self._index_name}.")
            return True
        return False

    def validate_index(self, mappings: dict[str, Any]) -> bool:
        """Validates the index.

        See the OpenSearch documentation for more information on the index
        mappings.

        Args:
            mappings: The expected mappings of the index to validate.

        Raises:
            Exception: There was an error validating the index.

        Returns:
            True if the index is valid, False if it is not based on the mappings
                supplied.
        """
        raise NotImplementedError("Not implemented.")

    def update_settings(self, settings: dict[str, Any]) -> None:
        """Updates the settings of the index.

        See the OpenSearch documentation for more information on the index
        settings.

        Args:
            settings: The settings to update the index with.

        Raises:
            Exception: There was an error updating the settings of the index.
        """
        raise NotImplementedError("Not implemented.")

    def index_document(self, document: DocumentChunk) -> OpenSearchIndexingResult:
        """Indexes a document.

        TODO(andrei): Check if the doc ID exists before indexing it!

        Args:
            document: The document to index. In Onyx this is a chunk of a
                document, OpenSearch simply refers to this as a document as
                well.

        Raises:
            Exception: There was an error indexing the document.

        Returns:
            The result of the indexing operation.
        """
        document_chunk_id: str = document.get_opensearch_doc_chunk_id()
        body: dict[str, Any] = document.model_dump(exclude_none=True)
        result = self._client.index(
            index=self._index_name, id=document_chunk_id, body=body
        )
        result_id = result.get("_id", "")
        if result_id != document_chunk_id:
            raise RuntimeError(
                f"OpenSearch responded with ID {id} instead of {document_chunk_id} which is the ID it was given."
            )
        result_string: str = result.get("result", "")
        match result_string:
            case "created":
                return OpenSearchIndexingResult.CREATED
            case "deleted":
                return OpenSearchIndexingResult.DELETED
            case "noop":
                return OpenSearchIndexingResult.NOOP
            case "not_found":
                return OpenSearchIndexingResult.NOT_FOUND
            case "updated":
                return OpenSearchIndexingResult.UPDATED
            case _:
                raise RuntimeError(
                    f"Unknown OpenSearch indexing result: {result_string}."
                )

    def delete_document(self) -> None:
        # TODO(andrei): For OS delete returns 404 if not found.
        raise NotImplementedError("Not implemented.")

    def update_document(self) -> None:
        raise NotImplementedError("Not implemented.")

    def get_document(self) -> DocumentChunk:
        raise NotImplementedError("Not implemented.")

    def check_if_document_exists(self, document_chunk_id: str) -> bool:
        raise NotImplementedError("Not implemented.")

    def create_search_pipeline(
        self,
        pipeline_id: str,
        pipeline_body: dict[str, Any],
    ) -> None:
        """Creates a search pipeline.

        See the OpenSearch documentation for more information on the search
        pipeline body.

        Args:
            pipeline_id: The ID of the search pipeline to create.
            pipeline_body: The body of the search pipeline to create.

        Raises:
            Exception: There was an error creating the search pipeline.
        """
        result = self._client.search_pipeline.put(id=pipeline_id, body=pipeline_body)
        if not result.get("acknowledged", False):
            raise RuntimeError(f"Failed to create search pipeline {pipeline_id}.")

    def delete_search_pipeline(self, pipeline_id: str) -> None:
        """Deletes a search pipeline.

        Args:
            pipeline_id: The ID of the search pipeline to delete.

        Raises:
            Exception: There was an error deleting the search pipeline.
        """
        result = self._client.search_pipeline.delete(id=pipeline_id)
        if not result.get("acknowledged", False):
            raise RuntimeError(f"Failed to delete search pipeline {pipeline_id}.")

    def search(
        self, body: dict[str, Any], search_pipeline_id: str | None
    ) -> list[DocumentChunk]:
        if search_pipeline_id:
            result: dict[Any, Any] = self._client.search(
                index=self._index_name, search_pipeline=search_pipeline_id, body=body
            )
        else:
            result: dict[Any, Any] = self._client.search(
                index=self._index_name, body=body
            )

        if result.get("timed_out", False):
            raise RuntimeError(f"Search timed out for index {self._index_name}.")
        hits_first_layer: dict[Any, Any] = result.get("hits", {})
        if not hits_first_layer:
            raise RuntimeError(
                f"Hits field missing from response when trying to search index {self._index_name}."
            )
        hits_second_layer: list[Any] = hits_first_layer.get("hits", [])

        result_chunks: list[DocumentChunk] = [
            DocumentChunk.model_validate(hit) for hit in hits_second_layer
        ]
        return result_chunks

    def close(self) -> None:
        """Closes the client.

        Raises:
            Exception: There was an error closing the client.
        """
        self._client.close()
