"""Enterprise code loads when the build ships it, and telemetry names the
instance domain only for a licensed deployment."""

from importlib.machinery import ModuleSpec
from unittest.mock import MagicMock, patch

import pytest

from onyx.configs.constants import MilestoneRecordType
from onyx.server.settings.models import Tier
from onyx.utils import telemetry, variable_functionality
from onyx.utils.variable_functionality import (
    global_version,
    is_ee_available,
    set_is_ee_if_available,
)


def test_ee_is_available_when_the_package_is_real() -> None:
    # Mocked, so this also runs on the MIT-only mirror, which has no `ee.onyx`.
    with patch(
        "onyx.utils.variable_functionality.importlib.util.find_spec",
        return_value=ModuleSpec("ee.onyx", loader=None, origin="ee/onyx/__init__.py"),
    ):
        assert is_ee_available()


def test_ee_is_unavailable_with_no_ee_package() -> None:
    with patch(
        "onyx.utils.variable_functionality.importlib.util.find_spec",
        side_effect=ModuleNotFoundError("No module named 'ee'"),
    ):
        assert not is_ee_available()


@pytest.mark.parametrize(
    "spec",
    [
        # The MIT-only mirror: a bare `ee` package with no `onyx` inside.
        None,
        # A leftover `ee/onyx` directory with no `__init__.py`.
        ModuleSpec("ee.onyx", loader=None, origin=None),
    ],
)
def test_ee_is_unavailable_without_a_real_package(spec: ModuleSpec | None) -> None:
    with patch(
        "onyx.utils.variable_functionality.importlib.util.find_spec",
        return_value=spec,
    ):
        assert not is_ee_available()


@pytest.mark.parametrize("available", [True, False])
def test_ee_loads_only_when_the_build_ships_it(available: bool) -> None:
    with patch.object(
        variable_functionality, "is_ee_available", return_value=available
    ):
        set_is_ee_if_available()
    try:
        assert global_version.is_ee_version() is available
    finally:
        global_version.unset_ee()


@pytest.mark.parametrize(
    "tier, sends_domain",
    [(Tier.COMMUNITY, False), (Tier.BUSINESS, True), (Tier.ENTERPRISE, True)],
)
def test_telemetry_names_the_domain_only_when_licensed(
    tier: Tier, sends_domain: bool
) -> None:
    with (
        patch.object(telemetry, "DISABLE_TELEMETRY", False),
        patch.object(telemetry, "MULTI_TENANT", False),
        patch.object(telemetry, "_get_tier", return_value=tier) as get_tier,
        patch.object(telemetry, "get_or_generate_uuid", return_value="uuid"),
        patch.object(
            telemetry, "_get_or_generate_instance_domain", return_value="acme.com"
        ),
        patch.object(telemetry.requests, "post") as post,
    ):
        post.return_value = MagicMock(ok=True)
        sent: bool | None = telemetry.optional_telemetry(
            record_type=telemetry.RecordType.USAGE,
            data={"milestone": MilestoneRecordType.RAN_QUERY.value},
            tenant_id="tenant_abc",
            blocking=True,
        )

    assert sent is True
    get_tier.assert_called_once_with("tenant_abc")
    payload: dict[str, object] = post.call_args.kwargs["json"]
    assert ("instance_domain" in payload) is sends_domain
