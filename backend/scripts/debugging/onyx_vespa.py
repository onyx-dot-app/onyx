"""
Vespa Debugging Tool!

Usage:
  python vespa_debug_tool.py --action <action> [options]

Actions:
  config          : Print Vespa configuration
  connect         : Check Vespa connectivity
  list_docs       : List documents
  list_connector  : List documents for a specific connector-credential pair
  search          : Search documents
  update          : Update a document
  delete          : Delete a document
  get_acls        : Get document ACLs

Options:
  --tenant-id     : Tenant ID
  --connector-id  : Connector ID
  --cc-pair-id    : Connector-Credential Pair ID
  --n             : Number of documents (default 10)
  --query         : Search query
  --doc-id        : Document ID
  --fields        : Fields to update (JSON)

Example:
  python vespa_debug_tool.py --action list_docs --tenant-id my_tenant --connector-id 1 --n 5
  python vespa_debug_tool.py --action list_connector --tenant-id my_tenant --cc-pair-id 1 --n 5
"""

import argparse
import json
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import and_

from onyx.configs.constants import INDEX_SEPARATOR
from onyx.context.search.models import IndexFilters
from onyx.context.search.models import SearchRequest
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Document
from onyx.db.models import DocumentByConnectorCredentialPair
from onyx.db.search_settings import get_current_search_settings
from onyx.document_index.document_index_utils import get_document_chunk_ids
from onyx.document_index.interfaces import EnrichedDocumentIndexingInfo
from onyx.document_index.vespa.index import VespaIndex
from onyx.document_index.vespa.shared_utils.utils import get_vespa_http_client
from onyx.document_index.vespa_constants import ACCESS_CONTROL_LIST
from onyx.document_index.vespa_constants import DOC_UPDATED_AT
from onyx.document_index.vespa_constants import DOCUMENT_ID_ENDPOINT
from onyx.document_index.vespa_constants import DOCUMENT_SETS
from onyx.document_index.vespa_constants import HIDDEN
from onyx.document_index.vespa_constants import METADATA_LIST
from onyx.document_index.vespa_constants import SEARCH_ENDPOINT
from onyx.document_index.vespa_constants import SOURCE_TYPE
from onyx.document_index.vespa_constants import VESPA_APP_CONTAINER_URL
from onyx.document_index.vespa_constants import VESPA_APPLICATION_ENDPOINT
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

logger = setup_logger()


class DocumentFilter(BaseModel):
    # Document filter for link matching.
    link: str | None = None


def build_vespa_filters(
    filters: IndexFilters,
    *,
    include_hidden: bool = False,
    remove_trailing_and: bool = False,
) -> str:
    # Build a combined Vespa filter string from the given IndexFilters.
    def _build_or_filters(key: str, vals: list[str] | None) -> str:
        if vals is None:
            return ""
        valid_vals = [val for val in vals if val]
        if not key or not valid_vals:
            return ""
        eq_elems = [f'{key} contains "{elem}"' for elem in valid_vals]
        or_clause = " or ".join(eq_elems)
        return f"({or_clause})"

    def _build_time_filter(
        cutoff: datetime | None,
        untimed_doc_cutoff: timedelta = timedelta(days=92),
    ) -> str:
        if not cutoff:
            return ""
        include_untimed = datetime.now(timezone.utc) - untimed_doc_cutoff > cutoff
        cutoff_secs = int(cutoff.timestamp())
        if include_untimed:
            return f"!({DOC_UPDATED_AT} < {cutoff_secs})"
        return f"({DOC_UPDATED_AT} >= {cutoff_secs})"

    filter_str = ""
    if not include_hidden:
        filter_str += f"AND !({HIDDEN}=true) "

    # if filters.tenant_id and MULTI_TENANT:
    #     filter_str += f'AND ({TENANT_ID} contains "{filters.tenant_id}") '

    if filters.access_control_list is not None:
        acl_str = _build_or_filters(ACCESS_CONTROL_LIST, filters.access_control_list)
        if acl_str:
            filter_str += f"AND {acl_str} "

    source_strs = (
        [s.value for s in filters.source_type] if filters.source_type else None
    )
    source_str = _build_or_filters(SOURCE_TYPE, source_strs)
    if source_str:
        filter_str += f"AND {source_str} "

    tags = filters.tags
    if tags:
        tag_attributes = [tag.tag_key + INDEX_SEPARATOR + tag.tag_value for tag in tags]
    else:
        tag_attributes = None
    tag_str = _build_or_filters(METADATA_LIST, tag_attributes)
    if tag_str:
        filter_str += f"AND {tag_str} "

    doc_set_str = _build_or_filters(DOCUMENT_SETS, filters.document_set)
    if doc_set_str:
        filter_str += f"AND {doc_set_str} "

    time_filter = _build_time_filter(filters.time_cutoff)
    if time_filter:
        filter_str += f"AND {time_filter} "

    if remove_trailing_and:
        while filter_str.endswith(" and "):
            filter_str = filter_str[:-5]
        while filter_str.endswith("AND "):
            filter_str = filter_str[:-4]

    return filter_str.strip()


def print_vespa_config() -> None:
    # Print Vespa configuration.
    logger.info("Printing Vespa configuration.")
    print(f"Vespa Application Endpoint: {VESPA_APPLICATION_ENDPOINT}")
    print(f"Vespa App Container URL: {VESPA_APP_CONTAINER_URL}")
    print(f"Vespa Search Endpoint: {SEARCH_ENDPOINT}")
    print(f"Vespa Document ID Endpoint: {DOCUMENT_ID_ENDPOINT}")


def check_vespa_connectivity() -> None:
    # Check connectivity to Vespa endpoints.
    logger.info("Checking Vespa connectivity.")
    endpoints = [
        f"{VESPA_APPLICATION_ENDPOINT}/ApplicationStatus",
        f"{VESPA_APPLICATION_ENDPOINT}/tenant",
        f"{VESPA_APPLICATION_ENDPOINT}/tenant/default/application/",
        f"{VESPA_APPLICATION_ENDPOINT}/tenant/default/application/default",
    ]

    for endpoint in endpoints:
        try:
            with get_vespa_http_client() as client:
                response = client.get(endpoint)
                logger.info(
                    f"Connected to Vespa at {endpoint}, status code {response.status_code}"
                )
                print(f"Successfully connected to Vespa at {endpoint}")
                print(f"Status code: {response.status_code}")
                print(f"Response: {response.text[:200]}...")
        except Exception as e:
            logger.error(f"Failed to connect to Vespa at {endpoint}: {str(e)}")
            print(f"Failed to connect to Vespa at {endpoint}: {str(e)}")

    print("Vespa connectivity check completed.")


def get_vespa_info() -> Dict[str, Any]:
    # Get info about the default Vespa application.
    url = f"{VESPA_APPLICATION_ENDPOINT}/tenant/default/application/default"
    with get_vespa_http_client() as client:
        response = client.get(url)
        response.raise_for_status()
        return response.json()


def get_index_name(tenant_id: str) -> str:
    # Return the index name for a given tenant.
    with get_session_with_tenant(tenant_id=tenant_id) as db_session:
        search_settings = get_current_search_settings(db_session)
        if not search_settings:
            raise ValueError(f"No search settings found for tenant {tenant_id}")
        return search_settings.index_name


def query_vespa(
    yql: str, tenant_id: Optional[str] = None, limit: int = 10
) -> List[Dict[str, Any]]:
    # Perform a Vespa query using YQL syntax.
    filters = IndexFilters(tenant_id=None, access_control_list=[])
    filter_string = build_vespa_filters(filters, remove_trailing_and=True)
    full_yql = yql.strip()
    if filter_string:
        full_yql = f"{full_yql} {filter_string}"
    full_yql = f"{full_yql} limit {limit}"

    params = {"yql": full_yql, "timeout": "10s"}
    search_request = SearchRequest(query="", limit=limit, offset=0)
    params.update(search_request.model_dump())

    logger.info(f"Executing Vespa query: {full_yql}")
    with get_vespa_http_client() as client:
        response = client.get(SEARCH_ENDPOINT, params=params)
        response.raise_for_status()
        result = response.json()
        documents = result.get("root", {}).get("children", [])
        logger.info(f"Found {len(documents)} documents from query.")
        return documents


def get_first_n_documents(n: int = 10) -> List[Dict[str, Any]]:
    # Get the first n documents from any source.
    yql = "select * from sources * where true"
    return query_vespa(yql, limit=n)


def print_documents(documents: List[Dict[str, Any]]) -> None:
    # Pretty-print a list of documents.
    for doc in documents:
        print(json.dumps(doc, indent=2))
        print("-" * 80)


def get_documents_for_tenant_connector(
    tenant_id: str, connector_id: int, n: int = 10
) -> None:
    # Get and print documents for a specific tenant and connector.
    index_name = get_index_name(tenant_id)
    logger.info(
        f"Fetching documents for tenant={tenant_id}, connector_id={connector_id}"
    )
    yql = f"select * from sources {index_name} where true"
    documents = query_vespa(yql, tenant_id, limit=n)
    print(
        f"First {len(documents)} documents for tenant {tenant_id}, connector {connector_id}:"
    )
    print_documents(documents)


def search_for_document(
    index_name: str,
    document_id: str | None = None,
    tenant_id: str = POSTGRES_DEFAULT_SCHEMA,
    max_hits: int | None = 10,
) -> List[Dict[str, Any]]:
    yql_query = f"select * from sources {index_name}"

    conditions = []
    if document_id is not None:
        conditions.append(f'document_id contains "{document_id}"')

    # if tenant_id is not None:
    #     conditions.append(f'tenant_id contains "{tenant_id}"')

    if conditions:
        yql_query += " where " + " and ".join(conditions)

    params: dict[str, Any] = {"yql": yql_query}
    if max_hits is not None:
        params["hits"] = max_hits
    with get_vespa_http_client() as client:
        response = client.get(f"{SEARCH_ENDPOINT}search/", params=params)
        response.raise_for_status()
        result = response.json()
        documents = result.get("root", {}).get("children", [])
        logger.info(f"Found {len(documents)} documents from query.")
        return documents


def search_documents(
    tenant_id: str, connector_id: int, query: str, n: int = 10
) -> None:
    # Search documents for a specific tenant and connector.
    index_name = get_index_name(tenant_id)
    logger.info(
        f"Searching documents for tenant={tenant_id}, connector_id={connector_id}, query='{query}'"
    )
    yql = f"select * from sources {index_name} where userInput(@query)"
    documents = query_vespa(yql, tenant_id, limit=n)
    print(f"Search results for query '{query}' in tenant {tenant_id}:")
    print_documents(documents)


def update_document(
    tenant_id: str, connector_id: int, doc_id: str, fields: Dict[str, Any]
) -> None:
    # Update a specific document.
    index_name = get_index_name(tenant_id)
    logger.info(
        f"Updating document doc_id={doc_id} in tenant={tenant_id}, connector_id={connector_id}"
    )
    url = DOCUMENT_ID_ENDPOINT.format(index_name=index_name) + f"/{doc_id}"
    update_request = {"fields": {k: {"assign": v} for k, v in fields.items()}}
    with get_vespa_http_client() as client:
        response = client.put(url, json=update_request)
        response.raise_for_status()
        logger.info(f"Document {doc_id} updated successfully.")
        print(f"Document {doc_id} updated successfully")


def delete_document(tenant_id: str, connector_id: int, doc_id: str) -> None:
    # Delete a specific document.
    index_name = get_index_name(tenant_id)
    logger.info(
        f"Deleting document doc_id={doc_id} in tenant={tenant_id}, connector_id={connector_id}"
    )
    url = DOCUMENT_ID_ENDPOINT.format(index_name=index_name) + f"/{doc_id}"
    with get_vespa_http_client() as client:
        response = client.delete(url)
        response.raise_for_status()
        logger.info(f"Document {doc_id} deleted successfully.")
        print(f"Document {doc_id} deleted successfully")


def list_documents(n: int = 10, tenant_id: Optional[str] = None) -> None:
    # List documents from any source, filtered by tenant if provided.
    logger.info(f"Listing up to {n} documents for tenant={tenant_id or 'ALL'}")
    yql = "select * from sources * where true"
    # if tenant_id:
    #     yql += f" and tenant_id contains '{tenant_id}'"
    documents = query_vespa(yql, tenant_id=tenant_id, limit=n)
    print(f"Total documents found: {len(documents)}")
    logger.info(f"Total documents found: {len(documents)}")
    print(f"First {min(n, len(documents))} documents:")
    for doc in documents[:n]:
        print(json.dumps(doc, indent=2))
        print("-" * 80)


def get_document_and_chunk_counts(
    tenant_id: str, cc_pair_id: int, filter_doc: DocumentFilter | None = None
) -> Dict[str, int]:
    # Return a dict mapping each document ID to its chunk count for a given connector.
    with get_session_with_tenant(tenant_id=tenant_id) as session:
        doc_ids_data = (
            session.query(DocumentByConnectorCredentialPair.id, Document.link)
            .join(
                ConnectorCredentialPair,
                and_(
                    DocumentByConnectorCredentialPair.connector_id
                    == ConnectorCredentialPair.connector_id,
                    DocumentByConnectorCredentialPair.credential_id
                    == ConnectorCredentialPair.credential_id,
                ),
            )
            .join(Document, DocumentByConnectorCredentialPair.id == Document.id)
            .filter(ConnectorCredentialPair.id == cc_pair_id)
            .distinct()
            .all()
        )
        doc_ids = []
        for doc_id, link in doc_ids_data:
            if filter_doc and filter_doc.link:
                if link and filter_doc.link.lower() in link.lower():
                    doc_ids.append(doc_id)
            else:
                doc_ids.append(doc_id)
        chunk_counts_data = (
            session.query(Document.id, Document.chunk_count)
            .filter(Document.id.in_(doc_ids))
            .all()
        )
    return {
        doc_id: chunk_count
        for doc_id, chunk_count in chunk_counts_data
        if chunk_count is not None
    }


def get_chunk_ids_for_connector(
    tenant_id: str,
    cc_pair_id: int,
    index_name: str,
    filter_doc: DocumentFilter | None = None,
) -> List[UUID]:
    # Return chunk IDs for a given connector.
    doc_id_to_new_chunk_cnt = get_document_and_chunk_counts(
        tenant_id, cc_pair_id, filter_doc
    )
    doc_infos: List[EnrichedDocumentIndexingInfo] = [
        VespaIndex.enrich_basic_chunk_info(
            index_name=index_name,
            http_client=get_vespa_http_client(),
            document_id=doc_id,
            previous_chunk_count=doc_id_to_new_chunk_cnt.get(doc_id, 0),
            new_chunk_count=0,
        )
        for doc_id in doc_id_to_new_chunk_cnt.keys()
    ]
    chunk_ids = get_document_chunk_ids(
        enriched_document_info_list=doc_infos,
        tenant_id=tenant_id,
        large_chunks_enabled=False,
    )
    if not isinstance(chunk_ids, list):
        raise ValueError(f"Expected list of chunk IDs, got {type(chunk_ids)}")
    return chunk_ids


def get_document_acls(
    tenant_id: str,
    cc_pair_id: int,
    n: int | None = 10,
    filter_doc: DocumentFilter | None = None,
) -> None:
    # Fetch document ACLs for the given tenant and connector pair.
    index_name = get_index_name(tenant_id)
    logger.info(
        f"Fetching document ACLs for tenant={tenant_id}, cc_pair_id={cc_pair_id}"
    )
    chunk_ids: List[UUID] = get_chunk_ids_for_connector(
        tenant_id, cc_pair_id, index_name, filter_doc
    )
    vespa_client = get_vespa_http_client()

    target_ids = chunk_ids if n is None else chunk_ids[:n]
    logger.info(
        f"Found {len(chunk_ids)} chunk IDs, showing ACLs for {len(target_ids)}."
    )
    for doc_chunk_id in target_ids:
        document_url = (
            f"{DOCUMENT_ID_ENDPOINT.format(index_name=index_name)}/{str(doc_chunk_id)}"
        )
        response = vespa_client.get(document_url)
        if response.status_code == 200:
            fields = response.json().get("fields", {})

            document_id = fields.get("document_id") or fields.get(
                "documentid", "Unknown"
            )
            acls = fields.get("access_control_list", {})
            title = fields.get("title", "")
            source_type = fields.get("source_type", "")
            doc_sets = fields.get("document_sets", [])
            user_file = fields.get("user_file", None)
            source_links_raw = fields.get("source_links", "{}")
            try:
                source_links = json.loads(source_links_raw)
            except json.JSONDecodeError:
                source_links = {}

            print(f"Document Chunk ID: {doc_chunk_id}")
            print(f"Document ID: {document_id}")
            print(f"ACLs:\n{json.dumps(acls, indent=2)}")
            print(f"Source Links: {source_links}")
            print(f"Title: {title}")
            print(f"Source Type: {source_type}")
            print(f"Document Sets: {doc_sets}")
            print(f"User File: {user_file}")
            if MULTI_TENANT:
                print(f"Tenant ID: {fields.get('tenant_id', 'N/A')}")
            print("-" * 80)
        else:
            logger.error(f"Failed to fetch document for chunk ID: {doc_chunk_id}")
            print(f"Failed to fetch document for chunk ID: {doc_chunk_id}")
            print(f"Status Code: {response.status_code}")
            print("-" * 80)


def get_current_chunk_count(document_id: str) -> int | None:
    with get_session_with_current_tenant() as session:
        return (
            session.query(Document.chunk_count)
            .filter(Document.id == document_id)
            .scalar()
        )


def get_number_of_chunks_we_think_exist(
    document_id: str, index_name: str, tenant_id: str
) -> int:
    current_chunk_count = get_current_chunk_count(document_id)
    print(f"Current chunk count: {current_chunk_count}")

    doc_info = VespaIndex.enrich_basic_chunk_info(
        index_name=index_name,
        http_client=get_vespa_http_client(),
        document_id=document_id,
        previous_chunk_count=current_chunk_count,
        new_chunk_count=0,
    )

    chunk_ids = get_document_chunk_ids(
        enriched_document_info_list=[doc_info],
        tenant_id=tenant_id,
        large_chunks_enabled=False,
    )
    return len(chunk_ids)


class VespaDebugging:
    # Class for managing Vespa debugging actions.
    def __init__(self, tenant_id: str = POSTGRES_DEFAULT_SCHEMA):
        SqlEngine.init_engine(pool_size=20, max_overflow=5)
        CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
        self.tenant_id = tenant_id
        self.index_name = get_index_name(self.tenant_id)

    def sample_document_counts(self) -> None:
        # Sample random documents and compare chunk counts
        mismatches = []
        no_chunks = []
        with get_session_with_current_tenant() as session:
            # Get a sample of random documents
            from sqlalchemy import func

            sample_docs = (
                session.query(Document.id, Document.link, Document.semantic_id)
                .order_by(func.random())
                .limit(1000)
                .all()
            )

            for doc in sample_docs:
                document_id, link, semantic_id = doc
                (
                    number_of_chunks_in_vespa,
                    number_of_chunks_we_think_exist,
                ) = self.compare_chunk_count(document_id)
                if number_of_chunks_in_vespa != number_of_chunks_we_think_exist:
                    mismatches.append(
                        (
                            document_id,
                            link,
                            semantic_id,
                            number_of_chunks_in_vespa,
                            number_of_chunks_we_think_exist,
                        )
                    )
                elif number_of_chunks_in_vespa == 0:
                    no_chunks.append((document_id, link, semantic_id))

        # Print results
        print("\nDocuments with mismatched chunk counts:")
        for doc_id, link, semantic_id, vespa_count, expected_count in mismatches:
            print(f"Document ID: {doc_id}")
            print(f"Link: {link}")
            print(f"Semantic ID: {semantic_id}")
            print(f"Chunks in Vespa: {vespa_count}")
            print(f"Expected chunks: {expected_count}")
            print("-" * 80)

        print("\nDocuments with no chunks in Vespa:")
        for doc_id, link, semantic_id in no_chunks:
            print(f"Document ID: {doc_id}")
            print(f"Link: {link}")
            print(f"Semantic ID: {semantic_id}")
            print("-" * 80)

        print(f"\nTotal mismatches: {len(mismatches)}")
        print(f"Total documents with no chunks: {len(no_chunks)}")

    def print_config(self) -> None:
        # Print Vespa config.
        print_vespa_config()

    def check_connectivity(self) -> None:
        # Check Vespa connectivity.
        check_vespa_connectivity()

    def list_documents(self, n: int = 10) -> None:
        # List documents for a tenant.
        list_documents(n, self.tenant_id)

    def list_connector(self, cc_pair_id: int, n: int = 10) -> None:
        # List documents for a specific connector-credential pair in the tenant
        logger.info(
            f"Listing documents for tenant={self.tenant_id}, cc_pair_id={cc_pair_id}"
        )

        # Get document IDs for this connector-credential pair
        with get_session_with_tenant(tenant_id=self.tenant_id) as session:
            # First get the connector_id from the cc_pair_id
            cc_pair = (
                session.query(ConnectorCredentialPair)
                .filter(ConnectorCredentialPair.id == cc_pair_id)
                .first()
            )

            if not cc_pair:
                print(f"No connector-credential pair found with ID {cc_pair_id}")
                return

            connector_id = cc_pair.connector_id

            # Now get document IDs for this connector
            doc_ids_data = (
                session.query(DocumentByConnectorCredentialPair.id)
                .filter(DocumentByConnectorCredentialPair.connector_id == connector_id)
                .distinct()
                .all()
            )

            doc_ids = [doc_id[0] for doc_id in doc_ids_data]

        if not doc_ids:
            print(f"No documents found for connector-credential pair ID {cc_pair_id}")
            return

        print(
            f"Found {len(doc_ids)} documents for connector-credential pair ID {cc_pair_id}"
        )

        # Limit to the first n document IDs
        target_doc_ids = doc_ids[:n]
        print(f"Retrieving details for first {len(target_doc_ids)} documents")
        # Search for each document in Vespa
        for doc_id in target_doc_ids:
            docs = search_for_document(self.index_name, doc_id, self.tenant_id)
            if not docs:
                print(f"No chunks found in Vespa for document ID: {doc_id}")
                continue

            print(f"Document ID: {doc_id}")
            print(f"Found {len(docs)} chunks in Vespa")

            # Print each chunk with all fields except embeddings
            for i, doc in enumerate(docs):
                print(f"  Chunk {i+1}:")
                fields = doc.get("fields", {})

                # Print all fields except embeddings
                for field_name, field_value in sorted(fields.items()):
                    # Skip embedding fields
                    if "embedding" in field_name:
                        continue

                    # Format the output based on field type
                    if isinstance(field_value, dict) or isinstance(field_value, list):
                        # Truncate dictionaries and lists
                        truncated = (
                            str(field_value)[:50] + "..."
                            if len(str(field_value)) > 50
                            else str(field_value)
                        )
                        print(f"    {field_name}: {truncated}")
                    else:
                        # Truncate strings and other values
                        str_value = str(field_value)
                        truncated = (
                            str_value[:50] + "..." if len(str_value) > 50 else str_value
                        )
                        print(f"    {field_name}: {truncated}")

                print("-" * 40)  # Separator between chunks

            print("=" * 80)  # Separator between documents

    def compare_chunk_count(self, document_id: str) -> tuple[int, int]:
        docs = search_for_document(self.index_name, document_id, max_hits=None)
        number_of_chunks_we_think_exist = get_number_of_chunks_we_think_exist(
            document_id, self.index_name, self.tenant_id
        )
        print(
            f"Number of chunks in Vespa: {len(docs)}, Number of chunks we think exist: {number_of_chunks_we_think_exist}"
        )
        return len(docs), number_of_chunks_we_think_exist

    def search_documents(self, connector_id: int, query: str, n: int = 10) -> None:
        # Search documents for a tenant and connector.
        search_documents(self.tenant_id, connector_id, query, n)

    def update_document(
        self, connector_id: int, doc_id: str, fields: Dict[str, Any]
    ) -> None:
        update_document(self.tenant_id, connector_id, doc_id, fields)

    def delete_documents_for_tenant(self, count: int | None = None) -> None:
        if not self.tenant_id:
            raise Exception("Tenant ID is not set")
        delete_documents_for_tenant(self.index_name, self.tenant_id, count=count)

    def search_for_document(
        self, document_id: str | None = None, tenant_id: str = POSTGRES_DEFAULT_SCHEMA
    ) -> List[Dict[str, Any]]:
        return search_for_document(self.index_name, document_id, tenant_id)

    def delete_document(self, connector_id: int, doc_id: str) -> None:
        # Delete a document.
        delete_document(self.tenant_id, connector_id, doc_id)

    def acls_by_link(self, cc_pair_id: int, link: str) -> None:
        # Get ACLs for a document matching a link.
        get_document_acls(
            self.tenant_id, cc_pair_id, n=None, filter_doc=DocumentFilter(link=link)
        )

    def acls(self, cc_pair_id: int, n: int | None = 10) -> None:
        # Get ACLs for a connector.
        get_document_acls(self.tenant_id, cc_pair_id, n)


def delete_where(
    index_name: str,
    selection: str,
    cluster: str = "default",
    bucket_space: str | None = None,
    continuation: str | None = None,
    time_chunk: str | None = None,
    timeout: str | None = None,
    tracelevel: int | None = None,
) -> None:
    """
    Removes visited documents in `cluster` where the given selection
    is true, using Vespa's 'delete where' endpoint.


    :param index_name: Typically <namespace>/<document-type> from your schema
    :param selection:  The selection string, e.g., "true" or "foo contains 'bar'"
    :param cluster:    The name of the cluster where documents reside
    :param bucket_space:  e.g. 'global' or 'default'
    :param continuation:  For chunked visits
    :param time_chunk:    If you want to chunk the visit by time
    :param timeout:       e.g. '10s'
    :param tracelevel:    Increase for verbose logs
    """
    # Using index_name of form <namespace>/<document-type>, e.g. "nomic_ai_nomic_embed_text_v1"
    # This route ends with "/docid/" since the actual ID is not specified — we rely on "selection".
    path = f"/document/v1/{index_name}/docid/"

    params = {
        "cluster": cluster,
        "selection": selection,
    }

    # Optional parameters
    if bucket_space is not None:
        params["bucketSpace"] = bucket_space
    if continuation is not None:
        params["continuation"] = continuation
    if time_chunk is not None:
        params["timeChunk"] = time_chunk
    if timeout is not None:
        params["timeout"] = timeout
    if tracelevel is not None:
        params["tracelevel"] = tracelevel  # type: ignore

    with get_vespa_http_client() as client:
        url = f"{VESPA_APPLICATION_ENDPOINT}{path}"
        logger.info(f"Performing 'delete where' on {url} with selection={selection}...")
        response = client.delete(url, params=params)
        # (Optionally, you can keep fetching `continuation` from the JSON response
        #  if you have more documents to delete in chunks.)
        response.raise_for_status()  # will raise HTTPError if not 2xx
        logger.info(f"Delete where completed with status: {response.status_code}")
        print(f"Delete where completed with status: {response.status_code}")


def delete_documents_for_tenant(
    index_name: str,
    tenant_id: str,
    route: str | None = None,
    condition: str | None = None,
    timeout: str | None = None,
    tracelevel: int | None = None,
    count: int | None = None,
) -> None:
    """
    For the given tenant_id and index_name (often in the form <namespace>/<document-type>),
    find documents via search_for_document, then delete them one at a time using Vespa's
    /document/v1/<namespace>/<document-type>/docid/<document-id> endpoint.

    :param index_name: Typically <namespace>/<document-type> from your schema
    :param tenant_id:  The tenant to match in your Vespa search
    :param route:      Optional route parameter for delete
    :param condition:  Optional conditional remove
    :param timeout:    e.g. '10s'
    :param tracelevel: Increase for verbose logs
    """
    deleted_count = 0
    while True:
        # Search for documents with the given tenant_id
        docs = search_for_document(
            index_name=index_name,
            document_id=None,
            tenant_id=tenant_id,
            max_hits=100,  # Fetch in batches of 100
        )

        if not docs:
            logger.info("No more documents found to delete.")
            break

        with get_vespa_http_client() as client:
            for doc in docs:
                if count is not None and deleted_count >= count:
                    logger.info(f"Reached maximum delete limit of {count} documents.")
                    return

                fields = doc.get("fields", {})
                doc_id_value = fields.get("document_id") or fields.get("documentid")
                tenant_id = fields.get("tenant_id")
                if tenant_id != tenant_id:
                    raise Exception("Tenant ID mismatch")

                if not doc_id_value:
                    logger.warning(
                        "Skipping a document that has no document_id in 'fields'."
                    )
                    continue

                url = f"{DOCUMENT_ID_ENDPOINT.format(index_name=index_name)}/{doc_id_value}"

                params = {}
                if condition:
                    params["condition"] = condition
                if route:
                    params["route"] = route
                if timeout:
                    params["timeout"] = timeout
                if tracelevel is not None:
                    params["tracelevel"] = str(tracelevel)

                response = client.delete(url, params=params)
                if response.status_code == 200:
                    logger.info(f"Successfully deleted doc_id={doc_id_value}")
                    deleted_count += 1
                else:
                    logger.error(
                        f"Failed to delete doc_id={doc_id_value}, "
                        f"status={response.status_code}, response={response.text}"
                    )
                    print(
                        f"Could not delete doc_id={doc_id_value}. "
                        f"Status={response.status_code}, response={response.text}"
                    )
                    raise Exception(
                        f"Could not delete doc_id={doc_id_value}. "
                        f"Status={response.status_code}, response={response.text}"
                    )

    logger.info(f"Deleted {deleted_count} documents in total.")


def main() -> None:
    SqlEngine.init_engine(pool_size=20, max_overflow=5)
    parser = argparse.ArgumentParser(description="Vespa debugging tool")
    parser.add_argument(
        "--action",
        choices=[
            "config",
            "connect",
            "list_docs",
            "list_connector",
            "search",
            "update",
            "delete",
            "get_acls",
            "delete-all-documents",
        ],
        required=True,
        help="Action to perform",
    )
    parser.add_argument("--tenant-id", help="Tenant ID")
    parser.add_argument("--connector-id", type=int, help="Connector ID")
    parser.add_argument("--cc-pair-id", type=int, help="Connector-Credential Pair ID")
    parser.add_argument(
        "--n", type=int, default=10, help="Number of documents to retrieve"
    )
    parser.add_argument("--query", help="Search query (for search action)")
    parser.add_argument("--doc-id", help="Document ID (for update and delete actions)")
    parser.add_argument(
        "--fields", help="Fields to update, in JSON format (for update)"
    )
    parser.add_argument(
        "--count",
        type=int,
        help="Maximum number of documents to delete (for delete-all-documents)",
    )
    parser.add_argument("--link", help="Document link (for get_acls filter)")

    args = parser.parse_args()
    vespa_debug = VespaDebugging(args.tenant_id)

    CURRENT_TENANT_ID_CONTEXTVAR.set(args.tenant_id or "public")
    if args.action == "delete-all-documents":
        if not args.tenant_id:
            parser.error("--tenant-id is required for delete-all-documents action")
        vespa_debug.delete_documents_for_tenant(count=args.count)
    elif args.action == "config":
        vespa_debug.print_config()
    elif args.action == "connect":
        vespa_debug.check_connectivity()
    elif args.action == "list_docs":
        vespa_debug.list_documents(args.n)
    elif args.action == "list_connector":
        if args.cc_pair_id is None:
            parser.error("--cc-pair-id is required for list_connector action")
        vespa_debug.list_connector(args.cc_pair_id, args.n)
    elif args.action == "search":
        if not args.query or args.connector_id is None:
            parser.error("--query and --connector-id are required for search action")
        vespa_debug.search_documents(args.connector_id, args.query, args.n)
    elif args.action == "update":
        if not args.doc_id or not args.fields or args.connector_id is None:
            parser.error(
                "--doc-id, --fields, and --connector-id are required for update action"
            )
        fields = json.loads(args.fields)
        vespa_debug.update_document(args.connector_id, args.doc_id, fields)
    elif args.action == "delete":
        if not args.doc_id or args.connector_id is None:
            parser.error("--doc-id and --connector-id are required for delete action")
        vespa_debug.delete_document(args.connector_id, args.doc_id)
    elif args.action == "get_acls":
        if args.cc_pair_id is None:
            parser.error("--cc-pair-id is required for get_acls action")

        if args.link is None:
            vespa_debug.acls(args.cc_pair_id, args.n)
        else:
            vespa_debug.acls_by_link(args.cc_pair_id, args.link)


if __name__ == "__main__":
    main()
