from collections.abc import Callable
from typing import cast

from onyx.access.models import ExternalAccess
from onyx.utils.variable_functionality import (
    fetch_versioned_implementation,
    global_version,
)

_EE_ACCESS_MODULE: str = "onyx.external_permissions.dealcloud.access"


def get_entry_type_access(base_url: str, entry_type_id: int) -> ExternalAccess | None:
    if not global_version.is_ee_version():
        return None
    ee_entry_type_access = cast(
        Callable[[str, int], ExternalAccess],
        fetch_versioned_implementation(_EE_ACCESS_MODULE, "entry_type_access"),
    )
    return ee_entry_type_access(base_url, entry_type_id)
