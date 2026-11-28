"""Helpers that the benchmark scripts share.

Imports no onyx code, so an orchestrator can use it before the benchmark
environment is set.
"""

import socket
import tempfile
from pathlib import Path

import psycopg2
import redis

# One benchmark run at a time on a machine: runs share services, and two at
# one time would change each other's timings.
LOCK_PATH = Path(tempfile.gettempdir()) / "docproc-bench.lock"

# Keys of the developer's env file that a benchmark process may read.
PASSED_ENV_PREFIXES = ("POSTGRES_", "REDIS_", "S3_", "OPENSEARCH_", "FILE_STORE_")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def read_env_file(path: Path) -> dict[str, str]:
    """The entries of an env file whose key has an allowed prefix."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.removeprefix("export ").strip()
        if key.startswith(PASSED_ENV_PREFIXES):
            values[key] = value.strip().strip("'\"")
    return values


def recreate_database(
    host: str, port: int | str, user: str, password: str, name: str
) -> None:
    """Drops and creates a throwaway database. The caller checks the name."""
    connection = psycopg2.connect(
        host=host, port=port, user=user, password=password, dbname="postgres"
    )
    connection.autocommit = True
    try:
        with connection.cursor() as cursor:
            cursor.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            cursor.execute(f'CREATE DATABASE "{name}"')
    finally:
        connection.close()


def flush_redis(host: str, port: int, db_number: int, password: str | None) -> None:
    if db_number == 0:
        raise RuntimeError("Refusing to flush Redis database 0. Set REDIS_DB_NUMBER.")
    client = redis.Redis(host=host, port=port, db=db_number, password=password)
    client.flushdb()
    client.close()
