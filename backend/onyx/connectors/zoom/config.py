from typing import Annotated, Self

from pydantic import StrictFloat, StrictInt

from onyx.connectors.connector_config import ConnectorConfig, CredentialBinding
from onyx.connectors.field_policy import (
    FieldClass,
    FieldPolicy,
    ScopeDirection,
    ScopeInclude,
    ScopeOpaque,
)

# Discovery mechanisms are a union, and an empty one adds nothing.
_DISCOVERY = FieldPolicy(FieldClass.SCOPE, scope=ScopeInclude(empty_means_all=False))
# None means included, which ScopeToggle cannot read: classify_scope_change
# gives the direction.
_SESSION_TYPE = FieldPolicy(FieldClass.SCOPE, scope=ScopeOpaque())
_INCLUDE_MEETINGS = "include_meetings"
_INCLUDE_WEBINARS = "include_webinars"


class ZoomCredentialBinding(CredentialBinding):
    # Sets only the rate limits. Not ZoomPlanTier: the constructor also takes
    # "" and any casing.
    plan_tier: Annotated[str | None, FieldPolicy(FieldClass.COSMETIC)] = None


class ZoomConnectorConfig(ZoomCredentialBinding, ConnectorConfig):
    meeting_ids: Annotated[list[str] | None, _DISCOVERY] = None
    webinar_ids: Annotated[list[str] | None, _DISCOVERY] = None
    host_emails: Annotated[list[str] | None, _DISCOVERY] = None
    group_id: Annotated[str | None, _DISCOVERY] = None
    # Strict so a bool is not coerced to 1 percent.
    rate_limit_percent: Annotated[
        StrictInt | StrictFloat | None, FieldPolicy(FieldClass.COSMETIC)
    ] = None
    include_meetings: Annotated[bool | None, _SESSION_TYPE] = None
    include_webinars: Annotated[bool | None, _SESSION_TYPE] = None
    # Sets the access the connector computes for each recording.
    treat_link_access_as_public: Annotated[
        bool | None, FieldPolicy(FieldClass.BEHAVIOR)
    ] = None

    @classmethod
    def classify_scope_change(  # ty: ignore[invalid-method-override]
        cls, old: Self, new: Self
    ) -> dict[str, ScopeDirection]:
        values = {
            _INCLUDE_MEETINGS: (old.include_meetings, new.include_meetings),
            _INCLUDE_WEBINARS: (old.include_webinars, new.include_webinars),
        }
        directions: dict[str, ScopeDirection] = {}
        for name, (old_value, new_value) in values.items():
            was_included = old_value is not False
            is_included = new_value is not False
            if was_included == is_included:
                directions[name] = ScopeDirection.NONE
            elif is_included:
                directions[name] = ScopeDirection.WIDEN
            else:
                directions[name] = ScopeDirection.NARROW
        return directions
