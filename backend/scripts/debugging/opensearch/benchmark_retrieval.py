#!/usr/bin/env python3
"""Benchmarks OpenSearchDocumentIndex latency.

Requires Onyx to be running as it reads search settings from the database.

Usage:
    source .venv/bin/activate
    python backend/scripts/debugging/opensearch/benchmark_retrieval.py --help
"""

import argparse
import statistics
import time

from onyx.configs.chat_configs import NUM_RETURNED_HITS
from onyx.context.search.enums import QueryType
from onyx.context.search.models import IndexFilters
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.search_settings import get_current_search_settings
from onyx.document_index.interfaces_new import TenantState
from onyx.document_index.opensearch.opensearch_document_index import (
    OpenSearchDocumentIndex,
)
from onyx.indexing.models import IndexingSetting
from scripts.debugging.opensearch.constants import DEV_TENANT_ID
from scripts.debugging.opensearch.embedding_io import load_query_embedding_from_file
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from shared_configs.contextvars import get_current_tenant_id

DEFAULT_N = 50


def main() -> None:
    def add_query_embedding_argument(parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "-e",
            "--embedding-file-path",
            type=str,
            required=True,
            help="Path to the query embedding file.",
        )

    def add_query_string_argument(parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "-q",
            "--query",
            type=str,
            required=True,
            help="Query string.",
        )

    parser = argparse.ArgumentParser(
        description="A benchmarking tool to measure OpenSearch retrieval latency."
    )
    parser.add_argument(
        "-n",
        type=int,
        default=DEFAULT_N,
        help=f"Number of samples to take (default: {DEFAULT_N}).",
    )
    subparsers = parser.add_subparsers(
        dest="query_type",
        help="Query type to benchmark.",
        required=True,
    )

    hybrid_parser = subparsers.add_parser(
        "hybrid", help="Benchmark hybrid retrieval latency."
    )
    add_query_embedding_argument(hybrid_parser)
    add_query_string_argument(hybrid_parser)

    keyword_parser = subparsers.add_parser(
        "keyword", help="Benchmark keyword retrieval latency."
    )
    add_query_string_argument(keyword_parser)

    semantic_parser = subparsers.add_parser(
        "semantic", help="Benchmark semantic retrieval latency."
    )
    add_query_embedding_argument(semantic_parser)

    args = parser.parse_args()

    if MULTI_TENANT:
        CURRENT_TENANT_ID_CONTEXTVAR.set(DEV_TENANT_ID)

    SqlEngine.init_engine(pool_size=1, max_overflow=0)
    with get_session_with_current_tenant() as session:
        search_settings = get_current_search_settings(session)
        indexing_setting = IndexingSetting.from_db_model(search_settings)

    tenant_state = TenantState(
        tenant_id=get_current_tenant_id(), multitenant=MULTI_TENANT
    )
    index = OpenSearchDocumentIndex(
        tenant_state=tenant_state,
        index_name=search_settings.index_name,
        embedding_dim=indexing_setting.final_embedding_dim,
        embedding_precision=indexing_setting.embedding_precision,
    )
    filters = IndexFilters(
        access_control_list=[],
        tenant_id=get_current_tenant_id(),
    )

    if args.query_type == "hybrid":
        embedding = load_query_embedding_from_file(args.embedding_file_path)
        search_callable = lambda: index.hybrid_retrieval(  # noqa: E731
            query=args.query,
            query_embedding=embedding,
            final_keywords=None,
            # This arg doesn't do anything right now.
            query_type=QueryType.KEYWORD,
            filters=filters,
            num_to_retrieve=NUM_RETURNED_HITS,
        )
    elif args.query_type == "keyword":
        search_callable = lambda: index.keyword_retrieval(  # noqa: E731
            query=args.query,
            filters=filters,
            num_to_retrieve=NUM_RETURNED_HITS,
        )
    elif args.query_type == "semantic":
        embedding = load_query_embedding_from_file(args.embedding_file_path)
        search_callable = lambda: index.semantic_retrieval(  # noqa: E731
            query_embedding=embedding,
            filters=filters,
            num_to_retrieve=NUM_RETURNED_HITS,
        )
    else:
        raise ValueError(f"Invalid query type: {args.query_type}")

    print(f"Running {args.n} invocations of {args.query_type} retrieval...")

    latencies: list[float] = []
    for i in range(args.n):
        start = time.perf_counter()
        results = search_callable()
        elapsed_ms = (time.perf_counter() - start) * 1000
        latencies.append(elapsed_ms)
        # Print the current iteration and its elapsed time on the same line.
        print(
            f"  [{i + 1:>{len(str(args.n))}}] {elapsed_ms:7.1f} ms  ({len(results)} results) (top result doc ID, chunk idx: {results[0].document_id if results else 'N/A'}, {results[0].chunk_id if results else 'N/A'})",
            end="\r",
            flush=True,
        )

    print()
    print(f"Results over {args.n} invocations:")
    print(f"   mean: {statistics.mean(latencies):7.1f} ms")
    print(
        f"  stdev: {statistics.stdev(latencies):7.1f} ms"
        if args.n > 1
        else "  stdev: N/A (only 1 sample)"
    )
    print(f"    max: {max(latencies):7.1f} ms (i: {latencies.index(max(latencies))})")
    print(f"    min: {min(latencies):7.1f} ms (i: {latencies.index(min(latencies))})")
    if args.n >= 20:
        print(f"    p50: {statistics.median(latencies):7.1f} ms")
        print(f"    p95: {statistics.quantiles(latencies, n=20)[-1]:7.1f} ms")


if __name__ == "__main__":
    main()
