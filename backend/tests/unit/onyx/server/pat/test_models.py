from onyx.db.enums import Permission
from onyx.server.gateway.configs import LLM_GATEWAY_MIN_TIER
from onyx.server.pat.models import SELECTABLE_PAT_SCOPES
from onyx.server.settings.models import Tier


def test_llm_gateway_scope_is_available_on_business_tier() -> None:
    assert LLM_GATEWAY_MIN_TIER is Tier.BUSINESS
    assert (
        SELECTABLE_PAT_SCOPES[Permission.USE_LLM_GATEWAY].min_tier
        is LLM_GATEWAY_MIN_TIER
    )
