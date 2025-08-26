from onyx.agents.agent_search.dr.sub_agents.internet_search.exa_client import ExaClient
from onyx.agents.agent_search.dr.sub_agents.internet_search.models import (
    InternetSearchProvider,
)
from onyx.configs.chat_configs import EXA_API_KEY


def get_default_provider() -> InternetSearchProvider | None:
    if EXA_API_KEY:
        # Lazy import to avoid circular dependency
        return ExaClient()
    return None
