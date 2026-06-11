#!/usr/bin/env python3
"""A utility to interact with OpenSearch.

Example Usage:
    Assuming running from ~/onyx/
        source .venv/bin/activate
        python backend/scripts/debugging/opensearch/opensearch_debug.py --help
        python backend/scripts/debugging/opensearch/opensearch_debug.py list
        python backend/scripts/debugging/opensearch/opensearch_debug.py delete
            <index_name>

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
import json
import os
import sys
from typing import Any

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
        print(f"Index '{client._index_name}' does not exist.")
        return

    confirm = input(f"Delete index '{client._index_name}'? (yes/no): ")
    if confirm.lower() != "yes":
        print("Aborted.")
        return

    if client.delete_index():
        print(f"Deleted index '{client._index_name}'.")
    else:
        print(f"Failed to delete index '{client._index_name}' for an unknown reason.")


def get_settings(
    client: OpenSearchIndexClient,
    include_defaults: bool = False,
    flat_settings: bool = False,
    pretty: bool = False,
    human: bool = False,
) -> None:
    settings, default_settings = client.get_settings(
        include_defaults=include_defaults,
        flat_settings=flat_settings,
        pretty=pretty,
        human=human,
    )
    print("Settings:")
    print(json.dumps(settings, indent=4))
    print("-" * 80)
    if default_settings:
        print("Default settings:")
        print(json.dumps(default_settings, indent=4))
        print("-" * 80)


def set_settings(client: OpenSearchIndexClient, settings: dict[str, Any]) -> None:
    client.update_settings(settings)
    print(f"Updated settings for index '{client._index_name}'.")


def open_index(client: OpenSearchIndexClient) -> None:
    client.open_index()
    print(f"Index '{client._index_name}' opened.")


def close_index(client: OpenSearchIndexClient) -> None:
    client.close_index()
    print(f"Index '{client._index_name}' closed.")


def reroute_retry_failed(client: OpenSearchClient) -> None:
    print(
        "About to call POST /_cluster/reroute?retry_failed=true.\n"
        "This resets the failed-allocation retry counter and re-attempts allocation\n"
        "for shards stuck UNASSIGNED with reason=ALLOCATION_FAILED."
    )
    confirm = input("Proceed? (yes/no): ")
    if confirm.lower() != "yes":
        print("Aborted.")
        return

    response = client.reroute_retry_failed()
    print("Reroute response (state omitted by default):")
    print(f"  acknowledged: {response.get('acknowledged')}")
    print()
    print("Post-reroute top-level cluster health:")
    health = client.cluster_health()
    print(f"  status: {health.get('status')}")
    print(f"  active_primary_shards: {health.get('active_primary_shards')}")
    print(f"  active_shards: {health.get('active_shards')}")
    print(f"  unassigned_shards: {health.get('unassigned_shards')}")
    print(f"  initializing_shards: {health.get('initializing_shards')}")
    print()
    print(
        "If status is still 'red', re-run 'health' to inspect the new "
        "allocation_explain output for the affected shards."
    )


def diagnose_health(client: OpenSearchClient) -> None:
    def banner(s: str) -> None:
        print("\n" + "=" * 80 + "\n" + s + "\n" + "=" * 80)

    banner("1) cluster.health() -- top-level summary")
    print(json.dumps(client.cluster_health(), indent=2))

    banner('2) cluster.health(level="indices") -- per-index status (non-green only)')
    per_index = client.cluster_health(level="indices").get("indices", {})
    non_green = {k: v for k, v in per_index.items() if v.get("status") != "green"}
    print(f"non-green indices: {len(non_green)} / {len(per_index)}")
    print(json.dumps(non_green, indent=2))

    banner("3) cat.shards() -- non-STARTED shards")
    shards = client.cat_shards()
    bad = [s for s in shards if s.get("state") != "STARTED"]
    print(f"total shards: {len(shards)}; non-STARTED: {len(bad)}")
    print(json.dumps(bad, indent=2))

    banner("4) cluster.allocation_explain() -- per unassigned shard (cap 10)")
    unassigned = [s for s in bad if s.get("state") == "UNASSIGNED"]
    for s in unassigned[:10]:
        explain_args: dict[str, Any] = {
            "index": s["index"],
            "shard": int(s["shard"]),
            "primary": s["prirep"] == "p",
        }
        print(f"\n--- {explain_args} ---")
        try:
            print(json.dumps(client.allocation_explain(**explain_args), indent=2))
        except Exception as e:
            print(f"ERROR: {e!r}")

    if not unassigned:
        print("\nNo UNASSIGNED shards. Calling allocation_explain() with no body:")
        try:
            print(json.dumps(client.allocation_explain(), indent=2))
        except Exception as e:
            print(f"(expected if everything is green) ERROR: {e!r}")


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
            help="OpenSearch port. If not provided, will fall back to OPENSEARCH_REST_API_PORT, then prompt for input.",
            type=int,
            default=int(os.environ.get("OPENSEARCH_REST_API_PORT", 0)),
        )
        parser.add_argument(
            "--username",
            help=(
                "OpenSearch username. If not provided, will fall back to OPENSEARCH_ADMIN_USERNAME, then prompt for "
                "input."
            ),
            type=str,
            default=os.environ.get("OPENSEARCH_ADMIN_USERNAME", ""),
        )
        parser.add_argument(
            "--password",
            help=(
                "OpenSearch password. If not provided, will fall back to OPENSEARCH_ADMIN_PASSWORD, then prompt for "
                "input."
            ),
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
    add_standard_arguments(parser)
    subparsers = parser.add_subparsers(
        dest="command", help="Command to execute.", required=True
    )

    subparsers.add_parser("list", help="List all indices with info.")

    subparsers.add_parser(
        "health",
        help=(
            "Diagnose cluster health. Reports overall status, non-green "
            "indices, non-STARTED shards, and allocation explanations for "
            "unassigned shards."
        ),
    )

    subparsers.add_parser(
        "reroute-retry-failed",
        help=(
            "Call POST /_cluster/reroute?retry_failed=true to retry allocation "
            "for shards stuck UNASSIGNED with reason=ALLOCATION_FAILED after "
            "exceeding the max retry count. Confirms before sending."
        ),
    )

    delete_parser = subparsers.add_parser("delete", help="Delete an index.")
    delete_parser.add_argument("index", help="Index name.", type=str)

    get_settings_parser = subparsers.add_parser(
        "get", help="Get settings for an index."
    )
    get_settings_parser.add_argument("index", help="Index name.", type=str)
    get_settings_parser.add_argument(
        "--include-defaults",
        help="Include default settings.",
        action="store_true",
        default=False,
    )
    get_settings_parser.add_argument(
        "--flat-settings",
        help="Return settings in flat format.",
        action="store_true",
        default=False,
    )
    get_settings_parser.add_argument(
        "--pretty",
        help="Pretty-format the returned JSON response.",
        action="store_true",
        default=False,
    )
    get_settings_parser.add_argument(
        "--human",
        help="Return statistics in human-readable format.",
        action="store_true",
        default=False,
    )

    set_settings_parser = subparsers.add_parser(
        "set", help="Set settings for an index."
    )
    set_settings_parser.add_argument("index", help="Index name.", type=str)
    set_settings_parser.add_argument("settings", help="Settings to set.", type=str)

    open_index_parser = subparsers.add_parser("open", help="Open an index.")
    open_index_parser.add_argument("index", help="Index name.", type=str)

    close_index_parser = subparsers.add_parser("close", help="Close an index.")
    close_index_parser.add_argument("index", help="Index name.", type=str)

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
    print()

    cluster_only_commands = {"list", "health", "reroute-retry-failed"}

    with (
        OpenSearchClient(
            host=host,
            port=port,
            auth=(username, password),
            use_ssl=not args.no_ssl,
            verify_certs=not args.no_verify_certs,
        )
        if args.command in cluster_only_commands
        else OpenSearchIndexClient(
            index_name=args.index,
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
        elif args.command == "health":
            diagnose_health(client)
        elif args.command == "reroute-retry-failed":
            reroute_retry_failed(client)
        elif args.command == "delete":
            delete_index(client)
        elif args.command == "get":
            get_settings(
                client,
                include_defaults=args.include_defaults,
                flat_settings=args.flat_settings,
                pretty=args.pretty,
                human=args.human,
            )
        elif args.command == "set":
            set_settings(client, json.loads(args.settings))
        elif args.command == "open":
            open_index(client)
        elif args.command == "close":
            close_index(client)
        else:
            print(f"Unknown command: {args.command}")
            sys.exit(1)


if __name__ == "__main__":
    main()
