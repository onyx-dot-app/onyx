from danswer.configs.app_configs import DYNAMIC_CONFIG_STORE
from danswer.dynamic_configs.interface import DynamicConfigStore
from danswer.dynamic_configs.store import FileSystemBackedDynamicConfigStore
from danswer.dynamic_configs.store import PostgresBackedDynamicConfigStore


def get_dynamic_config_store() -> DynamicConfigStore:
    dynamic_config_store_type = DYNAMIC_CONFIG_STORE
    if dynamic_config_store_type == FileSystemBackedDynamicConfigStore.__name__:
        raise NotImplementedError("File based config store no longer supported")
    if dynamic_config_store_type == PostgresBackedDynamicConfigStore.__name__:
        return PostgresBackedDynamicConfigStore()

    # TODO: change exception type
    raise Exception("Unknown dynamic config store type")
