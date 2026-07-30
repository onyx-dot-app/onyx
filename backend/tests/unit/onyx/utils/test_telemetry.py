from typing import Any
from unittest.mock import Mock

from onyx.configs.constants import MilestoneRecordType
from onyx.utils import telemetry as telemetry_utils


class CloudIdentifyHarness:
    def __init__(
        self,
        *,
        mapped_tenant_id: str = "tenant_dev",
        anon_id: str | None = None,
    ) -> None:
        self.mapped_tenant_id = mapped_tenant_id
        self.anon_id = anon_id
        self.lookup_emails: list[str] = []
        self.alias_calls: list[tuple[str, str]] = []
        self.identify_calls: list[tuple[str, dict[str, str]]] = []

    def fetch_versioned_implementation_with_fallback(
        self, module: str, attribute: str, fallback: Any
    ) -> Any:
        if (
            module == "onyx.server.tenants.user_mapping"
            and attribute == "get_tenant_id_for_email"
        ):
            return self.get_tenant_id_for_email
        if (
            module == "onyx.utils.posthog_client"
            and attribute == "get_anon_id_from_request"
        ):
            return lambda _request: self.anon_id
        if module == "onyx.utils.posthog_client" and attribute == "alias_user":
            return self.alias_user
        if module == "onyx.utils.telemetry" and attribute == "identify_user":
            return self.identify_user
        return fallback

    def get_tenant_id_for_email(self, email: str) -> str:
        self.lookup_emails.append(email)
        return self.mapped_tenant_id

    def alias_user(self, distinct_id: str, anonymous_id: str) -> None:
        self.alias_calls.append((distinct_id, anonymous_id))

    def identify_user(self, distinct_id: str, properties: dict[str, str]) -> None:
        self.identify_calls.append((distinct_id, properties))


def test_mt_cloud_telemetry_noop_when_not_multi_tenant(monkeypatch: Any) -> None:
    fetch_impl = Mock()
    monkeypatch.setattr(
        telemetry_utils,
        "fetch_versioned_implementation_with_fallback",
        fetch_impl,
    )
    # mt_cloud_telemetry reads the module-local imported symbol, so patch this path.
    monkeypatch.setattr("onyx.utils.telemetry.MULTI_TENANT", False)

    telemetry_utils.mt_cloud_telemetry(
        tenant_id="tenant-1",
        distinct_id="12345678-1234-1234-1234-123456789abc",
        event=MilestoneRecordType.USER_MESSAGE_SENT,
        properties={"origin": "web"},
    )

    fetch_impl.assert_not_called()


def test_mt_cloud_telemetry_calls_event_telemetry_when_multi_tenant(
    monkeypatch: Any,
) -> None:
    event_telemetry = Mock()
    fetch_impl = Mock(return_value=event_telemetry)
    monkeypatch.setattr(
        telemetry_utils,
        "fetch_versioned_implementation_with_fallback",
        fetch_impl,
    )
    # mt_cloud_telemetry reads the module-local imported symbol, so patch this path.
    monkeypatch.setattr("onyx.utils.telemetry.MULTI_TENANT", True)

    telemetry_utils.mt_cloud_telemetry(
        tenant_id="tenant-1",
        distinct_id="12345678-1234-1234-1234-123456789abc",
        event=MilestoneRecordType.USER_MESSAGE_SENT,
        properties={"origin": "web"},
    )

    fetch_impl.assert_called_once_with(
        module="onyx.utils.telemetry",
        attribute="event_telemetry",
        fallback=telemetry_utils.noop_fallback,
    )
    event_telemetry.assert_called_once_with(
        "12345678-1234-1234-1234-123456789abc",
        MilestoneRecordType.USER_MESSAGE_SENT,
        {"origin": "web", "tenant_id": "tenant-1"},
    )


def test_mt_cloud_identify_user_resolves_tenant_by_email_when_not_provided(
    monkeypatch: Any,
) -> None:
    harness = CloudIdentifyHarness(mapped_tenant_id="tenant_dev")

    monkeypatch.setattr("onyx.utils.telemetry.MULTI_TENANT", True)
    monkeypatch.setattr(
        telemetry_utils,
        "fetch_versioned_implementation_with_fallback",
        harness.fetch_versioned_implementation_with_fallback,
    )

    telemetry_utils.mt_cloud_identify_user(
        distinct_id="user-id",
        email="wenxi@onyx.app",
    )

    assert harness.lookup_emails == ["wenxi@onyx.app"]
    assert harness.identify_calls == [
        ("user-id", {"email": "wenxi@onyx.app", "tenant_id": "tenant_dev"})
    ]


def test_mt_cloud_identify_user_uses_provided_tenant_without_lookup(
    monkeypatch: Any,
) -> None:
    harness = CloudIdentifyHarness(anon_id="anon-id")
    request = object()

    monkeypatch.setattr("onyx.utils.telemetry.MULTI_TENANT", True)
    monkeypatch.setattr(
        telemetry_utils,
        "fetch_versioned_implementation_with_fallback",
        harness.fetch_versioned_implementation_with_fallback,
    )

    telemetry_utils.mt_cloud_identify_user(
        distinct_id="user-id",
        email="wenxi@onyx.app",
        request=request,
        tenant_id="tenant_dev",
    )

    assert harness.lookup_emails == []
    assert harness.alias_calls == [("user-id", "anon-id")]
    assert harness.identify_calls == [
        ("user-id", {"email": "wenxi@onyx.app", "tenant_id": "tenant_dev"})
    ]


def test_mt_cloud_identify_user_omits_public_tenant(
    monkeypatch: Any,
) -> None:
    harness = CloudIdentifyHarness(
        mapped_tenant_id=telemetry_utils.POSTGRES_DEFAULT_SCHEMA
    )

    monkeypatch.setattr("onyx.utils.telemetry.MULTI_TENANT", True)
    monkeypatch.setattr(
        telemetry_utils,
        "fetch_versioned_implementation_with_fallback",
        harness.fetch_versioned_implementation_with_fallback,
    )

    telemetry_utils.mt_cloud_identify_user(
        distinct_id="user-id",
        email="wenxi@onyx.app",
    )

    assert harness.lookup_emails == ["wenxi@onyx.app"]
    assert harness.identify_calls == [("user-id", {"email": "wenxi@onyx.app"})]


def test_mt_cloud_identify_user_noop_when_not_multi_tenant(monkeypatch: Any) -> None:
    monkeypatch.setattr("onyx.utils.telemetry.MULTI_TENANT", False)
    monkeypatch.setattr(
        telemetry_utils,
        "fetch_versioned_implementation_with_fallback",
        Mock(side_effect=AssertionError("tenant mapping should not be looked up")),
    )

    telemetry_utils.mt_cloud_identify_user(
        distinct_id="user-id",
        email="wenxi@onyx.app",
    )
