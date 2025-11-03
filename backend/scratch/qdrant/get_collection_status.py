"""
Script to get and display the status of a Qdrant collection.

Usage:
    python -m scratch.qdrant.get_collection_status [collection_name]

If no collection name is provided, shows ACCURACY_TESTING by default.
"""

import sys

from scratch.qdrant.client import QdrantClient
from scratch.qdrant.schemas.collection_name import CollectionName


def main():
    # Get collection name from command line or use default
    if len(sys.argv) > 1:
        collection_name_str = sys.argv[1]
        # Try to match to CollectionName enum
        try:
            collection_name = CollectionName[collection_name_str.upper()]
        except KeyError:
            # If not in enum, use the string directly
            collection_name = collection_name_str
    else:
        collection_name = CollectionName.ACCURACY_TESTING

    # Initialize client
    client = QdrantClient()

    print("=" * 80)
    print(f"COLLECTION STATUS: {collection_name}")
    print("=" * 80)
    print()

    try:
        collection_info = client.get_collection(collection_name)

        print("General Info:")
        print(f"  Status: {collection_info.status}")
        print(f"  Points count: {collection_info.points_count:,}")
        print(f"  Indexed vectors count: {collection_info.indexed_vectors_count:,}")
        print(f"  Optimizer status: {collection_info.optimizer_status}")
        print()

        print("Configuration:")
        print(f"  Vectors config: {collection_info.config.params.vectors}")
        print(
            f"  Sparse vectors config: {collection_info.config.params.sparse_vectors}"
        )
        print(f"  Shard number: {collection_info.config.params.shard_number}")
        print(
            f"  Replication factor: {collection_info.config.params.replication_factor}"
        )
        print()

        if collection_info.config.optimizer_config:
            print("Optimizer Config:")
            print(
                f"  Deleted threshold: {collection_info.config.optimizer_config.deleted_threshold}"
            )
            print(
                f"  Vacuum min vector number: {collection_info.config.optimizer_config.vacuum_min_vector_number}"
            )
            print(
                f"  Default segment number: {collection_info.config.optimizer_config.default_segment_number}"
            )
            print(
                f"  Max segment size: {collection_info.config.optimizer_config.max_segment_size}"
            )
            print(
                f"  Memmap threshold: {collection_info.config.optimizer_config.memmap_threshold}"
            )
            print(
                f"  Indexing threshold: {collection_info.config.optimizer_config.indexing_threshold}"
            )
            print(
                f"  Flush interval sec: {collection_info.config.optimizer_config.flush_interval_sec}"
            )
            print(
                f"  Max optimization threads: {collection_info.config.optimizer_config.max_optimization_threads}"
            )
            print()

        if collection_info.payload_schema:
            print("Payload Schema:")
            for field, schema in collection_info.payload_schema.items():
                print(f"  {field}: {schema}")
            print()

    except Exception as e:
        print(f"Error retrieving collection: {e}")
        print()
        print("Available collections:")
        # Try to list collections
        try:
            collections = client.client.get_collections()
            for col in collections.collections:
                print(f"  - {col.name}")
        except Exception as list_error:
            print(f"  Could not list collections: {list_error}")


if __name__ == "__main__":
    main()
