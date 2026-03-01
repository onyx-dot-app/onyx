#!/usr/bin/env python3
"""A utility to interact with OpenSearch.

Usage:
    python3 opensearch_debug.py --help
    python3 opensearch_debug.py list
    python3 opensearch_debug.py info <index_name>
    python3 opensearch_debug.py delete <index_name>

Environment Variables:
    OPENSEARCH_HOST: OpenSearch host
    OPENSEARCH_REST_API_PORT: OpenSearch port
    OPENSEARCH_ADMIN_USERNAME: Admin username
    OPENSEARCH_ADMIN_PASSWORD: Admin password

Dependencies:
    opensearch-py
"""

import argparse
import json
import os
import sys

try:
    from opensearchpy import OpenSearch
except ImportError as e:
    print("Error: Missing dependency. Run: pip install opensearch-py")
    print(f"Details: {e}")
    sys.exit(1)


def get_client(
    host: str,
    port: int,
    username: str,
    password: str,
    use_ssl: bool,
    verify_certs: bool,
) -> OpenSearch:
    return OpenSearch(
        hosts=[{"host": host, "port": port}],
        http_auth=(username, password),
        use_ssl=use_ssl,
        verify_certs=verify_certs,
        ssl_show_warn=False,
    )


def list_indices(client: OpenSearch) -> None:
    indices = client.cat.indices(format="json")
    print(f"\n{'Index':<80} {'Health':<10} {'Docs':<10} {'Size':<10}")
    print("-" * 120)
    for idx in sorted(indices, key=lambda x: x.get("index", "")):
        name = idx.get("index", "")
        if not name.startswith("."):
            print(
                f"{name:<80} {idx.get('health', 'N/A'):<10} "
                f"{idx.get('docs.count', 'N/A'):<10} {idx.get('store.size', 'N/A'):<10}"
            )


def get_index_info(client: OpenSearch, index: str) -> None:
    if not client.indices.exists(index=index):
        print(f"Index '{index}' does not exist.")
        return

    # Get mapping.
    mapping = client.indices.get_mapping(index=index)
    print(f"\n=== Mapping for {index} ===")
    print(json.dumps(mapping, indent=2))

    # Get settings.
    settings = client.indices.get_settings(index=index)
    print(f"\n=== Settings for {index} ===")
    print(json.dumps(settings, indent=2))

    # Get doc count.
    count = client.count(index=index).get("count", 0)
    print(f"\n=== Document count: {count} ===")


def delete_index(client: OpenSearch, index: str) -> None:
    if not client.indices.exists(index=index):
        print(f"Index '{index}' does not exist.")
        return

    confirm = input(f"Delete index '{index}'? (yes/no): ")
    if confirm.lower() != "yes":
        print("Aborted.")
        return

    result = client.indices.delete(index=index)
    if result.get("acknowledged"):
        print(f"Deleted index '{index}'.")
    else:
        print(f"Failed: {result}.")


def main() -> None:
    def add_standard_arguments(parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--host",
            help="OpenSearch host. If not provided, will fall back to OPENSEARCH_HOST, then prompt for input.",
            type=str,
            default=os.environ.get("OPENSEARCH_HOST", ""),
        )
        parser.add_argument(
            "--port",
            help="OpenSearch port. If not provided, will fall back to OPENSEARCH_PORT, then prompt for input.",
            type=int,
            default=int(os.environ.get("OPENSEARCH_REST_API_PORT", 0)),
        )
        parser.add_argument(
            "--username",
            help="OpenSearch username. If not provided, will fall back to OPENSEARCH_USERNAME, then prompt for input.",
            type=str,
            default=os.environ.get("OPENSEARCH_ADMIN_USERNAME", ""),
        )
        parser.add_argument(
            "--password",
            help="OpenSearch password. If not provided, will fall back to OPENSEARCH_PASSWORD, then prompt for input.",
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

    parser = argparse.ArgumentParser(
        description="A utility to interact with OpenSearch."
    )
    subparsers = parser.add_subparsers(
        dest="command", help="Command to execute.", required=True
    )

    list_parser = subparsers.add_parser("list", help="List all indices.")
    add_standard_arguments(list_parser)

    info_parser = subparsers.add_parser("info", help="Get index info.")
    info_parser.add_argument("index", help="Index name.", type=str)
    add_standard_arguments(info_parser)

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

    client = get_client(
        host, port, username, password, not args.no_ssl, not args.no_verify_certs
    )

    try:
        if not client.ping():
            print("Error: Could not connect to OpenSearch.")
            sys.exit(1)

        if args.command == "list":
            list_indices(client)
        elif args.command == "info":
            get_index_info(client, args.index)
        elif args.command == "delete":
            delete_index(client, args.index)
    finally:
        client.close()


if __name__ == "__main__":
    main()
