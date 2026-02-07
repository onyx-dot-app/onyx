import logging
import time
from typing import Any
from typing import Generic
from typing import TypeVar

from opensearchpy import OpenSearch
from opensearchpy import TransportError
from opensearchpy.helpers import bulk
from pydantic import BaseModel

from onyx.configs.app_configs import OPENSEARCH_ADMIN_PASSWORD
from onyx.configs.app_configs import OPENSEARCH_ADMIN_USERNAME
from onyx.configs.app_configs import OPENSEARCH_HOST
from onyx.configs.app_configs import OPENSEARCH_REST_API_PORT
from onyx.document_index.interfaces_new import TenantState
from onyx.document_index.opensearch.schema import DocumentChunk
from onyx.document_index.opensearch.schema import get_opensearch_doc_chunk_id
from onyx.document_index.opensearch.search import DEFAULT_OPENSEARCH_MAX_RESULT_WINDOW
from onyx.utils.logger import setup_logger
from onyx.utils.timing import log_function_time


logger = setup_logger(__name__)
# Set the logging level to WARNING to ignore INFO and DEBUG logs from
# opensearch. By default it emits INFO-level logs for every request.
# The opensearch-py library uses "opensearch" as the logger name for HTTP
# requests (see opensearchpy/connection/base.py)
opensearch_logger = logging.getLogger("opensearch")
opensearch_logger.setLevel(logging.WARNING)


SchemaDocumentModel = TypeVar("SchemaDocumentModel")


class SearchHit(BaseModel, Generic[SchemaDocumentModel]):
    """Represents a hit from OpenSearch in response to a query.

    Templated on the specific document model as defined by a schema.
    """

    model_config = {"frozen": True}

    # The document chunk source retrieved from OpenSearch.
    document_chunk: SchemaDocumentModel
    # The match score for the document chunk as calculated by OpenSearch. Only
    # relevant for "fuzzy searches"; this will be None for direct queries where
    # score is not relevant like direct retrieval on ID.
    score: float | None = None
    # Maps schema property name to a list of highlighted snippets with match
    # terms wrapped in tags (e.g. "something <hi>keyword</hi> other thing").
    match_highlights: dict[str, list[str]] = {}


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
        logger.debug(
            f"Creating OpenSearch client for index {index_name} with host {host} and port {port}."
        )
        self._client = OpenSearch(
            hosts=[{"host": host, "port": port}],
            http_auth=auth,
            use_ssl=use_ssl,
            verify_certs=verify_certs,
            ssl_show_warn=ssl_show_warn,
        )
        logger.debug(
            f"OpenSearch client created successfully for index {self._index_name}."
        )

    @log_function_time(print_only=True, debug_only=True, include_args=True)
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
        logger.debug(f"Creating index {self._index_name} with body {body}.")
        response = self._client.indices.create(index=self._index_name, body=body)
        if not response.get("acknowledged", False):
            raise RuntimeError(f"Failed to create index {self._index_name}.")
        response_index = response.get("index", "")
        if response_index != self._index_name:
            raise RuntimeError(
                f"OpenSearch responded with index name {response_index} when creating index {self._index_name}."
            )
        logger.debug(f"Index {self._index_name} created successfully.")

    @log_function_time(print_only=True, debug_only=True)
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

        logger.debug(f"Deleting index {self._index_name}.")
        response = self._client.indices.delete(index=self._index_name)
        if not response.get("acknowledged", False):
            raise RuntimeError(f"Failed to delete index {self._index_name}.")
        return True

    @log_function_time(print_only=True, debug_only=True)
    def index_exists(self) -> bool:
        """Checks if the index exists.

        Raises:
            Exception: There was an error checking if the index exists.

        Returns:
            True if the index exists, False if it does not.
        """
        return self._client.indices.exists(index=self._index_name)

    @log_function_time(print_only=True, debug_only=True, include_args=True)
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
        logger.debug(
            f"Validating index {self._index_name} with expected mappings {expected_mappings}."
        )

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

        logger.debug(f"Index {self._index_name} validated successfully.")
        return True

    @log_function_time(print_only=True, debug_only=True, include_args=True)
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

    @log_function_time(
        print_only=True,
        debug_only=True,
        include_args_subset={
            "document": str,
            "tenant_state": str,
            "update_if_exists": str,
        },
    )
    def index_document(
        self,
        document: DocumentChunk,
        tenant_state: TenantState,
        update_if_exists: bool = False,
    ) -> None:
        """Indexes a document.

        Args:
            document: The document to index. In Onyx this is a chunk of a
                document, OpenSearch simply refers to this as a document as
                well.
            tenant_state: The tenant state of the caller.
            update_if_exists: Whether to update the document if it already
                exists. If False, will raise an exception if the document
                already exists. Defaults to False.

        Raises:
            Exception: There was an error indexing the document. This includes
                the case where a document with the same ID already exists if
                update_if_exists is False.
        """
        logger.debug(
            f"Trying to index document ID {document.document_id} for tenant {tenant_state.tenant_id}. "
            f"update_if_exists={update_if_exists}."
        )
        document_chunk_id: str = get_opensearch_doc_chunk_id(
            tenant_state=tenant_state,
            document_id=document.document_id,
            chunk_index=document.chunk_index,
            max_chunk_size=document.max_chunk_size,
        )
        body: dict[str, Any] = document.model_dump(exclude_none=True)
        # client.create will raise if a doc with the same ID exists.
        # client.index does not do this.
        if update_if_exists:
            result = self._client.index(
                index=self._index_name, id=document_chunk_id, body=body
            )
        else:
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
            # Sanity check.
            case "created":
                pass
            case "updated":
                if not update_if_exists:
                    raise RuntimeError(
                        f'The OpenSearch client returned result "updated" for indexing document chunk "{document_chunk_id}". '
                        "This indicates that a document chunk with that ID already exists, which is not expected."
                    )
            case _:
                raise RuntimeError(
                    f'Unknown OpenSearch indexing result: "{result_string}".'
                )
        logger.debug(f"Successfully indexed {document_chunk_id}.")

    @log_function_time(
        print_only=True,
        debug_only=True,
        include_args_subset={
            "documents": len,
            "tenant_state": str,
            "update_if_exists": str,
        },
    )
    def bulk_index_documents(
        self,
        documents: list[DocumentChunk],
        tenant_state: TenantState,
        update_if_exists: bool = False,
    ) -> None:
        """Bulk indexes documents.

        Raises if there are any errors during the bulk index. It should be
        assumed that no documents in the batch were indexed successfully if
        there is an error.

        Retries on 429 too many requests.

        Args:
            documents: The documents to index. In Onyx this is a chunk of a
                document, OpenSearch simply refers to this as a document as
                well.
            tenant_state: The tenant state of the caller.
            update_if_exists: Whether to update the document if it already
                exists. If False, will raise an exception if the document
                already exists. Defaults to False.

        Raises:
            Exception: There was an error during the bulk index. This
                includes the case where a document with the same ID already
                exists if update_if_exists is False.
        """
        if not documents:
            return
        logger.debug(
            f"Bulk indexing {len(documents)} documents for tenant {tenant_state.tenant_id}. update_if_exists={update_if_exists}."
        )
        data = []
        for document in documents:
            document_chunk_id: str = get_opensearch_doc_chunk_id(
                tenant_state=tenant_state,
                document_id=document.document_id,
                chunk_index=document.chunk_index,
                max_chunk_size=document.max_chunk_size,
            )
            body: dict[str, Any] = document.model_dump(exclude_none=True)
            data_for_document: dict[str, Any] = {
                "_index": self._index_name,
                "_id": document_chunk_id,
                "_op_type": "index" if update_if_exists else "create",
                "_source": body,
            }
            data.append(data_for_document)
        # max_retries is the number of times to retry a request if we get a 429.
        success, errors = bulk(self._client, data, max_retries=3)
        if errors:
            raise RuntimeError(
                f"Failed to bulk index documents for index {self._index_name}. Errors: {errors}"
            )
        if success != len(documents):
            raise RuntimeError(
                f"OpenSearch reported no errors during bulk index but the number of successful operations "
                f"({success}) does not match the number of documents ({len(documents)})."
            )
        logger.debug(f"Successfully bulk indexed {len(documents)} documents.")

    @log_function_time(print_only=True, debug_only=True, include_args=True)
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
            logger.debug(
                f"Trying to delete document chunk {document_chunk_id} from index {self._index_name}."
            )
            result = self._client.delete(index=self._index_name, id=document_chunk_id)
        except TransportError as e:
            if e.status_code == 404:
                logger.debug(
                    f"Document chunk {document_chunk_id} not found in index {self._index_name}."
                )
                return False
            else:
                raise e

        result_string: str = result.get("result", "")
        match result_string:
            case "deleted":
                logger.debug(
                    f"Successfully deleted document chunk {document_chunk_id} from index {self._index_name}."
                )
                return True
            case "not_found":
                logger.debug(
                    f"Document chunk {document_chunk_id} not found in index {self._index_name}."
                )
                return False
            case _:
                raise RuntimeError(
                    f'Unknown OpenSearch deletion result: "{result_string}".'
                )

    @log_function_time(print_only=True, debug_only=True)
    def delete_by_query(self, query_body: dict[str, Any]) -> int:
        """Deletes documents by a query.

        Args:
            query_body: The body of the query to delete documents by.

        Raises:
            Exception: There was an error deleting the documents.

        Returns:
            The number of documents deleted.
        """
        logger.debug(
            f"Trying to delete documents by query for index {self._index_name}."
        )
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

        logger.debug(
            f"Successfully deleted {num_deleted} documents by query for index {self._index_name}."
        )
        return num_deleted

    @log_function_time(
        print_only=True,
        debug_only=True,
        include_args_subset={
            "document_chunk_id": str,
            "properties_to_update": lambda x: x.keys(),
        },
    )
    def update_document(
        self, document_chunk_id: str, properties_to_update: dict[str, Any]
    ) -> None:
        """Updates an OpenSearch document chunk's properties.

        Args:
            document_chunk_id: The OpenSearch ID of the document chunk to
                update.
            properties_to_update: The properties of the document to update. Each
                property should exist in the schema.

        Raises:
            Exception: There was an error updating the document.
        """
        logger.debug(
            f"Trying to update document chunk {document_chunk_id} for index {self._index_name}."
        )
        update_body: dict[str, Any] = {"doc": properties_to_update}
        result = self._client.update(
            index=self._index_name,
            id=document_chunk_id,
            body=update_body,
            _source=False,
        )
        result_id = result.get("_id", "")
        # Sanity check.
        if result_id != document_chunk_id:
            raise RuntimeError(
                f'Upon trying to update a document, OpenSearch responded with ID "{result_id}" '
                f'instead of "{document_chunk_id}" which is the ID it was given.'
            )
        result_string: str = result.get("result", "")
        match result_string:
            # Sanity check.
            case "updated":
                logger.debug(
                    f"Successfully updated document chunk {document_chunk_id} for index {self._index_name}."
                )
                return
            case "noop":
                logger.warning(
                    f'OpenSearch reported a no-op when trying to update document with ID "{document_chunk_id}".'
                )
                return
            case _:
                raise RuntimeError(
                    f'The OpenSearch client returned result "{result_string}" for updating document chunk "{document_chunk_id}". '
                    "This is unexpected."
                )

    @log_function_time(print_only=True, debug_only=True, include_args=True)
    def get_document(self, document_chunk_id: str) -> DocumentChunk:
        """Gets an OpenSearch document chunk.

        Will raise an exception if the document chunk is not found.

        Args:
            document_chunk_id: The OpenSearch ID of the document chunk to get.

        Raises:
            Exception: There was an error getting the document. This includes
                the case where the document is not found.

        Returns:
            The document chunk.
        """
        logger.debug(
            f"Trying to get document chunk {document_chunk_id} from index {self._index_name}."
        )
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

        logger.debug(
            f"Successfully got document chunk {document_chunk_id} from index {self._index_name}."
        )
        return DocumentChunk.model_validate(document_chunk_source)

    @log_function_time(print_only=True, debug_only=True, include_args=True)
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

    @log_function_time(print_only=True, debug_only=True, include_args=True)
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

    @log_function_time(print_only=True, debug_only=True)
    def search(
        self, body: dict[str, Any], search_pipeline_id: str | None
    ) -> list[SearchHit[DocumentChunk]]:
        """Searches the index.

        TODO(andrei): Ideally we could check that every field in the body is
        present in the index, to avoid a class of runtime bugs that could easily
        be caught during development. Or change the function signature to accept
        a predefined pydantic model of allowed fields.

        Args:
            body: The body of the search request. See the OpenSearch
                documentation for more information on search request bodies.
            search_pipeline_id: The ID of the search pipeline to use. If None,
                the default search pipeline will be used.

        Raises:
            Exception: There was an error searching the index.

        Returns:
            List of search hits that match the search request.
        """
        logger.debug(
            f"Trying to search index {self._index_name} with search pipeline {search_pipeline_id}."
        )
        result: dict[str, Any]
        if search_pipeline_id:
            result = self._client.search(
                index=self._index_name, search_pipeline=search_pipeline_id, body=body
            )
        else:
            result = self._client.search(index=self._index_name, body=body)

        hits = self._get_hits_from_search_result(result)

        search_hits: list[SearchHit[DocumentChunk]] = []
        for hit in hits:
            document_chunk_source: dict[str, Any] | None = hit.get("_source")
            if not document_chunk_source:
                raise RuntimeError(
                    f"Document chunk with ID \"{hit.get('_id', '')}\" has no data."
                )
            document_chunk_score = hit.get("_score", None)
            match_highlights: dict[str, list[str]] = hit.get("highlight", {})
            search_hit = SearchHit[DocumentChunk](
                document_chunk=DocumentChunk.model_validate(document_chunk_source),
                score=document_chunk_score,
                match_highlights=match_highlights,
            )
            search_hits.append(search_hit)
        logger.debug(
            f"Successfully searched index {self._index_name} and got {len(search_hits)} hits."
        )
        return search_hits

    @log_function_time(print_only=True, debug_only=True)
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
        logger.debug(
            f"Trying to search for document chunk IDs in index {self._index_name}."
        )
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
        logger.debug(
            f"Successfully searched for document chunk IDs in index {self._index_name} and got {len(document_chunk_ids)} hits."
        )
        return document_chunk_ids

    @log_function_time(print_only=True, debug_only=True)
    def refresh_index(self) -> None:
        """Refreshes the index to make recent changes searchable.

        In OpenSearch, documents are not immediately searchable after indexing.
        This method forces a refresh to make them available for search.

        Raises:
            Exception: There was an error refreshing the index.
        """
        self._client.indices.refresh(index=self._index_name)

    @log_function_time(print_only=True, debug_only=True, include_args=True)
    def set_cluster_auto_create_index_setting(self, enabled: bool) -> bool:
        """Sets the cluster auto create index setting.

        By default, when you index a document to a non-existent index,
        OpenSearch will automatically create the index. This behavior is
        undesirable so this function exposes the ability to disable it.

        See
        https://docs.opensearch.org/latest/install-and-configure/configuring-opensearch/index/#updating-cluster-settings-using-the-api

        Args:
            enabled: Whether to enable the auto create index setting.

        Returns:
            True if the setting was updated successfully, False otherwise. Does
                not raise.
        """
        try:
            body = {"persistent": {"action.auto_create_index": enabled}}
            response = self._client.cluster.put_settings(body=body)
            if response.get("acknowledged", False):
                logger.info(f"Successfully set action.auto_create_index to {enabled}.")
                return True
            else:
                logger.error(f"Failed to update setting: {response}.")
                return False
        except Exception:
            logger.exception("Error setting auto_create_index.")
            return False

    @log_function_time(print_only=True, debug_only=True)
    def ping(self) -> bool:
        """Pings the OpenSearch cluster.

        Returns:
            True if OpenSearch could be reached, False if it could not.
        """
        return self._client.ping()

    @log_function_time(print_only=True, debug_only=True)
    def close(self) -> None:
        """Closes the client.

        TODO(andrei): Can we have some way to auto close when the client no
        longer has any references?

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


def wait_for_opensearch_with_timeout(
    wait_interval_s: int = 5,
    wait_limit_s: int = 60,
    client: OpenSearchClient | None = None,
) -> bool:
    """Waits for OpenSearch to become ready subject to a timeout.

    Will create a new dummy client if no client is provided. Will close this
    client at the end of the function. Will not close the client if it was
    supplied.

    Args:
        wait_interval_s: The interval in seconds to wait between checks.
            Defaults to 5.
        wait_limit_s: The total timeout in seconds to wait for OpenSearch to
            become ready. Defaults to 60.
        client: The OpenSearch client to use for pinging. If None, a new dummy
            client will be created. Defaults to None.

    Returns:
        True if OpenSearch is ready, False otherwise.
    """
    made_client = False
    try:
        if client is None:
            # NOTE: index_name does not matter because we are only using this object
            # to ping.
            # TODO(andrei): Make this better.
            client = OpenSearchClient(index_name="")
            made_client = True
        time_start = time.monotonic()
        while True:
            if client.ping():
                logger.info("[OpenSearch] Readiness probe succeeded. Continuing...")
                return True
            time_elapsed = time.monotonic() - time_start
            if time_elapsed > wait_limit_s:
                logger.info(
                    f"[OpenSearch] Readiness probe did not succeed within the timeout "
                    f"({wait_limit_s} seconds)."
                )
                return False
            logger.info(
                f"[OpenSearch] Readiness probe ongoing. elapsed={time_elapsed:.1f} timeout={wait_limit_s:.1f}"
            )
            time.sleep(wait_interval_s)
    finally:
        if made_client:
            assert client is not None
            client.close()
