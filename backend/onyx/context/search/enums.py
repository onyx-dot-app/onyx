"""NOTE: this needs to be separate from models.py because of circular imports.
Both search/models.py and db/models.py import enums from this file AND
search/models.py imports from db/models.py."""

from enum import Enum


class RecencyBiasSetting(str, Enum):
    FAVOR_RECENT = "favor_recent"  # 2x decay rate
    BASE_DECAY = "base_decay"
    NO_DECAY = "no_decay"
    # Determine based on query if to use base_decay or favor_recent
    AUTO = "auto"


class OptionalSearchSetting(str, Enum):
    ALWAYS = "always"
    NEVER = "never"
    # Determine whether to run search based on history and latest query
    AUTO = "auto"


class SearchType(str, Enum):
    KEYWORD = "keyword"
    SEMANTIC = "semantic"
    INTERNET = "internet"


class LLMEvaluationType(str, Enum):
    AGENTIC = "agentic"  # applies agentic evaluation
    BASIC = "basic"  # applies boolean evaluation
    SKIP = "skip"  # skips evaluation
    UNSPECIFIED = "unspecified"  # reverts to default


class QueryFlow(str, Enum):
    SEARCH = "search"
    QUESTION_ANSWER = "question-answer"
