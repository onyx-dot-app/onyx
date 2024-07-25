from enum import Enum


class EmbedTextType(str, Enum):
    QUERY = "query"
    PASSAGE = "passage"
