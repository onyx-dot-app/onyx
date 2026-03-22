# This file is purely for development use, not included in any builds
# Remember to first to send over the schema information (run API Server)
import argparse
import json
import os
import subprocess
import tempfile
from typing import BinaryIO

import requests

from alembic import command
from alembic.config import Config
from onyx.configs.app_configs import POSTGRES_DB
from onyx.configs.app_configs import POSTGRES_HOST
from onyx.configs.app_configs import POSTGRES_PASSWORD
from onyx.configs.app_configs import POSTGRES_PORT
from onyx.configs.app_configs import POSTGRES_USER
from onyx.document_index.vespa.index import DOCUMENT_ID_ENDPOINT
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _sanitize_log_output(text: str) -> str:
    if not text:
        return text
    if POSTGRES_PASSWORD:
        return text.replace(POSTGRES_PASSWORD, "***REDACTED***")
    return text


def _run_command(args: list[str], stdout: BinaryIO | None = None) -> None:
    try:
        subprocess.run(
            args,
            check=True,
            stdout=stdout,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or b"").decode("utf-8", errors="replace")
        stderr = _sanitize_log_output(stderr).strip()
        logger.error(f"Command failed: {args[0]} ({stderr})")
        raise


def _create_pgpass_file(db_host: str) -> str:
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        delete=False,
        prefix=".pgpass_",
    ) as tmp:
        tmp.write(
            f"{db_host}:{POSTGRES_PORT}:{POSTGRES_DB}:{POSTGRES_USER}:{POSTGRES_PASSWORD}\n"
        )
        local_pgpass_path = tmp.name

    os.chmod(local_pgpass_path, 0o600)
    return local_pgpass_path


def _copy_pgpass_to_container(container_name: str, local_pgpass_path: str) -> str:
    container_pgpass_path = "/tmp/.pgpass"

    _run_command(
        ["docker", "cp", local_pgpass_path, f"{container_name}:{container_pgpass_path}"]
    )
    _run_command(
        ["docker", "exec", container_name, "chmod", "600", container_pgpass_path]
    )

    return container_pgpass_path


def _cleanup_pgpass(
    container_name: str, local_pgpass_path: str, container_pgpass_path: str
) -> None:
    try:
        if os.path.exists(local_pgpass_path):
            os.remove(local_pgpass_path)
    except OSError:
        logger.warning("Could not remove local temporary .pgpass file")

    subprocess.run(
        ["docker", "exec", container_name, "rm", "-f", container_pgpass_path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def save_postgres(filename: str, container_name: str) -> None:
    logger.notice("Attempting to take Postgres snapshot")

    local_pgpass_path = _create_pgpass_file(POSTGRES_HOST)
    container_pgpass_path = _copy_pgpass_to_container(container_name, local_pgpass_path)

    try:
        with open(filename, "wb") as file:
            _run_command(
                [
                    "docker",
                    "exec",
                    "--env",
                    f"PGPASSFILE={container_pgpass_path}",
                    container_name,
                    "pg_dump",
                    "-U",
                    POSTGRES_USER,
                    "-h",
                    POSTGRES_HOST,
                    "-p",
                    str(POSTGRES_PORT),
                    "-w",
                    "-F",
                    "t",
                    POSTGRES_DB,
                ],
                stdout=file,
            )
    finally:
        _cleanup_pgpass(container_name, local_pgpass_path, container_pgpass_path)


def load_postgres(filename: str, container_name: str) -> None:
    logger.notice("Attempting to load Postgres snapshot")

    try:
        alembic_cfg = Config("alembic.ini")
        command.upgrade(alembic_cfg, "head")
    except Exception as e:
        logger.error(f"Alembic upgrade failed: {_sanitize_log_output(str(e))}")

    host_file_path = os.path.abspath(filename)
    container_file_path = f"/tmp/{os.path.basename(filename)}"

    local_pgpass_path = _create_pgpass_file("localhost")
    container_pgpass_path = _copy_pgpass_to_container(container_name, local_pgpass_path)

    try:
        _run_command(
            ["docker", "cp", host_file_path, f"{container_name}:{container_file_path}"]
        )

        _run_command(
            [
                "docker",
                "exec",
                "--env",
                f"PGPASSFILE={container_pgpass_path}",
                container_name,
                "pg_restore",
                "--clean",
                "-U",
                POSTGRES_USER,
                "-h",
                "localhost",
                "-p",
                str(POSTGRES_PORT),
                "-d",
                POSTGRES_DB,
                "-1",
                "-F",
                "t",
                "-w",
                container_file_path,
            ]
        )
    finally:
        _cleanup_pgpass(container_name, local_pgpass_path, container_pgpass_path)
        subprocess.run(
            ["docker", "exec", container_name, "rm", "-f", container_file_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )


def save_vespa(filename: str) -> None:
    logger.notice("Attempting to take Vespa snapshot")
    continuation = ""
    params = {}
    doc_jsons: list[dict] = []

    while continuation is not None:
        if continuation:
            params = {"continuation": continuation}

        response = requests.get(DOCUMENT_ID_ENDPOINT, params=params)
        response.raise_for_status()
        found = response.json()
        continuation = found.get("continuation")
        docs = found["documents"]

        for doc in docs:
            doc_json = {"update": doc["id"], "create": True, "fields": doc["fields"]}
            doc_jsons.append(doc_json)

    with open(filename, "w", encoding="utf-8") as jsonl_file:
        for doc in doc_jsons:
            json_str = json.dumps(doc)
            jsonl_file.write(json_str + "\n")


def load_vespa(filename: str) -> None:
    headers = {"Content-Type": "application/json"}

    with open(filename, "r", encoding="utf-8") as f:
        for line in f:
            new_doc = json.loads(line.strip())
            doc_id = new_doc["update"].split("::")[-1]
            response = requests.post(
                DOCUMENT_ID_ENDPOINT + "/" + doc_id,
                headers=headers,
                json=new_doc,
            )
            response.raise_for_status()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Onyx checkpoint saving and loading.")
    parser.add_argument(
        "--save", action="store_true", help="Save Onyx state to directory."
    )
    parser.add_argument(
        "--load", action="store_true", help="Load Onyx state from save directory."
    )
    parser.add_argument(
        "--postgres_container_name",
        type=str,
        default="onyx-relational_db-1",
        help="Name of the postgres container to dump",
    )
    parser.add_argument(
        "--checkpoint_dir",
        type=str,
        default=os.path.join("..", "onyx_checkpoint"),
        help="A directory to store temporary files to.",
    )

    args = parser.parse_args()
    checkpoint_dir = args.checkpoint_dir
    postgres_container = args.postgres_container_name

    if not os.path.exists(checkpoint_dir):
        os.makedirs(checkpoint_dir)

    if not args.save and not args.load:
        raise ValueError("Must specify --save or --load")

    if args.load:
        load_postgres(
            os.path.join(checkpoint_dir, "postgres_snapshot.tar"),
            postgres_container,
        )
        load_vespa(os.path.join(checkpoint_dir, "vespa_snapshot.jsonl"))
    else:
        save_postgres(
            os.path.join(checkpoint_dir, "postgres_snapshot.tar"),
            postgres_container,
        )
        save_vespa(os.path.join(checkpoint_dir, "vespa_snapshot.jsonl"))
