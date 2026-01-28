#!/usr/bin/env python3
"""
Debug utility for querying and inspecting hierarchy data in OpenSearch.

This script connects to OpenSearch and allows you to:
- Query documents by ID and view their hierarchy ancestor node IDs
- List documents that have hierarchy data

Usage:
    python query_hierarchy_debug.py --document-id <doc_id>
    python query_hierarchy_debug.py --list-with-hierarchy

Environment Variables:
    OPENSEARCH_HOST: OpenSearch host (default: localhost)
    OPENSEARCH_PORT: OpenSearch port (default: 9200)

Dependencies:
    pip install opensearch-py
"""

import argparse
import os
import sys

try:
    from opensearchpy import OpenSearch
except ImportError as e:
    print("Error: Missing dependency. Run: pip install opensearch-py")
    print(f"Details: {e}")
    sys.exit(1)


def get_client() -> OpenSearch:
    """Create OpenSearch client from environment variables."""
    host = os.environ.get("OPENSEARCH_HOST", "localhost")
    port = int(os.environ.get("OPENSEARCH_PORT", "9200"))
    return OpenSearch(
        hosts=[{"host": host, "port": port}],
        http_auth=None,  # Add auth if needed
        use_ssl=False,
    )


def query_document(client: OpenSearch, index: str, doc_id: str) -> None:
    """Query a specific document and view its hierarchy ancestor node IDs."""
    query = {"query": {"term": {"document_id": doc_id}}, "size": 10}

    result = client.search(index=index, body=query)
    hits = result.get("hits", {}).get("hits", [])

    if not hits:
        print(f"No document found with ID: {doc_id}")
        return

    print(f"Found {len(hits)} chunk(s) for document ID: {doc_id}\n")

    for hit in hits:
        source = hit.get("_source", {})
        ancestor_ids = source.get("ancestor_hierarchy_node_ids", [])

        print(f"  Chunk Index: {source.get('chunk_index')}")
        print(f"  Semantic ID: {source.get('semantic_identifier', 'N/A')}")

        if ancestor_ids:
            print(f"  Ancestor Node IDs: {ancestor_ids}")
        else:
            print("  Ancestor Node IDs: (none)")
        print()


def list_with_hierarchy(client: OpenSearch, index: str, limit: int = 10) -> None:
    """List documents that have hierarchy data."""
    query = {
        "query": {"exists": {"field": "ancestor_hierarchy_node_ids"}},
        "size": limit,
        "_source": [
            "document_id",
            "chunk_index",
            "ancestor_hierarchy_node_ids",
            "semantic_identifier",
        ],
    }

    result = client.search(index=index, body=query)
    hits = result.get("hits", {}).get("hits", [])

    print(f"Found {len(hits)} document chunks with hierarchy data (limit: {limit}):\n")

    for hit in hits:
        source = hit.get("_source", {})
        ancestor_ids = source.get("ancestor_hierarchy_node_ids", [])

        print(f"  {source.get('document_id')} (chunk {source.get('chunk_index')})")
        print(f"    Semantic ID: {source.get('semantic_identifier', 'N/A')}")
        print(f"    Ancestors: {ancestor_ids}\n")


def list_indices(client: OpenSearch) -> None:
    """List available indices."""
    indices = client.indices.get_alias(index="*")
    print("Available indices:")
    for index_name in sorted(indices.keys()):
        if not index_name.startswith("."):  # Skip system indices
            print(f"  - {index_name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Debug hierarchy data in OpenSearch")
    parser.add_argument("--document-id", help="Query a specific document by ID")
    parser.add_argument(
        "--list-with-hierarchy",
        action="store_true",
        help="List documents with hierarchy data",
    )
    parser.add_argument("--list-indices", action="store_true", help="List all indices")
    parser.add_argument("--index", default="onyx_index", help="OpenSearch index name")
    parser.add_argument("--limit", type=int, default=10, help="Limit for list queries")

    args = parser.parse_args()

    client = get_client()

    if args.list_indices:
        list_indices(client)
    elif args.document_id:
        query_document(client, args.index, args.document_id)
    elif args.list_with_hierarchy:
        list_with_hierarchy(client, args.index, args.limit)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
