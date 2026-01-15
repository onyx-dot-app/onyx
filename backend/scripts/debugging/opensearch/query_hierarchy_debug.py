#!/usr/bin/env python3
"""
Debug utility for querying and inspecting hierarchy bitmap data in OpenSearch.

This script connects to OpenSearch and allows you to:
- Query documents by ID and decode their hierarchy bitmap
- List documents that have hierarchy data
- Decode raw base64 bitmap values

Usage:
    python query_hierarchy_debug.py --document-id <doc_id>
    python query_hierarchy_debug.py --list-with-hierarchy
    python query_hierarchy_debug.py --decode-field <base64_value>

Environment Variables:
    OPENSEARCH_HOST: OpenSearch host (default: localhost)
    OPENSEARCH_PORT: OpenSearch port (default: 9200)

Dependencies:
    pip install opensearch-py pyroaring
"""

import argparse
import base64
import os
import sys

try:
    from opensearchpy import OpenSearch
    from pyroaring import BitMap
except ImportError as e:
    print("Error: Missing dependency. Run: pip install opensearch-py pyroaring")
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


def decode_bitmap(encoded: str) -> list[int]:
    """Decode base64-encoded RoaringBitmap to list of integers."""
    if not encoded:
        return []
    serialized = base64.b64decode(encoded.encode("utf-8"))
    bitmap = BitMap.deserialize(serialized)
    return sorted(bitmap)


def query_document(client: OpenSearch, index: str, doc_id: str) -> None:
    """Query a specific document and decode its hierarchy bitmap."""
    query = {"query": {"term": {"document_id": doc_id}}, "size": 10}

    result = client.search(index=index, body=query)
    hits = result.get("hits", {}).get("hits", [])

    if not hits:
        print(f"No document found with ID: {doc_id}")
        return

    print(f"Found {len(hits)} chunk(s) for document ID: {doc_id}\n")

    for hit in hits:
        source = hit.get("_source", {})
        bitmap_value = source.get("ancestor_hierarchy_bitmap", "")

        print(f"  Chunk Index: {source.get('chunk_index')}")
        print(f"  Semantic ID: {source.get('semantic_identifier', 'N/A')}")

        if bitmap_value:
            truncated = (
                f"{bitmap_value[:50]}..." if len(bitmap_value) > 50 else bitmap_value
            )
            print(f"  Raw Bitmap: {truncated}")
            ids = decode_bitmap(bitmap_value)
            print(f"  Ancestor Node IDs: {ids}")
        else:
            print("  Ancestor Node IDs: (none)")
        print()


def list_with_hierarchy(client: OpenSearch, index: str, limit: int = 10) -> None:
    """List documents that have hierarchy bitmap data."""
    query = {
        "query": {"exists": {"field": "ancestor_hierarchy_bitmap"}},
        "size": limit,
        "_source": [
            "document_id",
            "chunk_index",
            "ancestor_hierarchy_bitmap",
            "semantic_identifier",
        ],
    }

    result = client.search(index=index, body=query)
    hits = result.get("hits", {}).get("hits", [])

    print(f"Found {len(hits)} document chunks with hierarchy data (limit: {limit}):\n")

    for hit in hits:
        source = hit.get("_source", {})
        bitmap_value = source.get("ancestor_hierarchy_bitmap", "")
        ids = decode_bitmap(bitmap_value) if bitmap_value else []

        print(f"  {source.get('document_id')} (chunk {source.get('chunk_index')})")
        print(f"    Semantic ID: {source.get('semantic_identifier', 'N/A')}")
        print(f"    Ancestors: {ids}\n")


def list_indices(client: OpenSearch) -> None:
    """List available indices."""
    indices = client.indices.get_alias(index="*")
    print("Available indices:")
    for index_name in sorted(indices.keys()):
        if not index_name.startswith("."):  # Skip system indices
            print(f"  - {index_name}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Debug hierarchy bitmap data in OpenSearch"
    )
    parser.add_argument("--document-id", help="Query a specific document by ID")
    parser.add_argument(
        "--list-with-hierarchy",
        action="store_true",
        help="List documents with hierarchy data",
    )
    parser.add_argument("--decode-field", help="Decode a base64 bitmap value")
    parser.add_argument("--list-indices", action="store_true", help="List all indices")
    parser.add_argument("--index", default="onyx_index", help="OpenSearch index name")
    parser.add_argument("--limit", type=int, default=10, help="Limit for list queries")

    args = parser.parse_args()

    if args.decode_field:
        ids = decode_bitmap(args.decode_field)
        print(f"Decoded IDs: {ids}")
        print(f"Count: {len(ids)}")
        return

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
