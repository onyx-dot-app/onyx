"""Setup phase of the chat turn benchmark. Runs with the benchmark environment.

Creates the throwaway database, migrates it and names the search settings so
that the API server only makes an index with the benchmark prefix.
"""

import json
import subprocess
import sys
from pathlib import Path

from sqlalchemy import select

from onyx.configs.app_configs import POSTGRES_DB, REDIS_DB_NUMBER
from onyx.db.engine.sql_engine import SqlEngine, get_session_with_current_tenant
from onyx.db.models import SearchSettings
from onyx.db.search_settings import (
    get_current_search_settings,
    get_secondary_search_settings,
)
from onyx.db.swap_index import check_and_perform_index_swap
from onyx.setup import setup_postgres
from scripts.docprocessing_bench.worker import _flush_redis, _recreate_database
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

# Every throwaway resource carries this prefix. Setup refuses any other name.
BENCH_PREFIX = "chat_bench"
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent


def setup(index_name: str) -> dict[str, str]:
    for kind, name in (("database", POSTGRES_DB), ("index", index_name)):
        if not name.startswith(BENCH_PREFIX):
            raise RuntimeError(
                f"Refusing to use {kind} '{name}': the name must start with "
                f"'{BENCH_PREFIX}'."
            )
    if REDIS_DB_NUMBER == 0:
        raise RuntimeError("Refusing to use Redis database 0.")

    _recreate_database()
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_BACKEND_DIR,
        check=True,
        stdout=sys.stderr,
    )
    _flush_redis()

    SqlEngine.set_app_name("chat_bench_setup")
    SqlEngine.init_engine(pool_size=2, max_overflow=2)
    CURRENT_TENANT_ID_CONTEXTVAR.set(POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)
    with get_session_with_current_tenant() as db_session:
        # The seeded rows name the indexes of a normal deployment. Rename them
        # before anything can create an index from them.
        next_settings = get_secondary_search_settings(
            db_session
        ) or get_current_search_settings(db_session)
        for row in db_session.scalars(select(SearchSettings)):
            row.index_name = (
                index_name
                if row.id == next_settings.id
                else f"{index_name}_retired_{row.id}"
            )
        db_session.commit()
        check_and_perform_index_swap(db_session=db_session)
        setup_postgres(db_session)
        current = get_current_search_settings(db_session)
        return {"index_name": current.index_name, "model_name": current.model_name}


if __name__ == "__main__":
    print(json.dumps(setup(sys.argv[1])))
