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


class QueryType(str, Enum):
    """
    The type of first-pass query to use for hybrid search.

    The values of this enum are injected into the ranking profile name which
    should match the name in the schema.
    """

    KEYWORD = "keyword"
    SEMANTIC = "semantic"


class SearchType(str, Enum):
    KEYWORD = "keyword"
    SEMANTIC = "semantic"
    INTERNET = "internet"
