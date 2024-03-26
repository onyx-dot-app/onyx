import json
from pathlib import Path

from danswer.configs.app_configs import DYNAMIC_CONFIG_DIR_PATH
from danswer.dynamic_configs.factory import PostgresBackedDynamicConfigStore
from danswer.dynamic_configs.interface import ConfigNotFoundError


def read_file_system_store(directory_path: str) -> dict:
    store = {}
    base_path = Path(directory_path)
    for file_path in base_path.iterdir():
        if file_path.is_file() and "." not in file_path.name:
            with open(file_path, "r") as file:
                key = file_path.stem
                value = json.load(file)

                if value:
                    store[key] = value
    return store


def insert_into_postgres(store_data: dict) -> None:
    port_once_key = "file_store_ported"
    config_store = PostgresBackedDynamicConfigStore()
    try:
        config_store.load(port_once_key)
        return
    except ConfigNotFoundError:
        pass

    for key, value in store_data.items():
        config_store.store(key, value)

    config_store.store(port_once_key, True)


def port_filesystem_to_postgres(directory_path: str = DYNAMIC_CONFIG_DIR_PATH) -> None:
    store_data = read_file_system_store(directory_path)
    insert_into_postgres(store_data)
