from collections.abc import Callable
from typing import cast

from onyx.configs.constants import DocumentSource
from onyx.utils.variable_functionality import fetch_ee_implementation_or_noop


def source_should_fetch_permissions_during_indexing(source: DocumentSource) -> bool:
    _source_should_fetch_permissions_during_indexing_func = cast(
        Callable[[DocumentSource], bool],
        fetch_ee_implementation_or_noop(
            "onyx.external_permissions.sync_params",
            "source_should_fetch_permissions_during_indexing",
            False,
        ),
    )
    return _source_should_fetch_permissions_during_indexing_func(source)
