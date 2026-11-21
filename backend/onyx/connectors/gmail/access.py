from collections.abc import Callable
from typing import cast

from onyx.access.models import ExternalAccess
from onyx.utils.variable_functionality import (
    fetch_versioned_implementation,
    global_version,
)


def get_group_mail_access(group_email: str) -> ExternalAccess | None:
    if not global_version.is_ee_version():
        return None

    ee_get_group_mail_access = cast(
        Callable[[str], ExternalAccess],
        fetch_versioned_implementation(
            "onyx.external_permissions.gmail.access",
            "get_group_mail_access",
        ),
    )

    return ee_get_group_mail_access(group_email)
