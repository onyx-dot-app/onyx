from enum import Enum


class HtmlBasedConnectorTransformLinksStrategy(str, Enum):
    # remove links entirely
    STRIP = "strip"
    # turn HTML links into markdown links
    MARKDOWN = "markdown"
