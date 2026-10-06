from enum import Enum


class EmbeddingProvider(str, Enum):
    OPENAI = "openai"
    COHERE = "cohere"
    VOYAGE = "voyage"
    GOOGLE = "google"
    LITELLM = "litellm"
    AZURE = "azure"


class RerankerProvider(str, Enum):
    COHERE = "cohere"
    LITELLM = "litellm"
    BEDROCK = "bedrock"


class EmbedTextType(str, Enum):
    QUERY = "query"
    PASSAGE = "passage"


class WebSearchProviderType(str, Enum):
    GOOGLE_PSE = "google_pse"
    SERPER = "serper"
    EXA = "exa"
    SEARXNG = "searxng"
    BRAVE = "brave"
    TAVILY = "tavily"


class WebContentProviderType(str, Enum):
    ONYX_WEB_CRAWLER = "onyx_web_crawler"
    FIRECRAWL = "firecrawl"
    EXA = "exa"
    TAVILY = "tavily"


class TracingProviderType(str, Enum):
    BRAINTRUST = "braintrust"
    LANGFUSE = "langfuse"


class UsageCredentialType(str, Enum):
    """CRAFT_PAT is separate from PAT because Craft sandbox tokens are
    agent-driven yet carry the owning human's user_id."""

    SESSION = "session"
    JWT = "jwt"
    PAT = "pat"
    CRAFT_PAT = "craft_pat"
    API_KEY = "api_key"
