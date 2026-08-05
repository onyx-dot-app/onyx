"""Auto-discovering coverage harness for source operations.

For every registered gateway, every (operation, variant) unit must be exercised,
per capability tag, by a capability check of that capability -- unless the
operation carries an ``untested`` reason. A per-connector session that registers
a gateway is picked up here automatically; it cannot forget to wire the test.
"""

import pytest

from onyx.connectors.capability_checks.registry import get_capability_checks
from onyx.connectors.source_operations import (
    SourceOperations,
    registered_source_operations,
)
from tests.unit.onyx.connectors.source_operation_harnesses import (
    compute_uncovered_units,
    import_all_source_operation_gateways,
)

import_all_source_operation_gateways()


@pytest.mark.usefixtures("enable_ee")
@pytest.mark.parametrize(
    "gateway_class",
    list(registered_source_operations().values()),
    ids=lambda gateway_class: gateway_class.source.value,
)
def test_every_operation_unit_is_exercised_by_a_check(
    gateway_class: type[SourceOperations],
) -> None:
    """Verifies check coverage of every non-exempt (operation, variant) unit.

    Runs with EE enabled: perm-sync checks live only in the EE registries, so
    perm-sync-tagged units are coverable only when EE resolution is on.
    """
    # Precondition.
    checks = get_capability_checks(gateway_class.source)

    # Under test.
    uncovered = compute_uncovered_units(gateway_class, checks)

    # Postcondition.
    assert not uncovered, (
        f"{gateway_class.source.value} has operation units no capability "
        f"check exercises: {uncovered}. Add a check composing them "
        '(variant-bearing operations must be invoked with variant="<name>") '
        'or annotate the operation untested="<reason>".'
    )
