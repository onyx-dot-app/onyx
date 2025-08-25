from enum import Enum


class ResearchType(str, Enum):
    """Research type options for agent search operations"""

    # BASIC = "BASIC"
    LEGACY_AGENTIC = "LEGACY_AGENTIC"  # only used for legacy agentic search migrations
    THOUGHTFUL = "THOUGHTFUL"
    DEEP = "DEEP"


class ResearchAnswerPurpose(str, Enum):
    """Research answer purpose options for agent search operations"""

    ANSWER = "ANSWER"
    CLARIFICATION_REQUEST = "CLARIFICATION_REQUEST"


class DRPath(str, Enum):
    CLARIFIER = "Clarifier"
    ORCHESTRATOR = "Orchestrator"
    INTERNAL_SEARCH = "Internal Search"
    GENERIC_TOOL = "Generic Tool"
    KNOWLEDGE_GRAPH = "Knowledge Graph"
    INTERNET_SEARCH = "Internet Search"
    INTERNET_SEARCH_ONLY = "Internet Search Only"
    INTERNET_URL_OPEN = "Internet URL Open"
    IMAGE_GENERATION = "Image Generation"
    CLOSER = "Closer"
    END = "End"
