import logging
from typing import Any

from opensearchpy import OpenSearch
from opensearchpy.exceptions import TransportError

from onyx.configs.app_configs import OPENSEARCH_ADMIN_PASSWORD
from onyx.configs.app_configs import OPENSEARCH_ADMIN_USERNAME
from onyx.configs.app_configs import OPENSEARCH_HOST
from onyx.configs.app_configs import OPENSEARCH_REST_API_PORT
from onyx.document_index.opensearch.schema import DocumentChunk
from onyx.document_index.opensearch.schema import get_opensearch_doc_chunk_id
from onyx.document_index.opensearch.search import DEFAULT_OPENSEARCH_MAX_RESULT_WINDOW
from onyx.utils.logger import setup_logger


logger = setup_logger(__name__)
# Set the logging level to WARNING to ignore INFO and DEBUG logs from
# opensearch. By default it emits INFO-level logs for every request.
opensearch_logger = logging.getLogger("opensearchpy")
opensearch_logger.setLevel(logging.WARNING)


class OpenSearchClient:
    """Client for interacting with OpenSearch.

    OpenSearch's Python module has pretty bad typing support so this client
    attempts to protect the rest of the codebase from this. As a consequence,
    most methods here return the minimum data needed for the rest of Onyx, and
    tend to rely on Exceptions to handle errors.

    TODO(andrei): This class currently assumes the structure of the database
    schema when it returns a DocumentChunk. Make the class, or at least the
    search method, templated on the structure the caller can expect.
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
        if not self._client.indices.exists(index=self._index_name):
            logger.warning(
                f"Tried to delete index {self._index_name} but it does not exist."
            )
            return False

        response = self._client.indices.delete(index=self._index_name)
        if not response.get("acknowledged", False):
            raise RuntimeError(f"Failed to delete index {self._index_name}.")
        return True

    def index_exists(self) -> bool:
        """Checks if the index exists.

        Raises:
            Exception: There was an error checking if the index exists.

        Returns:
            True if the index exists, False if it does not.
        """
        return self._client.indices.exists(index=self._index_name)

    def validate_index(self, expected_mappings: dict[str, Any]) -> bool:
        """Validates the index.

        Short-circuit returns False on the first mismatch. Logs the mismatch.

        See the OpenSearch documentation for more information on the index
        mappings.
        https://docs.opensearch.org/latest/mappings/

        Args:
            mappings: The expected mappings of the index to validate.

        Raises:
            Exception: There was an error validating the index.

        Returns:
            True if the index is valid, False if it is not based on the mappings
                supplied.
        """
        # OpenSearch's documentation makes no mention of what happens when you
        # invoke client.indices.get on an index that does not exist, so we check
        # for existence explicitly just to be sure.
        exists_response = self.index_exists()
        if not exists_response:
            logger.warning(
                f"Tried to validate index {self._index_name} but it does not exist."
            )
            return False

        get_result = self._client.indices.get(index=self._index_name)
        index_info: dict[str, Any] = get_result.get(self._index_name, {})
        if not index_info:
            raise ValueError(
                f"Bug: OpenSearch did not return any index info for index {self._index_name}, "
                "even though it confirmed that the index exists."
            )
        index_mapping_properties: dict[str, Any] = index_info.get("mappings", {}).get(
            "properties", {}
        )
        expected_mapping_properties: dict[str, Any] = expected_mappings.get(
            "properties", {}
        )
        assert (
            expected_mapping_properties
        ), "Bug: No properties were found in the provided expected mappings."

        for property in expected_mapping_properties:
            if property not in index_mapping_properties:
                logger.warning(
                    f'The field "{property}" was not found in the index {self._index_name}.'
                )
                return False

            expected_property_type = expected_mapping_properties[property].get(
                "type", ""
            )
            assert (
                expected_property_type
            ), f'Bug: The field "{property}" in the supplied expected schema mappings has no type.'

            index_property_type = index_mapping_properties[property].get("type", "")
            if expected_property_type != index_property_type:
                logger.warning(
                    f'The field "{property}" in the index {self._index_name} has type {index_property_type} '
                    f"but the expected type is {expected_property_type}."
                )
                return False

        return True

    def update_settings(self, settings: dict[str, Any]) -> None:
        """Updates the settings of the index.

        See the OpenSearch documentation for more information on the index
        settings.
        https://docs.opensearch.org/latest/install-and-configure/configuring-opensearch/index-settings/

        Args:
            settings: The settings to update the index with.

        Raises:
            Exception: There was an error updating the settings of the index.
        """
        # TODO(andrei): Implement this.
        raise NotImplementedError

    def index_document(self, document: DocumentChunk) -> None:
        """Indexes a document.

        Indexing will fail if a document with the same ID already exists.

        Args:
            document: The document to index. In Onyx this is a chunk of a
                document, OpenSearch simply refers to this as a document as
                well.

        Raises:
            Exception: There was an error indexing the document. This includes
                the case where a document with the same ID already exists.
        """
        document_chunk_id: str = get_opensearch_doc_chunk_id(
            document_id=document.document_id,
            chunk_index=document.chunk_index,
            max_chunk_size=document.max_chunk_size,
        )
        body: dict[str, Any] = document.model_dump(exclude_none=True)
        # client.create will raise if a doc with the same ID exists.
        # client.index does not do this.
        result = self._client.create(
            index=self._index_name, id=document_chunk_id, body=body
        )
        result_id = result.get("_id", "")
        # Sanity check.
        if result_id != document_chunk_id:
            raise RuntimeError(
                f'Upon trying to index a document, OpenSearch responded with ID "{result_id}" '
                f'instead of "{document_chunk_id}" which is the ID it was given.'
            )
        result_string: str = result.get("result", "")
        match result_string:
            case "created":
                return
            # Sanity check.
            case "updated":
                raise RuntimeError(
                    f'The OpenSearch client returned result "updated" for indexing document chunk "{document_chunk_id}". '
                    "This indicates that a document chunk with that ID already exists, which is not expected."
                )
            case _:
                raise RuntimeError(
                    f'Unknown OpenSearch indexing result: "{result_string}".'
                )

    def delete_document(self, document_chunk_id: str) -> bool:
        """Deletes a document.

        Args:
            document_chunk_id: The OpenSearch ID of the document chunk to
                delete.

        Raises:
            Exception: There was an error deleting the document.

        Returns:
            True if the document was deleted, False if it was not found.
        """
        try:
            result = self._client.delete(index=self._index_name, id=document_chunk_id)
        except TransportError as e:
            if e.status_code == 404:
                return False
            else:
                raise e

        result_string: str = result.get("result", "")
        match result_string:
            case "deleted":
                return True
            case "not_found":
                return False
            case _:
                raise RuntimeError(
                    f'Unknown OpenSearch deletion result: "{result_string}".'
                )

    def delete_by_query(self, query_body: dict[str, Any]) -> int:
        """Deletes documents by a query.

        Args:
            query_body: The body of the query to delete documents by.

        Raises:
            Exception: There was an error deleting the documents.

        Returns:
            The number of documents deleted.
        """
        result = self._client.delete_by_query(index=self._index_name, body=query_body)
        if result.get("timed_out", False):
            raise RuntimeError(
                f"Delete by query timed out for index {self._index_name}."
            )
        if len(result.get("failures", [])) > 0:
            raise RuntimeError(
                f"Failed to delete some or all of the documents for index {self._index_name}."
            )

        num_deleted = result.get("deleted", 0)
        num_processed = result.get("total", 0)
        if num_deleted != num_processed:
            raise RuntimeError(
                f"Failed to delete some or all of the documents for index {self._index_name}. "
                f"{num_deleted} documents were deleted out of {num_processed} documents that were processed."
            )

        return num_deleted

    def update_document(self) -> None:
        # TODO(andrei): Implement this.
        raise NotImplementedError("Not implemented.")

    def get_document(self, document_chunk_id: str) -> DocumentChunk:
        """Gets a document.

        Will raise an exception if the document is not found.

        Args:
            document_chunk_id: The OpenSearch ID of the document chunk to get.

        Raises:
            Exception: There was an error getting the document. This includes
                the case where the document is not found.

        Returns:
            The document chunk.
        """
        result = self._client.get(index=self._index_name, id=document_chunk_id)
        found_result: bool = result.get("found", False)
        if not found_result:
            raise RuntimeError(
                f'Document chunk with ID "{document_chunk_id}" was not found.'
            )

        document_chunk_source: dict[str, Any] | None = result.get("_source")
        if not document_chunk_source:
            raise RuntimeError(
                f'Document chunk with ID "{document_chunk_id}" has no data.'
            )

        return DocumentChunk.model_validate(document_chunk_source)

    def create_search_pipeline(
        self,
        pipeline_id: str,
        pipeline_body: dict[str, Any],
    ) -> None:
        """Creates a search pipeline.

        See the OpenSearch documentation for more information on the search
        pipeline body.
        https://docs.opensearch.org/latest/search-plugins/search-pipelines/index/

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
        """Searches the index.

        TODO(andrei): Ideally we could check that every field in the body is
        present in the index, to avoid a class of runtime bugs that could easily
        be caught during development.

        Args:
            body: The body of the search request. See the OpenSearch
                documentation for more information on search request bodies.
            search_pipeline_id: The ID of the search pipeline to use. If None,
                the default search pipeline will be used.

        Raises:
            Exception: There was an error searching the index.

        Returns:
            List of document chunks that match the search request.
        """
        result: dict[str, Any]
        if search_pipeline_id:
            result = self._client.search(
                index=self._index_name, search_pipeline=search_pipeline_id, body=body
            )
        else:
            result = self._client.search(index=self._index_name, body=body)

        hits = self._get_hits_from_search_result(result)

        result_chunks: list[DocumentChunk] = []
        for hit in hits:
            document_chunk_source: dict[str, Any] | None = hit.get("_source")
            if not document_chunk_source:
                raise RuntimeError(
                    f"Document chunk with ID \"{hit.get('_id', '')}\" has no data."
                )
            result_chunks.append(DocumentChunk.model_validate(document_chunk_source))
        return result_chunks

    def search_for_document_ids(self, body: dict[str, Any]) -> list[str]:
        """Searches the index and returns only document chunk IDs.

        In order to take advantage of the performance benefits of only returning
        IDs, the body should have a key, value pair of "_source": False.
        Otherwise, OpenSearch will return the entire document body and this
        method's performance will be the same as the search method's.

        TODO(andrei): Ideally we could check that every field in the body is
        present in the index, to avoid a class of runtime bugs that could easily
        be caught during development.

        Args:
            body: The body of the search request. See the OpenSearch
                documentation for more information on search request bodies.
                TODO(andrei): Make this a more deep interface; callers shouldn't
                need to know to set _source: False for example.

        Raises:
            Exception: There was an error searching the index.

        Returns:
            List of document chunk IDs that match the search request.
        """
        if "_source" not in body or body["_source"] is not False:
            logger.warning(
                "The body of the search request for document chunk IDs is missing the key, value pair of "
                '"_source": False. This query will therefore be inefficient.'
            )

        result: dict[str, Any] = self._client.search(index=self._index_name, body=body)

        hits = self._get_hits_from_search_result(result)

        # TODO(andrei): Implement scroll/point in time for results so that we
        # can return arbitrarily-many IDs.
        if len(hits) == DEFAULT_OPENSEARCH_MAX_RESULT_WINDOW:
            logger.warning(
                "The search request for document chunk IDs returned the maximum number of results. "
                "It is extremely likely that there are more hits in OpenSearch than the returned results."
            )

        # Extract only the _id field from each hit.
        document_chunk_ids: list[str] = []
        for hit in hits:
            document_chunk_id = hit.get("_id")
            if not document_chunk_id:
                raise RuntimeError(
                    "Received a hit from OpenSearch but the _id field is missing."
                )
            document_chunk_ids.append(document_chunk_id)
        return document_chunk_ids

    def refresh_index(self) -> None:
        """Refreshes the index to make recent changes searchable.

        In OpenSearch, documents are not immediately searchable after indexing.
        This method forces a refresh to make them available for search.

        Raises:
            Exception: There was an error refreshing the index.
        """
        self._client.indices.refresh(index=self._index_name)

    def ping(self) -> bool:
        """Pings the OpenSearch cluster.

        Returns:
            True if OpenSearch could be reached, False if it could not.
        """
        return self._client.ping()

    def close(self) -> None:
        """Closes the client.

        Raises:
            Exception: There was an error closing the client.
        """
        self._client.close()

    def _get_hits_from_search_result(self, result: dict[str, Any]) -> list[Any]:
        """Extracts the hits from a search result.

        Args:
            result: The search result to extract the hits from.

        Raises:
            Exception: There was an error extracting the hits from the search
                result. This includes the case where the search timed out.

        Returns:
            The hits from the search result.
        """
        if result.get("timed_out", False):
            raise RuntimeError(f"Search timed out for index {self._index_name}.")
        hits_first_layer: dict[str, Any] = result.get("hits", {})
        if not hits_first_layer:
            raise RuntimeError(
                f"Hits field missing from response when trying to search index {self._index_name}."
            )
        hits_second_layer: list[Any] = hits_first_layer.get("hits", [])
        return hits_second_layer
