#!/usr/bin/env python3
"""Embeds a query and saves the embedding to a file.

Requires Onyx to be running as it reads search settings from the database.

Usage:
    source .venv/bin/activate
    python backend/scripts/debugging/opensearch/embed_and_save.py --help
"""

import argparse
import time

from onyx.context.search.utils import get_query_embedding
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.engine.sql_engine import SqlEngine
from scripts.debugging.opensearch.embedding_io import save_query_embedding_to_file
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

DEV_TENANT_ID = "tenant_dev"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="A tool to embed a query and save the embedding to a file."
    )
    parser.add_argument(
        "-q",
        "--query",
        type=str,
        required=True,
        help="Query string to embed.",
    )
    parser.add_argument(
        "-f",
        "--file-path",
        type=str,
        required=True,
        help="Path to the output file to save the embedding to.",
    )

    args = parser.parse_args()

    if MULTI_TENANT:
        CURRENT_TENANT_ID_CONTEXTVAR.set(DEV_TENANT_ID)

    SqlEngine.init_engine(pool_size=1, max_overflow=0)
    with get_session_with_current_tenant() as session:
        start = time.perf_counter()
        query_embedding = get_query_embedding(
            query=args.query,
            db_session=session,
            embedding_model=None,
        )
        elapsed_ms = (time.perf_counter() - start) * 1000

    save_query_embedding_to_file(query_embedding, args.file_path)
    print(
        f"Query embedding of dimension {len(query_embedding)} generated in {elapsed_ms:.1f} ms and saved to {args.file_path}."
    )


if __name__ == "__main__":
    main()
