#!/usr/bin/env python3
"""A utility to interact with OpenSearch.

Usage:
    python3 opensearch_debug.py --help
    python3 opensearch_debug.py list
    python3 opensearch_debug.py delete <index_name>

Environment Variables:
    OPENSEARCH_HOST: OpenSearch host
    OPENSEARCH_REST_API_PORT: OpenSearch port
    OPENSEARCH_ADMIN_USERNAME: Admin username
    OPENSEARCH_ADMIN_PASSWORD: Admin password

Dependencies:
    backend/shared_configs/configs.py
    backend/onyx/document_index/opensearch/client.py
"""

import argparse
import os
import sys

from onyx.document_index.opensearch.client import OpenSearchClient
from onyx.document_index.opensearch.client import OpenSearchIndexClient
from shared_configs.configs import MULTI_TENANT


def list_indices(client: OpenSearchClient) -> None:
    indices = client.list_indices_with_info()
    print(f"Found {len(indices)} indices.")
    print("-" * 80)
    for index in sorted(indices, key=lambda x: x.name):
        print(f"Index: {index.name}")
        print(f"Health: {index.health}")
        print(f"Status: {index.status}")
        print(f"Num Primary Shards: {index.num_primary_shards}")
        print(f"Num Replica Shards: {index.num_replica_shards}")
        print(f"Docs Count: {index.docs_count}")
        print(f"Docs Deleted: {index.docs_deleted}")
        print(f"Created At: {index.created_at}")
        print(f"Total Size: {index.total_size}")
        print(f"Primary Shards Size: {index.primary_shards_size}")
        print("-" * 80)


def delete_index(client: OpenSearchIndexClient) -> None:
    if not client.index_exists():
        print(f"Index '{client.index_name}' does not exist.")
        return

    confirm = input(f"Delete index '{client.index_name}'? (yes/no): ")
    if confirm.lower() != "yes":
        print("Aborted.")
        return

    if client.delete_index():
        print(f"Deleted index '{client.index_name}'.")
    else:
        print(f"Failed to delete index '{client.index_name}' for an unknown reason.")


def main() -> None:
    def add_standard_arguments(parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--host",
            help="OpenSearch host. If not provided, will fall back to OPENSEARCH_HOST, then prompt "
            "for input.",
            type=str,
            default=os.environ.get("OPENSEARCH_HOST", ""),
        )
        parser.add_argument(
            "--port",
            help="OpenSearch port. If not provided, will fall back to OPENSEARCH_REST_API_PORT, "
            "then prompt for input.",
            type=int,
            default=int(os.environ.get("OPENSEARCH_REST_API_PORT", 0)),
        )
        parser.add_argument(
            "--username",
            help="OpenSearch username. If not provided, will fall back to OPENSEARCH_ADMIN_USERNAME, "
            "then prompt for input.",
            type=str,
            default=os.environ.get("OPENSEARCH_ADMIN_USERNAME", ""),
        )
        parser.add_argument(
            "--password",
            help="OpenSearch password. If not provided, will fall back to OPENSEARCH_ADMIN_PASSWORD, "
            "then prompt for input.",
            type=str,
            default=os.environ.get("OPENSEARCH_ADMIN_PASSWORD", ""),
        )
        parser.add_argument(
            "--no-ssl", help="Disable SSL.", action="store_true", default=False
        )
        parser.add_argument(
            "--no-verify-certs",
            help="Disable certificate verification (for self-signed certs).",
            action="store_true",
            default=False,
        )
        parser.add_argument(
            "--use-aws-managed-opensearch",
            help="Whether to use AWS-managed OpenSearch. If not provided, will fall back to checking "
            "USING_AWS_MANAGED_OPENSEARCH=='true', then default to False.",
            action=argparse.BooleanOptionalAction,
            default=os.environ.get("USING_AWS_MANAGED_OPENSEARCH", "").lower()
            == "true",
        )

    parser = argparse.ArgumentParser(
        description="A utility to interact with OpenSearch."
    )
    subparsers = parser.add_subparsers(
        dest="command", help="Command to execute.", required=True
    )

    list_parser = subparsers.add_parser("list", help="List all indices with info.")
    add_standard_arguments(list_parser)

    delete_parser = subparsers.add_parser("delete", help="Delete an index.")
    delete_parser.add_argument("index", help="Index name.", type=str)
    add_standard_arguments(delete_parser)

    args = parser.parse_args()

    if not (host := args.host or input("Enter the OpenSearch host: ")):
        print("Error: OpenSearch host is required.")
        sys.exit(1)
    if not (port := args.port or int(input("Enter the OpenSearch port: "))):
        print("Error: OpenSearch port is required.")
        sys.exit(1)
    if not (username := args.username or input("Enter the OpenSearch username: ")):
        print("Error: OpenSearch username is required.")
        sys.exit(1)
    if not (password := args.password or input("Enter the OpenSearch password: ")):
        print("Error: OpenSearch password is required.")
        sys.exit(1)
    print("Using AWS-managed OpenSearch: ", args.use_aws_managed_opensearch)
    print(f"MULTI_TENANT: {MULTI_TENANT}")

    with (
        OpenSearchIndexClient(
            index_name=args.index,
            host=host,
            port=port,
            auth=(username, password),
            use_ssl=not args.no_ssl,
            verify_certs=not args.no_verify_certs,
        )
        if args.command == "delete"
        else OpenSearchClient(
            host=host,
            port=port,
            auth=(username, password),
            use_ssl=not args.no_ssl,
            verify_certs=not args.no_verify_certs,
        )
    ) as client:
        if not client.ping():
            print("Error: Could not connect to OpenSearch.")
            sys.exit(1)

        if args.command == "list":
            list_indices(client)
        elif args.command == "delete":
            delete_index(client)


if __name__ == "__main__":
    main()
