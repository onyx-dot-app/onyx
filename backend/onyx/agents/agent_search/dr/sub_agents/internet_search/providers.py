from onyx.agents.agent_search.dr.sub_agents.internet_search.clients.exa_client import (
    ExaClient,
)
from onyx.agents.agent_search.dr.sub_agents.internet_search.clients.google_client import (
    GoogleClient,
)
from onyx.agents.agent_search.dr.sub_agents.internet_search.models import (
    InternetSearchProvider,
)
from onyx.configs.chat_configs import EXA_API_KEY, GOOGLE_API_KEY, GOOGLE_CSE_ID


def get_default_provider() -> InternetSearchProvider | None:
    if GOOGLE_API_KEY and GOOGLE_CSE_ID:
        try:
            return GoogleClient()
        except ValueError:
            pass
    if EXA_API_KEY:
        return ExaClient()
    return None