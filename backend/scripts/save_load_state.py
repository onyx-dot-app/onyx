# This file is purely for development use, not included in any builds
# Remember to first to send over the schema information (run API Server)
import argparse
import json
import os
import subprocess

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


def save_postgres(filename: str, container_name: str) -> None:
    logger.notice("Attempting to take Postgres snapshot")
    cmd = f"docker exec {container_name} pg_dump -U {POSTGRES_USER} -h {POSTGRES_HOST} -p {POSTGRES_PORT} -W -F t {POSTGRES_DB}"
    with open(filename, "w") as file:
        subprocess.run(
            cmd,
            shell=True,
            check=True,
            stdout=file,
            text=True,
            input=f"{POSTGRES_PASSWORD}\n",
        )


def load_postgres(filename: str, container_name: str) -> None:
    logger.notice("Attempting to load Postgres snapshot")
    try:
        alembic_cfg = Config("alembic.ini")
        command.upgrade(alembic_cfg, "head")
    except Exception as e:
        logger.error(f"Alembic upgrade failed: {e}")

    host_file_path = os.path.abspath(filename)

    copy_cmd = f"docker cp {host_file_path} {container_name}:/tmp/"
    subprocess.run(copy_cmd, shell=True, check=True)

    container_file_path = f"/tmp/{os.path.basename(filename)}"

    restore_cmd = (
        f"docker exec {container_name} pg_restore --clean -U {POSTGRES_USER} "
        f"-h localhost -p {POSTGRES_PORT} -d {POSTGRES_DB} -1 -F t {container_file_path}"
    )
    subprocess.run(restore_cmd, shell=True, check=True)


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

    with open(filename, "w") as jsonl_file:
        for doc in doc_jsons:
            json_str = json.dumps(doc)
            jsonl_file.write(json_str + "\n")


def load_vespa(filename: str) -> None:
    headers = {"Content-Type": "application/json"}
    with open(filename, "r") as f:
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
            os.path.join(checkpoint_dir, "postgres_snapshot.tar"), postgres_container
        )
        load_vespa(os.path.join(checkpoint_dir, "vespa_snapshot.jsonl"))
    else:
        save_postgres(
            os.path.join(checkpoint_dir, "postgres_snapshot.tar"), postgres_container
        )
        save_vespa(os.path.join(checkpoint_dir, "vespa_snapshot.jsonl"))
