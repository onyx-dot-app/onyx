import csv
import os
import tempfile
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace

import yaml

from tests.regression.answer_quality.api_utils import check_indexing_status
from tests.regression.answer_quality.api_utils import create_cc_pair
from tests.regression.answer_quality.api_utils import create_connector
from tests.regression.answer_quality.api_utils import create_credential
from tests.regression.answer_quality.api_utils import run_cc_once
from tests.regression.answer_quality.api_utils import upload_file


def unzip_and_get_file_paths(zip_file_path: str) -> list[str]:
    persistent_dir = tempfile.mkdtemp()
    with zipfile.ZipFile(zip_file_path, "r") as zip_ref:
        zip_ref.extractall(persistent_dir)

    file_paths = []
    for root, _, files in os.walk(persistent_dir):
        for file in sorted(files):
            file_paths.append(os.path.join(root, file))

    return file_paths


def create_temp_zip_from_files(file_paths: list[str]) -> str:
    persistent_dir = tempfile.mkdtemp()
    zip_file_path = os.path.join(persistent_dir, "temp.zip")

    with zipfile.ZipFile(zip_file_path, "w") as zip_file:
        for file_path in file_paths:
            zip_file.write(file_path, Path(file_path).name)

    return zip_file_path


def upload_test_files(zip_file_path: str, env_name: str) -> None:
    print("zip:", zip_file_path)
    file_paths = upload_file(env_name, zip_file_path)

    conn_id = create_connector(env_name, file_paths)
    cred_id = create_credential(env_name)

    create_cc_pair(env_name, conn_id, cred_id)
    run_cc_once(env_name, conn_id, cred_id)


def manage_file_upload(zip_file_path: str, env_name: str) -> None:
    start_time = time.time()
    unzipped_file_paths = unzip_and_get_file_paths(zip_file_path)
    total_file_count = len(unzipped_file_paths)
    problem_file_list: list[str] = []

    while True:
        doc_count, ongoing_index_attempts = check_indexing_status(env_name)

        if ongoing_index_attempts:
            print(
                f"{doc_count} docs indexed but waiting for ongoing indexing jobs to finish..."
            )
        elif not doc_count:
            print("No docs indexed, waiting for indexing to start")
            temp_zip_file_path = create_temp_zip_from_files(unzipped_file_paths)
            upload_test_files(temp_zip_file_path, env_name)
            os.unlink(temp_zip_file_path)
        elif (doc_count + len(problem_file_list)) < total_file_count:
            print(f"No ongooing indexing attempts but only {doc_count} docs indexed")
            remaining_files = unzipped_file_paths[doc_count + len(problem_file_list) :]
            problem_file_list.append(remaining_files.pop(0))
            print(
                f"Removing first doc and grabbed last {len(remaining_files)} docs to try agian"
            )
            temp_zip_file_path = create_temp_zip_from_files(remaining_files)
            upload_test_files(temp_zip_file_path, env_name)
            os.unlink(temp_zip_file_path)
        else:
            print(f"Successfully uploaded {doc_count} docs!")
            break

        time.sleep(10)

    if problem_file_list:
        problem_file_csv_path = os.path.join(current_dir, "problem_files.csv")
        with open(problem_file_csv_path, "w", newline="") as csvfile:
            csvwriter = csv.writer(csvfile)
            csvwriter.writerow(["Problematic File Paths"])
            for problem_file in problem_file_list:
                csvwriter.writerow([problem_file])

    for file in unzipped_file_paths:
        os.unlink(file)
    print(f"Total time taken: {(time.time() - start_time)/60} minutes")


if __name__ == "__main__":
    current_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(current_dir, "search_test_config.yaml")
    with open(config_path, "r") as file:
        config = SimpleNamespace(**yaml.safe_load(file))
    file_location = config.zipped_documents_file
    env_name = config.environment_name
    manage_file_upload(file_location, env_name)
