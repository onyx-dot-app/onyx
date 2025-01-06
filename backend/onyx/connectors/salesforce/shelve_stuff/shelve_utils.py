import os

from onyx.connectors.salesforce.utils import BASE_DATA_PATH
from onyx.connectors.salesforce.utils import get_object_type_path


def get_object_shelf_path(object_type: str) -> str:
    """Get the path to the shelf file for a specific object type."""
    base_path = get_object_type_path(object_type)
    os.makedirs(base_path, exist_ok=True)
    return os.path.join(base_path, "data.shelf")


def get_id_type_shelf_path() -> str:
    """Get the path to the ID-to-type mapping shelf."""
    os.makedirs(BASE_DATA_PATH, exist_ok=True)
    return os.path.join(BASE_DATA_PATH, "id_type_mapping.shelf.4g")


def get_parent_to_child_shelf_path() -> str:
    """Get the path to the parent-to-child mapping shelf."""
    os.makedirs(BASE_DATA_PATH, exist_ok=True)
    return os.path.join(BASE_DATA_PATH, "parent_to_child_mapping.shelf.4g")


def get_child_to_parent_shelf_path() -> str:
    """Get the path to the child-to-parent mapping shelf."""
    os.makedirs(BASE_DATA_PATH, exist_ok=True)
    return os.path.join(BASE_DATA_PATH, "child_to_parent_mapping.shelf.4g")
