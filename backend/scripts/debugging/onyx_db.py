"""Onyx Database tool"""

import os

# hack to work around excessive use of globals in other functions
os.environ["MULTI_TENANT"] = "True"

if True:  # noqa: E402
    import csv
    import argparse

    from pydantic import BaseModel
    from sqlalchemy import func

    from onyx.db.engine.sql_engine import (
        SYNC_DB_API,
        USE_IAM_AUTH,
        build_connection_string,
    )
    from onyx.db.engine.tenant_utils import get_all_tenant_ids
    from onyx.db.engine.sql_engine import get_session_with_tenant
    from onyx.db.engine.sql_engine import SqlEngine
    from onyx.db.models import Document
    from onyx.db.models import User
    from onyx.utils.logger import setup_logger
    from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

    import heapq

    logger = setup_logger()


class TenantMetadata(BaseModel):
    first_email: str | None
    user_count: int
    num_docs: int
    num_chunks: int


class SQLAlchemyDebugging:
    # Class for managing DB debugging actions.
    def __init__(self) -> None:
        pass

    def top_chunks(self, filename: str, k: int = 10) -> None:
        tenants_to_total_chunks: dict[str, TenantMetadata] = {}

        logger.info("Fetching all tenant id's.")
        tenant_ids = get_all_tenant_ids()
        num_tenant_ids = len(tenant_ids)

        logger.info(f"Found {num_tenant_ids} tenant id's.")

        num_processed = 0
        for tenant_id in tenant_ids:
            num_processed += 1

            token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)

            try:
                with get_session_with_tenant(tenant_id=tenant_id) as db_session:
                    first_email = None

                    first_user = db_session.query(User).first()
                    if first_user:
                        first_email = first_user.email

                    user_count = db_session.query(User).count()

                    # Calculate the total number of document rows for the current tenant
                    total_documents = db_session.query(Document).count()
                    # marginally useful to skip some tenants ... maybe we can improve on this
                    # if total_documents < 100:
                    #     logger.info(f"{num_processed} of {num_tenant_ids}: Tenant '{tenant_id}': "
                    #                 f"docs={total_documents} skip=True")
                    #     continue

                    # Calculate the sum of chunk_count for the current tenant
                    # If there are no documents or all chunk_counts are NULL, sum will be None
                    total_chunks = db_session.query(
                        func.sum(Document.chunk_count)
                    ).scalar()

                    total_chunks = total_chunks or 0

                    logger.info(
                        f"{num_processed} of {num_tenant_ids}: Tenant '{tenant_id}': "
                        f"first_email={first_email} user_count={user_count} "
                        f"docs={total_documents} chunks={total_chunks}"
                    )

                tenants_to_total_chunks[tenant_id] = TenantMetadata(
                    first_email=first_email,
                    user_count=user_count,
                    num_docs=total_documents,
                    num_chunks=total_chunks,
                )
            except Exception as e:
                logger.error(f"Error processing tenant '{tenant_id}': {e}")
            finally:
                CURRENT_TENANT_ID_CONTEXTVAR.reset(token)

        # sort all by docs and dump to csv
        sorted_tenants = sorted(
            tenants_to_total_chunks.items(),
            key=lambda x: (x[1].num_chunks, x[1].num_docs),
            reverse=True,
        )

        with open(filename, "w") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(
                ["tenant_id", "first_user_email", "num_user", "num_docs", "num_chunks"]
            )  # Write header
            # Write data rows (using the sorted list)
            for tenant_id, metadata in sorted_tenants:
                writer.writerow(
                    [
                        tenant_id,
                        metadata.first_email,
                        metadata.user_count,
                        metadata.num_docs,
                        metadata.num_chunks,
                    ]
                )
            logger.info(f"Successfully wrote statistics to {filename}")

        # output top k by chunks
        top_k_tenants = heapq.nlargest(
            k, tenants_to_total_chunks.items(), key=lambda x: x[1].num_docs
        )

        logger.info(f"Top {k} tenants by total chunks: {top_k_tenants}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Database/SQL debugging tool")
    parser.add_argument("--username", help="Database username", default="postgres")
    parser.add_argument("--password", help="Database password", required=True)
    parser.add_argument("--host", help="Database host", default="localhost")
    parser.add_argument("--port", help="Database port", default=5432)
    parser.add_argument("--db", help="Database default db name", default="danswer")

    parser.add_argument("--report", help="Generate the given report")

    parser.add_argument(
        "--filename",
        type=str,
        default="tenants_by_num_docs.csv",
        help="Generate the given report",
        required=False,
    )

    args = parser.parse_args()

    logger.info(f"{args}")

    connection_string = build_connection_string(
        db_api=SYNC_DB_API,
        app_name="onyx_db_sync",
        use_iam_auth=USE_IAM_AUTH,
        user=args.username,
        password=args.password,
        host=args.host,
        port=args.port,
        db=args.db,
    )

    SqlEngine.init_engine(
        pool_size=20, max_overflow=5, connection_string=connection_string
    )

    debugger = SQLAlchemyDebugging()

    if args.report == "top-chunks":
        debugger.top_chunks(args.filename, 10)
    else:
        logger.info("No action.")


if __name__ == "__main__":
    main()
