import os
from types import SimpleNamespace

import yaml

from tests.regression.answer_quality.api_utils import create_cc_pair
from tests.regression.answer_quality.api_utils import create_connector
from tests.regression.answer_quality.api_utils import create_credential
from tests.regression.answer_quality.api_utils import run_cc_once
from tests.regression.answer_quality.api_utils import upload_file


def upload_test_files(zip_file_path: str, run_suffix: str) -> None:
    print("zip:", zip_file_path)
    file_paths = upload_file(run_suffix, zip_file_path)

    conn_id = create_connector(run_suffix, file_paths)
    cred_id = create_credential(run_suffix)

    create_cc_pair(run_suffix, conn_id, cred_id)
    run_cc_once(run_suffix, conn_id, cred_id)


if __name__ == "__main__":
    current_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(current_dir, "search_test_config.yaml")
    with open(config_path, "r") as file:
        config = SimpleNamespace(**yaml.safe_load(file))
    file_location = config.zipped_documents_file
    run_suffix = config.existing_test_suffix
    upload_test_files(file_location, run_suffix)
