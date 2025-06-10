import os
from types import SimpleNamespace

import yaml

from tests.regression.answer_quality.cli_utils import (
    manage_data_directories,
    set_env_variables,
    start_docker_compose,
    switch_to_commit,
)


def load_config(config_filename: str) -> SimpleNamespace:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(current_dir, config_filename)
    with open(config_path) as file:
        return SimpleNamespace(**yaml.safe_load(file))


def main() -> None:
    config = load_config("search_test_config.yaml")
    if config.environment_name:
        env_name = config.environment_name
        print("launching onyx with environment name:", env_name)
    else:
        print("No env name defined. Not launching docker.")
        print(
            "Please define a name in the config yaml to start a new env "
            "or use an existing env"
        )
        return

    set_env_variables(
        config.model_server_ip,
        config.model_server_port,
        config.use_cloud_gpu,
        config.llm,
    )
    manage_data_directories(env_name, config.output_folder, config.use_cloud_gpu)
    if config.commit_sha:
        switch_to_commit(config.commit_sha)

    start_docker_compose(
        env_name, config.launch_web_ui, config.use_cloud_gpu, config.only_state
    )


if __name__ == "__main__":
    main()
