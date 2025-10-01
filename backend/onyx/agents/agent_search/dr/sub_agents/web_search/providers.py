from onyx.agents.agent_search.dr.sub_agents.web_search.clients.exa_client import (
    ExaClient,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.clients.firecrawl_client import (
    FirecrawlContentClient,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.clients.google_client import (
    GoogleSearchClient,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.clients.mux_client import (
    MuxClient,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.clients.serper_client import (
    SerperClient,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.models import (
    InternetSearchProvider,
)
from onyx.configs.chat_configs import EXA_API_KEY
from onyx.configs.chat_configs import FIRECRAWL_API_KEY
from onyx.configs.chat_configs import GOOGLE_SEARCH_API_KEY
from onyx.configs.chat_configs import GOOGLE_SEARCH_CX
from onyx.configs.chat_configs import SERPER_API_KEY


def get_default_provider() -> InternetSearchProvider | None:
    if EXA_API_KEY:
        return ExaClient()
    if FIRECRAWL_API_KEY and GOOGLE_SEARCH_API_KEY and GOOGLE_SEARCH_CX:
        return MuxClient(
            search_client=GoogleSearchClient(),
            content_client=FirecrawlContentClient(),
        )
    if SERPER_API_KEY:
        return SerperClient()
    return None
