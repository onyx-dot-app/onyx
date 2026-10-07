"""Cloud product analytics. Fleet callhome uses fleet_telemetry instead."""

from typing import Any

from onyx.configs.constants import MilestoneRecordType
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import (
    fetch_versioned_implementation_with_fallback,
    noop_fallback,
)
from shared_configs.configs import MULTI_TENANT, POSTGRES_DEFAULT_SCHEMA

logger = setup_logger()


def mt_cloud_telemetry(
    tenant_id: str,
    distinct_id: str,
    event: MilestoneRecordType,
    properties: dict[str, Any] | None = None,
) -> None:
    if not MULTI_TENANT:
        return

    # Automatically include tenant_id in properties
    all_properties = {**properties} if properties else {}
    if properties and "tenant_id" in properties:
        logger.warning(
            "tenant_id already in properties: %s. Overwriting with new value %s.",
            properties,
            tenant_id,
        )
    all_properties["tenant_id"] = tenant_id

    # MIT version should not need to include any Posthog code
    # This is only for Onyx MT Cloud, this code should also never be hit, no reason for any orgs to
    # be running the Multi Tenant version of Onyx.
    fetch_versioned_implementation_with_fallback(
        module="onyx.utils.telemetry",
        attribute="event_telemetry",
        fallback=noop_fallback,
    )(distinct_id, event, all_properties)


def _get_tenant_id_for_user_identify(user_email: str) -> str | None:
    try:
        return fetch_versioned_implementation_with_fallback(
            module="onyx.db.user_tenant_mapping",
            attribute="get_tenant_id_for_email",
            fallback=lambda _email: POSTGRES_DEFAULT_SCHEMA,
        )(user_email)
    except Exception:
        logger.exception("Failed to resolve tenant id for user %s", user_email)

    return None


def mt_cloud_identify_user(
    *,
    distinct_id: str,
    email: str,
    request: Any = None,
    tenant_id: str | None = None,
) -> None:
    """Create/update a Cloud PostHog user profile and link any anonymous session."""
    if not MULTI_TENANT:
        return

    if request:
        anon_id = fetch_versioned_implementation_with_fallback(
            module="onyx.utils.posthog_client",
            attribute="get_anon_id_from_request",
            fallback=noop_fallback,
        )(request)
        if anon_id:
            fetch_versioned_implementation_with_fallback(
                module="onyx.utils.posthog_client",
                attribute="alias_user",
                fallback=noop_fallback,
            )(distinct_id, anon_id)

    resolved_tenant_id = tenant_id or _get_tenant_id_for_user_identify(email)
    properties: dict[str, str] = {"email": email}
    if resolved_tenant_id and resolved_tenant_id != POSTGRES_DEFAULT_SCHEMA:
        properties["tenant_id"] = resolved_tenant_id

    fetch_versioned_implementation_with_fallback(
        module="onyx.utils.telemetry",
        attribute="identify_user",
        fallback=noop_fallback,
    )(distinct_id, properties)
