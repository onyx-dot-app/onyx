from enum import Enum


class ResearchType(str, Enum):
    """Research type options for agent search operations"""

    # BASIC = "BASIC"
    THOUGHTFUL = "THOUGHTFUL"
    DEEP = "DEEP"


class DRPath(str, Enum):
    CLARIFIER = "CLARIFIER"
    ORCHESTRATOR = "ORCHESTRATOR"
    INTERNAL_SEARCH = "INTERNAL_SEARCH"
    GENERIC_TOOL = "GENERIC_TOOL"
    KNOWLEDGE_GRAPH = "KNOWLEDGE_GRAPH"
    INTERNET_SEARCH = "INTERNET_SEARCH"
    CLOSER = "CLOSER"
    END = "END"
