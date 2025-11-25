# Re-export FirecrawlClient for convenience
# The actual implementation lives in web_search/clients/firecrawl_client.py
from onyx.tools.tool_implementations.web_search.clients.firecrawl_client import (
    FirecrawlClient,
)

__all__ = ["FirecrawlClient"]
