"""Auto-discovering import fence for source operations.

For every registered gateway declaring ``sdk_modules``, the source SDK may be
imported only from the gateway's own file within the connector's OSS directory
and its EE perm-sync directory. This is what keeps the gateway boundary from
decaying over time.
"""

import pytest

from onyx.connectors.source_operations import (
    SourceOperations,
    registered_source_operations,
)
from tests.unit.onyx.connectors.source_operation_harnesses import (
    find_import_fence_violations,
    gateway_fence_paths,
    import_all_source_operation_gateways,
)

import_all_source_operation_gateways()


@pytest.mark.parametrize(
    "gateway_class",
    [
        gateway_class
        for gateway_class in registered_source_operations().values()
        if gateway_class.sdk_modules
    ],
    ids=lambda gateway_class: gateway_class.source.value,
)
def test_sdk_imports_stay_inside_the_gateway(
    gateway_class: type[SourceOperations],
) -> None:
    """Verifies the source SDK is imported only from the gateway file."""
    # Under test.
    gateway_file, directories = gateway_fence_paths(gateway_class)
    violations = find_import_fence_violations(
        directories,
        gateway_class.sdk_modules,
        allowed_file=gateway_file,
    )

    # Postcondition.
    assert not violations, (
        f"{gateway_class.source.value} imports its SDK outside the gateway: "
        f"{violations}. Route the calls through source operations."
    )
