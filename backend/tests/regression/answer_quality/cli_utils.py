import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime
from threading import Thread
from typing import IO

import yaml
from retry import retry


def _run_command(command: str, stream_output: bool = False) -> tuple[str, str]:
    process = subprocess.Popen(
        command,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    def process_stream(stream: IO[str], lines: list[str]) -> None:
        for line in stream:
            lines.append(line)
            if stream_output:
                print(
                    line,
                    end="",
                    file=sys.stdout if stream == process.stdout else sys.stderr,
                )

    stdout_thread = Thread(target=process_stream, args=(process.stdout, stdout_lines))
    stderr_thread = Thread(target=process_stream, args=(process.stderr, stderr_lines))

    stdout_thread.start()
    stderr_thread.start()

    stdout_thread.join()
    stderr_thread.join()

    process.wait()

    if process.returncode != 0:
        raise RuntimeError(f"Command failed with error: {''.join(stderr_lines)}")

    return "".join(stdout_lines), "".join(stderr_lines)


def get_current_commit_sha() -> str:
    print("Getting current commit SHA...")
    stdout, _ = _run_command("git rev-parse HEAD")
    sha = stdout.strip()
    print(f"Current commit SHA: {sha}")
    return sha


def switch_to_commit(commit_sha: str) -> None:
    print(f"Switching to commit: {commit_sha}...")
    _run_command(f"git checkout {commit_sha}")
    print(f"Successfully switched to commit: {commit_sha}")
    print("Repository updated successfully.")


def get_docker_container_env_vars(env_name: str) -> dict:
    """
    Retrieves environment variables from "background" and "api_server" Docker containers.
    """
    print(f"Getting environment variables for containers with env_name: {env_name}")

    combined_env_vars = {}
    for container_type in ["background", "api_server"]:
        container_name = _run_command(
            f"docker ps -a --format '{{{{.Names}}}}' | awk '/{container_type}/ && /{env_name}/'"
        )[0].strip()
        if not container_name:
            raise RuntimeError(
                f"No {container_type} container found with env_name: {env_name}"
            )

        env_vars_json = _run_command(
            f"docker inspect --format='{{{{json .Config.Env}}}}' {container_name}"
        )[0]
        env_vars_list = json.loads(env_vars_json.strip())

        for env_var in env_vars_list:
            key, value = env_var.split("=", 1)
            combined_env_vars[key] = value

    return combined_env_vars


def manage_data_directories(env_name: str, base_path: str, use_cloud_gpu: bool) -> None:
    # Use the user's home directory as the base path
    target_path = os.path.join(os.path.expanduser(base_path), env_name)
    directories = {
        "DANSWER_POSTGRES_DATA_DIR": os.path.join(target_path, "postgres/"),
        "DANSWER_VESPA_DATA_DIR": os.path.join(target_path, "vespa/"),
    }
    if not use_cloud_gpu:
        directories["DANSWER_INDEX_MODEL_CACHE_DIR"] = os.path.join(
            target_path, "index_model_cache/"
        )
        directories["DANSWER_INFERENCE_MODEL_CACHE_DIR"] = os.path.join(
            target_path, "inference_model_cache/"
        )

    # Create directories if they don't exist
    for env_var, directory in directories.items():
        os.makedirs(directory, exist_ok=True)
        os.environ[env_var] = directory
        print(f"Set {env_var} to: {directory}")
    results_output_path = os.path.join(target_path, "evaluations_output/")
    os.makedirs(results_output_path, exist_ok=True)


def set_env_variables(
    remote_server_ip: str,
    remote_server_port: str,
    use_cloud_gpu: bool,
    llm_config: dict,
) -> None:
    env_vars: dict = {}
    env_vars["ENV_SEED_CONFIGURATION"] = json.dumps({"llms": [llm_config]})
    env_vars["ENABLE_PAID_ENTERPRISE_EDITION_FEATURES"] = "true"
    if use_cloud_gpu:
        env_vars["MODEL_SERVER_HOST"] = remote_server_ip
        env_vars["MODEL_SERVER_PORT"] = remote_server_port
        env_vars["INDEXING_MODEL_SERVER_HOST"] = remote_server_ip

    for env_var_name, env_var in env_vars.items():
        os.environ[env_var_name] = env_var
        print(f"Set {env_var_name} to: {env_var}")


def _is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", port)) == 0


def start_docker_compose(
    env_name: str, launch_web_ui: bool, use_cloud_gpu: bool, only_state: bool = False
) -> None:
    print("Starting Docker Compose...")
    os.chdir(os.path.dirname(__file__))
    os.chdir("../../../../deployment/docker_compose/")
    command = (
        f"docker compose -f docker-compose.search-testing.yml -p onyx-{env_name} up -d"
    )
    command += " --build"
    command += " --force-recreate"

    if only_state:
        command += " index relational_db"
    else:
        if use_cloud_gpu:
            command += " --scale indexing_model_server=0"
            command += " --scale inference_model_server=0"
        if launch_web_ui:
            web_ui_port = 3000
            while _is_port_in_use(web_ui_port):
                web_ui_port += 1
            print(f"UI will be launched at http://localhost:{web_ui_port}")
            os.environ["NGINX_PORT"] = str(web_ui_port)
        else:
            command += " --scale web_server=0"
            command += " --scale nginx=0"

    print("Docker Command:\n", command)

    _run_command(command, stream_output=True)
    print("Containers have been launched")


def cleanup_docker(env_name: str) -> None:
    print(
        f"Deleting Docker containers, volumes, and networks for project env_name: {env_name}"
    )

    stdout, _ = _run_command("docker ps -a --format '{{json .}}'")

    containers = [json.loads(line) for line in stdout.splitlines()]
    if not env_name:
        env_name = datetime.now().strftime("-%Y")
    project_name = f"onyx{env_name}"
    containers_to_delete = [
        c for c in containers if c["Names"].startswith(project_name)
    ]

    if not containers_to_delete:
        print(f"No containers found for project: {project_name}")
    else:
        container_ids = " ".join([c["ID"] for c in containers_to_delete])
        _run_command(f"docker rm -f {container_ids}")

        print(
            f"Successfully deleted {len(containers_to_delete)} containers for project: {project_name}"
        )

    stdout, _ = _run_command("docker volume ls --format '{{.Name}}'")

    volumes = stdout.splitlines()

    volumes_to_delete = [v for v in volumes if v.startswith(project_name)]

    if not volumes_to_delete:
        print(f"No volumes found for project: {project_name}")
        return

    # Delete filtered volumes
    volume_names = " ".join(volumes_to_delete)
    _run_command(f"docker volume rm {volume_names}")

    print(
        f"Successfully deleted {len(volumes_to_delete)} volumes for project: {project_name}"
    )
    stdout, _ = _run_command("docker network ls --format '{{.Name}}'")

    networks = stdout.splitlines()

    networks_to_delete = [n for n in networks if env_name in n]

    if not networks_to_delete:
        print(f"No networks found containing env_name: {env_name}")
    else:
        network_names = " ".join(networks_to_delete)
        _run_command(f"docker network rm {network_names}")

        print(
            f"Successfully deleted {len(networks_to_delete)} networks containing env_name: {env_name}"
        )


@retry(tries=5, delay=5, backoff=2)
def get_api_server_host_port(env_name: str) -> str:
    """
    This pulls all containers with the provided env_name
    It then grabs the JSON specific container with a name containing "api_server"
    It then grabs the port info from the JSON and strips out the relevent data
    """
    container_name = "api_server"

    stdout, _ = _run_command("docker ps -a --format '{{json .}}'")
    containers = [json.loads(line) for line in stdout.splitlines()]
    server_jsons = []

    for container in containers:
        if container_name in container["Names"] and env_name in container["Names"]:
            server_jsons.append(container)

    if not server_jsons:
        raise RuntimeError(
            f"No container found containing: {container_name} and {env_name}"
        )
    elif len(server_jsons) > 1:
        raise RuntimeError(
            f"Too many containers matching {container_name} found, please indicate a env_name"
        )
    server_json = server_jsons[0]

    # This is in case the api_server has multiple ports
    client_port = "8080"
    ports = server_json.get("Ports", "")
    port_infos = ports.split(",") if ports else []
    port_dict = {}
    for port_info in port_infos:
        port_arr = port_info.split(":")[-1].split("->") if port_info else []
        if len(port_arr) == 2:
            port_dict[port_arr[1]] = port_arr[0]

    # Find the host port where client_port is in the key
    matching_ports = [value for key, value in port_dict.items() if client_port in key]

    if len(matching_ports) > 1:
        raise RuntimeError(f"Too many ports matching {client_port} found")
    if not matching_ports:
        raise RuntimeError(
            f"No port found containing: {client_port} for container: {container_name} and env_name: {env_name}"
        )
    return matching_ports[0]


# Added function to restart Vespa container
def restart_vespa_container(env_name: str) -> None:
    print(f"Restarting Vespa container for env_name: {env_name}")

    # Find the Vespa container
    stdout, _ = _run_command(
        f"docker ps -a --format '{{{{.Names}}}}' | awk '/index-1/ && /{env_name}/'"
    )
    container_name = stdout.strip()

    if not container_name:
        raise RuntimeError(f"No Vespa container found with env_name: {env_name}")

    # Restart the container
    _run_command(f"docker restart {container_name}")

    print(f"Vespa container '{container_name}' has begun restarting")

    time.sleep(30)
    print(f"Vespa container '{container_name}' has been restarted")


if __name__ == "__main__":
    """
    Running this just cleans up the docker environment for the container indicated by environment_name
    If no environment_name is indicated, will just clean up all onyx docker containers/volumes/networks
    Note: vespa/postgres mounts are not deleted
    """
    current_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(current_dir, "search_test_config.yaml")
    with open(config_path, "r") as file:
        config = yaml.safe_load(file)

    if not isinstance(config, dict):
        raise TypeError("config must be a dictionary")
    cleanup_docker(config["environment_name"])
